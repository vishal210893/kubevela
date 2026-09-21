#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
CAPABILITY: Sets up screenshot sync

Starts screenshot synchronization daemon that monitors macOS screenshots directory
and syncs them to the devcontainer workspace for easy access from Claude Code.
"""

import os
import subprocess
import sys
from pathlib import Path

# ==================== Main Execution ====================

def main() -> int:
    """Start screenshot synchronization daemon."""
    print("Starting screenshot sync daemon...")

    workspace_root = os.environ.get("WSROOT", "")
    if not workspace_root:
        print("  WSROOT -> not set")
        print("ERROR: WSROOT environment variable not set for screenshot sync")
        return 0

    print(f"  WSROOT -> {workspace_root}")

    screenshot_sync = Path(workspace_root) / ".devcontainer" / "post-start-scripts" / "screenshot-sync-daemon.py"

    if not screenshot_sync.exists():
        print(f"  daemon script -> not found at {screenshot_sync}")
        print("  skipping screenshot sync")
        return 0

    print(f"  daemon script -> {screenshot_sync}")

    # Check if screenshots directory is mounted
    screenshots_dir = Path("/workspaces/.screenshots")
    if not screenshots_dir.exists():
        print("  screenshots dir -> /workspaces/.screenshots not found")
        print("")
        print("This usually means ~/.screenshots doesn't exist on the host")
        print("Run 'dev profile install standard' on the host to set it up")
        print("Then restart the container with 'dev restart'")
        return 0

    print(f"  screenshots dir -> {screenshots_dir}")

    try:
        # Create logs directory
        logs_dir = Path.home() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Open log file for daemon output
        log_file = logs_dir / "screenshot-daemon.log"
        print(f"  log file -> {log_file}")

        with open(log_file, "a") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Starting screenshot daemon at container startup\n")
            f.write(f"{'='*60}\n")

        with open(log_file, "a") as log_f:
            subprocess.Popen(
                ["python3", str(screenshot_sync)],
                stdout=log_f,
                stderr=log_f,
                start_new_session=True
            )

        print("[OK] Screenshot sync daemon started")
        return 0
    except Exception as e:
        print(f"ERROR: Failed to start screenshot sync: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
