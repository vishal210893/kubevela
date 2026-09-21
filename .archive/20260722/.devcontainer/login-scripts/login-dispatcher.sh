#!/bin/sh
# Login dispatcher - sources all shell helper files in priority order
# This file is sourced by ~/.zshrc on every shell session start.
#
# The dispatcher pattern:
# 1. ~/.zshrc sources $WSROOT/.devcontainer/login-scripts/login-dispatcher.sh
# 2. This script sources all NNN-*.sh files in its directory in sorted order
# 3. Each capability's shell customizations (aliases, functions, key bindings) get loaded

# Get the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Source all .sh files in priority order (NNN-*.sh)
for helper in "$SCRIPT_DIR"/[0-9][0-9][0-9]-*.sh; do
    [ -f "$helper" ] && source "$helper"
done
