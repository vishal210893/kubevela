#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
#
# [tool.claude]
# description = "List GitHub issues"
# model = "haiku"
#
# [[tool.claude.argument]]
# name = "filter"
# type = "optional-passthrough"
# hint = "[filter]"
# description = "Filter by label (P1, bug, feature), assignee (@username), or state (open, closed, all)"
#
# [tool.claude.output]
# prompt = """Only use the Bash tool. Do not output any text before or after the tool call."""
# ///

"""
List GitHub issues with priority sorting and colored output.

Checks local cache first ($WSROOT/.claude/gh-issues-cache.json),
falls back to GitHub API if cache is missing or stale (> 1 hour old).
Sorts by priority (P1-P5 labels) and title, with colored terminal output.

Accepts optional filter argument:
- Label: P1, P2, P3, P4, P5, bug, feature, documentation, etc.
- Assignee: @username
- State: open, closed, all
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ANSI color codes
class Colors:
    RESET = '\x1b[0m'
    BLUE = '\x1b[94m'  # bright blue
    GREEN = '\x1b[32m'
    RED = '\x1b[31m'
    YELLOW = '\x1b[33m'
    CYAN = '\x1b[36m'
    DIM = '\x1b[2m'
    NO_UNDERLINE = '\x1b[24m'


def link(url: str, text: str) -> str:
    """Create a terminal hyperlink (OSC 8) with no underline."""
    return f'\x1b]8;;{url}\x07{Colors.NO_UNDERLINE}{text}\x1b]8;;\x07'


def get_workspace_root() -> Path | None:
    """Get workspace root from WSROOT env var or git root."""
    if ws := os.environ.get('WSROOT'):
        return Path(ws)

    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True,
            text=True,
            check=True
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return None


def get_cache_path() -> Path | None:
    """Get the cache file path."""
    ws = get_workspace_root()
    if ws:
        return ws / '.claude' / 'gh-issues-cache.json'
    return None


def is_cache_fresh(cache_path: Path, max_age_seconds: int = 3600) -> bool:
    """Check if cache file exists and is fresh (< max_age_seconds old)."""
    if not cache_path.exists():
        return False

    stat = cache_path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    age = (datetime.now(tz=timezone.utc) - mtime).total_seconds()
    return age < max_age_seconds


def load_from_cache(cache_path: Path) -> list[dict[str, Any]] | None:
    """Load issues from cache file. Returns None if cache is unavailable."""
    try:
        with open(cache_path) as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return None


def get_current_repo() -> str:
    """Get current repository name from gh CLI."""
    try:
        result = subprocess.run(
            ['gh', 'repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print('Error: Cannot fetch current repository.', file=sys.stderr)
        print(f'Details: {e}', file=sys.stderr)
        print('Ensure you are:', file=sys.stderr)
        print('1. Inside a Git repository', file=sys.stderr)
        print('2. GitHub CLI (gh) is installed', file=sys.stderr)
        print('3. Authenticated with gh CLI (`gh auth login`)', file=sys.stderr)
        sys.exit(1)


def get_priority(labels: list[dict[str, Any]]) -> int:
    """Extract priority from labels (P1, P2, P3, etc.)."""
    for label in labels:
        match = re.match(r'^P([1-5])$', label['name'], re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 99  # No priority = sort last


def get_priority_color(priority: int) -> str:
    """Get ANSI color for priority level."""
    if priority == 1:
        return Colors.RED
    elif priority == 2:
        return Colors.YELLOW
    elif priority == 3:
        return Colors.GREEN
    else:
        return Colors.DIM


def get_state(issue: dict[str, Any]) -> str:
    """Get state from issue labels (working, pr, or empty)."""
    for label in issue['labels']:
        name = label['name'].lower()
        if name in ('pr', 'has-pr'):
            return 'pr'
        if name in ('working', 'in-progress', 'in progress', 'wip'):
            return 'working'
    return ''


def format_state(state: str) -> str:
    """Format state as 7 chars left-justified."""
    return (state or '').ljust(7)


def parse_filter(filter_arg: str | None) -> tuple[str, str | None, str | None]:
    """
    Parse filter argument and determine type.

    Returns (state, label, assignee):
    - If filter starts with @: assignee filter
    - If filter is "open", "closed", or "all": state filter
    - Otherwise: label filter
    - If no filter: default to state=open
    """
    if filter_arg is None:
        return ('open', None, None)

    filter_lower = filter_arg.lower()

    # Check if it's an assignee (starts with @)
    if filter_arg.startswith('@'):
        return ('open', None, filter_arg)

    # Check if it's a state filter
    if filter_lower in ('open', 'closed', 'all'):
        return (filter_lower, None, None)

    # Otherwise, treat as label filter (keep state=open by default)
    return ('open', filter_arg, None)


def fetch_issues_from_api(repo: str, state: str = 'open', label: str | None = None, assignee: str | None = None) -> list[dict[str, Any]] | None:
    """Fetch issues from GitHub API with optional filters."""
    try:
        cmd = ['gh', 'issue', 'list', '--repo', repo, '--state', state, '--limit', '500']

        # Add label filter if specified
        if label:
            cmd.extend(['--label', label])

        # Add assignee filter if specified
        if assignee:
            cmd.extend(['--assignee', assignee])

        cmd.extend(['--json', 'number,title,url,labels'])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f'Error: Failed to fetch issues from API: {e}', file=sys.stderr)
        return None


def main() -> int:
    """Main entry point."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='List GitHub issues with optional filters.')
    parser.add_argument('filter', nargs='?', help='Filter by label, assignee (@username), or state (open/closed/all)')
    args = parser.parse_args()

    # Parse the filter argument
    state, label, assignee = parse_filter(args.filter)

    repo = get_current_repo()
    issues = None
    source = 'api'

    # If using filters, skip cache and go straight to API
    # Cache is only used for default state=open with no filters
    use_cache = (state == 'open' and label is None and assignee is None)

    # Try cache first (only if no filters)
    if use_cache:
        cache_path = get_cache_path()
        if cache_path and is_cache_fresh(cache_path):
            cached_issues = load_from_cache(cache_path)
            if cached_issues:
                # Cache contains all issues, filter to open only
                issues = [i for i in cached_issues if i.get('state', '').upper() == 'OPEN']
                # Ensure URL field exists (cache may have different structure)
                for issue in issues:
                    if 'url' not in issue:
                        issue['url'] = f"https://github.com/{repo}/issues/{issue['number']}"
                source = 'cache'

    # Fall back to API if no cache or if using filters
    if issues is None:
        issues = fetch_issues_from_api(repo, state, label, assignee)
        if issues is None:
            return 1

    if not issues:
        print('No issues found.')
        return 0

    # Add priority and sort by priority, then by title
    for issue in issues:
        issue['priority'] = get_priority(issue['labels'])

    sorted_issues = sorted(issues, key=lambda i: (i['priority'], i['title']))

    # Show source indicator
    if source == 'cache':
        print(f'{Colors.DIM}(from cache){Colors.RESET}\n')

    # Output each issue on a single line
    for issue in sorted_issues:
        num = str(issue['number']).rjust(3)
        prio = f"P{issue['priority']}" if issue['priority'] < 99 else '  '
        prio_color = get_priority_color(issue['priority'])
        linked_num = link(issue['url'], num)
        state = format_state(get_state(issue))

        print(f"{Colors.BLUE}{linked_num}{Colors.RESET} "
              f"{prio_color}{prio}{Colors.RESET} "
              f"{Colors.CYAN}{state}{Colors.RESET} "
              f"{issue['title']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
