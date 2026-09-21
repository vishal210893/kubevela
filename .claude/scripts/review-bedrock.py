#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3", "botocore[crt]"]
#
# [tool.claude]
# description = "Run a single Bedrock model code review"
# model = "opus"
# allowed-tools = ["Bash($WSROOT/.claude/scripts/review-bedrock.py)", "Read"]
#
# [tool.claude.output]
# prompt = "Parse the JSON output and incorporate the external model review findings."
# ///

"""
Single-model code review via AWS Bedrock.

Reads code context (diff + file contents) from stdin, sends it to a Bedrock
model for review, and outputs structured JSON to stdout. Designed to be called
in parallel by the review orchestrator -- one invocation per model.

Exits 0 for normal completion (review-level errors reported as JSON).
Exits 1 for hard failures (missing dependencies, invalid invocation).
"""

import sys
import os
import json
import argparse
from pathlib import Path

# Early dependency check -- detect wrong invocation (python3 instead of direct exec).
# Output JSON to stdout (matching CLI engine pattern) so the orchestrator can parse it.
try:
    import boto3  # noqa: F401
except ImportError:
    print(
        json.dumps({
            'error': (
                "Missing dependencies. This script must be run directly, not via python3.\n"
                "\n"
                "  CORRECT:  $WSROOT/.claude/scripts/review-bedrock.py --preflight\n"
                "  WRONG:    python3 $WSROOT/.claude/scripts/review-bedrock.py --preflight\n"
                "\n"
                "The script's uv shebang manages dependencies automatically.\n"
                "Using python3 bypasses this and causes ImportError."
            )
        })
    )
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from lib.bedrocklib import MODELS, resolve_model, get_client, converse, preflight, get_max_tokens
from lib.reviewlib import (
    PERSONAS_NOT_FOUND_ERROR,
    load_perspectives,
    list_perspectives_json,
    resolve_persona,
    validate_stdin_context,
    build_review_prompt,
    sanitize_filename,
    persist_review,
    build_success_output,
    build_error_output,
)


# Load perspectives at module level (reads persona files once per invocation)
PERSPECTIVES, _PERSONAS_DIR = load_perspectives(start_path=Path(__file__).resolve().parent)
FOCUS_AREAS = {k: v['description'] for k, v in PERSPECTIVES.items()}
PERSONAS = {k: v['persona'] for k, v in PERSPECTIVES.items()}



SYSTEM_PROMPT = """\
{persona}

You are reviewing code changes (diffs and file contents) provided by a developer. \
Provide a thorough, actionable review.

Your review focus: {focus_description}

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

Also note positive observations -- good patterns, well-structured code, etc.

Format your response as structured markdown with findings grouped by priority. \
Start with a brief summary (2-3 sentences), then list findings.

## Cross-Reference and Consistency Checking

The review context includes structural metadata:
- **Repository Structure**: shows what files/directories actually exist on disk
- **Git Status**: shows uncommitted changes, deleted files, untracked files
- **Cross-Reference Notes**: pre-verified reference checks (broken references already identified)

Use these to:
- Flag documentation or code that references files, commands, or paths that do not exist
- Check that config/manifest entries correspond to actual directories
- Verify import paths resolve to existing modules
- Note when recently deleted files are still referenced elsewhere

Cross-reference failures are typically P0 (broken functionality) or P1 (misleading documentation)."""




def main():
    parser = argparse.ArgumentParser(
        description='Single-model code review via AWS Bedrock'
    )
    parser.add_argument('--model', default=None,
                        help='Model alias (e.g. nova-pro) or full Bedrock model ID')
    parser.add_argument('--focus', default=None,
                        help='Review focus area (e.g. security, architecture). '
                             'Required for review execution; optional for --preflight / --list / --list-perspectives.')
    parser.add_argument('--persona', default=None,
                        help='Override the built-in persona/role description '
                             '(if omitted, auto-selected from --focus)')
    parser.add_argument('--target', default='code changes',
                        help='Description of what is being reviewed (e.g. "commit abc123")')
    parser.add_argument('--region', default=None,
                        help='AWS region override')
    parser.add_argument('--profile', default=None,
                        help='AWS profile name override')
    parser.add_argument('--effort', default=None, choices=['low', 'medium', 'high', 'max'],
                        help='Reasoning effort level (adaptive thinking for Claude models). '
                             'Default: unset (non-Claude Converse models reject the thinking field)')
    parser.add_argument('--max-tokens', type=int, default=32768,
                        help='Max response tokens (default: 32768)')
    parser.add_argument('--temperature', type=float, default=0.3,
                        help='Inference temperature 0.0-1.0 (default: 0.3)')
    parser.add_argument('--reviews-dir', default=None,
                        help='Directory to persist review files and metadata sidecars')
    parser.add_argument('--list', action='store_true', dest='list_models',
                        help='List available model aliases and exit')
    parser.add_argument('--list-perspectives', '--list-agents', action='store_true',
                        help='List available review perspectives and exit')
    parser.add_argument('--preflight', action='store_true',
                        help='Verify AWS credentials and exit with JSON result')
    args = parser.parse_args()

    # --list: print model aliases as JSON and exit
    if args.list_models:
        print(json.dumps({'models': MODELS}))
        sys.exit(0)

    # --list-perspectives: print all perspectives and packs as JSON and exit
    if args.list_perspectives:
        print(json.dumps(list_perspectives_json(PERSPECTIVES, _PERSONAS_DIR)))
        sys.exit(0)

    # --preflight: verify AWS credentials and optionally test model access
    if args.preflight:
        try:
            result = preflight(
                region=args.region, profile=args.profile, model=args.model,
            )
            print(json.dumps(result))
        except RuntimeError as e:
            print(json.dumps({'error': str(e), 'preflight': True}))
        sys.exit(0)

    # --focus and --model are required for review execution
    # (but not for --list/--list-perspectives/--preflight above)
    if not args.focus:
        parser.error("--focus is required for review execution")
    if not args.model:
        parser.error("--model is required for review execution")

    # Resolve model (region + profile needed for cross-region inference prefix)
    try:
        alias, model_id = resolve_model(args.model, region=args.region, profile=args.profile)
    except Exception as e:
        print(f"Invalid model: {e}", file=sys.stderr)
        print(json.dumps(build_error_output(
            model_alias=args.model, focus=args.focus,
            error=f"Invalid model: {e}", engine='converse',
        )))
        sys.exit(0)

    # Preflight: personas directory must exist (unless --persona override provided)
    if _PERSONAS_DIR is None and not args.persona:
        output = build_error_output(
            model_alias=alias, focus=args.focus,
            error=PERSONAS_NOT_FOUND_ERROR, engine='converse',
        )
        output['preflight_personas'] = False
        print(json.dumps(output))
        sys.exit(0)

    # Resolve focus area and persona
    focus_description = FOCUS_AREAS.get(args.focus, args.focus)
    try:
        persona = resolve_persona(args.focus, PERSONAS, args.persona)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        print(json.dumps(build_error_output(
            model_alias=alias, focus=args.focus,
            error=str(e), engine='converse',
        )))
        sys.exit(0)

    # Read context from stdin
    if sys.stdin.isatty():
        print(json.dumps(build_error_output(
            model_alias=alias, focus=args.focus,
            error='No input on stdin. Pipe diff + file contents to this script.',
            engine='converse',
        )))
        sys.exit(0)

    context = sys.stdin.read()
    if not context.strip():
        print(json.dumps(build_error_output(
            model_alias=alias, focus=args.focus,
            error='Empty input on stdin.',
            engine='converse',
        )))
        sys.exit(0)

    # Validate context for common orchestrator mistakes (shared with CLI engine)
    ctx_ok, ctx_error = validate_stdin_context(context)
    if not ctx_ok:
        print(json.dumps(build_error_output(
            model_alias=alias, focus=args.focus,
            error=ctx_error, engine='converse',
        )))
        sys.exit(0)

    # Build prompts
    # Use .replace() instead of .format() -- persona text may contain curly braces
    # (JSON examples, code snippets) which would cause KeyError/ValueError with .format().
    system_prompt = (SYSTEM_PROMPT
                     .replace('{persona}', persona)
                     .replace('{focus_description}', focus_description))
    user_prompt = build_review_prompt(context, args.target)

    # Cap max_tokens at the model's known limit to avoid Bedrock validation errors
    model_limit = get_max_tokens(alias)
    effective_max_tokens = min(args.max_tokens, model_limit)

    # Create client and run review
    try:
        client = get_client(region=args.region, profile=args.profile)
        result = converse(
            client, model_id, system_prompt, user_prompt,
            max_tokens=effective_max_tokens, temperature=args.temperature,
            effort=args.effort,
        )
        output = build_success_output(
            model_alias=alias,
            model_id=model_id,
            focus=args.focus,
            review_content=result['text'],
            engine='converse',
            input_tokens=result['input_tokens'],
            output_tokens=result['output_tokens'],
        )
    except RuntimeError as e:
        output = build_error_output(
            model_alias=alias, focus=args.focus,
            error=str(e), engine='converse',
        )

    # Persist to disk if --reviews-dir is provided
    if args.reviews_dir:
        persist_review(args.reviews_dir, alias, args.focus, output)

    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
