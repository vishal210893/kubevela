#!/bin/sh
# Claude Code aliases for workspace-aware Claude sessions
# This file is sourced by the container's ~/.zshrc
#
# When using 'dev cc/ccc/ccr' from host, default flags from ~/.dev/dev.yaml
# are automatically included. These aliases are for use inside the container.

# ccl - Claude Code with Link
# Creates .claude symlink in current directory (if not exists),
# then starts Claude with MCP config and passes through all args
ccl() {
    [ ! -e .claude ] && ln -s $WSROOT/.claude .claude && echo "Note: Created symlink from .claude to \$WSROOT/.claude"
    claude --mcp-config $WSROOT/.mcp.json "$@"
}

# cccl - Claude Code Continue with Link
# Same as ccl but with -c (continue) flag
cccl() {
    [ ! -e .claude ] && ln -s $WSROOT/.claude .claude && echo "Note: Created symlink from .claude to \$WSROOT/.claude"
    claude --mcp-config $WSROOT/.mcp.json -c "$@"
}

# ccrl - Claude Code Resume with Link
# Same as ccl but with --resume flag
ccrl() {
    [ ! -e .claude ] && ln -s $WSROOT/.claude .claude && echo "Note: Created symlink from .claude to \$WSROOT/.claude"
    claude --mcp-config $WSROOT/.mcp.json --resume "$@"
}

# devx - Smart dev CLI routing
# In aidev repo: uses local dev.js
# Otherwise: finds mounted aidev repo or falls back to npx
devx() {
    # Check for version override flags
    case "$1" in
        -b|--beta)   shift; npx @aidev/dev@beta "$@"; return ;;
        -a|--alpha)  shift; npx @aidev/dev@alpha "$@"; return ;;
        -l|--latest) shift; npx @aidev/dev@latest "$@"; return ;;
    esac

    # Check if we're in the aidev repo
    local wsroot
    wsroot=$(git rev-parse --show-toplevel 2>/dev/null)
    if [ -n "$wsroot" ] && [ -f "$wsroot/dev.js" ]; then
        node "$wsroot/dev.js" "$@"
        return
    fi

    # Host fallback
    npx @aidev/dev@latest "$@"
}
