#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
CAPABILITY: Installs the zshenv-secrets loader into the container ~/.zshenv

The container image bakes ~/.zshrc but ships no ~/.zshenv. Interactive shells
source ~/.zshrc (and thus ~/.zshrc.local); NON-interactive shells (tools, gradle
launchers, the ccbridge headless launcher, MCP subprocesses) source ONLY
~/.zshenv. Secrets kept in ~/.zshrc.local therefore never reach non-interactive
tooling -- e.g. a launcher reading DEPENDENCY_REPOSITORY_USERNAME /
DEPENDENCY_REPOSITORY_PASSWORD via System.getenv gets nothing, causing
Artifactory 401s.

This script ensures the container ~/.zshenv contains a managed block that sources
~/.zshenv.secrets (the mounted, mode-600, never-committed secret values) for ALL
shells, plus a transition shim that still loads legacy ~/.zshrc.local in
interactive shells only (so non-interactive ~/.zshenv stays silent), for any
consumer that has not migrated yet.

Idempotent: the managed block is delimited by markers. On re-run the block is
replaced in place (or skipped if byte-identical); it is never appended twice. The
block body is pure exports/sourcing with NO stdout -- ~/.zshenv runs on every
shell including the non-interactive ones scp/rsync/ssh use, and any banner output
there corrupts those transfers.
"""

import sys
from pathlib import Path

BEGIN_MARKER = "# >>> ispl zshenv-secrets loader (managed) >>>"
END_MARKER = "# <<< ispl zshenv-secrets loader (managed) <<<"

# The managed block. Keep this SILENT (no echo/print) and fast (no network):
# ~/.zshenv is sourced by every shell, including the non-interactive shells that
# scp/rsync/ssh spawn, where stray stdout breaks the transfer.
MANAGED_BLOCK = "\n".join(
    [
        BEGIN_MARKER,
        '[ -f "$HOME/.zshenv.secrets" ] && source "$HOME/.zshenv.secrets"',
        "# transition shim: load legacy ~/.zshrc.local in interactive shells only (deprecated)",
        'case $- in *i*) [ -f "$HOME/.zshrc.local" ] && source "$HOME/.zshrc.local" ;; esac',
        END_MARKER,
    ]
)


def replace_managed_block(content: str) -> str:
    """Return content with the managed block inserted or replaced in place.

    If both markers are present, the region between them (inclusive) is replaced
    with the current MANAGED_BLOCK. If they are absent, the block is appended,
    separated from any existing content by a single blank line. If only one
    marker is present (hand-edited / truncated file), we treat the block as
    absent and append a fresh one rather than guessing at a partial region.
    """
    begin = content.find(BEGIN_MARKER)
    end = content.find(END_MARKER)

    if begin != -1 and end != -1 and end > begin:
        end_full = end + len(END_MARKER)
        return content[:begin] + MANAGED_BLOCK + content[end_full:]

    if content and not content.endswith("\n"):
        content += "\n"
    if content:
        content += "\n"
    return content + MANAGED_BLOCK + "\n"


def main() -> int:
    """Ensure the managed zshenv-secrets loader block is present in ~/.zshenv."""
    zshenv = Path.home() / ".zshenv"

    print("Installing zshenv-secrets loader into ~/.zshenv...")

    try:
        existing = zshenv.read_text() if zshenv.exists() else ""
    except Exception as e:
        print(f"ERROR: could not read {zshenv}: {e}", file=sys.stderr)
        return 1

    updated = replace_managed_block(existing)

    if updated == existing:
        print(f"  {zshenv} -> managed block already current")
        return 0

    try:
        zshenv.write_text(updated)
    except Exception as e:
        print(f"ERROR: could not write {zshenv}: {e}", file=sys.stderr)
        return 1

    if BEGIN_MARKER in existing:
        print(f"  {zshenv} -> managed block updated")
    else:
        print(f"  {zshenv} -> managed block added")
    print("[OK] zshenv-secrets loader installed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
