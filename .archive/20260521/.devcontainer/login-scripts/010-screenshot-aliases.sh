#!/bin/sh
# Screenshot helper aliases for Claude Code
# This file is sourced by the container's ~/.zshrc

# Get the full path of the most recent screenshot
alias img='echo "$HOME/img.png"'

# List the 20 most recent screenshots with timestamps
alias imgall='ls -lth /workspaces/.screenshots 2>/dev/null | head -21 || echo "No screenshots directory found at /workspaces/.screenshots"'
