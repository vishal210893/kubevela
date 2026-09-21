#!/usr/bin/env bash
#
# zshenv-secrets-doctor.sh -- audit (and optionally fix) the zshenv-secrets
# convention on BOTH the Mac host and the devcontainer.
#
# The convention (see setup-zshenv-secrets.sh): secret exports live ONLY in
# ~/.zshenv.secrets (mode 600), loaded by a managed block in ~/.zshenv so they
# reach every shell, including non-interactive ones. Legacy locations
# (~/.zshrc, ~/.zshrc.local, ~/.zshenv itself) must not define secrets.
#
# This doctor:
#   - finds secret-looking exports (TOKEN/PASSWORD/SECRET/KEY/... names) in the
#     legacy files and classifies each: UNMIGRATED (not yet in the secrets
#     file), DUPLICATE (in both -- remove from legacy), or MANUAL (not a
#     simple single-line export; move by hand)
#   - pairs usernames with their secrets (FOO_USERNAME travels with
#     FOO_PASSWORD/TOKEN) so credential pairs stay together
#   - verifies ~/.zshenv.secrets exists with mode 600 and that ~/.zshenv
#     carries the canonical managed loader block (same check on host and
#     container = the "same deferral" guarantee)
#   - lints the secrets file for ordering bugs (a reference like
#     X="$Y" where Y is defined later in the file or nowhere)
#   - NEVER prints a secret value -- only variable names and value shape
#     (literal vs reference)
#
# --fix behavior differs by side, deliberately:
#   - HOST: append each unmigrated line to ~/.zshenv.secrets, then REMOVE the
#     migrated/duplicate lines from the legacy files (timestamped .bak kept).
#   - CONTAINER: ~/.zshrc.local is the SAME bind-mounted file as the host's;
#     deleting from it here would strip the Mac's tokens before the host has
#     migrated. So in a container, --fix only COPIES unmigrated lines into the
#     (container-local) ~/.zshenv.secrets and leaves shared files untouched --
#     run the host-side --fix to do the actual cleanup. After the next
#     container rebuild, the mount-bind replaces the container-local secrets
#     file with the host's copy and the two sides converge.
#
# Usage:
#   zshenv-secrets-doctor.sh           # audit only (exit 0 clean, 1 findings)
#   zshenv-secrets-doctor.sh --fix     # audit, then migrate/clean as above
#   zshenv-secrets-doctor.sh --format json   # machine-readable, read-only (no --fix)
#
# Limitations: only a simple standalone single-line `export NAME=...` /
# `NAME=...` assignment is auto-migrated. A secret-named assignment embedded
# in a compound/guarded command (e.g. `cond && export X=y`) or a
# multi-assignment line is reported MANUAL and never auto-migrated. A simple
# assignment that happens to sit on its own line INSIDE a block (e.g. an
# `if/fi`) still classifies as a normal assignment; before deleting it `--fix`
# parse-checks the file with its own shell and refuses any removal that would
# newly break it (so a bash/sh file is never left with an empty `then` body),
# leaving the line as a DUPLICATE to clean by hand. (zsh tolerates empty
# blocks, so for a zsh file a lone literal in-block export may be hoisted with
# the now-empty block left behind -- benign; backups are kept either way.)
#
# Env: ZSHENV_DOCTOR_SIDE=host|container overrides side auto-detection
# (used by the test suite; not needed in normal use).

set -uo pipefail

SECRETS="$HOME/.zshenv.secrets"
ZSHENV="$HOME/.zshenv"
BEGIN_MARKER="# >>> ispl zshenv-secrets loader (managed) >>>"
END_MARKER="# <<< ispl zshenv-secrets loader (managed) <<<"

# Name patterns that mark an export as secret-bearing.
SECRET_NAME_RE='TOKEN|PASSWORD|PASSWD|SECRET|APIKEY|API_KEY|ACCESS_KEY|PRIVATE_KEY|CREDENTIAL|PASSPHRASE'

FIX=0
FORMAT=text
while [ $# -gt 0 ]; do
    case "$1" in
        --fix) FIX=1; shift ;;
        --format) FORMAT="${2:-text}"; shift; [ $# -gt 0 ] && shift ;;
        --format=*) FORMAT="${1#*=}"; shift ;;
        -h|--help) sed -n '3,53p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;  # docstring through Limitations, before the test-only Env: note
        *) echo "Unknown argument: $1 (try --help)" >&2; exit 2 ;;
    esac
done
case "$FORMAT" in text|json) ;; *) echo "Invalid --format: $FORMAT" >&2; exit 2 ;; esac
if [ "$FIX" = 1 ] && [ "$FORMAT" = json ]; then
    echo "Error: --fix cannot be combined with --format json (json output is read-only)." >&2; exit 2
fi

# ---- environment detection --------------------------------------------------

IN_CONTAINER=0
if [ -f /.dockerenv ] || [ -d /workspaces ] || [ -n "${REMOTE_CONTAINERS:-}" ]; then
    IN_CONTAINER=1
fi
case "${ZSHENV_DOCTOR_SIDE:-}" in
    host) IN_CONTAINER=0 ;;
    container) IN_CONTAINER=1 ;;
esac
SIDE=host; [ "$IN_CONTAINER" = 1 ] && SIDE=container

# Files scanned for stray secrets. The first three are the convention's
# explicit legacy set; the rest are informational extras that often hide the
# original definition on the host.
LEGACY_FILES="$HOME/.zshrc $HOME/.zshrc.local $HOME/.zshenv $HOME/.zprofile $HOME/.profile $HOME/.bash_profile $HOME/.bashrc"

# Bind-mounted files shared between host and container: never rewritten from
# the container side (see header).
is_shared_file() {
    [ "$IN_CONTAINER" = 1 ] && [ "$1" = "$HOME/.zshrc.local" ]
}

FAILS=0
WARNS=0
# JSON accumulation for --format json (ccbridge schema). pass/warn/fail also
# append a row here; the key is a slug of the message (call sites stay unchanged,
# so the text output is byte-for-byte what it always was). In json mode the
# human [PASS]/[WARN]/[FAIL] lines are suppressed and a single JSON document is
# printed at the end -- so stdout is exactly that document.
JSON_ROWS=""
add_row() { # <status: ok|warn|problem> <message>
    local st="$1"; shift
    local msg="$*" key em
    key="$(printf '%s' "$msg" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/^_+//; s/_+$//' | cut -c1-48)"
    em="${msg//\\/\\\\}"; em="${em//\"/\\\"}"
    JSON_ROWS="${JSON_ROWS:+$JSON_ROWS,}{\"section\":\"zshenv-secrets\",\"status\":\"$st\",\"key\":\"$key\",\"message\":\"$em\"}"
}
pass() { add_row ok "$1"; [ "$FORMAT" = text ] && printf '[PASS] %s\n' "$1" || true; }
warn() { add_row warn "$1"; WARNS=$((WARNS + 1)); [ "$FORMAT" = text ] && printf '[WARN] %s\n' "$1" || true; }
fail() { add_row problem "$1"; FAILS=$((FAILS + 1)); [ "$FORMAT" = text ] && printf '[FAIL] %s\n' "$1" || true; }

file_mode() { # portable octal mode
    case "$(uname -s)" in
        Darwin) stat -f '%Lp' "$1" 2>/dev/null ;;
        *) stat -c '%a' "$1" 2>/dev/null ;;
    esac
}

# Extract "NAME<TAB>kind" for secret-looking assignments in a file.
# kind = literal | reference:$REF for a SIMPLE STANDALONE assignment (optionally
# export-prefixed, nothing before NAME= on the line); kind = manual for a line
# that assigns a secret-named var but is NOT a simple standalone assignment
# (part of a compound/guarded command, or a multi-assignment line) -- those are
# reported and never auto-migrated. Skips comments and the managed block.
secret_assignments() { # <file>
    awk -v re="$SECRET_NAME_RE" -v b="$BEGIN_MARKER" -v e="$END_MARKER" '
        $0 == b { inblock = 1; next }
        $0 == e { inblock = 0; next }
        inblock { next }
        /^[[:space:]]*#/ { next }
        {
            # Clean, top-level, simple secret assignment? Require that nothing
            # but whitespace (and an optional "export") precedes NAME= on the
            # line -- so a guarded/compound line does not look standalone.
            s = $0
            sub(/^[[:space:]]*/, "", s)
            sub(/^export[[:space:]]+/, "", s)
            if (s ~ /^[A-Za-z_][A-Za-z0-9_]*=/) {
                name = s; sub(/=.*/, "", name)
                if (toupper(name) ~ re) {
                    head = $0
                    sub(/^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=.*/, "", head)
                    if (head ~ /^[[:space:]]*$/) {
                        rhs = s; sub(/^[A-Za-z_][A-Za-z0-9_]*=/, "", rhs)
                        kind = "literal"
                        if (rhs ~ /^"?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"?$/) {
                            ref = rhs; gsub(/["${}]/, "", ref); kind = "reference:$" ref
                        }
                        print name "\t" kind
                        next
                    }
                }
            }
            # Otherwise: does the line assign a secret-named var ANYWHERE? If so
            # it is not a simple standalone assignment -> MANUAL (move by hand;
            # never auto-migrated, so --fix cannot mangle a compound line).
            up = toupper($0)
            if (match(up, "(^|[^A-Z0-9_])[A-Z0-9_]*(" re ")[A-Z0-9_]*=")) {
                tok = substr($0, RSTART, RLENGTH)
                sub(/^[^A-Za-z0-9_]/, "", tok)
                sub(/=.*/, "", tok)
                print tok "\tmanual"
            }
        }
    ' "$1"
}

# Does the secrets file already define NAME?
in_secrets() { # <name>
    [ -f "$SECRETS" ] || return 1
    grep -Eq "^[[:space:]]*(export[[:space:]]+)?$1=" "$SECRETS"
}

# Full original line(s) for NAME in a file (for migration).
lines_for_var() { # <file> <name>
    grep -E "^[[:space:]]*(export[[:space:]]+)?$2=" "$1"
}

# Parse-check a file with the shell it belongs to (-n = syntax only, no
# execution / sourcing). Used by --fix to refuse a removal that would break
# the file -- e.g. stripping the lone export out of an if/fi block. Best
# effort: if the right parser is unavailable, returns non-zero so the caller
# treats the file as un-checkable and skips the guard.
syntax_ok() { # <file> <basename-of-target>
    case "$2" in
        .bashrc|.bash_profile|.bashrc.local)
            command -v bash >/dev/null 2>&1 && bash -n "$1" 2>/dev/null ;;
        .profile)
            command -v sh >/dev/null 2>&1 && sh -n "$1" 2>/dev/null ;;
        *)  # zsh dotfiles (and default): prefer zsh, fall back to bash
            if command -v zsh >/dev/null 2>&1; then zsh -n "$1" 2>/dev/null
            elif command -v bash >/dev/null 2>&1; then bash -n "$1" 2>/dev/null
            else return 1; fi ;;
    esac
}

if [ "$FORMAT" = text ]; then
    echo "zshenv-secrets doctor -- side: $SIDE -- $(date '+%Y-%m-%d %H:%M')"
    echo
fi

# ---- check 1: secrets file exists, mode 600 ---------------------------------

if [ -f "$SECRETS" ]; then
    mode="$(file_mode "$SECRETS")"
    if [ "$mode" = "600" ]; then
        pass "~/.zshenv.secrets exists (mode 600)"
    else
        fail "~/.zshenv.secrets has mode $mode (want 600) -- run: chmod 600 ~/.zshenv.secrets"
    fi
else
    fail "~/.zshenv.secrets missing -- run setup-zshenv-secrets.sh first"
fi

# ---- check 2: canonical managed loader block in ~/.zshenv -------------------

expected_block() {
    printf '%s\n' "$BEGIN_MARKER"
    printf '%s\n' '[ -f "$HOME/.zshenv.secrets" ] && source "$HOME/.zshenv.secrets"'
    printf '%s\n' '# transition shim: load legacy ~/.zshrc.local in interactive shells only (deprecated)'
    printf '%s\n' 'case $- in *i*) [ -f "$HOME/.zshrc.local" ] && source "$HOME/.zshrc.local" ;; esac'
    printf '%s\n' "$END_MARKER"
}

if [ -f "$ZSHENV" ] && grep -qF "$BEGIN_MARKER" "$ZSHENV"; then
    actual="$(awk -v b="$BEGIN_MARKER" -v e="$END_MARKER" '
        $0 == b { p = 1 } p { print } $0 == e { p = 0 }' "$ZSHENV")"
    if [ "$actual" = "$(expected_block)" ]; then
        pass "~/.zshenv managed loader block matches canonical"
    else
        fail "~/.zshenv managed block DRIFTED from canonical -- re-run setup-zshenv-secrets.sh to refresh"
    fi
else
    fail "~/.zshenv has no managed loader block -- run setup-zshenv-secrets.sh"
fi

# ---- check 3: stray secrets in legacy files ---------------------------------

MIGRATE_LIST=""   # file<TAB>name lines needing migration
CLEAN_LIST=""     # file<TAB>name lines present in secrets, removable from legacy
ALL_SECRET_NAMES=""

for f in $LEGACY_FILES; do
    [ -f "$f" ] || continue
    [ "$f" = "$SECRETS" ] && continue
    found="$(secret_assignments "$f")"
    [ -n "$found" ] || continue
    while IFS="$(printf '\t')" read -r name kind; do
        [ -n "$name" ] || continue
        if [ "$kind" = "manual" ]; then
            warn "$f: $name (manual) -- MANUAL: secret-named but not a simple standalone 'export NAME=value' (compound, guarded, or multi-assignment line). Move it to ~/.zshenv.secrets by hand -- --fix will not touch it."
            continue
        fi
        ALL_SECRET_NAMES="$ALL_SECRET_NAMES $name"
        shared_note=""
        is_shared_file "$f" && shared_note=" [shared with host -- container --fix will not rewrite it]"
        if in_secrets "$name"; then
            warn "$f: $name ($kind) -- DUPLICATE: already in ~/.zshenv.secrets; remove from $(basename "$f")$shared_note"
            CLEAN_LIST="$CLEAN_LIST$f	$name
"
        else
            fail "$f: $name ($kind) -- UNMIGRATED: move to ~/.zshenv.secrets$shared_note"
            MIGRATE_LIST="$MIGRATE_LIST$f	$name
"
        fi
    done <<EOF_FOUND
$found
EOF_FOUND
done

# Username pairing: FOO_USERNAME / FOO_USER should travel with FOO_<secret>.
for f in $LEGACY_FILES; do
    [ -f "$f" ] || continue
    [ "$f" = "$SECRETS" ] && continue
    unames="$(awk '
        /^[[:space:]]*#/ { next }
        {
            line = $0
            sub(/^[[:space:]]*export[[:space:]]+/, "", line)
            if (line !~ /^[A-Za-z_][A-Za-z0-9_]*=/) next
            name = line; sub(/=.*/, "", name)
            if (toupper(name) ~ /(USERNAME|_USER)$/) print name
        }' "$f")"
    for uname_var in $unames; do
        prefix="$(printf '%s' "$uname_var" | sed -E 's/_(USERNAME|USER)$//')"
        case " $ALL_SECRET_NAMES " in
            *" ${prefix}_"*)
                if ! in_secrets "$uname_var"; then
                    warn "$f: $uname_var pairs with a migrating ${prefix}_* secret -- move it to ~/.zshenv.secrets too"
                    MIGRATE_LIST="$MIGRATE_LIST$f	$uname_var
"
                fi
                ;;
        esac
    done
done

if [ -z "$MIGRATE_LIST" ] && [ -z "$CLEAN_LIST" ]; then
    pass "no secret-looking exports left in legacy files (zshrc, zshrc.local, zshenv, profiles)"
fi

# ---- check 4: ordering lint inside the secrets file -------------------------

if [ -f "$SECRETS" ]; then
    order_problems="$(awk '
        /^[[:space:]]*#/ { next }
        {
            line = $0
            sub(/^[[:space:]]*export[[:space:]]+/, "", line)
            if (line !~ /^[A-Za-z_][A-Za-z0-9_]*=/) next
            name = line; sub(/=.*/, "", name)
            rhs = line; sub(/^[A-Za-z_][A-Za-z0-9_]*=/, "", rhs)
            if (rhs ~ /^"?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"?$/) {
                ref = rhs; gsub(/["${}]/, "", ref)
                if (!(ref in defined)) print name " references $" ref " before/without its definition in this file"
            }
            defined[name] = 1
        }
    ' "$SECRETS")"
    if [ -n "$order_problems" ]; then
        while IFS= read -r p; do
            [ -n "$p" ] && warn "~/.zshenv.secrets ordering: $p (OK only if the referent reliably arrives via process env)"
        done <<EOF_ORD
$order_problems
EOF_ORD
    else
        pass "~/.zshenv.secrets ordering: every reference follows its definition"
    fi
fi

# ---- check 5: MCP credential references resolve -----------------------------
# An MCP server config that interpolates ${VAR} into its env starts SILENTLY
# unauthenticated/degraded when VAR is unset -- e.g. the github MCP server reads
# ${GH_TOKEN}; an empty value yields anonymous, public-only access with no
# error (private-repo calls just return "Not Found"). The secrets file is where
# that VAR is supposed to live, so flag any plain ${NAME} reference in an
# .mcp.json that is neither exported in ~/.zshenv.secrets nor present (non-empty)
# in the environment. Devcontainer ${localEnv:..}/${containerEnv:..} forms carry
# a colon and are not matched, so they never false-positive here.

mcp_ref_resolved() { # <name> -- defined in the secrets file or live environment?
    in_secrets "$1" && return 0
    [ -n "${!1:-}" ]
}

# Collect .mcp.json configs, de-duplicated by resolved path (so $PWD == $HOME
# does not count the same file twice). Walk up from $PWD to the nearest
# .mcp.json so the check still works when run from a project subdirectory, then
# also include the home-level one.
MCP_CONFIGS=""
mcp_seen=" "
add_mcp_config() { # <path>
    [ -f "$1" ] || return
    local rp
    rp="$(cd "$(dirname "$1")" 2>/dev/null && pwd)/$(basename "$1")" || rp="$1"
    case "$mcp_seen" in *" $rp "*) return ;; esac
    mcp_seen="$mcp_seen$rp "
    MCP_CONFIGS="$MCP_CONFIGS $1"
}
d="$PWD"
while :; do
    if [ -f "$d/.mcp.json" ]; then add_mcp_config "$d/.mcp.json"; break; fi
    [ "$d" = "/" ] || [ -z "$d" ] && break
    d="$(dirname "$d")"
done
add_mcp_config "$HOME/.mcp.json"
# Runtime vars that legitimately arrive from the environment, not the secrets file.
MCP_REF_SKIP_RE='^(HOME|PATH|USER|LOGNAME|PWD|SHELL|TERM|LANG|LC_[A-Z]+|TMPDIR|HOSTNAME|XDG_[A-Z_]+)$'

mcp_refs_checked=0
mcp_refs_missing=0
for cfg in $MCP_CONFIGS; do
    for var in $(grep -hoE '\$\{[A-Za-z_][A-Za-z0-9_]*\}' "$cfg" 2>/dev/null | tr -d '${}' | sort -u); do
        printf '%s\n' "$var" | grep -qE "$MCP_REF_SKIP_RE" && continue
        mcp_refs_checked=$((mcp_refs_checked + 1))
        if ! mcp_ref_resolved "$var"; then
            mcp_refs_missing=$((mcp_refs_missing + 1))
            warn "${cfg#"$HOME"/} references \$$var but it is unset (not in ~/.zshenv.secrets or the environment) -- that MCP server starts unauthenticated/degraded. Add 'export $var=...' to ~/.zshenv.secrets, then restart the container/app."
        fi
    done
done
if [ "$mcp_refs_checked" -gt 0 ] && [ "$mcp_refs_missing" -eq 0 ]; then
    pass "MCP credential references resolve ($mcp_refs_checked checked across .mcp.json)"
fi

# ---- --fix ------------------------------------------------------------------

if [ "$FIX" = 1 ] && { [ -n "$MIGRATE_LIST" ] || [ -n "$CLEAN_LIST" ]; }; then
    echo
    echo "--fix ($SIDE):"
    ts="$(date '+%Y%m%d-%H%M%S')"
    appended_header=0

    # Ensure the secrets file exists with tight permissions BEFORE any
    # append: creating it via >> would use the current umask (often 644),
    # leaving a brief world-readable window with secrets in it when --fix
    # runs before setup-zshenv-secrets.sh ever did.
    if [ ! -f "$SECRETS" ]; then
        ( umask 077; : > "$SECRETS" )
    fi
    chmod 600 "$SECRETS"

    # 1. Append unmigrated lines to the secrets file (both sides).
    printf '%s' "$MIGRATE_LIST" | while IFS="$(printf '\t')" read -r f name; do
        [ -n "$name" ] || continue
        in_secrets "$name" && continue
        if [ "$appended_header" = 0 ]; then
            printf '\n# --- migrated from legacy shell files by zshenv-secrets-doctor on %s ---\n' "$ts" >> "$SECRETS"
            appended_header=1
        fi
        # A legacy file may define the same secret more than once. Shell
        # `source` is last-wins, so migrate the LAST definition (the value the
        # interactive shell actually saw) -- step 2 then strips ALL of them, so
        # taking the first would silently discard the effective value. Surface a
        # warning (never printing any value) when the duplicates disagree, so a
        # silent value swap can't slip through.
        var_defs="$(lines_for_var "$f" "$name")"
        if [ "$(printf '%s\n' "$var_defs" | sort -u | grep -c .)" -gt 1 ]; then
            warn "$name is defined more than once with differing values in $(basename "$f"); migrated the last (shell source is last-wins) -- check the timestamped backup if that is not what you intended"
        fi
        printf '%s\n' "$var_defs" | tail -1 >> "$SECRETS"
        echo "  moved   $name  (from $(basename "$f") -> ~/.zshenv.secrets)"
    done
    chmod 600 "$SECRETS"

    # 2. Remove migrated/duplicate lines from legacy files -- host only, and
    #    never for shared files when run in a container.
    printf '%s%s' "$MIGRATE_LIST" "$CLEAN_LIST" | sort -u | while IFS="$(printf '\t')" read -r f name; do
        [ -n "$name" ] || continue
        if is_shared_file "$f"; then
            echo "  kept    $name in $(basename "$f") (bind-mounted; clean it with the HOST-side --fix run)"
            continue
        fi
        in_secrets "$name" || continue
        bn="$(basename "$f")"
        tmp="$(mktemp)"
        grep -Ev "^[[:space:]]*(export[[:space:]]+)?$name=" "$f" > "$tmp"
        # Guard: refuse a removal that would newly break the file's shell
        # syntax (e.g. the line was the lone body of an if/fi block). The
        # value is already in ~/.zshenv.secrets, so leaving the legacy copy
        # is safe -- it just surfaces as a DUPLICATE next run.
        if syntax_ok "$f" "$bn" && ! syntax_ok "$tmp" "$bn"; then
            warn "$f: removing $name would break the file's shell syntax (likely a block-guarded export) -- left in place; move it by hand"
            rm -f "$tmp"
            continue
        fi
        [ -f "$f.bak-$ts" ] || cp -p "$f" "$f.bak-$ts"
        cat "$tmp" > "$f"
        rm -f "$tmp"
        echo "  removed $name  (from $bn; backup $bn.bak-$ts)"
    done

    echo
    echo "Re-run without --fix to verify the end state."
fi

# ---- summary ----------------------------------------------------------------

if [ "$FORMAT" = json ]; then
    # ccbridge schema: problems counts [FAIL] rows; ok = no fails. Warnings are
    # advisory rows (status:warn) but, as in text mode, still make the exit code
    # non-zero so the profile-doctor aggregator surfaces them.
    ok=true; [ "$FAILS" -gt 0 ] && ok=false
    printf '{"schema_version":1,"doctor":"zshenv-secrets","problems":%s,"ok":%s,"checks":[%s]}\n' \
        "$FAILS" "$ok" "$JSON_ROWS"
    { [ "$FAILS" = 0 ] && [ "$WARNS" = 0 ]; } && exit 0
    exit 1
fi

echo
if [ "$FAILS" = 0 ] && [ "$WARNS" = 0 ]; then
    echo "Summary ($SIDE): CLEAN -- secrets live only in ~/.zshenv.secrets, loader in place."
    exit 0
else
    echo "Summary ($SIDE): $FAILS fail(s), $WARNS warning(s)."
    [ "$FIX" = 0 ] && echo "Run with --fix to migrate/clean (timestamped backups kept; container side never rewrites shared files)."
    exit 1
fi
