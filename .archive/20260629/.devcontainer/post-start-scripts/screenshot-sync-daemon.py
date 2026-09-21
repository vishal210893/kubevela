#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///

"""
Screenshot synchronization daemon

Maintains ~/img.png through ~/img5.png as copies of the 5 most recent screenshots.
Monitors /workspaces/.screenshots/*.png and automatically copies the path to clipboard
when new screenshots are detected using OSC 52 escape sequences.

This script forks to background immediately so it doesn't block container startup.
"""

import base64
import fcntl
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional

# Configure logging (only for daemon process)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Single-instance lock. Prevents duplicate daemons when the login-shell self-heal
# and the post-start launcher race, or when the script is invoked more than once.
# The lock is held for the daemon's lifetime via a file descriptor inherited by the
# forked child, and is released automatically by the kernel when the process dies,
# so a crashed daemon never leaves a stale lock behind.
LOCK_PATH = Path.home() / ".cache" / "screenshot-sync-daemon.lock"
_lock_fd = None  # module-level reference keeps the fd (and its flock) alive

# ==================== Main Execution ====================

def acquire_singleton_lock() -> bool:
    """Acquire the single-instance lock. Returns True if this process got it."""
    global _lock_fd
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = open(LOCK_PATH, "w")
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    _lock_fd = fd  # keep the fd open so the lock is held
    return True


def main() -> None:
    """Fork to background and run daemon."""
    # Bail out early if another instance already holds the lock.
    if not acquire_singleton_lock():
        print("Screenshot sync daemon already running, skipping")
        sys.exit(0)

    # Fork to background so we don't block the dispatcher
    try:
        pid = os.fork()
        if pid > 0:
            # Parent exits immediately - dispatcher can continue. The child
            # inherits the lock fd, so the single-instance lock stays held.
            print(f"Screenshot sync daemon started (PID {pid})")
            sys.exit(0)
    except OSError as e:
        print(f"Failed to fork daemon: {e}", file=sys.stderr)
        sys.exit(1)

    # Child: detach from parent session
    os.setsid()
    os.umask(0)

    # Run the daemon loop
    run_daemon()


def run_daemon() -> None:
    """Daemon loop that monitors screenshots and maintains copies."""
    logger.info("Screenshot sync daemon running...")
    logger.info("Monitoring /workspaces/.screenshots/*.png")
    logger.info("Maintaining copies: ~/img.png through ~/img5.png")

    last_screenshot: Optional[Path] = None
    filenames = ["img.png", "img2.png", "img3.png", "img4.png", "img5.png"]

    try:
        while True:
            # Get the 5 most recent screenshots
            screenshots = get_recent_screenshots(5)

            # Copy screenshots to home directory
            for i, filename in enumerate(filenames):
                if i < len(screenshots):
                    copy_screenshot(filename, screenshots[i])

                    # For the most recent screenshot (~/img.png), copy to clipboard when new
                    if i == 0 and screenshots[0] != last_screenshot:
                        copy_to_clipboard("@~/img.png")
                        logger.info(f"New screenshot detected: {screenshots[0].name}")
                        logger.info("Copied '@~/img.png' to clipboard")
                        last_screenshot = screenshots[0]
                else:
                    # Remove file if there aren't enough screenshots
                    copy_screenshot(filename, None)

            # Sleep for 1 second before next check
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Screenshot sync daemon stopped")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise

# ==================== Helper Functions ====================

def get_recent_screenshots(count: int = 5) -> List[Path]:
    """
    Get the N most recent PNG screenshots from /workspaces/.screenshots.

    Args:
        count: Number of recent screenshots to return

    Returns:
        List of Path objects sorted by modification time (most recent first)
    """
    try:
        screenshot_dir = Path("/workspaces/.screenshots")
        if not screenshot_dir.exists():
            return []

        # Get all PNG files sorted by modification time (newest first)
        screenshots = sorted(
            screenshot_dir.glob("*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        return screenshots[:count]
    except Exception as e:
        logger.error(f"Error getting screenshots: {e}")
        return []

def copy_screenshot(filename: str, source: Optional[Path]) -> None:
    """
    Copy a screenshot to the home directory or remove it if no source.

    Args:
        filename: Name of the destination file (e.g., "img.png", "img2.png")
        source: Path to copy from, or None to remove the file
    """
    try:
        home = Path.home()
        dest_path = home / filename

        if source is None:
            # Remove file if it exists
            if dest_path.exists():
                dest_path.unlink()
        else:
            # Copy the screenshot file
            shutil.copy2(source, dest_path)
    except Exception as e:
        logger.debug(f"Failed to copy screenshot {filename}: {e}")

def copy_to_clipboard(text: str) -> None:
    """
    Copy text to clipboard using OSC 52 escape sequence.

    Works in iTerm2, Terminal.app, VS Code, and other terminals that support OSC 52.
    Writes to all accessible /dev/pts/* terminals.

    Args:
        text: The text to copy to clipboard
    """
    try:
        # Encode text as base64
        encoded = base64.b64encode(text.encode()).decode()
        # OSC 52 escape sequence: ESC]52;c;<base64>BEL
        osc_seq = f"\033]52;c;{encoded}\a"

        # Write to all active PTYs (terminals) that are writable
        pts_path = Path("/dev/pts")
        if pts_path.exists():
            for tty in pts_path.iterdir():
                try:
                    # Check if the terminal is writable
                    if tty.is_char_device() and tty.stat().st_mode & 0o200:
                        with open(tty, 'w') as f:
                            f.write(osc_seq)
                except (PermissionError, OSError):
                    # Silently ignore terminals we can't write to
                    pass
    except Exception as e:
        logger.debug(f"Failed to copy to clipboard: {e}")

if __name__ == "__main__":
    main()
