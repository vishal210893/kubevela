#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///

"""
CAPABILITY: Prepares mount sources and volume ownership before container start

This script reads mount configurations from the profile.yaml file and performs
two preparation tasks before the devcontainer is created:

1. Bind-mount sources (ensure-exists): creates any host directory or file
   marked with the 'ensure-exists' property. Docker bind mounts fail if the
   source path does not exist.

   - ensure-exists: directory - Creates directory with parents if missing
   - ensure-exists: file      - Creates empty file if missing

2. Volume-mount ownership: for every mount with type: volume AND
   volume-nocopy: true, runs a throwaway Alpine container that chowns the
   volume root to the container user (uid:gid 1000:1000). Docker creates a
   new volume's mount point as root:root, which prevents the non-root
   container user from writing. The volume-nocopy gate is intentional:
   volumes without it rely on Docker's auto-copy behavior (which seeds the
   volume from the image on first mount), and pre-touching such a volume
   with a throwaway container can suppress auto-copy. Volumes that declare
   volume-nocopy: true are by definition meant to start empty, so chown
   cannot interfere with auto-copy. The Alpine image is pulled on demand
   by docker run if not cached locally. Idempotent; any failure to pull
   or chown is fatal so the user is not left with a silently-broken
   root-owned volume.

The profile.yaml file is copied to .devcontainer/ during the build process
and contains all capability mount metadata, providing a single source of
truth for mount configuration.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

TARGET_UID = 1000
TARGET_GID = 1000
ALPINE_IMAGE = "artifactory.guidewire.com/hub-docker-remote/alpine"

# ==================== Main Execution ====================

def main() -> int:
    """Main entry point."""
    print("Checking mounts from profile.yaml...")

    profile_config = load_profile_config()

    if not profile_config:
        print("  (no profile.yaml found - skipping)")
        return 0  # Not an error - might not be in a devcontainer context

    mounts = profile_config.get("devcontainer", {}).get("mounts", [])

    bind_errors, bind_processed = ensure_bind_sources_exist(mounts)
    volume_errors, volume_processed = ensure_volume_ownership(mounts)

    total_errors = bind_errors + volume_errors
    total_processed = bind_processed + volume_processed

    if total_processed == 0 and total_errors == 0:
        print("  (no mounts to process)")
    elif total_errors == 0:
        print(f"OK: {total_processed} mount(s) processed")
    else:
        print(f"FAIL: {total_errors} error(s) encountered")

    return 1 if total_errors > 0 else 0

# ==================== Bind-Mount Source Preparation ====================

def ensure_bind_sources_exist(mounts: list[Dict[str, Any]]) -> tuple[int, int]:
    """Ensure bind-mount sources with ensure-exists property exist on the host.

    Returns:
        tuple: (error_count, processed_count)
    """
    errors = 0
    processed = 0

    for mount in mounts:
        mount_type = mount.get("type", "bind")
        if mount_type != "bind":
            continue

        ensure_type = mount.get("ensure-exists")
        if not ensure_type:
            continue

        source = mount.get("source", "")
        if not source:
            continue

        processed += 1

        source = expand_env_vars(source)
        source_path = Path(source).expanduser()

        display_path = format_display_path(source_path)
        kind = "dir" if ensure_type == "directory" else "file"

        try:
            if ensure_type == "directory":
                if source_path.exists():
                    print(f"  {display_path} ({kind}) -> already exists")
                else:
                    source_path.mkdir(parents=True, exist_ok=True)
                    print(f"  {display_path} ({kind}) -> creating directory")

            elif ensure_type == "file":
                if source_path.exists():
                    print(f"  {display_path} ({kind}) -> already exists")
                else:
                    source_path.parent.mkdir(parents=True, exist_ok=True)
                    source_path.touch()
                    print(f"  {display_path} ({kind}) -> creating file")

        except Exception as e:
            print(f"  {display_path} ({kind}) -> ERROR: {e}", file=sys.stderr)
            errors += 1

    return errors, processed

# ==================== Volume Ownership Preparation ====================

def ensure_volume_ownership(mounts: list[Dict[str, Any]]) -> tuple[int, int]:
    """Chown the root of type: volume mounts that opt in via volume-nocopy.

    Docker creates a new volume's mount point as root:root. Since the
    devcontainer runs as a non-root user (uid 1000), we chown the volume
    root via a throwaway Alpine container so the container user can write.

    Only volumes with volume-nocopy: true are processed. Without that flag,
    Docker auto-copies the image's content at the mount target into the
    volume on first use (preserving ownership from the image); pre-touching
    the volume with our throwaway Alpine container can suppress that copy,
    so we leave those alone. A volume declared with volume-nocopy: true is
    explicitly opting out of auto-copy, so it is safe to chown.

    The Alpine image is pulled on demand by docker run itself if not cached
    locally; any pull failure surfaces through the docker subprocess's
    captured stderr and is reported as a hard error. Skipping silently
    leaves volume mount points owned by root, which prevents the container
    user from writing and is confusing to diagnose after the fact.

    All volumes are chowned in a single docker run invocation: one
    container start with N -v mounts and a single chown of N paths.
    This keeps the script well under the host dispatcher's per-script
    timeout even on cold-cache + slow-network hosts where the alpine
    pull dominates wall time.

    Idempotent: re-running against an already-correct volume is a no-op.

    Returns:
        tuple: (error_count, processed_count)
    """
    volumes = [
        m for m in mounts
        if m.get("type") == "volume" and m.get("volume-nocopy") is True
    ]
    if not volumes:
        return 0, 0

    errors = 0
    valid_names: list[str] = []
    for mount in volumes:
        source = mount.get("source", "")
        if not source:
            continue

        volume_name = expand_env_vars(source)
        if not volume_name:
            print(f"  ERROR: volume source '{source}' expanded to empty", file=sys.stderr)
            errors += 1
            continue

        valid_names.append(volume_name)

    if not valid_names:
        return errors, 0

    mount_paths = [f"/mnt/v{i}" for i in range(len(valid_names))]
    docker_args = ["docker", "run", "--rm"]
    for name, path in zip(valid_names, mount_paths):
        docker_args += ["-v", f"{name}:{path}"]
    docker_args += [ALPINE_IMAGE, "chown", f"{TARGET_UID}:{TARGET_GID}", *mount_paths]

    try:
        result = subprocess.run(docker_args, capture_output=True, text=True)
    except FileNotFoundError:
        print("  ERROR: docker not found on PATH; cannot initialize volume ownership", file=sys.stderr)
        return errors + len(valid_names), 0

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        print(f"  ERROR: chown failed (exit {result.returncode}): {error}", file=sys.stderr)
        for name in valid_names:
            print(f"    {name} (volume) -> not chowned", file=sys.stderr)
        return errors + len(valid_names), 0

    for name in valid_names:
        print(f"  {name} (volume) -> owner {TARGET_UID}:{TARGET_GID}")
    return errors, len(valid_names)

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
    current = Path.cwd()

    locations = [
        current / ".devcontainer" / "profile.yaml",
        current / "profile.yaml",
    ]

    for location in locations:
        if location.exists():
            return location

    return None


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

    pattern = r'\$\{localEnv:([^}]+)\}'

    def replace_env(match):
        env_var = match.group(1)
        default = ""
        # Support ${localEnv:VAR:-default} (the profile.yaml form used by
        # mount-volume / mount-volume-src). Split off a ":-default" suffix.
        if ":-" in env_var:
            env_var, default = env_var.split(":-", 1)
        elif ":" in env_var:
            # ${localEnv:VAR:default} alternate form seen in the codebase.
            env_var, default = env_var.split(":", 1)
        return os.environ.get(env_var, default) or default

    return re.sub(pattern, replace_env, value)

if __name__ == "__main__":
    sys.exit(main())
