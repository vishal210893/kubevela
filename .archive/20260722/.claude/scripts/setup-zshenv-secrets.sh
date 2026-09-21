#!/usr/bin/env bash
#
# setup-zshenv-secrets.sh -- host-side setup for the zshenv-secrets convention.
#
# Run this ON YOUR HOST (not inside the container). It prepares the two host
# files the convention relies on, both of which are bind-mounted into every
# container by the mount-bind capability:
#
#   ~/.zshenv.secrets  -- where secret VALUES live (mode 600, never committed).
#                         Sourced by ~/.zshenv inside the container, so the
#                         exports reach ALL shells, including the non-interactive
#                         ones (gradle launchers, the ccbridge headless launcher,
#                         MCP subprocesses) that source ~/.zshenv but never
#                         ~/.zshrc / ~/.zshrc.local.
#
#   ~/.zshenv          -- a silent LOADER that sources ~/.zshenv.secrets (and, as
#                         a transition shim, legacy ~/.zshrc.local). This is the
#                         host copy; the container gets the same managed block
#                         installed by the base capability's post-create script.
#
# Why ~/.zshrc.local was insufficient: it is sourced only by interactive shells
# (via ~/.zshrc). Secrets kept there never reached non-interactive tooling, so a
# launcher reading e.g. DEPENDENCY_REPOSITORY_USERNAME / _PASSWORD via getenv got
# nothing or a stale value -- the cause of Artifactory 401s in the ccbridge
# launcher.
#
# This script NEVER silently rewrites your dotfiles. It creates the secrets file
# if missing, offers (with confirmation) to migrate ~/.zshrc.local into it, adds
# a clearly-marked managed loader block to ~/.zshenv, prints exactly what it did,
# and is safe to re-run.
#
# Flags:
#   -y, --yes    Assume "yes" to the migration prompt (non-interactive use).
#   -n, --no     Assume "no" to the migration prompt (skip migration).
#   -h, --help   Show this help and exit.

set -uo pipefail

SECRETS="$HOME/.zshenv.secrets"
ZSHENV="$HOME/.zshenv"
ZSHRC_LOCAL="$HOME/.zshrc.local"

BEGIN_MARKER="# >>> ispl zshenv-secrets loader (managed) >>>"
END_MARKER="# <<< ispl zshenv-secrets loader (managed) <<<"

ASSUME=""   # "", "yes", or "no"

usage() {
    sed -n '2,35p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        -y|--yes) ASSUME="yes" ;;
        -n|--no) ASSUME="no" ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown argument: $1" >&2; usage 1 ;;
    esac
    shift
done

# Track what we did so we can print an honest summary at the end.
DID_CREATE_SECRETS=0
DID_MIGRATE=0
DID_INSTALL_LOADER=0
DID_UPDATE_LOADER=0
LOADER_ALREADY_CURRENT=0

# managed_block: the exact block written into ~/.zshenv. Silent (no output) and
# fast (no network) -- ~/.zshenv is sourced by every shell, including the
# non-interactive shells scp/rsync/ssh spawn, where stray stdout breaks the
# transfer.
managed_block() {
    printf '%s\n' "$BEGIN_MARKER"
    printf '%s\n' '[ -f "$HOME/.zshenv.secrets" ] && source "$HOME/.zshenv.secrets"'
    printf '%s\n' '# transition shim: load legacy ~/.zshrc.local in interactive shells only (deprecated)'
    printf '%s\n' 'case $- in *i*) [ -f "$HOME/.zshrc.local" ] && source "$HOME/.zshrc.local" ;; esac'
    printf '%s\n' "$END_MARKER"
}

# 1. Ensure ~/.zshenv.secrets exists, mode 600.
if [ -f "$SECRETS" ]; then
    chmod 600 "$SECRETS"
    echo "OK   $SECRETS exists (mode set to 600)"
else
    umask 077
    : > "$SECRETS"
    chmod 600 "$SECRETS"
    DID_CREATE_SECRETS=1
    echo "NEW  created $SECRETS (mode 600)"
fi

# 2. Offer to migrate existing ~/.zshrc.local secrets into ~/.zshenv.secrets.
#    We never clobber: migrated content is APPENDED under a dated header, and we
#    do not delete or edit ~/.zshrc.local (the transition shim keeps sourcing it
#    until the user removes the secrets there by hand).
if [ -s "$ZSHRC_LOCAL" ]; then
    do_migrate="$ASSUME"
    if [ -z "$do_migrate" ]; then
        if [ -t 0 ]; then
            printf 'Append a copy of %s into %s for migration? [y/N] ' "$ZSHRC_LOCAL" "$SECRETS"
            read -r reply
            case "$reply" in
                y|Y|yes|YES) do_migrate="yes" ;;
                *) do_migrate="no" ;;
            esac
        else
            do_migrate="no"
        fi
    fi

    if [ "$do_migrate" = "yes" ]; then
        {
            printf '\n# --- migrated from ~/.zshrc.local on %s ---\n' "$(date '+%Y-%m-%d')"
            printf '# Review these, keep only the SECRET exports here, and remove the\n'
            printf '# secret lines from ~/.zshrc.local once confirmed working.\n'
            cat "$ZSHRC_LOCAL"
        } >> "$SECRETS"
        chmod 600 "$SECRETS"
        DID_MIGRATE=1
        echo "OK   appended a copy of $ZSHRC_LOCAL into $SECRETS for review"
    else
        echo "SKIP migration of $ZSHRC_LOCAL (you can move secret exports by hand later)"
    fi
fi

# 3. Add / refresh the managed loader block in ~/.zshenv, idempotently.
if [ -f "$ZSHENV" ] && grep -qF "$BEGIN_MARKER" "$ZSHENV"; then
    # Replace the existing managed region in place. Use a temp file; preserve
    # everything outside the markers untouched.
    tmp="$(mktemp "${TMPDIR:-/tmp}/zshenv.XXXXXX")"
    awk -v b="$BEGIN_MARKER" -v e="$END_MARKER" '
        $0 == b { skip = 1; next }
        $0 == e { skip = 0; next }
        skip != 1 { print }
    ' "$ZSHENV" > "$tmp"
    # Drop a single trailing blank line if present, then re-append the block.
    managed_block >> "$tmp"
    if cmp -s "$tmp" "$ZSHENV"; then
        LOADER_ALREADY_CURRENT=1
        echo "OK   $ZSHENV managed block already current"
        rm -f "$tmp"
    else
        cat "$tmp" > "$ZSHENV"
        rm -f "$tmp"
        DID_UPDATE_LOADER=1
        echo "OK   $ZSHENV managed block refreshed"
    fi
else
    if [ -s "$ZSHENV" ]; then
        printf '\n' >> "$ZSHENV"
    fi
    managed_block >> "$ZSHENV"
    DID_INSTALL_LOADER=1
    echo "NEW  added managed loader block to $ZSHENV"
fi

# 4. Honest summary + next steps.
echo
echo "Summary:"
[ "$DID_CREATE_SECRETS" = 1 ] && echo "  - created $SECRETS (mode 600)"
[ "$DID_CREATE_SECRETS" = 0 ] && echo "  - $SECRETS already existed (mode reset to 600)"
[ "$DID_MIGRATE" = 1 ] && echo "  - appended ~/.zshrc.local into $SECRETS for review (originals untouched)"
[ "$DID_INSTALL_LOADER" = 1 ] && echo "  - installed the managed loader block in $ZSHENV"
[ "$DID_UPDATE_LOADER" = 1 ] && echo "  - refreshed the managed loader block in $ZSHENV"
[ "$LOADER_ALREADY_CURRENT" = 1 ] && echo "  - loader block in $ZSHENV was already current"
echo
echo "Next steps (host):"
echo "  1. Edit $SECRETS and keep only SECRET exports there, e.g.:"
echo "       export ATLASSIAN_API_TOKEN=..."
echo "       export DEPENDENCY_REPOSITORY_USERNAME=..."
echo "       export DEPENDENCY_REPOSITORY_PASSWORD=..."
echo "  2. Remove those same secret lines from ~/.zshrc.local once confirmed."
echo "  3. $SECRETS is outside any git repo, so it is naturally untracked --"
echo "     never commit its contents anywhere."
echo "  4. Rebuild your container (dev rebuild) so the mounts and the container"
echo "     ~/.zshenv loader pick up the new file."

exit 0
