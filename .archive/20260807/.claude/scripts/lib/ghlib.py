#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = []
# ///

"""
GitHub issue operations for Claude Code.
Shared functionality for fetching and formatting issues.
"""

import subprocess
import json
import sys
from pathlib import Path

# Ensure lib dir is on path for devyaml import
_lib_dir = str(Path(__file__).parent)
if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)
from devyaml import register_repo_defaults as _register_repo_defaults, get as _yaml_get


def _gh_repo_defaults(repo):
    """Return default config for a new gh repo section."""
    return {
        'gh-issue-repo': get_current_owner_repo(),
    }

_register_repo_defaults('gh', _gh_repo_defaults)


def check_gh_available():
    """Check if gh CLI is available.

    Returns:
        bool: True if gh is available
    """
    try:
        result = subprocess.run(
            ['gh', '--version'],
            capture_output=True,
            check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def check_gh_authenticated():
    """Check if gh CLI is authenticated.

    Returns:
        bool: True if authenticated
    """
    result = subprocess.run(
        ['gh', 'auth', 'status'],
        capture_output=True,
        check=False
    )
    return result.returncode == 0


def _get_repo_name():
    """Extract repo name (last segment) from origin remote URL."""
    from gitlib import get_repo_name
    return get_repo_name()


def get_current_owner_repo():
    """Get the current repo as owner/repo from git remote origin.

    Returns:
        str: 'owner/repo' string, or None if cannot determine
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

    # Normalize: strip .git suffix and trailing slash
    if url.endswith('.git'):
        url = url[:-4]
    url = url.rstrip('/')

    # Handle both https and ssh formats:
    #   https://github.com/owner/repo  -> owner/repo
    #   git@github.com:owner/repo      -> owner/repo
    url = url.replace(':', '/')
    parts = url.split('/')
    if len(parts) >= 2:
        return '/'.join(parts[-2:]).lower()
    return None


def get_configured_issue_repo():
    """Get configured gh-issue-repo from dev.yaml."""
    repo = _get_repo_name()
    if not repo:
        return None
    value = _yaml_get(f'gh.{repo}.gh-issue-repo')
    return value if value else None


def get_effective_issue_repo():
    """Get the effective issue repo: configured value or current repo as default.

    Returns:
        str: 'owner/repo' string (configured or derived from current remote)
        None: if cannot determine
    """
    configured = get_configured_issue_repo()
    if configured:
        return configured
    return get_current_owner_repo()


def get_gh_repo_args(repo=None):
    """Get --repo arguments for gh commands.

    When repo is None, reads from config (gen2 global, gen1 local).
    When no config exists, defaults to current repo from git remote.

    Args:
        repo: Explicit repo override (owner/repo format), or None to auto-detect

    Returns:
        list: ['--repo', 'owner/repo'] always (using current repo as default)
    """
    if repo is None:
        repo = get_configured_issue_repo()
        if repo is None:
            repo = get_current_owner_repo()

    if repo:
        return ['--repo', repo]
    return []


def fetch_issue(issue_number, repo=None):
    """Fetch GitHub issue details.

    Args:
        issue_number: Issue number to fetch
        repo: Optional owner/repo for cross-repo issue tracking

    Returns:
        dict: Issue data with keys: number, title, body, labels, assignees,
              milestone, html_url, state
        None: If issue doesn't exist or fetch fails

    Raises:
        RuntimeError: If gh CLI not available or not authenticated
    """
    # Check prerequisites
    if not check_gh_available():
        raise RuntimeError(
            "GitHub CLI (gh) is not installed.\n"
            "Install it from: https://cli.github.com/"
        )

    if not check_gh_authenticated():
        raise RuntimeError(
            "GitHub CLI is not authenticated.\n"
            "Run: gh auth login"
        )

    # Fetch issue
    repo_args = get_gh_repo_args(repo)
    result = subprocess.run(
        [
            'gh', 'issue', 'view', str(issue_number),
            '--json', 'number,title,body,labels,assignees,milestone,url,state'
        ] + repo_args,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        # Issue doesn't exist or other error
        return None

    try:
        issue_data = json.loads(result.stdout)
        return {
            'number': issue_data.get('number'),
            'title': issue_data.get('title', ''),
            'body': issue_data.get('body', ''),
            'labels': [l['name'] for l in issue_data.get('labels', [])],
            'assignees': [a['login'] for a in issue_data.get('assignees', [])],
            'milestone': issue_data.get('milestone', {}).get('title') if issue_data.get('milestone') else None,
            'html_url': issue_data.get('url', ''),
            'state': issue_data.get('state', 'open')
        }
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing issue data: {e}", file=sys.stderr)
        return None


def format_issue_for_spec(issue):
    """Format issue data for spec reqs.md file.

    Args:
        issue: Issue dict from fetch_issue()

    Returns:
        str: Formatted markdown content for reqs.md
    """
    content = f"""# {issue['title']}

**Source**: GitHub Issue [#{issue['number']}]({issue['html_url']})
**Status**: {issue['state']}

"""

    # Add labels if present
    if issue['labels']:
        labels_str = ', '.join(f"`{label}`" for label in issue['labels'])
        content += f"**Labels**: {labels_str}  \n"

    # Add assignees if present
    if issue['assignees']:
        assignees_str = ', '.join(f"@{assignee}" for assignee in issue['assignees'])
        content += f"**Assignees**: {assignees_str}  \n"

    # Add milestone if present
    if issue['milestone']:
        content += f"**Milestone**: {issue['milestone']}  \n"

    content += "\n## Overview\n\n"

    # Add issue body
    if issue['body']:
        content += issue['body'] + "\n\n"
    else:
        content += "[No description provided]\n\n"

    # Add template sections
    content += """## Requirements

### Requirement 1: [Feature Area - refine from issue description above]

**User Story:** As a [role], I want [capability], so that [benefit]

#### Acceptance Criteria

1. WHEN [event] THE SYSTEM SHALL [action]
2. WHEN [event] AND [condition] THE SYSTEM SHALL [action]
3. IF [condition] THEN THE SYSTEM SHALL [action]

### Requirement 2: [Feature Area]

**User Story:** As a [role], I want [capability], so that [benefit]

#### Acceptance Criteria

1. WHEN [event] THE SYSTEM SHALL [action]
2. WHILE [state] THE SYSTEM SHALL [action]

## Constraints

- [Technical or business constraint]

## Notes

This spec was seeded from the GitHub issue above. Refine with `/spec:requirements` or `/spec:interview`.
"""

    return content


def format_issue_for_context(issue):
    """Format issue data for Claude session context.

    Args:
        issue: Issue dict from fetch_issue()

    Returns:
        str: Formatted text for injection into Claude context
    """
    context = f"""GitHub Issue #{issue['number']}: {issue['title']}

URL: {issue['html_url']}
Status: {issue['state']}
"""

    if issue['labels']:
        context += f"Labels: {', '.join(issue['labels'])}\n"

    if issue['body']:
        context += f"\nDescription:\n{issue['body']}\n"

    return context
