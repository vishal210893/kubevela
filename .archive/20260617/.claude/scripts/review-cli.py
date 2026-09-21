#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3"]
#
# [tool.claude]
# description = "Run a single code review perspective via claude -p on Bedrock"
# model = "opus"
# allowed-tools = ["Bash($WSROOT/.claude/scripts/review-cli.py)", "Read"]
#
# [tool.claude.output]
# prompt = "Parse the JSON output and incorporate the review findings."
# ///

"""
Single-perspective code review via claude -p subprocess on Bedrock.

Spawns a claude -p subprocess with tool access (Read, Bash, Glob, Grep, WebFetch) running on
Bedrock via CLAUDE_CODE_USE_BEDROCK=1. The subprocess dynamically explores the
codebase and produces a review -- no pre-compiled static context needed.

Designed to be called in parallel by the review orchestrator -- one
invocation per perspective. Mirrors the interface of review-bedrock.py
so the orchestrator can use either interchangeably.

Exits 0 for normal completion (review-level errors reported as JSON).
Exits 1 for hard failures (missing dependencies, invalid invocation).
"""

import sys
import os
import json
import argparse
import subprocess
import tempfile
from pathlib import Path

# Early dependency check -- detect wrong invocation (python3 instead of direct exec).
# Canary import: boto3 is declared in the PEP 723 metadata and installed by the
# uv shebang. This script does NOT use boto3 -- it shells out to `claude -p`.
# boto3 exists here solely as an invocation guard: if the import fails, the user
# ran `python3 script.py` instead of `./script.py`, bypassing uv's environment.
# A lighter alternative could replace this, but the pattern works reliably.
try:
    import boto3  # noqa: F401
except ImportError:
    print(
        json.dumps({
            'error': (
                "Missing dependencies. This script must be run directly, not via python3.\n"
                "\n"
                "  CORRECT:  $WSROOT/.claude/scripts/review-cli.py --preflight\n"
                "  WRONG:    python3 $WSROOT/.claude/scripts/review-cli.py --preflight\n"
                "\n"
                "The script's uv shebang manages dependencies automatically.\n"
                "Using python3 bypasses this and causes ImportError."
            )
        })
    )
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from lib.reviewlib import (
    PACKS,
    PERSONAS_NOT_FOUND_ERROR,
    load_perspectives,
    list_perspectives_json,
    resolve_persona,
    validate_stdin_context,
    build_review_prompt_with_tools,
    sanitize_filename,
    persist_review,
    is_claude_model,
    build_success_output,
    build_error_output,
    build_subprocess_env,
)
from lib.bedrocklib import resolve_model, preflight as bedrock_preflight


# Load perspectives at module level (reads persona files once per invocation)
PERSPECTIVES, _PERSONAS_DIR = load_perspectives(start_path=Path(__file__).resolve().parent)
FOCUS_AREAS = {k: v['description'] for k, v in PERSPECTIVES.items()}
PERSONAS = {k: v['persona'] for k, v in PERSPECTIVES.items()}


# ---------------------------------------------------------------------------
# Disallowed tool patterns for claude -p subprocess
# ---------------------------------------------------------------------------
# When granting Bash access, block destructive/network/escape commands.
# Uses --disallowedTools which enforces even with bypassPermissions (verified).
# Pattern syntax: Bash(command *) blocks any invocation starting with that command.

DISALLOWED_TOOLS = ','.join([
    'Bash(rm *)', 'Bash(rmdir *)', 'Bash(mv *)', 'Bash(cp *)',
    'Bash(chmod *)', 'Bash(chown *)',
    'Bash(kill *)', 'Bash(pkill *)',
    'Bash(curl *)', 'Bash(wget *)', 'Bash(ssh *)', 'Bash(scp *)', 'Bash(nc *)',
    'Bash(python *)', 'Bash(python3 *)', 'Bash(node *)',
    'Bash(pip *)', 'Bash(npm *)', 'Bash(apt *)',
    'Bash(sudo *)', 'Bash(su *)',
    'Bash(eval *)', 'Bash(exec *)', 'Bash(source *)',
    'Bash(git push *)', 'Bash(git commit *)', 'Bash(git reset *)',
    'Bash(git checkout *)', 'Bash(git merge *)', 'Bash(git rebase *)',
    'Bash(git clean *)', 'Bash(git branch -D *)', 'Bash(git branch -d *)',
    'Edit',
])


# ---------------------------------------------------------------------------
# System prompt template for the claude -p subprocess
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
{persona}

You are reviewing code changes. You have tool access to the codebase.

**Use your tools extensively:**
- Read every changed file IN FULL before forming opinions
- Use Grep to find callers, importers, and dependencies of changed code
- Use Glob to check for related test files, docs, and configuration
- Use Bash for git commands: `git log`, `git diff`, `git show`, `git blame`, `ls`
- Use WebFetch to look up external references when needed (e.g., OWASP guidelines, CVE details)
- Read files NOT in the change set if you need context (imports, base classes, configs)
- Verify every claim -- do not speculate about what code does

Your review focus: {focus_description}

## Output Format

Start with a brief summary (2-3 sentences), then list findings grouped by priority:

**Priority levels:**
- **P0 Critical** -- must fix before merge. Code is broken, dangerous, or causes immediate harm.
- **P1 Significant** -- should fix before merge. Will cause problems under known conditions, or creates expensive-to-fix design debt.
- **P2 Recommended** -- improves the PR. Code works but could be cleaner, smaller, more testable, or more focused.
- **P3 Note** -- optional. Subjective preference or minor improvement.

For each finding, provide:
- **Priority**: P0 / P1 / P2 / P3 per the definitions above
- **File**: specific file path and line number(s) if applicable
- **Issue**: clear description of the problem
- **Why it matters**: impact and risk
- **Fix**: concrete recommendation

End with **Positive Observations** -- good patterns, well-structured code, etc.

## Cross-Reference and Consistency Checking

For each changed file:
- Verify that imports resolve to existing modules
- Check that documentation references point to existing files/commands
- Verify manifest/registry entries correspond to actual directories
- Flag any references to recently deleted files

Cross-reference failures are typically P0 (broken functionality) or P1 (misleading documentation)."""



# ---------------------------------------------------------------------------
# Preflight: validate Bedrock credentials via claude -p
# ---------------------------------------------------------------------------

def run_preflight(region=None, profile=None, model=None):
    """Verify AWS credentials and model access via Bedrock APIs.

    Tests both streaming (InvokeModelWithResponseStream, used by claude -p) and
    non-streaming (Converse) APIs to detect SCP blocks that would cause claude -p
    to hang for ~5 min retrying a permanent 403.

    Always tests model access. When model is provided, tests that specific model.
    Otherwise defaults to DEFAULT_MODEL so preflight always validates Bedrock
    invocation, not just STS credentials.

    Args:
        region: AWS region override
        profile: AWS profile override
        model: Model alias to validate (e.g., 'opus-4.6'). Defaults to
               DEFAULT_MODEL when not provided.

    Returns:
        dict: {"ok": True, ...} on success, {"error": "..."} on failure.
              When streaming is SCP-blocked, returns:
              {"error": "...", "scp_blocked": True, "converse_ok": True/False,
               "scp_details": "...", "suggestion": "..."}
    """
    from lib.bedrocklib import DEFAULT_MODEL
    effective_model = model or DEFAULT_MODEL

    try:
        result = bedrock_preflight(
            region=region, profile=profile, model=effective_model,
        )
    except RuntimeError as e:
        return {'error': str(e)}

    if not result.get('ok'):
        return {'error': result.get('error', 'Preflight failed')}

    access = result.get('model_access')
    if access is None:
        return result

    if access['scp_blocked']:
        response = {
            'error': (
                "Streaming API (InvokeModelWithResponseStream) is blocked by an "
                "Organization SCP. claude -p requires streaming and will hang.\n"
                f"  {access['scp_details'] or 'No details available'}"
            ),
            'scp_blocked': True,
            'converse_ok': access['converse_ok'],
            'scp_details': access['scp_details'],
        }
        suggestions = []
        if access['converse_ok']:
            suggestions.append(
                "Try the Converse engine (--engine converse) which uses "
                "the non-streaming API and is not blocked by this SCP."
            )
        suggestions.append(
            "Run the review locally (--local) if you have enough "
            "session context remaining."
        )
        response['suggestion'] = ' Or: '.join(suggestions)
        return response

    if not access['streaming_ok'] and not access['converse_ok']:
        return {
            'error': access.get('error', 'Both streaming and non-streaming APIs failed'),
            'suggestion': (
                "Run the review locally (--local) if you have enough "
                "session context remaining."
            ),
        }

    if not access['streaming_ok']:
        return {
            'error': f"Streaming API failed: {access.get('error', 'unknown')}",
            'converse_ok': access['converse_ok'],
            'suggestion': (
                "Try the Converse engine (--engine converse). "
                "Or: Run the review locally (--local) if you have enough "
                "session context remaining."
            ),
        }

    result['preflight'] = True
    return result




# ---------------------------------------------------------------------------
# Invoke claude -p subprocess
# ---------------------------------------------------------------------------

def invoke_claude_p(system_prompt, seed_prompt, model=None,
                    effort=None, region=None, profile=None, workspace_root=None):
    """Invoke a claude -p subprocess with tool access on Bedrock.

    Args:
        system_prompt: Full system prompt text (persona + review instructions)
        seed_prompt: User prompt (diff + file list + instructions)
        model: Optional model alias override (e.g., 'opus-4.6')
        effort: Optional effort level (low/medium/high/max)
        region: AWS region override
        profile: AWS profile override
        workspace_root: Working directory for the subprocess

    Returns:
        dict: Parsed JSON output from claude -p, or error dict
    """
    # Detect region from profile config if not explicitly provided.
    # The subprocess needs AWS_REGION set; without it, claude -p can't
    # determine which Bedrock endpoint to connect to and hangs.
    from lib.bedrocklib import _detect_region
    effective_region = region or _detect_region(profile=profile)

    env = build_subprocess_env(region=effective_region, profile=profile)

    # Write system prompt to temp file to avoid shell escaping issues
    sysprompt_fd, sysprompt_path = tempfile.mkstemp(
        suffix='.md', prefix='.review-sysprompt-'
    )
    try:
        with os.fdopen(sysprompt_fd, 'w', encoding='utf-8') as f:
            f.write(system_prompt)

        # -- CLI contract ----------------------------------------------
        # These flags are assumed stable in Claude Code but are NOT a
        # versioned API. Verified against Claude Code 2.1.112.
        # If a future update breaks one, preflight will catch it.
        # See TestCliContractFlags for the test that pins these.
        #
        # NOTE: Do NOT use --bare. It strips Glob, Grep, WebFetch, Write,
        # and Edit from the tool set on Bedrock. Use --strict-mcp-config
        # instead to avoid loading MCP server tools (which bloat context
        # by ~20K tokens) while keeping all built-in tools available.
        # -------------------------------------------------------------
        cmd = [
            'claude', '-p',
            '--no-session-persistence',
            '--output-format', 'json',
            '--strict-mcp-config',
            '--tools', 'Read,Bash,Glob,Grep,WebFetch',
            '--disallowedTools', DISALLOWED_TOOLS,
            '--permission-mode', 'bypassPermissions',
            '--system-prompt-file', sysprompt_path,
        ]

        if model:
            _, resolved_id = resolve_model(model, region=region, profile=profile)
            cmd.extend(['--model', resolved_id])

        if effort:
            cmd.extend(['--effort', effort])

        cwd = workspace_root or os.getcwd()

        # NOTE: subprocess.run with capture_output=True kills the direct child on
        # timeout, but grandchildren (node workers, tool subprocesses spawned by
        # claude -p) may survive. A full fix would use Popen + start_new_session +
        # os.killpg() for process-group cleanup, but the added complexity isn't
        # justified -- timeouts are rare and orphaned node processes are short-lived.
        result = subprocess.run(
            cmd,
            input=seed_prompt,
            capture_output=True, text=True,
            timeout=600,  # 10 minute timeout
            cwd=cwd,
            env=env,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            return {'error': f"claude -p failed (exit {result.returncode}): {stderr[:500]}"}

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            # claude -p may output non-JSON in some error cases
            return {'error': f"claude -p returned non-JSON output: {result.stdout[:500]}"}

        if data.get('is_error'):
            return {'error': data.get('result', 'Unknown claude -p error')}

        return data

    except subprocess.TimeoutExpired:
        return {'error': 'Review timed out after 10 minutes'}
    except FileNotFoundError:
        return {'error': 'claude CLI not found. Is Claude Code installed?'}
    finally:
        # Clean up temp system prompt file
        try:
            os.unlink(sysprompt_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Single-perspective code review via claude -p on Bedrock'
    )
    parser.add_argument('--model', default=None,
                        help='Claude model alias (e.g., opus-4.6, sonnet-4.6). '
                             'Defaults to inheriting the session model.')
    parser.add_argument('--focus', default=None,
                        help='Review focus area (e.g., security, architecture). '
                             'Required for review execution; optional for --preflight / --list-perspectives.')
    parser.add_argument('--persona', default=None,
                        help='Override the built-in persona text')
    parser.add_argument('--target', default='code changes',
                        help='Description of what is being reviewed')
    parser.add_argument('--region', default=None,
                        help='AWS region override')
    parser.add_argument('--profile', default=None,
                        help='AWS profile name override')
    parser.add_argument('--effort', default=None, choices=['low', 'medium', 'high', 'max'],
                        help='Reasoning effort level')
    parser.add_argument('--reviews-dir', default=None,
                        help='Directory to persist review files and metadata sidecars')
    parser.add_argument('--list-perspectives', '--list-agents', action='store_true',
                        help='List available review perspectives and exit')
    parser.add_argument('--preflight', action='store_true',
                        help='Verify Bedrock credentials via claude -p and exit')
    args = parser.parse_args()

    # --list-perspectives: print all perspectives and packs as JSON and exit
    if args.list_perspectives:
        print(json.dumps(list_perspectives_json(PERSPECTIVES, _PERSONAS_DIR)))
        sys.exit(0)

    # --preflight: verify Bedrock credentials via claude -p and exit
    if args.preflight:
        result = run_preflight(region=args.region, profile=args.profile, model=args.model)
        print(json.dumps(result))
        sys.exit(0)

    # --focus is required for review execution (but not for --list/--preflight above)
    if not args.focus:
        parser.error("--focus is required for review execution")

    # Validate model is a Claude model (if specified)
    if args.model and not is_claude_model(args.model):
        print(json.dumps(build_error_output(
            model_alias=args.model, focus=args.focus,
            error=(
                f"Model '{args.model}' is not a Claude model. "
                f"The CLI engine only supports Claude models (opus, sonnet, haiku). "
                f"For non-Claude models, use --engine converse in the /review command."
            ),
            engine='cli',
        )))
        sys.exit(0)

    # Preflight: personas directory must exist (unless --persona override provided)
    alias = args.model or 'inherited'
    if _PERSONAS_DIR is None and not args.persona:
        print(json.dumps(build_error_output(
            model_alias=alias, focus=args.focus,
            error=PERSONAS_NOT_FOUND_ERROR, engine='cli',
        )))
        sys.exit(0)

    # Resolve focus area and persona
    focus_description = FOCUS_AREAS.get(args.focus, args.focus)
    try:
        persona = resolve_persona(args.focus, PERSONAS, args.persona)
    except ValueError as e:
        print(json.dumps(build_error_output(
            model_alias=alias, focus=args.focus,
            error=str(e), engine='cli',
        )))
        sys.exit(0)

    # Read seed context from stdin
    if sys.stdin.isatty():
        print(json.dumps(build_error_output(
            model_alias=alias, focus=args.focus,
            error='No input on stdin. Pipe seed context (diff + file list) to this script.',
            engine='cli',
        )))
        sys.exit(0)

    context = sys.stdin.read()
    if not context.strip():
        print(json.dumps(build_error_output(
            model_alias=alias, focus=args.focus,
            error='Empty input on stdin.',
            engine='cli',
        )))
        sys.exit(0)

    # Validate context for common orchestrator mistakes (shared with Converse engine)
    ctx_ok, ctx_error = validate_stdin_context(context)
    if not ctx_ok:
        print(json.dumps(build_error_output(
            model_alias=alias, focus=args.focus,
            error=ctx_error, engine='cli',
        )))
        sys.exit(0)

    # Build system prompt and seed prompt
    # Use .replace() instead of .format() -- persona text may contain curly braces
    # (JSON examples, code snippets) which would cause KeyError/ValueError with .format().
    system_prompt = (SYSTEM_PROMPT_TEMPLATE
                     .replace('{persona}', persona)
                     .replace('{focus_description}', focus_description))
    seed_prompt = build_review_prompt_with_tools(context, args.target)

    # Determine workspace root (for cwd of subprocess)
    workspace_root = os.environ.get('WSROOT', os.getcwd())

    # Invoke claude -p
    data = invoke_claude_p(
        system_prompt=system_prompt,
        seed_prompt=seed_prompt,
        model=args.model,
        effort=args.effort,
        region=args.region,
        profile=args.profile,
        workspace_root=workspace_root,
    )

    # Build output
    if 'error' in data:
        output = build_error_output(
            model_alias=alias, focus=args.focus,
            error=data['error'], engine='cli',
        )
    else:
        # Extract token usage from claude -p JSON output
        usage = data.get('usage', {})
        model_usage = data.get('modelUsage', {})

        output = build_success_output(
            model_alias=alias,
            model_id=next(iter(model_usage.keys()), ''),
            focus=args.focus,
            review_content=data.get('result', ''),
            engine='cli',
            input_tokens=usage.get('input_tokens', 0),
            output_tokens=usage.get('output_tokens', 0),
            cache_read=usage.get('cache_read_input_tokens', 0),
            cache_creation=usage.get('cache_creation_input_tokens', 0),
        )

    # Persist to disk if --reviews-dir is provided
    if args.reviews_dir:
        persist_review(args.reviews_dir, alias, args.focus, output)

    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
