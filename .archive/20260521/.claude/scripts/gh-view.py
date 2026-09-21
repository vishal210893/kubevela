#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
#
# [tool.claude]
# description = "View GitHub issue details"
# model = "haiku"
#
# [[tool.claude.argument]]
# name = "issue-number"
# type = "required-passthrough"
# hint = "<issue-number>"
# description = "Issue number or URL to view"
#
# [tool.claude.output]
# prompt = """Only use the Bash tool. Do not output any text before or after the tool call."""
# ///

"""
View a GitHub issue with cache support.

Checks local cache first ($WSROOT/.claude/gh-issues-cache.json),
falls back to GitHub API if cache is missing or stale (> 1 hour old).

Usage:
    gh-view.py <issue-number>
"""

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
    BOLD = '\x1b[1m'
    DIM = '\x1b[2m'
    GREEN = '\x1b[32m'
    RED = '\x1b[31m'
    YELLOW = '\x1b[33m'
    CYAN = '\x1b[36m'
    MAGENTA = '\x1b[35m'


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


def load_issue_from_cache(cache_path: Path, issue_number: int) -> dict[str, Any] | None:
    """Load a specific issue from cache. Returns None if not found."""
    try:
        with open(cache_path) as f:
            issues = json.load(f)
        for issue in issues:
            if issue.get('number') == issue_number:
                return issue
        return None
    except (IOError, json.JSONDecodeError):
        return None


def parse_issue_number(arg: str) -> int | None:
    """Parse issue number from argument (number or URL)."""
    # Direct number
    if arg.isdigit():
        return int(arg)

    # GitHub URL: https://github.com/owner/repo/issues/123
    match = re.search(r'/issues/(\d+)', arg)
    if match:
        return int(match.group(1))

    return None


def format_labels(labels: list[dict[str, Any]]) -> str:
    """Format labels for display."""
    if not labels:
        return ''
    names = [l.get('name', '') for l in labels]
    return ', '.join(names)


def format_date(date_str: str | None) -> str:
    """Format ISO date string for display."""
    if not date_str:
        return 'N/A'
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M')
    except (ValueError, AttributeError):
        return date_str


def display_issue_from_cache(issue: dict[str, Any]) -> None:
    """Display issue from cache data."""
    print(f'{Colors.DIM}(from cache){Colors.RESET}\n')

    # Title and number
    state = issue.get('state', 'UNKNOWN').upper()
    state_color = Colors.GREEN if state == 'OPEN' else Colors.RED
    print(f"{Colors.BOLD}#{issue['number']}: {issue.get('title', 'No title')}{Colors.RESET}")
    print(f"{state_color}{state}{Colors.RESET}")
    print()

    # Labels
    labels = format_labels(issue.get('labels', []))
    if labels:
        print(f"{Colors.YELLOW}Labels:{Colors.RESET} {labels}")

    # Dates
    print(f"{Colors.DIM}Created:{Colors.RESET} {format_date(issue.get('createdAt'))}")
    print(f"{Colors.DIM}Updated:{Colors.RESET} {format_date(issue.get('updatedAt'))}")
    if issue.get('closedAt'):
        print(f"{Colors.DIM}Closed:{Colors.RESET} {format_date(issue.get('closedAt'))}")
    print()

    # Body
    body = issue.get('body', '').strip()
    if body:
        print(f"{Colors.CYAN}--- Description ---{Colors.RESET}")
        print(body)
        print()

    # Comments
    comments = issue.get('comments', [])
    if comments:
        print(f"{Colors.CYAN}--- Comments ({len(comments)}) ---{Colors.RESET}")
        for comment in comments:
            author = comment.get('author', {}).get('login', 'unknown')
            created = format_date(comment.get('createdAt'))
            body = comment.get('body', '').strip()
            print(f"\n{Colors.MAGENTA}@{author}{Colors.RESET} {Colors.DIM}({created}){Colors.RESET}")
            print(body)


def fetch_from_api(issue_number: int) -> dict[str, Any] | None:
    """Fetch issue from GitHub REST API.

    Uses 'gh api' to avoid the deprecated projectCards GraphQL field
    that causes 'gh issue view' to fail.
    """
    try:
        # Fetch issue details
        result = subprocess.run(
            ['gh', 'api', f'repos/{{owner}}/{{repo}}/issues/{issue_number}'],
            capture_output=True,
            text=True,
            check=True
        )
        issue = json.loads(result.stdout)

        # Fetch comments
        comments_result = subprocess.run(
            ['gh', 'api', f'repos/{{owner}}/{{repo}}/issues/{issue_number}/comments'],
            capture_output=True,
            text=True,
            check=True
        )
        comments = json.loads(comments_result.stdout)

        # Convert REST API format to cache format for display_issue_from_cache
        return {
            'number': issue.get('number'),
            'title': issue.get('title'),
            'state': issue.get('state', '').upper(),
            'body': issue.get('body', ''),
            'labels': issue.get('labels', []),
            'createdAt': issue.get('created_at'),
            'updatedAt': issue.get('updated_at'),
            'closedAt': issue.get('closed_at'),
            'comments': [
                {
                    'author': {'login': c.get('user', {}).get('login', 'unknown')},
                    'createdAt': c.get('created_at'),
                    'body': c.get('body', '')
                }
                for c in comments
            ]
        }
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f'Error fetching issue from API: {e}', file=sys.stderr)
        return None


def display_issue_from_api(issue: dict[str, Any]) -> None:
    """Display issue fetched from API."""
    print(f'{Colors.DIM}(from API){Colors.RESET}\n')

    # Title and number
    state = issue.get('state', 'UNKNOWN').upper()
    state_color = Colors.GREEN if state == 'OPEN' else Colors.RED
    print(f"{Colors.BOLD}#{issue['number']}: {issue.get('title', 'No title')}{Colors.RESET}")
    print(f"{state_color}{state}{Colors.RESET}")
    print()

    # Labels
    labels = format_labels(issue.get('labels', []))
    if labels:
        print(f"{Colors.YELLOW}Labels:{Colors.RESET} {labels}")

    # Dates
    print(f"{Colors.DIM}Created:{Colors.RESET} {format_date(issue.get('createdAt'))}")
    print(f"{Colors.DIM}Updated:{Colors.RESET} {format_date(issue.get('updatedAt'))}")
    if issue.get('closedAt'):
        print(f"{Colors.DIM}Closed:{Colors.RESET} {format_date(issue.get('closedAt'))}")
    print()

    # Body
    body = issue.get('body', '').strip()
    if body:
        print(f"{Colors.CYAN}--- Description ---{Colors.RESET}")
        print(body)
        print()

    # Comments
    comments = issue.get('comments', [])
    if comments:
        print(f"{Colors.CYAN}--- Comments ({len(comments)}) ---{Colors.RESET}")
        for comment in comments:
            author = comment.get('author', {}).get('login', 'unknown')
            created = format_date(comment.get('createdAt'))
            body = comment.get('body', '').strip()
            print(f"\n{Colors.MAGENTA}@{author}{Colors.RESET} {Colors.DIM}({created}){Colors.RESET}")
            print(body)


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print('Usage: gh-view.py <issue-number|url>', file=sys.stderr)
        return 1

    issue_number = parse_issue_number(sys.argv[1])
    if issue_number is None:
        print(f'Error: Cannot parse issue number from: {sys.argv[1]}', file=sys.stderr)
        return 1

    # Try cache first
    cache_path = get_cache_path()
    if cache_path and is_cache_fresh(cache_path):
        issue = load_issue_from_cache(cache_path, issue_number)
        if issue:
            display_issue_from_cache(issue)
            return 0

    # Fall back to REST API
    issue = fetch_from_api(issue_number)
    if issue:
        display_issue_from_api(issue)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
