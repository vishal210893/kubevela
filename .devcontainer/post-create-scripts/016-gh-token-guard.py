#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
CAPABILITY: Drop an empty GH_TOKEN in ~/.zshenv so it cannot shadow the gh keyring

The gh capability forwards GH_TOKEN from host to container via devcontainer
remoteEnv ("${localEnv:GH_TOKEN}") AND bind-mounts ~/.config/gh. When the host
has no GH_TOKEN set, the substitution resolves to an empty string and injects
GH_TOKEN="" into the container session environment. gh treats set-but-empty as a
credential: its GraphQL path (gh pr create / merge) fails with "401 Bad
credentials" while REST silently falls back to the mounted keyring -- a confusing
partial-auth split for users on the gh-auth-login (mounted keyring) option.

The cleanup must reach NON-interactive shells too -- in particular the GitHub MCP
subprocess, which reads GH_TOKEN and never sources ~/.zshrc. Interactive shells
source ~/.zshrc; non-interactive shells (tools, launchers, MCP subprocesses)
source ONLY ~/.zshenv. So the guard goes in ~/.zshenv, alongside the
zshenv-secrets loader, rather than in an interactive-only login-script.

Installs a managed block into ~/.zshenv that unsets GH_TOKEN when it is
set-but-empty; a non-empty host token (the GH_TOKEN auth option) is left
untouched.

Idempotent: the block is delimited by markers and replaced in place on re-run
(or skipped if byte-identical); it is never appended twice. The block body is
SILENT (no stdout) -- ~/.zshenv runs on every shell including the non-interactive
ones scp/rsync/ssh spawn, where stray output corrupts those transfers.
"""

import sys
from pathlib import Path

BEGIN_MARKER = "# >>> ispl gh-token-guard (managed) >>>"
END_MARKER = "# <<< ispl gh-token-guard (managed) <<<"

# Keep this SILENT (no echo/print): ~/.zshenv is sourced by every shell,
# including the non-interactive shells scp/rsync/ssh spawn, where stray stdout
# breaks the transfer. The `if` form always returns 0 (safe under `set -e`).
MANAGED_BLOCK = "\n".join(
    [
        BEGIN_MARKER,
        "# Drop an empty GH_TOKEN (host var unset, forwarded empty via remoteEnv) so it",
        "# cannot shadow the bind-mounted ~/.config/gh keyring on gh's GraphQL path.",
        'if [ -z "${GH_TOKEN:-}" ]; then unset GH_TOKEN; fi',
        END_MARKER,
    ]
)


def replace_managed_block(content: str) -> str:
    """Return content with the managed block inserted or replaced in place.

    If both markers are present, the region between them (inclusive) is replaced.
    If absent, the block is appended after a single blank line. If only one marker
    is present (hand-edited / truncated), treat the block as absent and append a
    fresh one rather than guessing at a partial region.
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
    """Ensure the managed gh-token-guard block is present in ~/.zshenv."""
    zshenv = Path.home() / ".zshenv"

    print("Installing gh-token-guard into ~/.zshenv...")

    try:
        existing = zshenv.read_text() if zshenv.exists() else ""
    except Exception as e:
        print(f"ERROR: could not read {zshenv}: {e}", file=sys.stderr)
        return 1

    updated = replace_managed_block(existing)

    if updated == existing:
        print(f"  {zshenv} -> gh-token-guard already current")
        return 0

    try:
        zshenv.write_text(updated)
    except Exception as e:
        print(f"ERROR: could not write {zshenv}: {e}", file=sys.stderr)
        return 1

    print(f"  {zshenv} -> gh-token-guard {'updated' if BEGIN_MARKER in existing else 'added'}")
    print("[OK] gh-token-guard installed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
