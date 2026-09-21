#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
CAPABILITY: Discovers gitconfig include files and adds dynamic bind mounts

Parses the host ~/.gitconfig for [include] and [includeIf] path directives,
ensures referenced files exist on the host (so Docker bind mounts don't fail),
and injects bind mounts into .devcontainer/devcontainer.json so the files are
available inside the container.

Runs in two contexts (both on the HOST, both idempotent):
  1. As a profile-install-script: during `dev profile install`, AFTER
     devcontainer.json is written but BEFORE container creation. This ensures
     mounts are present on first container start.
  2. As an initialize-script: during `initializeCommand` for container rebuilds.
     Must run after ensure-mounts.py (priority 10) which creates the base
     ~/.gitconfig if it doesn't exist.

The profile-install-scripts copy is a symlink to this file.
"""

import json
import os
import re
import sys
from pathlib import Path


CONTAINER_HOME = "/home/node"


def main() -> int:
    """Discover gitconfig includes and add mounts to devcontainer.json."""
    home_str = os.environ.get("HOME")
    if not home_str or not Path(home_str).is_dir():
        print("  (HOME not set or not a directory -- skipping)")
        return 0
    home = Path(home_str)

    gitconfig_path = home / ".gitconfig"
    if not gitconfig_path.exists():
        print("  (no ~/.gitconfig found -- skipping)")
        return 0

    include_paths = parse_gitconfig_includes(gitconfig_path)
    if not include_paths:
        print("  (no include/includeIf paths found in ~/.gitconfig)")
        return 0

    devcontainer_json = find_devcontainer_json()
    if not devcontainer_json:
        print("  Warning: could not find .devcontainer/devcontainer.json", file=sys.stderr)
        return 0

    added = add_include_mounts(include_paths, devcontainer_json, home)
    if added:
        print(f"  Added {added} gitconfig include mount(s) to devcontainer.json")
    else:
        print("  (all gitconfig include mounts already present)")

    return 0


def parse_gitconfig_includes(config_path: Path) -> list[Path]:
    """Parse [include] and [includeIf] path directives from a gitconfig file.

    Returns resolved absolute paths for each discovered include.
    """
    try:
        content = config_path.read_text()
    except Exception:
        return []

    paths: list[Path] = []
    in_include_section = False

    for line in content.splitlines():
        stripped = line.strip()

        # Detect section headers
        if stripped.startswith("["):
            in_include_section = bool(
                re.match(r'\[include(?:If\s+"[^"]*")?\]', stripped, re.IGNORECASE)
            )
            continue

        # Extract path from include/includeIf sections
        if in_include_section:
            match = re.match(r"path\s*=\s*(.+)", stripped, re.IGNORECASE)
            if match:
                raw_path = match.group(1).strip()
                resolved = resolve_gitconfig_path(raw_path, config_path.parent)
                if resolved:
                    paths.append(resolved)

    return paths


def resolve_gitconfig_path(raw_path: str, config_dir: Path) -> Path | None:
    """Resolve a gitconfig path value to an absolute path.

    Handles:
    - ~/path -> $HOME/path
    - /absolute/path -> as-is
    - relative/path -> relative to config file's directory
    """
    if not raw_path:
        return None

    # Expand ~ to HOME
    if raw_path.startswith("~/") or raw_path == "~":
        home = os.environ.get("HOME", "")
        if not home:
            return None
        expanded = Path(home) / raw_path[2:] if raw_path != "~" else Path(home)
        return expanded.resolve()

    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()

    # Relative to config file directory
    return (config_dir / path).resolve()


def find_devcontainer_json() -> Path | None:
    """Find .devcontainer/devcontainer.json from current working directory."""
    candidates = [
        Path.cwd() / ".devcontainer" / "devcontainer.json",
        Path.cwd() / "devcontainer.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def add_include_mounts(
    include_paths: list[Path], devcontainer_json: Path, home: Path
) -> int:
    """Add bind mounts for include files to devcontainer.json.

    Returns number of mounts added.
    """
    try:
        content = devcontainer_json.read_text()
        config = json.loads(content)
    except Exception as e:
        print(f"  Warning: could not read {devcontainer_json}: {e}", file=sys.stderr)
        return 0

    mounts = config.get("mounts", [])
    existing_targets = set()
    for mount in mounts:
        # Parse target from mount string
        if isinstance(mount, str):
            for part in mount.split(","):
                if part.startswith("target="):
                    existing_targets.add(part.split("=", 1)[1])

    added = 0
    for include_path in include_paths:
        # Compute relative-to-home path for the mount target
        try:
            rel_path = include_path.relative_to(home)
        except ValueError:
            # Path is not under HOME -- use the basename in container home
            rel_path = Path(include_path.name)

        target = f"{CONTAINER_HOME}/{rel_path}"
        if target in existing_targets:
            print(f"  {target} -> already mounted")
            continue

        # Ensure the source file exists on host (Docker fails on missing bind sources)
        ensure_file_exists(include_path)

        # Build mount source using ${localEnv:HOME} for portability
        try:
            source_rel = include_path.relative_to(home)
            source = f"${{localEnv:HOME}}/{source_rel}"
        except ValueError:
            source = str(include_path)

        mount_str = f"type=bind,source={source},target={target},consistency=cached"
        mounts.append(mount_str)
        existing_targets.add(target)
        added += 1
        print(f"  {target} -> adding mount")

    if added > 0:
        config["mounts"] = mounts
        try:
            devcontainer_json.write_text(json.dumps(config, indent=2) + "\n")
        except Exception as e:
            print(f"  Error: could not write {devcontainer_json}: {e}", file=sys.stderr)
            return 0

    return added


def ensure_file_exists(file_path: Path) -> None:
    """Ensure a file exists on the host, creating it if needed."""
    if file_path.exists():
        return
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
        print(f"  {file_path} -> created empty file")
    except Exception as e:
        print(f"  Warning: could not create {file_path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
