#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = []
# ///

"""
Git workflow library for Claude Code.
All shared functionality for git scripts.

This library provides:
- Core git operations with authenticated GitHub URLs
- Worktree detection and management
- Output formatting (JSON mode for Claude Code, human-readable for CLI)
- Comprehensive error handling
- LLM integration helpers (PEP 723 metadata parsing, claude -p invocation)
- Template formatting
"""

import subprocess
import sys
import os
import json
import re
from pathlib import Path

# Register git per-repo defaults for auto-materialization in dev.yaml
# Add both parent and parent/lib so devyaml is found whether gitlib is
# exec()d (where __file__ = caller path, so parent/lib = scripts/lib/)
# or imported as a module (where __file__ = gitlib.py, so parent = scripts/lib/)
for _d in [str(Path(__file__).parent / 'lib'), str(Path(__file__).parent)]:
    if _d not in sys.path:
        sys.path.insert(0, _d)
from devyaml import register_repo_defaults as _register_repo_defaults


def _git_repo_defaults(repo):
    """Return default config for a new git repo section."""
    return {
        'issue-in-branch': False,
        'spec-in-branch': False,
    }

_register_repo_defaults('git', _git_repo_defaults)


# ============================================================================
# CORE GIT OPERATIONS
# ============================================================================

def get_repo_info():
    """
    Get repository owner/name from gh CLI.

    Returns:
        str: Repository in "owner/repo" format

    Exits:
        1 if gh CLI fails (not authenticated or not a GitHub repo)
    """
    result = subprocess.run(
        'gh repo view --json nameWithOwner -q .nameWithOwner',
        shell=True, capture_output=True, text=True
    )
    if result.returncode != 0:
        print("Error: Failed to get repo info from gh CLI.", file=sys.stderr)
        if result.stderr:
            print(f"gh error: {result.stderr.strip()}", file=sys.stderr)
        print("Ensure 'gh' is authenticated (run: gh auth login)", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def get_repo_name():
    """
    Get repository name from origin remote URL.

    Extracts the last path segment (repo name) from the origin remote,
    stripping any .git suffix.

    Returns:
        str: Lowercase repository name, or None if not available
    """
    result = subprocess.run(
        ['git', 'remote', 'get-url', 'origin'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    if not url:
        return None
    if url.endswith('.git'):
        url = url[:-4]
    url = url.rstrip('/')
    name = url.split('/')[-1]
    return name.lower() if name else None


def get_repo_url():
    """
    Build authenticated GitHub URL using GH_TOKEN.

    Returns:
        str: Authenticated URL (https://x-access-token:TOKEN@github.com/owner/repo.git)

    Exits:
        1 if GH_TOKEN environment variable is not set
    """
    token = os.getenv('GH_TOKEN')
    if not token:
        print("Error: GH_TOKEN environment variable not set", file=sys.stderr)
        print("Set it with: export GH_TOKEN=<your-token>", file=sys.stderr)
        sys.exit(1)
    repo = get_repo_info()
    return f"https://x-access-token:{token}@github.com/{repo}.git"


def get_current_branch():
    """
    Get current branch name.

    Returns:
        str: Current branch name

    Exits:
        1 if not in a git repository
    """
    result = subprocess.run(
        ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def get_default_branch():
    """
    Get the default branch name (main or master).

    Returns:
        str: Default branch name ('main' or 'master')

    Examples:
        >>> default = get_default_branch()
        >>> print(default)
        'main'
    """
    # Try to get default branch from origin
    result = subprocess.run(
        ['git', 'symbolic-ref', 'refs/remotes/origin/HEAD'],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        # Output is like: refs/remotes/origin/main
        branch = result.stdout.strip().split('/')[-1]
        return branch

    # Fallback: check if main exists locally
    result = subprocess.run(
        ['git', 'rev-parse', '--verify', 'main'],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return 'main'

    # Fallback: check if master exists locally
    result = subprocess.run(
        ['git', 'rev-parse', '--verify', 'master'],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return 'master'

    # Default to 'main' if nothing found
    return 'main'


def get_repo_root():
    """
    Get repository root directory.

    Returns:
        str: Absolute path to repository root

    Exits:
        1 if not in a git repository
    """
    result = subprocess.run(
        ['git', 'rev-parse', '--show-toplevel'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def branch_exists(branch_name):
    """
    Check if a branch exists locally.

    Args:
        branch_name: Name of branch to check

    Returns:
        bool: True if branch exists locally
    """
    result = subprocess.run(
        ['git', 'rev-parse', '--verify', branch_name],
        capture_output=True, text=True
    )
    return result.returncode == 0


def remote_branch_exists(branch_name, repo_url):
    """
    Check if a branch exists on remote.

    Args:
        branch_name: Name of branch to check
        repo_url: Authenticated repository URL

    Returns:
        bool: True if branch exists on remote
    """
    result = subprocess.run(
        ['git', 'ls-remote', '--heads', repo_url, branch_name],
        capture_output=True, text=True
    )
    return len(result.stdout.strip()) > 0


def has_uncommitted_changes(path=None):
    """
    Check if there are uncommitted changes in working directory.

    Args:
        path: Optional repository path (uses current directory if None)

    Returns:
        bool: True if there are uncommitted changes
    """
    cmd = ['git']
    if path:
        cmd.extend(['-C', path])
    cmd.extend(['status', '--porcelain'])
    result = subprocess.run(
        cmd,
        capture_output=True, text=True
    )
    return len(result.stdout.strip()) > 0


# ============================================================================
# PIPELINE FLAG HELPERS
# ============================================================================

# Canonical mapping from pipeline-default values to the flags they enable.
# Keys are dev.yaml values; values are sets of flag names to enable.
_PIPELINE_DEFAULTS = {
    'pr':       {'pr'},
    'poll':     {'pr', 'poll'},
    'pr-poll':  {'pr', 'poll'},   # kept for pipeline-default compat
    'fix':      {'pr', 'poll', 'fix'},
    'pr-fix':   {'pr', 'poll', 'fix'},
    'merge':    {'pr', 'poll', 'fix', 'merge'},
    'pr-merge': {'pr', 'poll', 'fix', 'merge'},
}


def apply_pipeline_default(args):
    """Apply pipeline-default from dev.yaml when no explicit pipeline flag is set.

    Inspects which pipeline flags exist on *args* (pr, poll, fix, merge) and,
    if none are set, reads ``git.<repo>.pipeline-default`` from dev.yaml and
    enables the corresponding flags.  Only flags that actually exist on *args*
    are touched, so callers with a smaller flag set (e.g. a script with only
    fix/merge) are handled automatically.
    """
    # Determine which pipeline flags this script defines
    known = [f for f in ('pr', 'poll', 'fix', 'merge') if hasattr(args, f)]
    if any(getattr(args, f) for f in known):
        return  # user set an explicit flag -- skip default

    try:
        from devyaml import get as yaml_get
        repo = get_repo_name()
        if not repo:
            return
        default = yaml_get(f'git.{repo}.pipeline-default')
        if not default:
            return
        for flag in _PIPELINE_DEFAULTS.get(default, ()):
            if hasattr(args, flag):
                setattr(args, flag, True)
    except Exception:
        pass


def apply_escalation(args):
    """Apply the flag escalation ladder.

    Rules (order matters):
      --merge  implies --fix and --pr  (need a PR to merge)
      --fix    implies --pr and --poll (need a PR to fix against)
      --pr     implies --impl          (need code to PR, branch/branch-create only)

    Only flags that exist on *args* are touched, so scripts that lack --impl
    or --pr are unaffected.  Notably, --poll does NOT imply --pr -- you can
    poll an existing PR without creating a new one.
    """
    if getattr(args, 'merge', False):
        if hasattr(args, 'fix'):
            args.fix = True
        if hasattr(args, 'pr'):
            args.pr = True
    if getattr(args, 'fix', False):
        if hasattr(args, 'pr'):
            args.pr = True
        if hasattr(args, 'poll'):
            args.poll = True
    if getattr(args, 'pr', False):
        if hasattr(args, 'impl'):
            args.impl = True


# ============================================================================
# OUTPUT & ERROR HANDLING
# ============================================================================

def is_test_mode():
    """Check if running in test mode (JSON + verbose output)."""
    return os.getenv('CLAUDE_TEST_MODE') == '1'


def output_result(data, template=None):
    """
    Output data in JSON or human-readable format.

    Uses CC environment variable to determine output format:
    - CC=1: Print JSON to stdout (for Claude Code)
    - Otherwise: Format template with data and print (for direct CLI use)

    In test mode (CLAUDE_TEST_MODE=1 + CC=1):
    - Also echoes human-readable output to stderr for visibility

    Args:
        data: Dict of output data
        template: Format string template (Python format syntax with {placeholders})

    Examples:
        >>> output_result({"branch": "main", "commits": 5},
        ...               "Branch: {branch}, Commits: {commits}")
        # CLI mode: "Branch: main, Commits: 5"
        # JSON mode: {"branch": "main", "commits": 5}
    """
    if os.getenv('CC') == '1':
        # JSON mode for Claude Code
        print(json.dumps(data))

        # In test mode, also echo human-readable to stderr for visibility
        if is_test_mode() and template:
            formatted = format_template(template, data)
            print(formatted, file=sys.stderr)
    else:
        # Human-readable mode for direct CLI
        if template:
            formatted = format_template(template, data)
            print(formatted)
        else:
            # Fallback: pretty print the data
            for key, value in data.items():
                print(f"{key}: {value}")


def error(message, command=None, stderr_output=None):
    """
    Print comprehensive error message to stderr.

    All errors go to stderr (never stdout), even in CC=1.
    Claude Code displays stderr to users, so errors must be human-readable.

    Args:
        message: Error description (what failed)
        command: Command that was run (string or list)
        stderr_output: stderr from failed command

    Examples:
        >>> error("Failed to push branch 'feature'",
        ...       command=["git", "push", "origin", "feature"],
        ...       stderr_output="fatal: remote rejected")
        # Outputs to stderr:
        # Error: Failed to push branch 'feature'
        # Command: git push origin feature
        # fatal: remote rejected
    """
    print(f"Error: {message}", file=sys.stderr)

    if command:
        if isinstance(command, list):
            command = ' '.join(command)
        # Hide credentials in output
        token = os.getenv('GH_TOKEN', '')
        if token:
            command = command.replace(token, '***')
        print(f"Command: {command}", file=sys.stderr)

    if stderr_output:
        token = os.getenv('GH_TOKEN', '')
        if token:
            stderr_output = stderr_output.replace(token, '***')
        print(stderr_output, file=sys.stderr, end='')


def run_git(args, operation_description=None, context=None, check=True, capture_output=False, echo=True):
    """
    Run git command with comprehensive error handling.

    This is the standard way to run git commands in all scripts.
    Replaces the old run() function.

    Args:
        args: List or string of git arguments (e.g., ['push', 'origin', 'main'])
        operation_description: Human-readable description (e.g., "push branch")
        context: Optional context (e.g., branch name)
        check: Exit on error (default True)
        capture_output: Return output instead of printing (default False)
        echo: Echo command to stderr (default True)

    Returns:
        CompletedProcess if capture_output=True, otherwise None

    Note:
        When capture_output=False and check=True (the default), stdout is
        still captured internally for error handling but discarded (returns
        None). This is intentional -- scripts produce their own formatted
        output via output_result() and raw git stdout would interleave.

    Exits:
        With git's exit code on failure if check=True

    Examples:
        >>> run_git(['status', '--short'],
        ...         operation_description="check status",
        ...         capture_output=True)
        # Returns CompletedProcess with output

        >>> run_git(['push', 'origin', 'main'],
        ...         operation_description="push branch",
        ...         context="main")
        # Exits with error message if push fails
    """
    if isinstance(args, str):
        args = args.split()

    cmd = ['git'] + args

    # Echo command to stderr (always, unless explicitly disabled)
    if echo:
        cmd_str = ' '.join(cmd)
        # Hide credentials in echoed command
        token = os.getenv('GH_TOKEN', '')
        if token:
            cmd_str = cmd_str.replace(token, '***')
        print(f"$ {cmd_str}", file=sys.stderr)

    try:
        result = subprocess.run(
            cmd,
            capture_output=capture_output or check,
            text=True,
            check=False  # We handle errors ourselves
        )

        # In test mode, echo stdout/stderr for visibility
        if is_test_mode() and echo:
            if result.stdout:
                print(result.stdout, file=sys.stderr, end='')
            if result.stderr:
                print(result.stderr, file=sys.stderr, end='')
            print('', file=sys.stderr)  # Blank line after output

        if result.returncode != 0 and check:
            # Build context-rich error message
            if operation_description:
                if context:
                    message = f"Failed to {operation_description} '{context}'"
                else:
                    message = f"Failed to {operation_description}"
            else:
                message = "Git command failed"

            error(message, command=cmd, stderr_output=result.stderr)
            sys.exit(result.returncode)

        return result if capture_output else None

    except Exception as e:
        error(f"Unexpected error running git command: {str(e)}", command=cmd)
        sys.exit(1)


def push_and_track(repo_url, branch, force=False):
    """
    Push branch to remote and set up full tracking.

    Performs the standard 4-step push sequence:
    1. Push HEAD to remote branch
    2. Set full fetch refspec (for narrow clones)
    3. Fetch remote tracking ref
    4. Set upstream tracking

    Args:
        repo_url: Authenticated repository URL
        branch: Branch name to push
        force: Use --force-with-lease (safe force push after rebase)
    """
    push_args = ['push']
    if force:
        push_args.append('--force-with-lease')
    push_args += [repo_url, f'HEAD:refs/heads/{branch}']
    run_git(
        push_args,
        operation_description="force push branch" if force else "push branch",
        context=branch
    )

    run_git(
        ['config', 'remote.origin.fetch', '+refs/heads/*:refs/remotes/origin/*'],
        operation_description="set full fetch refspec",
        context='origin'
    )

    run_git(
        ['fetch', repo_url, f'{branch}:refs/remotes/origin/{branch}'],
        operation_description="fetch remote tracking ref",
        context=branch
    )

    run_git(
        ['branch', '--set-upstream-to', f'origin/{branch}'],
        operation_description="set upstream tracking",
        context=branch
    )


# ============================================================================
# VALIDATION
# ============================================================================

def require_not_in_worktree():
    """
    Exit with error if running inside a git linked worktree.

    Worktrees are no longer supported. Commands that create branches or manage
    issues must run from the main working tree.

    Exits:
        1 if the current directory is a linked worktree
    """
    git_dir = subprocess.run(
        ['git', 'rev-parse', '--git-dir'], capture_output=True, text=True, check=False)
    common_dir = subprocess.run(
        ['git', 'rev-parse', '--git-common-dir'], capture_output=True, text=True, check=False)
    if (git_dir.returncode == 0 and common_dir.returncode == 0
            and git_dir.stdout.strip() != common_dir.stdout.strip()):
        error("Cannot run from a git worktree")
        print("Switch to the main working tree and retry.", file=sys.stderr)
        sys.exit(1)


def check_rebased_on_main(default_branch=None):
    """
    Check if current branch is rebased on latest default branch (no divergence).

    Args:
        default_branch: Default branch name (auto-detected if not provided)

    Returns:
        bool: True if branch is up-to-date with default branch (no rebase needed)

    Examples:
        >>> if not check_rebased_on_main():
        ...     print("Branch needs rebasing on main")
    """
    if not default_branch:
        default_branch = get_default_branch()
    remote_ref = f'origin/{default_branch}'

    # Get merge base between current branch and remote default
    result = subprocess.run(
        ['git', 'merge-base', 'HEAD', remote_ref],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False
    merge_base = result.stdout.strip()

    # Get remote default branch commit
    result = subprocess.run(
        ['git', 'rev-parse', remote_ref],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False
    main_commit = result.stdout.strip()

    # If merge base equals remote default, we're up-to-date
    return merge_base == main_commit


# ============================================================================
# PEP 723 METADATA PARSING
# ============================================================================

_pep723_cache = {}


def parse_pep723_metadata(script_path):
    """
    Parse PEP 723 metadata from a script file.

    Extracts the [tool.claude] section from the PEP 723 metadata block.

    Args:
        script_path: Path to script (required, typically __file__)

    Returns:
        dict: Parsed [tool.claude] section as nested dict

    Examples:
        >>> metadata = parse_pep723_metadata(__file__)
        >>> print(metadata['description'])
        'Create a git commit'
    """
    # Import tomllib or tomli for TOML parsing
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            error("tomllib not available (Python 3.11+) and tomli not installed")
            print("Install tomli: pip install tomli", file=sys.stderr)
            sys.exit(1)

    if not script_path:
        error("script_path is required for parse_pep723_metadata")
        sys.exit(1)

    # Check cache
    cache_key = str(Path(script_path).resolve())
    if cache_key in _pep723_cache:
        return _pep723_cache[cache_key]

    try:
        with open(script_path, 'r') as f:
            content = f.read()
    except Exception as e:
        error(f"Failed to read script file: {str(e)}")
        sys.exit(1)

    # Extract PEP 723 block
    lines = content.split('\n')
    in_block = False
    toml_lines = []

    for line in lines:
        if line.strip() == '# /// script':
            in_block = True
            continue
        if line.strip() == '# ///':
            break
        if in_block:
            if line.startswith('# '):
                toml_lines.append(line[2:])  # Strip '# '
            elif line.strip() == '#':
                toml_lines.append('')  # Empty line

    if not toml_lines:
        error("No PEP 723 metadata block found in script")
        sys.exit(1)

    toml_str = '\n'.join(toml_lines)

    try:
        metadata = tomllib.loads(toml_str)
    except Exception as e:
        error(f"Failed to parse PEP 723 metadata: {str(e)}")
        sys.exit(1)

    result = metadata.get('tool', {}).get('claude', {})
    _pep723_cache[cache_key] = result
    return result


def get_prompt_from_metadata(arg_name, script_path):
    """
    Extract LLM generation prompt for a specific argument.

    Args:
        arg_name: Name of the argument (e.g., 'message', 'body', 'title')
        script_path: Path to script (required, typically __file__)

    Returns:
        str: The prompt string, or None if not found

    Examples:
        >>> prompt = get_prompt_from_metadata('message')
        >>> print(prompt)
        'Analyze the changes and generate a commit subject line...'
    """
    metadata = parse_pep723_metadata(script_path)

    # Find the argument definition
    for arg in metadata.get('argument', []):
        if arg.get('name') == arg_name:
            llm_gen = arg.get('llm-generation', {})
            return llm_gen.get('prompt')

    return None


def get_context_commands_from_metadata(arg_name, script_path):
    """
    Extract context-gathering commands for LLM generation.

    Args:
        arg_name: Name of the argument
        script_path: Path to script (required, typically __file__)

    Returns:
        list: Commands to run for context (e.g., ['git status', 'git diff HEAD'])

    Examples:
        >>> commands = get_context_commands_from_metadata('message')
        >>> print(commands)
        ['git status', 'git diff HEAD', 'git log --oneline -10']
    """
    metadata = parse_pep723_metadata(script_path)

    for arg in metadata.get('argument', []):
        if arg.get('name') == arg_name:
            llm_gen = arg.get('llm-generation', {})
            return llm_gen.get('context-commands', [])

    return []


def get_template_from_metadata(script_path):
    """
    Extract output template from metadata.

    Args:
        script_path: Path to script (required, typically __file__)

    Returns:
        str: The template string from [tool.claude.output]

    Examples:
        >>> template = get_template_from_metadata(__file__)
        >>> print(template)
        '[OK] Created commit {commit_hash}\n{message}'
    """
    metadata = parse_pep723_metadata(script_path)
    return metadata.get('output', {}).get('template')


# ============================================================================
# SPEC-SCRIPT HELPERS (shared by branch / branch-create)
# ============================================================================

def _ensure_speclib_importable():
    """Make `lib.speclib` importable when running from the source tree.

    At runtime (post-`profile install`), speclib.py lives alongside gitlib.py in
    `.claude/scripts/lib/`. In the source tree it lives under the spec capability,
    so callers invoking a git script directly (e.g., tests) need the spec
    capability's scripts dir on sys.path first.
    """
    try:
        from lib import speclib  # noqa: F401
        return
    except ImportError:
        pass
    gitlib_dir = os.path.dirname(os.path.abspath(__file__))
    scripts_dir = os.path.dirname(gitlib_dir)
    spec_src = os.path.abspath(os.path.join(scripts_dir, '..', '..', '..', '..', 'spec', 'src', 'claude', 'scripts'))
    if os.path.isdir(spec_src) and spec_src not in sys.path:
        sys.path.insert(0, spec_src)


def find_spec_script(script_name):
    """Locate a spec-capability script by checking common paths."""
    # bin_dir = directory of the caller script; fall back to gitlib's scripts/ dir
    caller_main = sys.modules.get('__main__')
    if caller_main and getattr(caller_main, '__file__', None):
        bin_dir = os.path.dirname(os.path.abspath(caller_main.__file__))
    else:
        bin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    candidates = [
        os.path.join(bin_dir, script_name),
        os.path.join(os.getenv('WSROOT', ''), '.claude', 'scripts', script_name),
        os.path.abspath(os.path.join(bin_dir, '..', '..', '..', '..', 'spec', 'src', 'claude', 'scripts', script_name)),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def run_spec_script(script_name, composite_spec):
    """Run a spec-capability script with a composite spec argument."""
    script_path = find_spec_script(script_name)
    if not script_path:
        return {'success': False, 'action': f'Script {script_name} not found'}

    env = {**os.environ, 'CC': '1'}
    result = subprocess.run([script_path, composite_spec], capture_output=True, text=True, env=env)

    if result.returncode == 0:
        action = 'created' if script_name == 'spec-create' else 'associated'
        return {'success': True, 'action': action}
    return {'success': False, 'action': result.stderr.strip()}


def spec_dir_exists(spec_name):
    """Check if a spec directory exists (queries `spec-list`)."""
    script_path = find_spec_script('spec-list')
    if not script_path:
        return False
    env = {**os.environ, 'CC': '1'}
    result = subprocess.run([script_path], capture_output=True, text=True, env=env)
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return False
    specs = data.get('specs', []) if isinstance(data, dict) else []
    return any(s.get('name') == spec_name for s in specs)


def apply_spec_to_current_branch(spec_arg):
    """Apply a --spec association to the current branch.

    Delegates to the spec-capability scripts (`spec-create` for a new spec,
    `spec` to associate / update an existing one, or to clear with the `-`
    sentinel). Returns (spec_status, spec_name); either may be None.
    """
    if not spec_arg:
        return None, None

    _ensure_speclib_importable()
    from lib.speclib import parse_composite_spec
    project, spec_name, ctx_refs, _ = parse_composite_spec(spec_arg)

    # Real spec name (not the `-` clear sentinel): create if missing, else associate.
    if spec_name and spec_name != '-':
        if spec_dir_exists(spec_name):
            result = run_spec_script('spec', spec_arg)
            if result['success']:
                return f"[OK] Associated existing spec '{spec_name}' with branch", spec_name
            return f"[WARNING] Failed to associate spec: {result['action']}", spec_name
        result = run_spec_script('spec-create', spec_arg)
        if result['success']:
            return f"[OK] Created spec '{spec_name}' and associated with branch", spec_name
        return f"[WARNING] Failed to create spec: {result['action']}", spec_name

    # No spec name, `-` clear sentinel, or project/ctx-only change: let `spec` handle it.
    result = run_spec_script('spec', spec_arg)
    if not result['success']:
        return f"[WARNING] Failed to apply --spec: {result['action']}", None

    parts = []
    if project and project != '-':
        parts.append(f"project '{project}'")
    if ctx_refs:
        parts.append(f"context(s) {', '.join(ctx_refs)}")
    if parts:
        return f"[OK] Set {' and '.join(parts)}", None
    if spec_name == '-' or project == '-':
        return "[OK] Cleared --spec association", None
    return None, None


# ============================================================================
# LLM INTEGRATION HELPERS
# ============================================================================

def parse_llm_response(response, format='single-line'):
    """
    Parse claude -p output based on expected format.

    Args:
        response: Raw response from claude -p
        format: Expected format:
            - 'single-line': Extract first line only
            - 'title-body': Parse TITLE: and BODY: format
            - 'multiline': Return full response (default processing)

    Returns:
        Parsed value(s) depending on format:
        - single-line: str (first line)
        - title-body: tuple (title, body)
        - multiline: str (full response)

    Examples:
        >>> parse_llm_response("feat: add auth\n\nBody text", 'single-line')
        'feat: add auth'

        >>> parse_llm_response("TITLE: Add auth\nBODY: Full desc", 'title-body')
        ('Add auth', 'Full desc')
    """
    if format == 'single-line':
        return response.strip().split('\n')[0]

    elif format == 'title-body':
        # Parse TITLE: and BODY: format
        lines = response.strip().split('\n')
        title = None
        body_lines = []
        in_body = False

        for line in lines:
            if line.startswith('TITLE:'):
                title = line[6:].strip()
            elif line.startswith('BODY:'):
                body_lines.append(line[5:].strip())
                in_body = True
            elif in_body:
                body_lines.append(line)

        body = '\n'.join(body_lines).strip() if body_lines else ''
        return title, body

    else:  # multiline
        return response.strip()


def generate_via_claude_p(prompt, context_data):
    """
    Wrapper for claude -p calls with error handling.

    Used when CC != 1 (direct CLI mode).

    Args:
        prompt: The generation prompt
        context_data: Context to append to prompt

    Returns:
        str: Generated text from Claude

    Exits:
        1 if claude -p fails

    Examples:
        >>> prompt = "Generate a commit message"
        >>> context = "git status output..."
        >>> message = generate_via_claude_p(prompt, context)
    """
    full_prompt = prompt + "\n\n" + context_data

    result = subprocess.run(
        ['claude', '-p'],
        input=full_prompt,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        error("Failed to generate via claude -p", stderr_output=result.stderr)
        sys.exit(1)

    return result.stdout.strip()


# ============================================================================
# TEMPLATE FORMATTING
# ============================================================================

def format_template(template, data):
    """
    Safe template formatting with validation.

    Ensures all template variables exist in data before formatting.

    Args:
        template: Format string with {placeholders}
        data: Dict of values to substitute

    Returns:
        str: Formatted string

    Raises:
        SystemExit: If template variable not in data (with helpful message)

    Examples:
        >>> format_template("Branch: {branch}", {"branch": "main"})
        'Branch: main'

        >>> format_template("Branch: {branch}", {})
        # Error: Template variables not in data: ['branch']
    """
    # Find all template variables
    variables = re.findall(r'\{(\w+)\}', template)

    # Check all variables exist in data
    missing = [v for v in variables if v not in data]
    if missing:
        error(f"Template variables not in data: {missing}")
        sys.exit(1)

    try:
        return template.format(**data)
    except KeyError as e:
        error(f"Template formatting error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        error(f"Unexpected template error: {str(e)}")
        sys.exit(1)


# ============================================================================
# COMMIT HELPERS
# ============================================================================

def get_commit_info(commit_hash):
    """Get commit message and file count for output.

    Args:
        commit_hash: Short or full commit hash

    Returns:
        tuple: (message, files_changed)
    """
    result = run_git(
        ['log', '-1', '--format=%s', commit_hash],
        operation_description="get commit message",
        capture_output=True
    )
    message = result.stdout.strip()

    result = run_git(
        ['show', '--stat', '--oneline', commit_hash],
        operation_description="get commit stats",
        capture_output=True
    )
    lines = result.stdout.strip().split('\n')[1:]
    files_changed = len([l for l in lines if l.strip() and '|' in l])

    return message, files_changed


def commit_all(message, body=None):
    """
    Stage all changes, commit, and return commit info.

    Performs the standard commit sequence:
    1. git add -A
    2. Commit with message (and body if provided)
    3. Get commit hash and info

    Args:
        message: Commit subject line (required)
        body: Commit body (optional)

    Returns:
        tuple: (commit_hash, commit_message, files_changed)
    """
    run_git(['add', '-A'], operation_description="stage changes")

    if body:
        full_message = f"{message}\n\n{body}"
        run_git(['commit', '-m', full_message], operation_description="create commit")
    else:
        run_git(['commit', '-m', message], operation_description="create commit")

    result = run_git(
        ['rev-parse', 'HEAD'],
        operation_description="get commit hash",
        capture_output=True
    )
    commit_hash = result.stdout.strip()[:7]

    commit_message, files_changed = get_commit_info(commit_hash)
    return commit_hash, commit_message, files_changed


def generate_message_if_needed(provided_message, script_path):
    """Generate commit message if not provided (hybrid LLM approach).

    In CC mode, message must be provided (Claude generates it).
    In direct CLI mode, uses claude -p to generate from metadata prompts.

    Args:
        provided_message: User-provided message or None
        script_path: Path to calling script (for metadata parsing)

    Returns:
        str: Commit message
    """
    if provided_message:
        return provided_message

    if os.getenv('CC') == '1':
        error("empty commit message - provide a message as argument")
        sys.exit(1)

    prompt = get_prompt_from_metadata('message', script_path=script_path)
    if not prompt:
        error("No LLM generation prompt found in metadata for 'message' argument")
        sys.exit(1)

    context_cmds = get_context_commands_from_metadata('message', script_path=script_path)
    context_data = ""
    for cmd in context_cmds:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            context_data += f"\n{cmd}:\n{result.stdout}"

    message = generate_via_claude_p(prompt, context_data)
    return parse_llm_response(message, format='single-line')


def generate_body_if_needed(provided_body=None, script_path=None):
    """Generate commit body (always-llm-generated).

    In CC mode, returns provided body or empty string.
    In direct CLI mode, uses claude -p to generate from metadata prompts.

    Args:
        provided_body: User-provided body or None
        script_path: Path to calling script (for metadata parsing)

    Returns:
        str: Commit body (may be empty)
    """
    if provided_body:
        return provided_body

    if os.getenv('CC') == '1':
        return ""

    prompt = get_prompt_from_metadata('body', script_path=script_path)
    if not prompt:
        return ""

    context_cmds = get_context_commands_from_metadata('body', script_path=script_path)
    context_data = ""
    for cmd in context_cmds:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            context_data += f"\n{cmd}:\n{result.stdout}"

    body = generate_via_claude_p(prompt, context_data)
    return parse_llm_response(body, format='multiline')


# ============================================================================
# PR POLLING AND CI/CD STATUS
# ============================================================================

def extract_issue_from_branch(branch_name):
    """Extract issue number from branch name.

    Supports branch naming formats:
        - 49/qualifier (slash format from /issue)
        - sclaussen/49/qualifier (prefixed format)
        - 49-qualifier (legacy dash format)

    Args:
        branch_name: Branch name (e.g., '49/feature', 'sclaussen/49/git/auth', '292-dev-cd-bug')

    Returns:
        str: Issue number if found, None otherwise
    """
    if not branch_name:
        return None
    # Strip known prefix patterns (anything before the first digit sequence)
    # Match: optional-prefix + digits + separator (/, :, or -)
    match = re.match(r'^(?:[^0-9]*?)(\d+)[/:\-]', branch_name)
    if match:
        return match.group(1)
    return None


def build_pr_body(description, branch):
    """
    Add issue reference to PR body based on branch name.

    Extracts issue number from branch name and appends a reference.
    Uses cross-repo format when gh-issue-repo is configured.

    Args:
        description: PR description text
        branch: Branch name to extract issue number from

    Returns:
        str: PR body with issue reference appended if applicable
    """
    pr_body = description
    issue_num = extract_issue_from_branch(branch)
    if issue_num:
        try:
            from lib.ghlib import get_configured_issue_repo
            gh_issue_repo = get_configured_issue_repo()
        except ImportError:
            gh_issue_repo = None
        if gh_issue_repo:
            ref = f"{gh_issue_repo}#{issue_num}"
            keyword = "Related to"
        else:
            ref = f"#{issue_num}"
            keyword = "Fixes"
        if ref not in pr_body:
            pr_body = f"{pr_body}\n\n{keyword} {ref}"
    return pr_body


def get_pr_info(pr_number):
    """Get PR info including URLs.

    Args:
        pr_number: PR number

    Returns:
        dict: PR info with keys: pr_url, issue_url (if linked), actions_url
    """
    result = subprocess.run(
        ['gh', 'pr', 'view', str(pr_number), '--json', 'url,body,headRefName,statusCheckRollup'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
        info = {
            'pr_url': data.get('url', ''),
            'issue_url': None,
            'actions_url': None
        }

        pr_url = info['pr_url']
        repo_url = pr_url.rsplit('/pull/', 1)[0] if '/pull/' in pr_url else None

        # Extract linked issue from PR body (looks for "Fixes #123" or "Closes #123")
        body = data.get('body', '') or ''
        issue_match = re.search(r'(?:fixes|closes|resolves)\s+#(\d+)', body, re.IGNORECASE)
        if issue_match and repo_url:
            info['issue_url'] = f"{repo_url}/issues/{issue_match.group(1)}"
        else:
            # Try to extract from branch name
            branch_name = data.get('headRefName', '')
            issue_num = extract_issue_from_branch(branch_name)
            if issue_num and repo_url:
                info['issue_url'] = f"{repo_url}/issues/{issue_num}"

        # Get actions URL from first check's detailsUrl
        checks = data.get('statusCheckRollup', [])
        if checks:
            details_url = checks[0].get('detailsUrl', '')
            # Extract run URL: .../actions/runs/12345/job/67890 -> .../actions/runs/12345
            if '/actions/runs/' in details_url:
                run_part = details_url.split('/actions/runs/')[1]
                run_id = run_part.split('/')[0]
                repo_url = details_url.split('/actions/runs/')[0]
                info['actions_url'] = f"{repo_url}/actions/runs/{run_id}"

        return info
    except (json.JSONDecodeError, KeyError):
        return None


def get_pr_checks(pr_number):
    """Get the status of all checks for a PR.

    Args:
        pr_number: PR number to check

    Returns:
        tuple: (checks_list, error_message)
            checks_list: List of check dicts if successful, None if error
            error_message: Error message if failed, None if successful
    """
    result = subprocess.run(
        ['gh', 'pr', 'view', str(pr_number), '--json', 'statusCheckRollup'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, result.stderr.strip()

    try:
        data = json.loads(result.stdout)
        checks = data.get('statusCheckRollup', [])
        return checks, None
    except json.JSONDecodeError:
        return None, "Failed to parse checks JSON"


def analyze_checks(checks):
    """Analyze check results and return summary.

    Args:
        checks: List of check dicts from get_pr_checks

    Returns:
        dict: Analysis summary with keys:
            - total: Total number of checks
            - completed: Number of completed checks
            - passed: Number of passed checks
            - failed: List of failed check dicts
            - pending: List of pending check names
            - all_complete: Boolean if all checks complete
            - all_passed: Boolean if all checks passed
            - has_real_ci: Boolean if any check ran real CI (SUCCESS or FAILURE,
              not just SKIPPED/NEUTRAL). Used to distinguish fast-skipped checks
              from actual CI pipeline results.
    """
    total = len(checks)
    completed = 0
    passed = 0
    failed = []
    pending = []
    has_real_ci = False

    for check in checks:
        status = check.get('status', '').upper()
        conclusion = check.get('conclusion', '').upper()
        name = check.get('name', 'Unknown')

        if status == 'COMPLETED':
            completed += 1
            if conclusion in ('SUCCESS', 'NEUTRAL', 'SKIPPED'):
                passed += 1
                if conclusion == 'SUCCESS':
                    has_real_ci = True
            else:
                failed.append({
                    'name': name,
                    'conclusion': conclusion,
                    'url': check.get('detailsUrl', '')
                })
                has_real_ci = True
        else:
            pending.append(name)

    return {
        'total': total,
        'completed': completed,
        'passed': passed,
        'failed': failed,
        'pending': pending,
        'all_complete': total > 0 and completed == total,
        'all_passed': total > 0 and completed == total and len(failed) == 0,
        'has_failures': len(failed) > 0,
        'has_real_ci': has_real_ci
    }


def get_failed_check_logs(pr_number, check_name):
    """Fetch logs for a failed check.

    Args:
        pr_number: PR number
        check_name: Name of the failed check

    Returns:
        str: Log output (last 100 lines), or None if not found
    """
    result = subprocess.run(
        ['gh', 'pr', 'view', str(pr_number), '--json', 'statusCheckRollup'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
        checks = data.get('statusCheckRollup', [])

        for check in checks:
            if check.get('name') == check_name:
                link = check.get('detailsUrl', '')
                if '/runs/' in link:
                    run_id = link.split('/runs/')[-1].split('/')[0].split('?')[0]
                    log_result = subprocess.run(
                        ['gh', 'run', 'view', run_id, '--log-failed'],
                        capture_output=True, text=True
                    )
                    if log_result.returncode == 0:
                        lines = log_result.stdout.strip().split('\n')
                        return '\n'.join(lines[-100:])
    except (json.JSONDecodeError, KeyError, IndexError):
        pass

    return None


def format_duration(seconds):
    """Format duration in seconds to human-readable string.

    Args:
        seconds: Duration in seconds

    Returns:
        str: Formatted duration (e.g., '1m 45s', '2s')
    """
    if seconds < 60:
        return f"{seconds}s"
    else:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s"


def cleanup_branch_associations(branch):
    """
    Clean up dev.yaml branch associations for a deleted branch.

    Removes spec and meeting associations (spec, ctx, project,
    active-meeting, meeting-file) for the given branch. Also removes
    the empty branch key if all subkeys were cleaned.

    Args:
        branch: Branch name to clean up

    Returns:
        bool: True if any associations were cleaned up
    """
    try:
        from lib.devyaml import unset as yaml_unset, read_config

        repo = get_repo_name()
        if not repo:
            return False

        removed = False
        for category in ('spec', 'meeting'):
            for subkey in ('spec', 'ctx', 'project', 'active-meeting', 'meeting-file'):
                if yaml_unset(f'{category}.{repo}.branches.{branch}.{subkey}'):
                    removed = True
            config = read_config()
            branch_data = (config.get(category, {})
                                 .get(repo, {})
                                 .get('branches', {})
                                 .get(branch, {}))
            if not branch_data:
                yaml_unset(f'{category}.{repo}.branches.{branch}')
        return removed
    except Exception:
        return False


def cleanup_merged_branch(branch):
    """Clean up local branch after a successful merge.

    Switches to the default branch, force-deletes the merged branch locally,
    and removes any spec associations. Remote branch deletion is handled by
    --delete-branch on gh pr merge.

    All operations are best-effort (check=False) -- cleanup should not crash
    the script if something fails.

    Args:
        branch: Name of the branch that was merged

    Returns:
        list: Action strings describing what was done (for JSON output)
    """
    actions = []
    default_branch = get_default_branch()
    current = get_current_branch()

    # Switch to default branch if we're on the merged branch
    if current == branch:
        result = subprocess.run(
            ['git', 'checkout', default_branch],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            actions.append(f"switched to {default_branch}")
        else:
            print(f"Warning: could not switch to {default_branch}: {result.stderr.strip()}", file=sys.stderr)
            return actions  # Can't delete branch if we're still on it

    # Force-delete local branch (-D because squash merges aren't recognized as merged)
    result = subprocess.run(
        ['git', 'branch', '-D', branch],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        actions.append(f"deleted local branch {branch}")
    else:
        print(f"Warning: could not delete local branch: {result.stderr.strip()}", file=sys.stderr)

    # Clean up spec associations from dev.yaml
    try:
        from lib.speclib import disassociate_spec
        disassociate_spec(branch)
        actions.append(f"removed spec association for {branch}")
    except (ImportError, Exception):
        pass

    # Clean up legacy spec associations from git config (if any remain)
    result = subprocess.run(
        ['git', 'config', '--local', '--remove-section', f'spec.{branch}'],
        capture_output=True, text=True
    )

    return actions


def poll_cicd(pr_number, poll_interval=15, timeout_minutes=30, show_progress=True):
    """Poll CI/CD status until completion.

    Args:
        pr_number: PR number to poll
        poll_interval: Seconds between polls (default: 15)
        timeout_minutes: Timeout in minutes (default: 30)
        show_progress: Whether to print progress to stderr (default: True)

    Returns:
        dict: Poll result with keys:
            - status: 'passed' | 'failed' | 'timeout'
            - duration: Human-readable duration string (e.g., '1m 45s')
            - checks_complete: Number of completed checks
            - checks_total: Total number of checks
            - failed_checks: List of failed check dicts (if status == 'failed')
            - error_analyses: List of error analysis dicts (if status == 'failed')
            - pr_info: dict with pr_url, issue_url, actions_url
    """
    import time
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60
    no_checks_wait_time = 30  # Wait 30 seconds for checks to be queued before assuming no CI
    # Minimum grace period when statusCheckRollup shows "all complete" early.
    # GitHub Actions takes 60-90s to queue workflows after a push, and the
    # rollup can briefly show stale/pre-push checks as "all complete" before
    # newly-triggered workflows register. Without this grace, poll_cicd can
    # return "passed" based on pre-push checks and admin-merge a PR whose new
    # commits haven't actually been validated. 90s covers GitHub's queuing
    # delay for both real CI returning and SKIPPED/NEUTRAL edge cases.
    all_complete_min_wait = 90

    # Get PR info and display URLs at start
    pr_info = get_pr_info(pr_number)
    if show_progress and pr_info:
        print(f"\n[LIST] PR: {pr_info['pr_url']}", file=sys.stderr)
        if pr_info.get('issue_url'):
            print(f"[TICKET] Issue: {pr_info['issue_url']}", file=sys.stderr)
        if pr_info.get('actions_url'):
            print(f"[SYNC] Actions: {pr_info['actions_url']}", file=sys.stderr)
        print("", file=sys.stderr)

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout_seconds:
            return {
                'status': 'timeout',
                'duration': format_duration(int(elapsed)),
                'checks_complete': 0,
                'checks_total': 0,
                'message': f'Polling timed out after {timeout_minutes} minutes',
                'pr_info': pr_info
            }

        checks, check_error = get_pr_checks(pr_number)
        if check_error:
            if show_progress:
                print(f"Warning: Failed to get PR checks: {check_error}", file=sys.stderr)
            time.sleep(poll_interval)
            continue

        analysis = analyze_checks(checks)

        # If no checks are configured and we've waited long enough, treat as passed
        if analysis['total'] == 0 and elapsed >= no_checks_wait_time:
            if show_progress:
                print(f"[OK] No CI checks configured (considered passed)", file=sys.stderr)
            return {
                'status': 'passed',
                'duration': format_duration(int(elapsed)),
                'checks_complete': 0,
                'checks_total': 0,
                'pr_info': pr_info
            }

        if analysis['all_complete']:
            # Don't trust "all complete" until we've waited long enough for
            # all workflows to queue. GitHub Actions takes 60-90s to queue
            # workflows after a push, and statusCheckRollup can briefly show
            # pre-push or stale-cached "all complete" state before new runs
            # register. Without this grace, a just-pushed PR can be admin-merged
            # against CI results that never validated the new commits.
            if elapsed < all_complete_min_wait:
                if show_progress:
                    elapsed_str = format_duration(int(elapsed))
                    if not analysis['has_real_ci']:
                        print(f"[WAITING] Only skipped/neutral checks so far, waiting for real CI to queue... ({analysis['completed']}/{analysis['total']} checks complete, {elapsed_str})",
                              file=sys.stderr)
                    else:
                        print(f"[WAITING] Waiting for all workflows to queue... ({analysis['completed']}/{analysis['total']} checks complete, {elapsed_str})",
                              file=sys.stderr)
                time.sleep(poll_interval)
                continue

            result = {
                'status': 'passed' if analysis['all_passed'] else 'failed',
                'duration': format_duration(int(elapsed)),
                'checks_complete': analysis['completed'],
                'checks_total': analysis['total']
            }

            if not analysis['all_passed']:
                result['failed_checks'] = []
                for failed in analysis['failed']:
                    check_data = {
                        'name': failed['name'],
                        'conclusion': failed['conclusion'],
                        'url': failed['url']
                    }
                    logs = get_failed_check_logs(pr_number, failed['name'])
                    if logs:
                        check_data['logs'] = logs
                    result['failed_checks'].append(check_data)

            result['pr_info'] = pr_info
            return result
        else:
            if show_progress:
                elapsed_str = format_duration(int(elapsed))
                if analysis['total'] == 0:
                    print(f"[WAITING] Waiting for CI/CD checks to be queued... ({elapsed_str})",
                          file=sys.stderr)
                else:
                    print(f"[WAITING] Polling CI/CD... ({analysis['completed']}/{analysis['total']} checks complete, {elapsed_str})",
                          file=sys.stderr)

            time.sleep(poll_interval)


def handle_poll_merge(pr_number, admin_auto_merge=False, poll_interval=30,
                      timeout_minutes=30, branch=None):
    """Poll CI/CD and optionally merge with admin authority.

    Shared logic used by git-sync and branch-create.

    Args:
        pr_number: PR number (string or int)
        admin_auto_merge: Merge with admin authority on success
        poll_interval: Seconds between polls (default: 30)
        timeout_minutes: Max polling duration (default: 30)
        branch: Branch name for cleanup after merge

    Returns:
        tuple: (auto_merge_result, cleanup_actions, poll_result)
            - auto_merge_result: dict with status/duration/checks_passed, or None
            - cleanup_actions: list of cleanup action strings, or None
            - poll_result: raw poll_cicd result dict
    """
    # Verify the PR belongs to the current branch (prevent context contamination)
    if branch:
        pr_head_result = subprocess.run(
            ['gh', 'pr', 'view', str(pr_number), '--json', 'headRefName', '-q', '.headRefName'],
            capture_output=True, text=True
        )
        if pr_head_result.returncode == 0:
            pr_head = pr_head_result.stdout.strip()
            if pr_head and pr_head != branch:
                error(f"PR #{pr_number} belongs to branch '{pr_head}', not '{branch}'")
                sys.exit(1)

    print(f"Polling CI/CD for PR #{pr_number}...", file=sys.stderr)
    poll_result = poll_cicd(pr_number, poll_interval=poll_interval,
                            timeout_minutes=timeout_minutes, show_progress=True)

    auto_merge_result = None
    cleanup_actions = None

    if poll_result['status'] == 'passed':
        print(f"[OK] All checks passed ({poll_result['duration']})", file=sys.stderr)

        if admin_auto_merge:
            result = subprocess.run(
                ['gh', 'pr', 'merge', '--admin', '--squash', '--delete-branch', str(pr_number)],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                auto_merge_result = {
                    'status': 'merged',
                    'duration': poll_result['duration'],
                    'checks_passed': True
                }
                print(f"[OK] Merged PR #{pr_number} with admin authority", file=sys.stderr)

                if branch:
                    cleanup_actions = cleanup_merged_branch(branch)
                    if cleanup_actions:
                        print(f"[OK] Deleted branch '{branch}'", file=sys.stderr)
            else:
                auto_merge_result = {
                    'status': 'merge_failed',
                    'error': result.stderr.strip(),
                    'duration': poll_result['duration'],
                    'checks_passed': True
                }
                print(f"[--] Failed to merge PR: {result.stderr.strip()}", file=sys.stderr)
        else:
            auto_merge_result = {
                'status': 'checks_passed',
                'duration': poll_result['duration'],
                'checks_passed': True
            }

    elif poll_result['status'] == 'failed':
        print(f"[--] CI/CD failed ({poll_result['duration']})", file=sys.stderr)
        print("", file=sys.stderr)

        for check in poll_result.get('failed_checks', []):
            print(f"Failed check: {check['name']}", file=sys.stderr)
            if check.get('logs'):
                print(check['logs'], file=sys.stderr)
            print("", file=sys.stderr)

        print(f"PR #{pr_number} was NOT merged. Fix the issues and retry.", file=sys.stderr)

        auto_merge_result = {
            'status': 'failed',
            'duration': poll_result['duration'],
            'checks_passed': False,
            'failed_checks': poll_result.get('failed_checks', [])
        }

    else:  # timeout
        print("[--] Polling timed out after 30 minutes", file=sys.stderr)
        auto_merge_result = {
            'status': 'timeout',
            'checks_passed': False
        }

    return auto_merge_result, cleanup_actions, poll_result
