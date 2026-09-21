#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///

"""
CAPABILITY: Ensures mount source paths exist on the host

This script reads mount configurations from the profile.yaml file and creates
any directories or files marked with 'ensure-exists' before the devcontainer
is created. Docker volume mounts fail if source paths don't exist, so this
prevents mount errors.

The script processes all mounts with an 'ensure-exists' property:
- ensure-exists: directory - Creates directory with parents if missing
- ensure-exists: file - Creates empty file if missing

The profile.yaml file is copied to .devcontainer/ during the build process
and contains all capability mount metadata, providing a single source of
truth for mount configuration.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

# ==================== Main Execution ====================

def main() -> int:
    """Main entry point."""
    print("Checking mounts from profile.yaml...")

    profile_config = load_profile_config()

    if not profile_config:
        print("  (no profile.yaml found - skipping)")
        return 0  # Not an error - might not be in a devcontainer context

    errors, processed = ensure_mount_sources_exist(profile_config)

    if processed == 0:
        print("  (no mounts with ensure-exists defined)")
    elif errors == 0:
        print(f"OK: All {processed} mount(s) verified")
    else:
        print(f"FAIL: {errors} error(s) encountered")

    return 1 if errors > 0 else 0

# ==================== Helper Functions ====================

def load_profile_config() -> Dict[str, Any] | None:
    """Load the profile.yaml configuration which contains mount metadata."""
    profile_path = find_profile_yaml()

    if not profile_path:
        print("  Warning: Could not find profile.yaml", file=sys.stderr)
        return None

    try:
        with open(profile_path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error:   Error loading profile.yaml: {e}", file=sys.stderr)
        return None

def find_profile_yaml() -> Path | None:
    """Find the profile.yaml file in the .devcontainer directory."""
    # Start from current directory and look up
    current = Path.cwd()

    # Check common locations
    locations = [
        current / ".devcontainer" / "profile.yaml",
        current / "profile.yaml",
    ]

    for location in locations:
        if location.exists():
            return location

    return None

def ensure_mount_sources_exist(config: Dict[str, Any]) -> tuple[int, int]:
    """Ensure all mount sources with ensure-exists property exist.

    Returns:
        tuple: (error_count, processed_count)
    """
    # Extract mounts from profile.yaml devcontainer configuration
    devcontainer = config.get("devcontainer", {})
    mounts = devcontainer.get("mounts", [])

    if not mounts:
        return 0, 0

    errors = 0
    processed = 0

    for mount in mounts:
        # Skip non-bind mounts (volume/tmpfs have no host paths to create)
        mount_type = mount.get("type", "bind")
        if mount_type != "bind":
            continue

        ensure_type = mount.get("ensure-exists")
        if not ensure_type:
            continue  # Skip mounts without ensure-exists

        source = mount.get("source", "")
        if not source:
            continue

        processed += 1

        # Expand environment variables
        source = expand_env_vars(source)
        source_path = Path(source).expanduser()

        # Format display path (use ~ for home directory)
        display_path = format_display_path(source_path)
        mount_type = "dir" if ensure_type == "directory" else "file"

        try:
            if ensure_type == "directory":
                if source_path.exists():
                    print(f"  {display_path} ({mount_type}) -> already exists")
                else:
                    source_path.mkdir(parents=True, exist_ok=True)
                    print(f"  {display_path} ({mount_type}) -> creating directory")

            elif ensure_type == "file":
                if source_path.exists():
                    print(f"  {display_path} ({mount_type}) -> already exists")
                else:
                    source_path.parent.mkdir(parents=True, exist_ok=True)
                    source_path.touch()
                    print(f"  {display_path} ({mount_type}) -> creating file")

        except Exception as e:
            print(f"  {display_path} ({mount_type}) -> ERROR: {e}", file=sys.stderr)
            errors += 1

    return errors, processed


def format_display_path(path: Path) -> str:
    """Format a path for display, using ~ for home directory."""
    try:
        home = Path.home()
        if path.is_relative_to(home):
            return "~/" + str(path.relative_to(home))
    except (ValueError, RuntimeError):
        pass
    return str(path)

def expand_env_vars(value: str) -> str:
    """Expand ${localEnv:VAR} syntax to environment variable values."""
    if not isinstance(value, str):
        return value

    # Handle ${localEnv:VAR} syntax
    import re
    pattern = r'\$\{localEnv:([^}]+)\}'

    def replace_env(match):
        env_var = match.group(1)
        return os.environ.get(env_var, match.group(0))

    return re.sub(pattern, replace_env, value)

if __name__ == "__main__":
    sys.exit(main())
