#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
CAPABILITY: lang-python

Installs/updates python-lsp-server (pylsp) for Python code intelligence.
Provides go-to-definition, find references, hover docs for Python files.
"""
import subprocess
import sys


def get_version() -> str | None:
    """Get installed pylsp version."""
    try:
        result = subprocess.run(
            ["pylsp", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def main() -> int:
    """Install/update python-lsp-server via uv tool."""
    print("Installing python-lsp-server...")

    try:
        result = subprocess.run(
            ["uv", "tool", "install", "--upgrade", "python-lsp-server"],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            print("ERROR: uv tool install failed", file=sys.stderr)
            if result.stderr:
                for line in result.stderr.strip().split('\n')[:5]:
                    print(f"  {line}", file=sys.stderr)
            return 1

        version = get_version()
        if version:
            print(f"  version -> {version}")
        print("[OK] python-lsp-server ready")
        return 0

    except subprocess.TimeoutExpired:
        print("ERROR: uv tool install timed out", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("ERROR: uv not found", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
