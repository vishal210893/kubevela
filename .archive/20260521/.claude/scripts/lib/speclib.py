"""
Shared library for spec-driven development scripts.

This module provides common functions used across spec commands:
- Branch operations (get current branch)
- Spec association (get/set spec for branch via dev.yaml)
- Doc root resolution
- Context management helpers
- Error handling patterns

Import like this in PEP 723 scripts:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from lib.speclib import get_current_branch, get_associated_spec, associate_spec

dev.yaml key scheme:
    spec.<repo>.spec-repo-directory
    spec.<repo>.project
    spec.<repo>.branches.<branch>.spec
    spec.<repo>.branches.<branch>.ctx
    spec.<repo>.branches.<branch>.project
"""

import subprocess
import json
import os
import re
import sys
from pathlib import Path

# Ensure lib dir is on path for devyaml import
_lib_dir = str(Path(__file__).parent)
if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)
from devyaml import get as _yaml_get, set as _yaml_set, unset as _yaml_unset, register_repo_defaults as _register_repo_defaults


def _spec_repo_defaults(repo):
    """Return default config for a new spec repo section.

    Note: 'project' is intentionally NOT included here. The repo name
    is used as a runtime fallback in get_project() tier 3, but is never
    persisted as a default. This prevents materialization from overwriting
    a user-configured project value.
    """
    return {
        'spec-repo-directory': '$WSROOT/specs',
    }

_register_repo_defaults('spec', _spec_repo_defaults)


# --- Repo identification (cached) ---

_repo_name_cache = None
_repo_name_resolved = False
_branch_cache = None
_branch_resolved = False


def get_repo_name():
    """Extract the repository name from the origin remote URL.

    Cached after first call since it cannot change during execution.

    Examples:
      https://github.com/gwre-pdo/ai-dev.git  ->  ai-dev
      git@github.com:gwre-pdo/ai-dev.git      ->  ai-dev

    Returns:
        str: Repository name, or None if no origin remote
    """
    global _repo_name_cache, _repo_name_resolved
    if _repo_name_resolved:
        return _repo_name_cache

    result = subprocess.run(
        ['git', 'remote', 'get-url', 'origin'],
        capture_output=True, text=True
    )
    _repo_name_resolved = True
    if result.returncode != 0:
        _repo_name_cache = None
        return None
    url = result.stdout.strip()
    if not url:
        _repo_name_cache = None
        return None

    if url.endswith('.git'):
        url = url[:-4]
    url = url.rstrip('/')

    name = url.split('/')[-1]
    _repo_name_cache = name.lower() if name else None
    return _repo_name_cache


# --- Spec repo directory ---

# Valid config keys for /spec:config
CONFIG_KEYS = ('spec-repo-directory', 'project')


def get_spec_repo_directory():
    """Get the spec repo directory from dev.yaml.

    Returns:
        str: Spec repo directory path (may contain env vars like $WSROOT)
    """
    repo = get_repo_name()
    if not repo:
        return '$WSROOT/specs'
    return _yaml_get(f'spec.{repo}.spec-repo-directory') or '$WSROOT/specs'


def set_spec_repo_directory(path):
    """Set spec repo directory in dev.yaml."""
    repo = get_repo_name()
    if not repo:
        return
    _yaml_set(f'spec.{repo}.spec-repo-directory', path)


# --- Project ---

def get_project(branch=None):
    """Get project with 3-tier lookup: branch override -> repo default -> repo name.

    Lookup order:
    1. dev.yaml: spec.<repo>.branches.<branch>.project (branch override)
    2. dev.yaml: spec.<repo>.project (repo default)
    3. get_repo_name() (fallback -- never persisted)

    Args:
        branch: Branch name. If None, uses current branch.

    Returns:
        str: Project name (always returns something via repo name fallback)
    """
    repo = get_repo_name()
    if not branch:
        branch = get_current_branch()

    if branch and repo:
        value = _yaml_get(f'spec.{repo}.branches.{branch}.project')
        if value:
            return value

    if repo:
        value = _yaml_get(f'spec.{repo}.project')
        if value:
            return value

    return repo or 'dev'


def set_project(name):
    """Set repo-wide project default in dev.yaml."""
    repo = get_repo_name()
    if not repo:
        return
    _yaml_set(f'spec.{repo}.project', name)


def set_branch_project(branch, name):
    """Set branch-scoped project override in dev.yaml."""
    repo = get_repo_name()
    if not repo or not branch:
        return
    _yaml_set(f'spec.{repo}.branches.{branch}.project', name)


def remove_branch_project(branch):
    """Remove branch project override from dev.yaml."""
    repo = get_repo_name()
    if not repo or not branch:
        return
    _yaml_unset(f'spec.{repo}.branches.{branch}.project')


# --- Doc root ---

def get_git_root():
    """Get the git repository root directory."""
    result = subprocess.run(
        ['git', 'rev-parse', '--show-toplevel'],
        capture_output=True, text=True
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def doc_root_for_project(project_name):
    """Resolve doc root for a specific project.

    Returns:
        Path: <spec-repo-directory>/<project_name>/
    """
    spec_dir = os.path.expandvars(get_spec_repo_directory())
    return Path(spec_dir) / project_name


def doc_root():
    """Return the doc root path: spec_repo_dir / project.

    Returns:
        Path: Resolved doc root path
    """
    project = get_project()
    if not project:
        print("Error: spec not configured. Run /spec:setup", file=sys.stderr)
        sys.exit(1)
    return doc_root_for_project(project)


# --- Branch operations ---

def get_current_branch():
    """Get current git branch name.

    Cached after first call since no spec script changes branches.

    Returns:
        str: Branch name if in git repo, None otherwise
    """
    global _branch_cache, _branch_resolved
    if _branch_resolved:
        return _branch_cache

    result = subprocess.run(
        ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
        capture_output=True, text=True
    )
    _branch_resolved = True
    _branch_cache = result.stdout.strip() if result.returncode == 0 else None
    return _branch_cache


def get_default_branch():
    """Get the default branch name (main, master, etc.).

    Returns:
        str: Default branch name, or 'main' if it cannot be determined
    """
    result = subprocess.run(
        'git symbolic-ref refs/remotes/origin/HEAD',
        shell=True, capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout.strip().split('/')[-1]
    for name in ('main', 'master'):
        result = subprocess.run(
            ['git', 'rev-parse', '--verify', name],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return name
    return 'main'


# --- Spec-branch association ---

def get_associated_spec(branch=None):
    """Get spec associated with a branch from dev.yaml.

    Args:
        branch: Branch name. If None, uses current branch.

    Returns:
        str: Spec name if associated, None otherwise
    """
    if branch is None:
        branch = get_current_branch()
    if not branch:
        return None
    repo = get_repo_name()
    if not repo:
        return None
    value = _yaml_get(f'spec.{repo}.branches.{branch}.spec')
    return value if value else None


def associate_spec(spec_name, branch=None):
    """Associate a spec with a branch in dev.yaml.

    Returns:
        bool: True if successful
    """
    if branch is None:
        branch = get_current_branch()
    repo = get_repo_name()
    if not repo or not branch:
        return False
    _yaml_set(f'spec.{repo}.branches.{branch}.spec', spec_name)
    return True


def disassociate_spec(branch=None):
    """Disassociate spec from a branch in dev.yaml.

    Idempotent: safe to call if no association exists.

    Args:
        branch: Branch name. If None, uses current branch.

    Returns:
        bool: True (always succeeds; idempotent)
    """
    if branch is None:
        branch = get_current_branch()
    repo = get_repo_name()
    if not repo or not branch:
        return True
    _yaml_unset(f'spec.{repo}.branches.{branch}.spec')
    return True


def get_all_associations():
    """Get all spec-branch associations from dev.yaml.

    Returns:
        dict: Mapping of branch -> spec name
    """
    associations = {}
    repo = get_repo_name()
    if not repo:
        return associations

    branches = _yaml_get(f'spec.{repo}.branches') or {}
    for branch, branch_data in branches.items():
        if isinstance(branch_data, dict) and branch_data.get('spec'):
            associations[branch] = branch_data['spec']

    return associations


def require_associated_spec(error_exit=True):
    """Get current branch's spec, exiting with error if none.

    Args:
        error_exit: If True, exit with error when no spec. If False, return None.

    Returns:
        tuple: (spec_name, branch) or exits with error
    """
    branch = get_current_branch()
    spec_name = get_associated_spec(branch)

    if not spec_name:
        if error_exit:
            if os.getenv('CC') == '1':
                print(json.dumps({'error': 'No spec associated with current branch', 'branch': branch}))
            else:
                print(f"Error: No spec associated with branch '{branch}'", file=sys.stderr)
                print("Use /spec <name> to associate a spec first", file=sys.stderr)
            sys.exit(1)
        return None, branch

    return spec_name, branch


# --- Path helpers ---

def spec_path(spec_name, project=None):
    """Get the Path to a spec directory under the doc root.

    Args:
        spec_name: Name of the spec
        project: Optional project override (uses that project's doc root)

    Returns:
        Path: Path to <doc-root>/specs/<spec_name>/
    """
    if project:
        return doc_root_for_project(project) / 'specs' / spec_name
    return doc_root() / 'specs' / spec_name


def is_valid_project(name):
    """Check if name is a valid project directory.

    A valid project has at least one of: specs/, subsystems/, steering/
    """
    spec_dir = os.path.expandvars(get_spec_repo_directory())
    candidate = Path(spec_dir) / name
    if not candidate.is_dir():
        return False
    return (candidate / 'specs').is_dir() or (candidate / 'subsystems').is_dir() or (candidate / 'steering').is_dir()


def parse_composite_spec(value):
    """Parse composite spec format: [project:]spec[:ctx1,ctx2]

    Disambiguation for 'a:b' (2 parts):
    1. Is 'a' a valid spec in the CURRENT project? -> spec=a, ctx=b.split(',')
    2. Is 'a' a valid project? -> project=a, spec=b
    3. Neither -> error: spec 'a' not found

    For 'a:b:c' (3 parts): always project:spec:ctx

    Returns:
        tuple: (project, spec_name, context_refs)
    Raises:
        SystemExit if disambiguation fails
    """
    if ':' not in value:
        return None, value, []

    parts = value.split(':')

    if len(parts) == 3:
        project = parts[0]
        spec_name = parts[1]
        ctx = [c.strip() for c in parts[2].split(',') if c.strip()]
        return project, spec_name, ctx

    if len(parts) == 2:
        a, b = parts[0], parts[1]
        # 1. Check if 'a' is a valid spec in current project
        if spec_path(a).is_dir():
            ctx = [c.strip() for c in b.split(',') if c.strip()]
            return None, a, ctx
        # 2. Check if 'a' is a valid project
        if is_valid_project(a):
            return a, b, []
        # 3. Neither -- error
        print(f"Error: '{a}' is not a valid spec in the current project, nor a valid project", file=sys.stderr)
        sys.exit(1)

    print(f"Error: Invalid composite spec format: '{value}'", file=sys.stderr)
    print("Expected: [project:]spec[:ctx1,ctx2]", file=sys.stderr)
    sys.exit(1)


def steering_path():
    """Get the Path to the steering directory under the doc root.

    Returns:
        Path: Path to <doc-root>/steering/
    """
    return doc_root() / 'steering'


def in_git_repo():
    """Check if we're in a git repository.

    Returns:
        bool: True if in git repo
    """
    result = subprocess.run(
        ['git', 'rev-parse', '--git-dir'],
        capture_output=True, text=True
    )
    return result.returncode == 0


# --- Context helpers ---

def get_contexts(branch=None):
    """Get contexts for a branch from dev.yaml.

    Args:
        branch: Branch name. If None, uses current branch.

    Returns:
        list: List of context references, empty if none
    """
    if branch is None:
        branch = get_current_branch()
    if not branch:
        return []
    repo = get_repo_name()
    if not repo:
        return []

    value = _yaml_get(f'spec.{repo}.branches.{branch}.ctx')
    if value:
        return [c.strip() for c in str(value).split(',') if c.strip()]

    return []


def set_contexts(contexts, branch=None):
    """Set contexts for a branch in dev.yaml.

    Args:
        contexts: List of context references
        branch: Branch name. If None, uses current branch.

    Returns:
        bool: True if successful
    """
    if branch is None:
        branch = get_current_branch()
    repo = get_repo_name()
    if not repo or not branch:
        return False
    ctx_str = ','.join(contexts)
    _yaml_set(f'spec.{repo}.branches.{branch}.ctx', ctx_str)
    return True


def parse_tasks(content):
    """Parse all tasks from tasks.md content into structured dicts.

    Handles both compact and detailed task formats:
        Compact:  - [ ] **1.1** Title
        Detailed: - [ ] **Task 1.1**: Title
                    - **File**: path/to/file
                    - **BlockedBy**: task-1.0

    Returns:
        list of dicts with keys:
            id: str (normalized numeric ID, e.g. "1.1")
            title: str
            completed: bool
            metadata: dict (File, Change, Outcome, Context, BlockedBy, etc.)
            raw_lines: list[str]
            line_num: int (1-based)
    """
    tasks = []
    lines = content.split('\n')

    task_pattern = re.compile(
        r'^(\s*)- \[([ xX])\] \*\*(?:Task\s+|T)?(\d+(?:\.\d+)*)\**[:\s]*(.*)'
    )
    meta_pattern = re.compile(r'^\s+- \*\*([^*]+)\*\*:?\s*(.*)')
    heading_pattern = re.compile(r'^#{1,6}\s')

    # Find all task line indices
    task_starts = []
    for i, line in enumerate(lines):
        m = task_pattern.match(line)
        if m:
            _indent, check, task_id, title = m.groups()
            task_starts.append((i, task_id.strip(), check.strip().lower() == 'x', title.strip()))

    for idx, (line_num, task_id, completed, title) in enumerate(task_starts):
        next_task_line = task_starts[idx + 1][0] if idx + 1 < len(task_starts) else len(lines)

        end = next_task_line
        for j in range(line_num + 1, next_task_line):
            if heading_pattern.match(lines[j]):
                end = j
                break

        raw_lines = lines[line_num:end]

        metadata = {}
        current_key = None
        for line in raw_lines[1:]:
            m = meta_pattern.match(line)
            if m:
                key, value = m.groups()
                key = key.strip()
                metadata[key] = value.strip()
                current_key = key
            elif current_key and line.startswith('  ') and line.strip():
                metadata[current_key] = metadata[current_key] + ' ' + line.strip()

        tasks.append({
            'id': task_id,
            'title': title,
            'completed': completed,
            'metadata': metadata,
            'raw_lines': raw_lines,
            'line_num': line_num + 1,
        })

    return tasks


def check_dependencies(task_id, tasks):
    """Check if all BlockedBy dependencies for a task are completed.

    Args:
        task_id: str - ID of the task to check (e.g. "1.2")
        tasks: list of task dicts from parse_tasks()

    Returns:
        tuple (satisfied: bool, unmet: list[str])
    """
    task_lookup = {t['id']: t for t in tasks}
    task = task_lookup.get(task_id)
    if not task:
        return True, []

    blocked_by = task['metadata'].get('BlockedBy', '').strip()
    if not blocked_by:
        return True, []

    normalized = blocked_by.replace('`', '')
    raw_ids = re.split(r'[,\s]+', normalized)

    blocker_ids = []
    for rid in raw_ids:
        rid = rid.strip()
        if not rid:
            continue
        if rid.startswith('task-'):
            rid = rid[5:]
        if re.match(r'^\d+(?:\.\d+)*$', rid):
            blocker_ids.append(rid)

    unmet = []
    for blocker_id in blocker_ids:
        blocker = task_lookup.get(blocker_id)
        if blocker is not None and not blocker['completed']:
            unmet.append(blocker_id)

    return len(unmet) == 0, unmet


def resolve_context_path(ref, project=None):
    """Resolve a context reference to a filesystem path.

    Format: [<project>:]<name>
    - 'steering' -> <doc-root>/steering/ (or steering.md)
    - anything else -> <doc-root>/ctx/<name>/ (or context/<name>/ or subsystems/<name>/)
    - project:name -> resolves against that project's doc root

    Args:
        ref: Context reference string
        project: Optional project override

    Returns:
        Path: Resolved path (directory preferred over file)
    """
    root = doc_root_for_project(project) if project else doc_root()

    if ':' in ref:
        team_override, name = ref.split(':', 1)
        root = doc_root_for_project(team_override)
    else:
        name = ref

    if name == 'steering':
        base = root / 'steering'
    else:
        ctx_base = root / 'ctx' / name
        context_base = root / 'context' / name
        subsystems_base = root / 'subsystems' / name
        if ctx_base.is_dir() or ctx_base.with_suffix('.md').is_file():
            base = ctx_base
        elif context_base.is_dir() or context_base.with_suffix('.md').is_file():
            base = context_base
        elif subsystems_base.is_dir() or subsystems_base.with_suffix('.md').is_file():
            base = subsystems_base
        else:
            base = ctx_base

    if base.is_dir():
        return base
    md_file = base.with_suffix('.md')
    if md_file.is_file():
        return md_file
    return base


def parse_spec_and_ctx(argv):
    """Parse spec composite format and --ctx from argv.

    Supports:
      spec-name                      -> project=None, spec='spec-name', ctx=[]
      project:spec:ctx1,ctx2         -> project='project', spec='spec', ctx=['ctx1','ctx2']
      spec:ctx1,ctx2                 -> project=None, spec='spec', ctx=['ctx1','ctx2']
      project:spec                   -> project='project', spec='spec', ctx=[]
      spec --ctx ctx1,ctx2           -> project=None, spec='spec', ctx=['ctx1','ctx2']
      spec,ctx1,ctx2                 -> project=None, spec='spec', ctx=['ctx1','ctx2'] (legacy comma)

    Returns:
        tuple: (project, spec_name, context_refs)
    """
    args = argv[1:]
    spec_name = None
    project = None
    context_refs = []
    positional = None

    i = 0
    while i < len(args):
        if args[i] in ('--ctx', '--context') and i + 1 < len(args):
            for ref in args[i + 1].split(','):
                ref = ref.strip()
                if ref:
                    context_refs.append(ref)
            i += 2
        elif not args[i].startswith('--'):
            positional = args[i]
            i += 1
        else:
            i += 1

    if positional:
        if ':' in positional:
            project, spec_name, composite_ctx = parse_composite_spec(positional)
            context_refs = composite_ctx + context_refs
        else:
            parts = [p.strip() for p in positional.split(',') if p.strip()]
            spec_name = parts[0]
            context_refs = parts[1:] + context_refs

    # Deduplicate preserving order
    seen = set()
    deduped = []
    for ref in context_refs:
        if ref not in seen:
            seen.add(ref)
            deduped.append(ref)

    return project, spec_name, deduped
