#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
CAPABILITY: Sets up Claude Code directory structure

Creates the ~/.claude directory and required subdirectories for Claude Code to function.
This prevents ENOENT errors when Claude Code tries to create todos, debug logs, etc.
"""

import sys
from pathlib import Path


def main() -> int:
    """Create Claude Code directory structure."""
    claude_dir = Path.home() / ".claude"

    # Create .claude and required subdirectories
    required_dirs = [
        claude_dir,
        claude_dir / "todos",
        claude_dir / "debug"
    ]

    print("Setting up Claude Code directory structure...")
    for directory in required_dirs:
        try:
            existed = directory.exists()
            directory.mkdir(parents=True, exist_ok=True)
            if existed:
                print(f"  {directory} -> already exists")
            else:
                print(f"  {directory} -> created")
        except Exception as e:
            print(f"ERROR: Failed to create {directory}: {e}", file=sys.stderr)
            return 1

    print("[OK] Claude Code directory structure initialized")
    return 0


if __name__ == "__main__":
    sys.exit(main())
