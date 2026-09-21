#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
CAPABILITY: lang-typescript

Installs/updates typescript-language-server for TypeScript/JavaScript code intelligence.
Provides go-to-definition, find references, hover docs for JS/TS files.
"""
import subprocess
import sys
from pathlib import Path


def get_version() -> str | None:
    """Get installed typescript-language-server version."""
    try:
        result = subprocess.run(
            ["typescript-language-server", "--version"],
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
    """Install/update typescript-language-server via npm."""
    print("Installing typescript-language-server...")

    npm_global = Path("/home/node/.npm-global")
    prefix = str(npm_global)

    try:
        result = subprocess.run(
            ["npm", "install", "-g", "--prefix", prefix, "typescript-language-server", "typescript"],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            print("ERROR: npm install failed", file=sys.stderr)
            if result.stderr:
                for line in result.stderr.strip().split('\n')[:5]:
                    print(f"  {line}", file=sys.stderr)
            return 1

        version = get_version()
        if version:
            print(f"  version -> {version}")
        print("[OK] typescript-language-server ready")
        return 0

    except subprocess.TimeoutExpired:
        print("ERROR: npm install timed out", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("ERROR: npm not found - Node.js not installed", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
