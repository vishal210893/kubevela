#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["ruamel.yaml"]
# ///

"""
SessionStart hook to load spec and context docs after /clear or on startup.

Checks if the current git branch has an associated spec and/or context list.
If so, outputs the documents as context for Claude.

Input: JSON via stdin with "source" field ("clear", "startup", "resume", "compact")
Output: Spec and context document contents to stdout (automatically injected as context)
"""

import json
import subprocess
import sys
from pathlib import Path

# Add parent directory for speclib imports
sys.path.insert(0, str(Path(__file__).parent))
from lib.speclib import (
    get_current_branch, get_associated_spec, spec_path, steering_path, in_git_repo,
    get_contexts, resolve_context_path
)


def read_spec_files(spec_dir: Path) -> list:
    """Read all .md files from a spec directory."""
    parts = []
    for filename, title in [
        ('requirements.md', 'Requirements'),
        ('design.md', 'Design'),
        ('tasks.md', 'Tasks'),
    ]:
        file_path = spec_dir / filename
        if file_path.is_file():
            content = file_path.read_text().strip()
            if content:
                parts.append(f"## {title}")
                parts.append(f"File: `{file_path}`")
                parts.append("")
                parts.append(content)
                parts.append("")

    # Also read any extra .md files not in the standard set
    standard = {'requirements.md', 'design.md', 'tasks.md'}
    for md_file in sorted(spec_dir.glob('*.md')):
        if md_file.name not in standard:
            content = md_file.read_text().strip()
            if content:
                title = md_file.stem.replace('-', ' ').title()
                parts.append(f"## {title}")
                parts.append(f"File: `{md_file}`")
                parts.append("")
                parts.append(content)
                parts.append("")

    return parts


def read_context_node(path: Path) -> list:
    """Read all .md files from a context node (directory or single file)."""
    parts = []
    if path.is_file():
        content = path.read_text().strip()
        if content:
            parts.append(content)
            parts.append("")
    elif path.is_dir():
        for md_file in sorted(path.glob('*.md')):
            content = md_file.read_text().strip()
            if content:
                parts.append(content)
                parts.append("")
    return parts


def main():
    # Parse input JSON from stdin
    try:
        input_data = json.load(sys.stdin)
        source = input_data.get('source', '')
    except (json.JSONDecodeError, KeyError):
        source = 'unknown'

    # Only run on clear or startup (not resume - that already has context)
    if source not in ('clear', 'startup', 'unknown'):
        sys.exit(0)

    if not in_git_repo():
        sys.exit(0)

    branch = get_current_branch()
    if not branch:
        sys.exit(0)

    output_parts = []

    # --- Spec context ---
    spec_name = get_associated_spec(branch)
    if spec_name:
        spec_dir = spec_path(spec_name)
        if spec_dir.is_dir():
            output_parts.append(f"# Spec Context: {spec_name}")
            output_parts.append(f"Branch `{branch}` is associated with spec `{spec_name}`.")
            output_parts.append("")
            output_parts.extend(read_spec_files(spec_dir))

    # --- Steering context (always loaded) ---
    steering_dir = steering_path()
    if steering_dir.is_dir():
        node_parts = read_context_node(steering_dir)
        if node_parts:
            if not output_parts:
                output_parts.append(f"# Context for branch `{branch}`")
                output_parts.append("")
            output_parts.append(f"## Steering")
            output_parts.append(f"Path: `{steering_dir}`")
            output_parts.append("")
            output_parts.extend(node_parts)
    elif (steering_dir.parent / 'steering.md').is_file():
        steering_file = steering_dir.parent / 'steering.md'
        node_parts = read_context_node(steering_file)
        if node_parts:
            if not output_parts:
                output_parts.append(f"# Context for branch `{branch}`")
                output_parts.append("")
            output_parts.append(f"## Steering")
            output_parts.append(f"Path: `{steering_file}`")
            output_parts.append("")
            output_parts.extend(node_parts)

    # --- Branch contexts ---
    contexts = get_contexts(branch)
    if contexts:
        if not output_parts:
            output_parts.append(f"# Context for branch `{branch}`")
            output_parts.append("")

        for ref in contexts:
            path = resolve_context_path(ref)
            node_parts = read_context_node(path)
            if node_parts:
                output_parts.append(f"## Context: {ref}")
                output_parts.append(f"Path: `{path}`")
                output_parts.append("")
                output_parts.extend(node_parts)

    if output_parts:
        print('\n'.join(output_parts))


if __name__ == '__main__':
    main()
