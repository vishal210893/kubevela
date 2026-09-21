#!/bin/sh
# Screenshot helper aliases for Claude Code
# This file is sourced by the container's ~/.zshrc

# Get the full path of the most recent screenshot
alias img='echo "$HOME/img.png"'

# List the 20 most recent screenshots with timestamps
alias imgall='ls -lth /workspaces/.screenshots 2>/dev/null | head -21 || echo "No screenshots directory found at /workspaces/.screenshots"'

# Self-heal the screenshot sync daemon. The daemon is normally launched by the
# post-start hook, but a bare VM resume can bring the container back without
# re-running post-start, leaving the daemon dead. Starting a shell ensures it is
# up. This is safe to run repeatedly: the daemon takes a single-instance flock and
# a second invocation exits as a no-op.
if [ -n "$WSROOT" ] && [ -f "$WSROOT/.devcontainer/post-start-scripts/screenshot-sync-daemon.py" ]; then
  if ! pgrep -f screenshot-sync-daemon.py >/dev/null 2>&1; then
    mkdir -p "$HOME/logs"
    nohup python3 "$WSROOT/.devcontainer/post-start-scripts/screenshot-sync-daemon.py" \
      >> "$HOME/logs/screenshot-daemon.log" 2>&1 &
    disown 2>/dev/null || true
  fi
fi
