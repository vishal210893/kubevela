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
Output: JSON with additionalContext (for Claude) and prompt to display summary to user
"""

import json
import subprocess
import sys
from pathlib import Path

# Add parent directory for speclib imports
sys.path.insert(0, str(Path(__file__).parent))
from lib.speclib import (
    get_current_branch, get_associated_spec, get_project, spec_path, steering_path,
    in_git_repo, get_contexts, resolve_context_path, get_default_branch,
    should_inject_steering, TRUNK_BRANCHES
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
    project = get_project(branch)

    # --- Spec context ---
    spec_name = get_associated_spec(branch)
    if spec_name:
        spec_dir = spec_path(spec_name)
        if spec_dir.is_dir():
            # Prominent location header so agents see project/spec/root immediately
            # and don't confuse same-named specs across projects (e.g. dev/build vs appmgr/build).
            output_parts.append("# SPEC LOCATION")
            output_parts.append(f"Project: {project}")
            output_parts.append(f"Spec: {spec_name}")
            output_parts.append(f"Root: {spec_dir}/")
            output_parts.append(f"Config: ~/.dev/dev.yaml (authoritative source)")
            output_parts.append("")
            output_parts.append(f"# Spec Context: {spec_name}")
            output_parts.append(f"Branch `{branch}` is associated with spec `{spec_name}`.")
            output_parts.append("")
            output_parts.extend(read_spec_files(spec_dir))
    elif branch not in TRUNK_BRANCHES:
        # Branch has no associated spec - warn and suggest /ccs:feature
        warning = (
            f"WARNING: Branch '{branch}' has no associated spec. "
            "Run /spec:create to start a new spec for this branch."
        )
        print(warning, file=sys.stderr)
        no_spec_context = (
            "# No Spec Associated\n\n"
            f"Branch `{branch}` has no associated spec. "
            "If this is a feature branch, run `/spec:create` to initialise one, "
            "or `/ccs:feature` if your project uses the CCS guided workflow."
        )
        output_parts.append(no_spec_context)
        output_parts.append("")

    # --- Steering context ---
    # memory.md is ALWAYS loaded (unconditionally) if it exists.
    # The rest of the steering directory is loaded based on the steering-context config.
    default_branch = get_default_branch()
    inject_steering = should_inject_steering(branch, spec_name, default_branch)
    steering_dir = steering_path()
    has_steering = False
    has_memory = False

    # Always load memory.md unconditionally
    memory_file = steering_dir / 'memory.md'
    if memory_file.is_file():
        memory_content = memory_file.read_text().strip()
        if memory_content:
            has_memory = True
            if not output_parts:
                output_parts.append(f"# Context for branch `{branch}`")
                output_parts.append("")
            output_parts.append(f"## Steering Memory")
            output_parts.append(f"Path: `{memory_file}`")
            output_parts.append("")
            output_parts.append(memory_content)
            output_parts.append("")

    # Load remaining steering files based on steering-context config
    if inject_steering and steering_dir.is_dir():
        node_parts = []
        for md_file in sorted(steering_dir.glob('*.md')):
            if md_file.name == 'memory.md':
                continue  # already loaded unconditionally above
            content = md_file.read_text().strip()
            if content:
                node_parts.append(content)
                node_parts.append("")
        if node_parts:
            has_steering = True
            if not output_parts:
                output_parts.append(f"# Context for branch `{branch}`")
                output_parts.append("")
            output_parts.append(f"## Steering")
            output_parts.append(f"Path: `{steering_dir}`")
            output_parts.append("")
            output_parts.extend(node_parts)
    elif inject_steering and (steering_dir.parent / 'steering.md').is_file():
        steering_file = steering_dir.parent / 'steering.md'
        node_parts = read_context_node(steering_file)
        if node_parts:
            has_steering = True
            if not output_parts:
                output_parts.append(f"# Context for branch `{branch}`")
                output_parts.append("")
            output_parts.append(f"## Steering")
            output_parts.append(f"Path: `{steering_file}`")
            output_parts.append("")
            output_parts.extend(node_parts)

    # --- Branch contexts ---
    contexts = get_contexts(branch)
    loaded_contexts = []
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
                loaded_contexts.append(ref)

    if output_parts:
        result = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": '\n'.join(output_parts),
            },
        }

        # Build dynamic injection message using qualified spec grammar:
        #   <project>:<spec>:<ctx1>,<ctx2>
        # Spec + contexts collapse into one qualified unit. Steering and
        # memory.md are appended as separate units joined by " & ".
        parts = []
        if spec_name or loaded_contexts:
            spec_part = spec_name or '-'
            ctx_part = ','.join(loaded_contexts) if loaded_contexts else ''
            if ctx_part:
                parts.append(f"{project}:{spec_part}:{ctx_part}")
            else:
                parts.append(f"{project}:{spec_part}")
        if has_steering:
            parts.append('steering')
        if has_memory:
            parts.append('memory.md')

        qual = ' & '.join(parts) if parts else project
        noun = "contexts" if len(parts) > 1 else "context"
        result["systemMessage"] = f"Injected the {qual} {noun} into the session"
        print(json.dumps(result))


if __name__ == '__main__':
    main()
