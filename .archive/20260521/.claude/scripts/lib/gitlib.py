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
        'issue-tracker': 'gh',
        'issue-in-branch': False,
        'spec-in-branch': False,
    }

_register_repo_defaults('git', _git_repo_defaults)


# ============================================================================
# CORE GIT OPERATIONS (EXISTING FUNCTIONS - PRESERVED)
# ============================================================================

def run(cmd, check=True):
    """
    Execute shell command with echo output.

    DEPRECATED: Use run_git() instead for git commands.

    Args:
        cmd: Shell command string to execute
        check: Exit on non-zero return code (default True)

    Returns:
        CompletedProcess result

    Exits:
        With command's return code if check=True and command fails
    """
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result


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
        'git rev-parse --abbrev-ref HEAD',
        shell=True, capture_output=True, text=True
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
        'git symbolic-ref refs/remotes/origin/HEAD',
        shell=True, capture_output=True, text=True
    )
    if result.returncode == 0:
        # Output is like: refs/remotes/origin/main
        branch = result.stdout.strip().split('/')[-1]
        return branch

    # Fallback: check if main exists locally
    result = subprocess.run(
        'git rev-parse --verify main',
        shell=True, capture_output=True, text=True
    )
    if result.returncode == 0:
        return 'main'

    # Fallback: check if master exists locally
    result = subprocess.run(
        'git rev-parse --verify master',
        shell=True, capture_output=True, text=True
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
        'git rev-parse --show-toplevel',
        shell=True, capture_output=True, text=True
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
        f'git rev-parse --verify {branch_name}',
        shell=True, capture_output=True, text=True
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
        f'git ls-remote --heads {repo_url} {branch_name}',
        shell=True, capture_output=True, text=True
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
    cmd = 'git status --porcelain'
    if path:
        cmd = f'git -C {path} status --porcelain'
    result = subprocess.run(
        cmd,
        shell=True, capture_output=True, text=True
    )
    return len(result.stdout.strip()) > 0


# ============================================================================
# OUTPUT & ERROR HANDLING (NEW FUNCTIONS)
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


# ============================================================================
# VALIDATION FUNCTIONS (NEW FUNCTIONS)
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


def check_main_clean():
    """
    Check if main branch has uncommitted changes and error if so.

    Used before operations that require clean main (like worktree-add).

    Exits:
        1 if main has uncommitted changes

    Examples:
        >>> check_main_clean()  # Ensures main is clean before proceeding
    """
    if has_uncommitted_changes():
        error("Main branch has uncommitted changes")
        print("Commit or stash changes before proceeding", file=sys.stderr)
        sys.exit(1)


def check_branch_pushed(branch, repo_url):
    """
    Check if a branch has been pushed to remote.

    Args:
        branch: Branch name to check
        repo_url: Authenticated repository URL

    Returns:
        bool: True if branch exists on remote

    Examples:
        >>> repo_url = get_repo_url()
        >>> if not check_branch_pushed('feature', repo_url):
        ...     print("Branch not pushed yet")
    """
    return remote_branch_exists(branch, repo_url)


def check_rebased_on_main():
    """
    Check if current branch is rebased on latest main (no divergence).

    Returns:
        bool: True if branch is up-to-date with main (no rebase needed)

    Examples:
        >>> if not check_rebased_on_main():
        ...     print("Branch needs rebasing on main")
    """
    # Get merge base between current branch and origin/main
    result = subprocess.run(
        'git merge-base HEAD origin/main',
        shell=True, capture_output=True, text=True
    )
    if result.returncode != 0:
        return False
    merge_base = result.stdout.strip()

    # Get origin/main commit
    result = subprocess.run(
        'git rev-parse origin/main',
        shell=True, capture_output=True, text=True
    )
    if result.returncode != 0:
        return False
    main_commit = result.stdout.strip()

    # If merge base equals origin/main, we're up-to-date
    return merge_base == main_commit


# ============================================================================
# PEP 723 METADATA PARSING (NEW FUNCTIONS)
# ============================================================================

def parse_pep723_metadata(script_path=None):
    """
    Parse PEP 723 metadata from a script file.

    Extracts the [tool.claude] section from the PEP 723 metadata block.

    Args:
        script_path: Path to script (defaults to current script via __file__)

    Returns:
        dict: Parsed [tool.claude] section as nested dict

    Examples:
        >>> metadata = parse_pep723_metadata()
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

    if script_path is None:
        # Get calling script's path
        import inspect
        frame = inspect.currentframe().f_back
        script_path = frame.f_globals.get('__file__')

    if not script_path:
        error("Could not determine script path")
        sys.exit(1)

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

    return metadata.get('tool', {}).get('claude', {})


def get_prompt_from_metadata(arg_name, script_path=None):
    """
    Extract LLM generation prompt for a specific argument.

    Args:
        arg_name: Name of the argument (e.g., 'message', 'body', 'title')
        script_path: Path to script (defaults to current script)

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


def get_context_commands_from_metadata(arg_name, script_path=None):
    """
    Extract context-gathering commands for LLM generation.

    Args:
        arg_name: Name of the argument
        script_path: Path to script

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


def get_template_from_metadata(script_path=None):
    """
    Extract output template from metadata.

    Args:
        script_path: Path to script (defaults to current script)

    Returns:
        str: The template string from [tool.claude.output]

    Examples:
        >>> template = get_template_from_metadata()
        >>> print(template)
        '[OK] Created commit {commit_hash}\n{message}'
    """
    metadata = parse_pep723_metadata(script_path)
    return metadata.get('output', {}).get('template')


# ============================================================================
# LLM INTEGRATION HELPERS (NEW FUNCTIONS)
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
        'claude -p',
        shell=True,
        input=full_prompt,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        error("Failed to generate via claude -p", stderr_output=result.stderr)
        sys.exit(1)

    return result.stdout.strip()


# ============================================================================
# TEMPLATE FORMATTING (NEW FUNCTIONS)
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
# PR POLLING AND CI/CD STATUS
# ============================================================================

def extract_issue_from_branch(branch_name):
    """Extract issue number from branch name.

    Supports all branch naming formats:
        - 49/qualifier (new slash format)
        - 49:spec/qualifier (new colon-spec format)
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
    """
    total = len(checks)
    completed = 0
    passed = 0
    failed = []
    pending = []

    for check in checks:
        status = check.get('status', '').upper()
        conclusion = check.get('conclusion', '').upper()
        name = check.get('name', 'Unknown')

        if status == 'COMPLETED':
            completed += 1
            if conclusion in ('SUCCESS', 'NEUTRAL', 'SKIPPED'):
                passed += 1
            else:
                failed.append({
                    'name': name,
                    'conclusion': conclusion,
                    'url': check.get('detailsUrl', '')
                })
        else:
            pending.append(name)

    return {
        'total': total,
        'completed': completed,
        'passed': passed,
        'failed': failed,
        'pending': pending,
        'all_complete': total > 0 and completed == total,
        'all_passed': total > 0 and completed == total and len(failed) == 0
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


def analyze_error(logs, check_name):
    """Analyze error logs and extract key information.

    Args:
        logs: Raw log output from failed check
        check_name: Name of the check that failed

    Returns:
        dict: Error analysis with keys:
            - check_name: Name of the failed check
            - error_type: Type of error (test failure, build error, lint error, etc.)
            - error_message: Primary error message
            - root_cause: Analysis of root cause
            - recommendation: Suggested fix
            - affected_files: List of affected file paths
    """
    analysis = {
        'check_name': check_name,
        'error_type': 'Unknown error',
        'error_message': 'See logs for details',
        'root_cause': 'Unable to determine root cause',
        'recommendation': 'Review the full logs for more details',
        'affected_files': []
    }

    if not logs:
        return analysis

    # Detect error type
    if 'FAILED' in logs.upper() and 'test' in logs.lower():
        analysis['error_type'] = 'Test assertion failed'
    elif 'error' in logs.lower() and 'compile' in logs.lower():
        analysis['error_type'] = 'Compilation error'
    elif 'error' in logs.lower() and ('lint' in logs.lower() or 'eslint' in logs.lower()):
        analysis['error_type'] = 'Linting error'
    elif 'error' in logs.lower() and 'syntax' in logs.lower():
        analysis['error_type'] = 'Syntax error'

    # Extract error message
    error_lines = []
    for line in logs.split('\n'):
        if any(keyword in line.upper() for keyword in ['ERROR:', 'FAIL:', 'FAILED:', 'ASSERTION']):
            error_lines.append(line.strip())

    if error_lines:
        analysis['error_message'] = error_lines[0]

    # Extract file paths
    file_pattern = r'(?:(?:at|in|from)\s+)?([a-zA-Z0-9_/.@-]+\.[a-z]+)(?::\d+)?'
    files = set()
    for match in re.finditer(file_pattern, logs):
        file_path = match.group(1)
        if not any(x in file_path for x in ['node_modules', 'http://', 'https://']):
            if '/' in file_path:
                files.add(file_path)

    analysis['affected_files'] = sorted(list(files))[:5]

    # Generate root cause and recommendation based on error type
    if 'test' in analysis['error_type'].lower():
        analysis['root_cause'] = 'Test assertion did not match expected value'
        analysis['recommendation'] = 'Update test expectation or fix the implementation'
    elif 'lint' in analysis['error_type'].lower():
        analysis['root_cause'] = 'Code style or linting rule violation'
        analysis['recommendation'] = 'Fix linting errors or update linting rules'
    elif 'compile' in analysis['error_type'].lower():
        analysis['root_cause'] = 'Code fails to compile'
        analysis['recommendation'] = 'Fix compilation errors in affected files'
    elif 'syntax' in analysis['error_type'].lower():
        analysis['root_cause'] = 'Invalid syntax in code'
        analysis['recommendation'] = 'Fix syntax errors in affected files'

    return analysis


def format_error_analysis(analysis):
    """Format error analysis for Claude conversation output.

    Args:
        analysis: Error analysis dict from analyze_error()

    Returns:
        str: Formatted error analysis string
    """
    lines = [
        "ERROR ANALYSIS",
        "-" * 60,
        f"Check: {analysis['check_name']}",
        f"Error: {analysis['error_type']}",
        "",
        "Root cause:",
        f"  {analysis['root_cause']}",
        "",
        "Recommendation:",
        f"  {analysis['recommendation']}"
    ]

    if analysis.get('affected_files'):
        lines.append("")
        lines.append("Affected files:")
        for file in analysis['affected_files']:
            lines.append(f"  - {file}")

    return '\n'.join(lines)


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
            # all workflows to queue. GitHub Actions queues workflows at
            # different times -- a fast SKIPPED check can appear "all done"
            # before the real CI pipeline is even queued.
            if elapsed < no_checks_wait_time:
                if show_progress:
                    elapsed_str = format_duration(int(elapsed))
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
                result['failed_checks'] = analysis['failed']
                result['error_analyses'] = []

                for failed in analysis['failed']:
                    logs = get_failed_check_logs(pr_number, failed['name'])
                    error_analysis = analyze_error(logs, failed['name'])
                    result['error_analyses'].append(error_analysis)

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
