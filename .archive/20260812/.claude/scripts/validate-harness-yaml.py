#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema", "pyyaml"]
# ///
# NOTE: harness.schema.yaml (Draft-07) in ../files/ is the single canonical schema for .harness.yaml; the /harness:validate command in harness.dev validates against it via `uvx check-jsonschema`. This script validates against that same file (pre-commit hook + legacy CI path).
"""
validate-harness-yaml.py - Validate .harness.yaml against the JSON schema.

Usage:
    uv run ns/harness/capabilities/ci/src/claude/scripts/validate-harness-yaml.py [path]

Exits 0 on success (no output). Exits 1 with human-readable errors on failure.

Uses PyYAML's safe_load. All glob patterns in .harness.yaml that contain
`**` must be quoted (e.g. "**/bld/**"); unquoted `**` is not valid YAML.
The config file follows this convention.
"""

import json
import os
import sys
from pathlib import Path

import yaml
from jsonschema import Draft7Validator


def find_schema():
    """Locate harness.schema.yaml from installed profile or source."""
    wsroot = os.environ.get("WSROOT", "")

    candidates = []
    if wsroot:
        candidates.append(Path(wsroot) / ".claude" / "files" / "harness.schema.yaml")

    # Source path fallback: script lives at
    # ns/harness/capabilities/ci/src/claude/scripts/validate-harness-yaml.py
    # Walk up to the capability root (ci/) and check src/ and bld/ files dirs.
    script_path = Path(__file__).resolve()
    cap_root = script_path.parent.parent.parent.parent  # ci/
    candidates.append(cap_root / "src" / "claude" / "files" / "harness.schema.yaml")
    candidates.append(cap_root / "bld" / "claude" / "files" / "harness.schema.yaml")

    for path in candidates:
        if path.exists():
            return path

    return None


def main():
    pr_yaml_path = sys.argv[1] if len(sys.argv) > 1 else ".harness.yaml"

    if not Path(pr_yaml_path).exists():
        print(f"Error: {pr_yaml_path} not found", file=sys.stderr)
        sys.exit(1)

    schema_path = find_schema()
    if not schema_path:
        print("Error: harness.schema.yaml not found", file=sys.stderr)
        sys.exit(1)

    with open(schema_path) as f:
        schema = yaml.safe_load(f)

    with open(pr_yaml_path) as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            print(f"Error: {pr_yaml_path}: YAML parse error: {exc}", file=sys.stderr)
            sys.exit(1)

    if not isinstance(data, dict):
        print(f"Error: {pr_yaml_path}: root must be an object", file=sys.stderr)
        sys.exit(1)

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))

    if not errors:
        sys.exit(0)

    for error in errors:
        path = ".".join(str(p) for p in error.path) or "(root)"
        value = error.instance
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)[:80]
        print(f"{pr_yaml_path}: {path}: {error.message} (got: {value})", file=sys.stderr)

    sys.exit(1)


if __name__ == "__main__":
    main()
