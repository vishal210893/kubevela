#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
CAPABILITY: lang-java

Installs Amazon Corretto 11, 17, and 21 via SDKMAN (skips if already installed).
Creates ~/.java/11, ~/.java/17, ~/.java/21 symlinks to installed versions.
"""
import os
import re
import subprocess
import sys

MAJOR_VERSIONS = ["11", "17", "21"]
DEFAULT_VERSION = "21"


def sdk(args: str, input: str = "") -> subprocess.CompletedProcess:
    """Run sdk command via bash."""
    cmd = f"source $HOME/.sdkman/bin/sdkman-init.sh && sdk {args}"
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, input=input)


def find_latest_corretto(major: str) -> str | None:
    """Find latest Amazon Corretto identifier for a major version."""
    result = sdk("list java")
    pattern = rf"(\d+\.\d+\.\d+-amzn)"
    for line in result.stdout.splitlines():
        if "-amzn" in line:
            match = re.search(pattern, line)
            if match and match.group(1).startswith(f"{major}."):
                return match.group(1)
    return None


def main() -> int:
    sdkman_java = os.path.expanduser("~/.sdkman/candidates/java")
    java_home = os.path.expanduser("~/.java")
    installed = set(os.listdir(sdkman_java)) if os.path.exists(sdkman_java) else set()

    for major in MAJOR_VERSIONS:
        if any(d.startswith(f"{major}.") for d in installed):
            print(f"  Java {major} already installed")
            continue

        version = find_latest_corretto(major)
        if not version:
            print(f"  Warning: Could not find Corretto {major}")
            continue

        print(f"  Installing Amazon Corretto {version}...")
        # Answer "n" to "set as default?" prompt to preserve current default
        result = sdk(f"install java {version}", input="n\n")
        if result.returncode != 0:
            print(f"  Warning: {result.stderr.strip()}")
        else:
            installed.add(version)

    # Refresh installed list and create symlinks
    installed = os.listdir(sdkman_java) if os.path.exists(sdkman_java) else []
    os.makedirs(java_home, exist_ok=True)

    for major in MAJOR_VERSIONS:
        for d in installed:
            if d.startswith(f"{major}.") and d.endswith("-amzn"):
                link = os.path.join(java_home, major)
                target = os.path.join(sdkman_java, d)
                if os.path.islink(link):
                    os.unlink(link)
                os.symlink(target, link)
                print(f"  ~/.java/{major} -> {d}")
                break

    # Set default Java version
    for d in installed:
        if d.startswith(f"{DEFAULT_VERSION}.") and d.endswith("-amzn"):
            print(f"  Setting default Java to {d}")
            sdk(f"default java {d}")
            break

    return 0


if __name__ == "__main__":
    sys.exit(main())
