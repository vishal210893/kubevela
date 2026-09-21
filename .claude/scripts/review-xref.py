#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Cross-reference analysis for code reviews.

Scans files for references to other files, commands, imports, and manifest
entries, then verifies each reference against the actual filesystem. Produces
a structured markdown report suitable for inclusion in the Bedrock review
context block.

Always exits 0. Errors are reported in the output, not via exit code.
"""

import argparse
import os
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Reference extraction patterns
# ---------------------------------------------------------------------------

# Slash commands: /word or /word:word (but not URLs like /path/to/thing)
RE_SLASH_COMMAND = re.compile(
    r'(?:^|[\s`(])'           # preceded by start, whitespace, backtick, or paren
    r'(/[a-z][a-z0-9-]+)'     # slash + word with hyphens
    r'(?::([a-z][a-z0-9-]+))?' # optional :subcommand
    r'(?=[\s`),.:;!?\'"}\]]|$)',  # followed by whitespace/punctuation/end
    re.MULTILINE
)

# Backtick-quoted file paths: `./path`, `.claude/path`, `path/to/file.ext`
RE_BACKTICK_PATH = re.compile(
    r'`'
    r'(\.?\.?/?'                # optional ./ or ../
    r'(?:[a-zA-Z0-9_-]+/)*'    # directory components
    r'[a-zA-Z0-9_.-]+\.[a-zA-Z0-9]+' # filename with extension
    r')`'
)

# Python relative imports: from lib.X import Y, from .X import Y
RE_PYTHON_IMPORT = re.compile(
    r'^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))',
    re.MULTILINE
)

# YAML file/path references: keys like file:, path:, script:, source:
RE_YAML_PATH = re.compile(
    r'^\s*(?:file|path|script|source|directory|dir)\s*:\s*["\']?'
    r'([\w./_-]+[./][\w._-]+)'  # value that looks like a path
    r'["\']?\s*$',
    re.MULTILINE
)

# Markdown links: [text](path) -- exclude URLs
RE_MD_LINK = re.compile(
    r'\[([^\]]*)\]\(([^)]+)\)'
)


# ---------------------------------------------------------------------------
# Reference types
# ---------------------------------------------------------------------------

class Ref:
    """A reference found in a file."""
    __slots__ = ('file', 'line', 'text', 'kind', 'resolved_path', 'exists')

    def __init__(self, file: str, line: int, text: str, kind: str):
        self.file = file
        self.line = line
        self.text = text
        self.kind = kind
        self.resolved_path = ''
        self.exists = False

    def __repr__(self):
        status = 'OK' if self.exists else 'MISSING'
        return f"Ref({self.file}:{self.line} {self.kind}={self.text} -> {status})"


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_refs(filepath: str, content: str, repo_root: Path) -> list[Ref]:
    """Extract all cross-references from a file's content."""
    refs = []
    lines = content.splitlines()

    # Slash commands
    for m in RE_SLASH_COMMAND.finditer(content):
        cmd = m.group(1)
        sub = m.group(2)
        line_no = content[:m.start()].count('\n') + 1
        # Skip common false positives
        if cmd in ('/bin', '/usr', '/etc', '/tmp', '/dev', '/var', '/home',
                   '/proc', '/sys', '/opt', '/root', '/mnt', '/srv',
                   '/http', '/https', '/api', '/v1', '/v2', '/v3'):
            continue
        full_cmd = f"{cmd}:{sub}" if sub else cmd
        refs.append(Ref(filepath, line_no, full_cmd, 'command'))

    # Backtick-quoted paths
    for m in RE_BACKTICK_PATH.finditer(content):
        path = m.group(1)
        line_no = content[:m.start()].count('\n') + 1
        # Skip things that look like code patterns, not file refs
        if path.startswith('http') or '@' in path:
            continue
        refs.append(Ref(filepath, line_no, path, 'file_path'))

    # Markdown links (non-URL only)
    for m in RE_MD_LINK.finditer(content):
        target = m.group(2)
        if target.startswith('http') or target.startswith('#') or target.startswith('mailto:'):
            continue
        line_no = content[:m.start()].count('\n') + 1
        refs.append(Ref(filepath, line_no, target, 'md_link'))

    # Python imports (only for .py files)
    if filepath.endswith('.py'):
        for m in RE_PYTHON_IMPORT.finditer(content):
            module = m.group(1) or m.group(2)
            line_no = content[:m.start()].count('\n') + 1
            refs.append(Ref(filepath, line_no, module, 'python_import'))

    # YAML path references (only for .yaml/.yml files)
    if filepath.endswith(('.yaml', '.yml')):
        for m in RE_YAML_PATH.finditer(content):
            path = m.group(1)
            line_no = content[:m.start()].count('\n') + 1
            refs.append(Ref(filepath, line_no, path, 'yaml_path'))

    return refs


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_refs(refs: list[Ref], repo_root: Path) -> list[Ref]:
    """Resolve each reference against the filesystem.

    Assumes the standard deployed layout where commands live at
    .claude/commands/<name>.md and skills at .claude/skills/<name>/SKILL.md.
    This script is designed to run in the target project repo, not in the
    toolbox development repo.
    """
    commands_dir = repo_root / '.claude' / 'commands'
    skills_dir = repo_root / '.claude' / 'skills'

    for ref in refs:
        if ref.kind == 'command':
            # Strip leading / and optional :subcommand
            cmd_name = ref.text.lstrip('/')
            # Check .claude/commands/<name>.md
            cmd_file = commands_dir / f"{cmd_name}.md"
            ref.resolved_path = str(cmd_file.relative_to(repo_root))
            ref.exists = cmd_file.is_file()
            # Also check as a skill
            if not ref.exists:
                skill_name = cmd_name.replace(':', '-')
                skill_file = skills_dir / skill_name / 'SKILL.md'
                if skill_file.is_file():
                    ref.resolved_path = str(skill_file.relative_to(repo_root))
                    ref.exists = True

        elif ref.kind in ('file_path', 'md_link', 'yaml_path'):
            path_str = ref.text
            # Try relative to the file's directory first
            file_dir = Path(ref.file).parent
            candidate = repo_root / file_dir / path_str
            if candidate.exists():
                ref.resolved_path = str(candidate.relative_to(repo_root))
                ref.exists = True
            else:
                # Try relative to repo root
                candidate = repo_root / path_str
                ref.resolved_path = path_str
                ref.exists = candidate.exists()

        elif ref.kind == 'python_import':
            # Resolve Python import to filesystem path
            module = ref.text
            # Convert dotpath to filesystem path
            parts = module.split('.')
            file_dir = Path(ref.file).parent

            # Try as relative import from the file's directory
            candidate = repo_root / file_dir / '/'.join(parts)
            if candidate.with_suffix('.py').is_file():
                ref.resolved_path = str(candidate.with_suffix('.py').relative_to(repo_root))
                ref.exists = True
            elif candidate.is_dir() and (candidate / '__init__.py').is_file():
                ref.resolved_path = str((candidate / '__init__.py').relative_to(repo_root))
                ref.exists = True
            else:
                # Likely a stdlib or third-party import -- mark as exists
                ref.resolved_path = f"(external: {module})"
                ref.exists = True

    return refs


# ---------------------------------------------------------------------------
# Manifest checking
# ---------------------------------------------------------------------------

def check_manifests(repo_root: Path) -> list[Ref]:
    """Check manifest/registry files for entries without corresponding directories."""
    refs = []

    # deploy-manifest.yaml
    manifest = repo_root / 'deploy-manifest.yaml'
    if manifest.is_file():
        content = manifest.read_text(encoding='utf-8')
        # Look for product entries (lines like "  - product: bc" or "  bc:")
        for i, line in enumerate(content.splitlines(), 1):
            # Match YAML list items or map keys that look like product codes
            m = re.match(r'\s*-?\s*(?:product:\s*)?([a-z]{2,4})\s*:', line)
            if not m:
                m = re.match(r'\s*-\s+([a-z]{2,4})\s*$', line)
            if m:
                product = m.group(1)
                product_dir = repo_root / product
                ref = Ref(str(manifest.relative_to(repo_root)), i,
                          product, 'manifest_entry')
                ref.resolved_path = f"{product}/"
                ref.exists = product_dir.is_dir()
                refs.append(ref)


    return refs


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def format_report(refs: list[Ref], manifest_refs: list[Ref]) -> str:
    """Format the cross-reference analysis as markdown."""
    all_refs = refs + manifest_refs
    broken = [r for r in all_refs if not r.exists]
    verified_count = sum(1 for r in all_refs if r.exists)

    lines = ['## Cross-Reference Analysis', '']

    if broken:
        lines.append(f'### Broken References ({len(broken)} found)')
        lines.append('')
        lines.append('| File | Line | Reference | Type | Status |')
        lines.append('|------|------|-----------|------|--------|')
        for ref in broken:
            status = f'`{ref.resolved_path}` not found'
            lines.append(
                f'| `{ref.file}` | {ref.line} | `{ref.text}` | {ref.kind} | {status} |'
            )
        lines.append('')
    else:
        lines.append('### No Broken References Found')
        lines.append('')

    lines.append(f'### Verified References: {verified_count} checked, all resolved')
    lines.append('')

    if manifest_refs:
        manifest_broken = [r for r in manifest_refs if not r.exists]
        if manifest_broken:
            lines.append(f'### Manifest/Registry Issues ({len(manifest_broken)} found)')
            lines.append('')
            lines.append('| Registry | Entry | Expected | Status |')
            lines.append('|----------|-------|----------|--------|')
            for ref in manifest_broken:
                lines.append(
                    f'| `{ref.file}` | `{ref.text}` | `{ref.resolved_path}` | not found |'
                )
            lines.append('')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Cross-reference analysis for code reviews'
    )
    parser.add_argument('--repo-root', default='.',
                        help='Repository root directory (default: current directory)')
    parser.add_argument('--files', nargs='*', default=[],
                        help='Specific files to scan for references')
    parser.add_argument('--include-docs', action='store_true',
                        help='Also scan CLAUDE.md and README.md for references')
    parser.add_argument('--all-docs', action='store_true',
                        help='Scan all markdown files in the repo root')
    parser.add_argument('--check-manifests', action='store_true', default=True,
                        help='Check manifest/registry files (default: true)')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON instead of markdown')
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()

    # Build file list
    files_to_scan = list(args.files)

    if args.include_docs:
        for doc in ['CLAUDE.md', 'README.md']:
            doc_path = repo_root / doc
            if doc_path.is_file() and doc not in files_to_scan:
                files_to_scan.append(doc)

    if args.all_docs:
        for md in repo_root.glob('*.md'):
            rel = str(md.relative_to(repo_root))
            if rel not in files_to_scan:
                files_to_scan.append(rel)

    # Extract and resolve references
    all_refs = []
    for filepath in files_to_scan:
        abs_path = repo_root / filepath
        if not abs_path.is_file():
            print(f"Warning: file not found: {filepath}", file=sys.stderr)
            continue
        try:
            content = abs_path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as e:
            print(f"Warning: cannot read {filepath}: {e}", file=sys.stderr)
            continue
        refs = extract_refs(filepath, content, repo_root)
        all_refs.extend(refs)

    all_refs = resolve_refs(all_refs, repo_root)

    # Deduplicate: same (file, text, kind) -> keep first occurrence only
    seen = set()
    deduped = []
    for ref in all_refs:
        key = (ref.file, ref.text, ref.kind)
        if key not in seen:
            seen.add(key)
            deduped.append(ref)
    all_refs = deduped

    # Check manifests
    manifest_refs = []
    if args.check_manifests:
        manifest_refs = check_manifests(repo_root)

    # Output
    if args.json:
        import json
        output = {
            'repo_root': str(repo_root),
            'files_scanned': files_to_scan,
            'references': [
                {
                    'file': r.file,
                    'line': r.line,
                    'text': r.text,
                    'kind': r.kind,
                    'resolved_path': r.resolved_path,
                    'exists': r.exists,
                }
                for r in all_refs + manifest_refs
            ],
            'summary': {
                'total': len(all_refs) + len(manifest_refs),
                'broken': sum(1 for r in all_refs + manifest_refs if not r.exists),
                'verified': sum(1 for r in all_refs + manifest_refs if r.exists),
            },
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_report(all_refs, manifest_refs))


if __name__ == '__main__':
    main()
