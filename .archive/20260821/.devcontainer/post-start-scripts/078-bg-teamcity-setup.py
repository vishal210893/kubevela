#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
CAPABILITY: TeamCity CLI skill install and authentication

Installs the JetBrains TeamCity CLI AI agent skill for Claude Code
and authenticates using forwarded credentials. Runs at every container
start to ensure the skill stays registered and auth stays current.
"""

import os
import shutil
import subprocess
import sys


def check_cli_installed() -> bool:
    """Check if the teamcity CLI is available."""
    return shutil.which("teamcity") is not None


def install_skill() -> tuple[bool, str]:
    """Install the TeamCity AI agent skill for Claude Code."""
    try:
        result = subprocess.run(
            ["teamcity", "skill", "install", "--agent", "claude-code"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Skill install timed out after 30s"
    except Exception as e:
        return False, str(e)


def authenticate() -> tuple[bool, str]:
    """Authenticate with TeamCity using environment variables.

    The teamcity CLI natively reads TEAMCITY_URL and TEAMCITY_TOKEN from the
    environment, so we invoke it without flags to avoid exposing the token on
    the command line (visible in /proc and ps output).
    """
    if not os.environ.get("TEAMCITY_TOKEN"):
        return False, "Missing: TEAMCITY_TOKEN"

    if not os.environ.get("TEAMCITY_URL"):
        return False, "Missing: TEAMCITY_URL"

    try:
        result = subprocess.run(
            ["teamcity", "auth", "login", "--no-input"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Auth login timed out after 30s"
    except Exception as e:
        return False, str(e)


def main() -> int:
    """Install TeamCity AI skill and authenticate."""

    # Check CLI is available
    if not check_cli_installed():
        print("  teamcity CLI not found in PATH, skipping setup")
        return 0

    print("  teamcity CLI -> found")

    # Authenticate first (skill install may need auth context)
    auth_ok, auth_msg = authenticate()
    if auth_ok:
        print("  auth -> authenticated")
    else:
        print(f"  auth -> {auth_msg}")
        print("  Set TEAMCITY_TOKEN on your host")

    # Install AI agent skill
    skill_ok, skill_msg = install_skill()
    if skill_ok:
        print("  skill -> installed for claude-code")
    else:
        print(f"  skill -> {skill_msg}")

    # Report read-only mode
    ro = os.environ.get("TEAMCITY_RO", "")
    if ro == "1":
        print("  mode -> read-only (TEAMCITY_RO=1)")
    else:
        print("  mode -> read-write")

    if auth_ok and skill_ok:
        print("[OK] TeamCity CLI ready")
        return 0
    elif skill_ok:
        print("[OK] TeamCity skill installed (auth pending)")
        return 0
    else:
        print("ERROR: TeamCity skill install failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
