#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
GitHub issue cache management.

Downloads and manages the gh-issues-cache.json artifact from GitHub Actions.
Cache is stored in $WSROOT/.claude/gh-issues-cache.json.

Usage:
    gh-issue-cache.py refresh     # Download latest artifact to cache
    gh-issue-cache.py status      # Show cache status (age, count)
    gh-issue-cache.py path        # Print cache file path
"""

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def get_workspace_root() -> Path:
    """Get workspace root from WSROOT env var or git root."""
    if ws := os.environ.get('WSROOT'):
        return Path(ws)

    # Fall back to git root
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True,
            text=True,
            check=True
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        print('Error: Cannot determine workspace root.', file=sys.stderr)
        print('Set WSROOT or run from a git repository.', file=sys.stderr)
        sys.exit(1)


def get_cache_path() -> Path:
    """Get the cache file path."""
    return get_workspace_root() / '.claude' / 'gh-issues-cache.json'


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
        print('Error: Cannot determine repository.', file=sys.stderr)
        sys.exit(1)


def download_artifact() -> bool:
    """Download the latest gh-issues-cache artifact from GitHub Actions."""
    repo = get_current_repo()
    cache_path = get_cache_path()

    # Ensure .claude directory exists
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # Find the latest artifact
    try:
        result = subprocess.run(
            ['gh', 'api', f'repos/{repo}/actions/artifacts',
             '--jq', '.artifacts[] | select(.name == "gh-issues-cache") | .id',
             '--paginate'],
            capture_output=True,
            text=True,
            check=True
        )

        artifact_ids = result.stdout.strip().split('\n')
        if not artifact_ids or not artifact_ids[0]:
            print('No gh-issues-cache artifact found.', file=sys.stderr)
            print('Run the gh-issue-sync workflow first, or use gh issue list directly.', file=sys.stderr)
            return False

        # Get the first (most recent) artifact
        artifact_id = artifact_ids[0]

        # Download artifact to temp file
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / 'artifact.zip'

            subprocess.run(
                ['gh', 'api', f'repos/{repo}/actions/artifacts/{artifact_id}/zip',
                 '--output', str(zip_path)],
                check=True,
                capture_output=True
            )

            # Extract the JSON file
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Find the JSON file in the archive
                json_files = [f for f in zf.namelist() if f.endswith('.json')]
                if not json_files:
                    print('No JSON file found in artifact.', file=sys.stderr)
                    return False

                # Extract to cache path
                with zf.open(json_files[0]) as src:
                    cache_path.write_bytes(src.read())

        print(f'Cache updated: {cache_path}')
        return True

    except subprocess.CalledProcessError as e:
        print(f'Error: Failed to download artifact: {e}', file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return False


def get_cache_status() -> dict:
    """Get cache status information."""
    cache_path = get_cache_path()

    if not cache_path.exists():
        return {'exists': False, 'path': str(cache_path)}

    stat = cache_path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    age_seconds = (datetime.now(tz=timezone.utc) - mtime).total_seconds()

    try:
        with open(cache_path) as f:
            issues = json.load(f)
        issue_count = len(issues)
    except (json.JSONDecodeError, IOError):
        issue_count = -1

    return {
        'exists': True,
        'path': str(cache_path),
        'mtime': mtime.isoformat(),
        'age_seconds': age_seconds,
        'age_hours': age_seconds / 3600,
        'issue_count': issue_count,
        'fresh': age_seconds < 3600  # Fresh if < 1 hour old
    }


def cmd_refresh() -> int:
    """Refresh the cache by downloading latest artifact."""
    if download_artifact():
        status = get_cache_status()
        print(f"Issues cached: {status.get('issue_count', 'unknown')}")
        return 0
    return 1


def cmd_status() -> int:
    """Show cache status."""
    status = get_cache_status()

    if not status['exists']:
        print(f"Cache: not found")
        print(f"Path: {status['path']}")
        print(f"\nRun 'gh-issue-cache.py refresh' to download.")
        return 1

    hours = status['age_hours']
    freshness = 'fresh' if status['fresh'] else 'stale'

    print(f"Cache: {freshness}")
    print(f"Path: {status['path']}")
    print(f"Age: {hours:.1f} hours")
    print(f"Issues: {status['issue_count']}")

    if not status['fresh']:
        print(f"\nCache is stale. Run 'gh-issue-cache.py refresh' to update.")

    return 0


def cmd_path() -> int:
    """Print cache file path."""
    print(get_cache_path())
    return 0


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]

    if cmd == 'refresh':
        return cmd_refresh()
    elif cmd == 'status':
        return cmd_status()
    elif cmd == 'path':
        return cmd_path()
    else:
        print(f"Error: Unknown command: {cmd}", file=sys.stderr)
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
