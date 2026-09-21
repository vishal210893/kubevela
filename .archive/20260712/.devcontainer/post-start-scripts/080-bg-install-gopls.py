#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
CAPABILITY: lang-go

Installs/updates gopls (Go language server) for Go code intelligence.
Provides go-to-definition, find references, hover docs for Go files.
"""
import subprocess
import sys


def get_version() -> str | None:
    """Get installed gopls version."""
    try:
        result = subprocess.run(
            ["gopls", "version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # First line contains version info
            first_line = result.stdout.strip().split('\n')[0]
            return first_line
    except Exception:
        pass
    return None


def main() -> int:
    """Install/update gopls via go install."""
    print("Installing gopls...")

    try:
        result = subprocess.run(
            ["go", "install", "golang.org/x/tools/gopls@latest"],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            print("ERROR: go install failed", file=sys.stderr)
            if result.stderr:
                for line in result.stderr.strip().split('\n')[:5]:
                    print(f"  {line}", file=sys.stderr)
            return 1

        version = get_version()
        if version:
            print(f"  version -> {version}")
        print("[OK] gopls ready")
        return 0

    except subprocess.TimeoutExpired:
        print("ERROR: go install timed out", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("ERROR: go not found - Go not installed", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
