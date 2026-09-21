#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
CAPABILITY: Configures git safe directories to prevent ownership errors

Automatically configures git safe.directory for all repositories under /workspaces.
This prevents "dubious ownership" errors that occur when the container user (node)
doesn't match the repository ownership on the host system. Without this configuration,
git commands would fail with security errors in the devcontainer.

NOTE: With Rancher Desktop (and other Lima-based setups), .gitconfig is mounted via
sshfs which doesn't support git's atomic write mechanism (lock file + rename).
This script appends directly to .gitconfig, bypassing git config's lock mechanism.
"""

import sys
from pathlib import Path

GITCONFIG = Path.home() / ".gitconfig"

# ==================== Main Execution ====================

def main() -> int:
    """Configure git safe.directory for all repositories under /workspaces."""
    workspaces_path = Path("/workspaces")

    if not workspaces_path.exists():
        print(f"ERROR: {workspaces_path} does not exist")
        return 0

    repos = find_git_directories(workspaces_path)
    print(f"Found {len(repos)} git repositories")

    if not repos:
        return 0

    # Append safe directories directly to .gitconfig (bypasses git's lock mechanism
    # which fails on sshfs mounts used by Rancher Desktop/Lima)
    added_count, already_safe, newly_configured = append_safe_directories(repos)
    if added_count < 0:
        print("ERROR: Failed to configure git safe directories", file=sys.stderr)
        return 1

    # Log each repository status
    for repo in already_safe:
        print(f"  {repo} -> already safe")
    for repo in newly_configured:
        print(f"  {repo} -> configuring")

    if added_count > 0:
        print(f"[OK] Configured {added_count} safe directories")
    else:
        print("[OK] All repositories already configured as safe")
    return 0

# ==================== Helper Functions ====================

def find_git_directories(base_path: Path, max_depth: int = 3) -> list[Path]:
    """
    Find all .git directories under base_path up to max_depth levels.
    Returns list of parent directories (the actual repositories).

    Limits search depth to avoid slow filesystem traversal on mounted volumes.
    Default depth of 3 covers: /workspaces/project/subrepo patterns.
    """
    import os

    repos = []
    # Directories to skip (don't descend into these)
    skip_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'vendor', '.cache', '.archive'}
    base_depth = str(base_path).count(os.sep)

    try:
        for dirpath, dirnames, _filenames in os.walk(base_path):
            current_depth = dirpath.count(os.sep) - base_depth

            # Check if .git exists in this directory
            if '.git' in dirnames:
                git_path = Path(dirpath) / '.git'
                if git_path.is_dir():
                    repos.append(Path(dirpath))
                    # Don't descend into this repository - no need to search deeper
                    dirnames.clear()
                    continue

            # Stop descending if we've reached max depth
            if current_depth >= max_depth:
                dirnames.clear()
                continue

            # Prune directories we don't want to descend into
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
    except Exception as e:
        print(f"ERROR: Could not search for git directories: {e}", file=sys.stderr)

    return repos


def append_safe_directories(repos: list[Path]) -> tuple[int, list[Path], list[Path]]:
    """
    Append safe.directory entries directly to .gitconfig.

    This bypasses git config's lock file mechanism which fails on sshfs mounts
    (used by Rancher Desktop/Lima). We read existing entries to avoid duplicates.

    Args:
        repos: List of repository paths to mark as safe

    Returns:
        Tuple of (count added or -1 on failure, already safe repos, newly configured repos)
    """
    try:
        # Read existing config to check for duplicates
        existing_dirs: set[str] = set()
        has_safe_section = False
        if GITCONFIG.exists():
            content = GITCONFIG.read_text()
            has_safe_section = "[safe]" in content
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("directory = "):
                    existing_dirs.add(line.split("=", 1)[1].strip())

        # Separate repos into already safe and new
        already_safe = [r for r in repos if str(r) in existing_dirs]
        new_repos = [r for r in repos if str(r) not in existing_dirs]

        if not new_repos:
            return 0, already_safe, []

        # Build lines to append
        lines = []
        if not has_safe_section:
            lines.append("[safe]")
        for repo in new_repos:
            lines.append(f"\tdirectory = {repo}")

        with open(GITCONFIG, "a") as f:
            f.write("\n" + "\n".join(lines) + "\n")

        return len(new_repos), already_safe, new_repos
    except Exception as e:
        print(f"ERROR: Failed to write git configuration: {e}", file=sys.stderr)
        return -1, [], []


if __name__ == "__main__":
    sys.exit(main())
