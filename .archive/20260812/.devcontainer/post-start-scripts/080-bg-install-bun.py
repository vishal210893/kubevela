#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
CAPABILITY: claude

Installs Bun into ~/.bun so the claude-mem Claude Code plugin can run its
hooks. Without Bun, every session start fails with
"Error: Bun not found. Please install Bun: https://bun.sh".
"""
import os
import subprocess
import sys
from pathlib import Path

INSTALL_URL = "https://bun.sh/install"
BUN_HOME = Path.home() / ".bun"
BUN_BIN = BUN_HOME / "bin" / "bun"
INSTALL_TIMEOUT = 300


def get_version() -> str | None:
    if not BUN_BIN.exists():
        return None
    try:
        result = subprocess.run(
            [str(BUN_BIN), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def main() -> int:
    version = get_version()
    if version:
        print(f"[OK] bun already installed -> {version}")
        return 0

    print("Installing bun...")
    env = dict(os.environ, BUN_INSTALL=str(BUN_HOME))

    try:
        result = subprocess.run(
            ["bash", "-c", f"curl -fsSL {INSTALL_URL} | bash"],
            capture_output=True,
            text=True,
            timeout=INSTALL_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        print("ERROR: bun install timed out", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if result.returncode != 0:
        print("ERROR: bun install failed", file=sys.stderr)
        for line in (result.stderr or "").strip().split("\n")[:5]:
            print(f"  {line}", file=sys.stderr)
        return 1

    version = get_version()
    if not version:
        print(f"ERROR: bun not found at {BUN_BIN} after install", file=sys.stderr)
        return 1

    print(f"  version -> {version}")
    print("[OK] bun ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
