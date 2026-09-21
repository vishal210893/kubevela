#!/bin/sh
# Backwards compatibility shim for containers that source local.sh
# Newer containers source login-scripts/login-dispatcher.sh directly
[ -f "$WSROOT/.devcontainer/login-scripts/login-dispatcher.sh" ] && \
    source "$WSROOT/.devcontainer/login-scripts/login-dispatcher.sh"
