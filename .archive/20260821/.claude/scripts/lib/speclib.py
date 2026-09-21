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

    For trunk branches (main/master/develop), <branch> is clone-scoped:
        <clone-basename>::<branch>  (e.g. dev2::main)
    For feature branches, <branch> is the plain git branch name.
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
from branchkey import TRUNK_BRANCHES, branch_key as _branch_key_impl


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
CONFIG_KEYS = ('spec-repo-directory', 'project', 'jira-project', 'steering-context', 'tracker-preference')

# Valid values for the tracker-preference config key
TRACKER_PREFERENCE_VALUES = ('ask', 'github', 'jira')

# Valid values for the steering-context config key
STEERING_CONTEXT_VALUES = ('manual', 'spec-branch', 'any-branch', 'always')
STEERING_CONTEXT_DEFAULT = 'spec-branch'


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


# --- Steering context mode ---

def get_steering_context():
    """Get the steering-context injection mode from dev.yaml.

    Returns:
        str: One of 'manual', 'spec-branch', 'any-branch', 'always'.
             Defaults to 'spec-branch'.
    """
    repo = get_repo_name()
    if not repo:
        return STEERING_CONTEXT_DEFAULT
    value = _yaml_get(f'spec.{repo}.steering-context')
    if value and value in STEERING_CONTEXT_VALUES:
        return value
    return STEERING_CONTEXT_DEFAULT


def set_steering_context(mode):
    """Set the steering-context injection mode in dev.yaml."""
    repo = get_repo_name()
    if not repo:
        return
    if mode not in STEERING_CONTEXT_VALUES:
        print(f"Error: Invalid steering-context value '{mode}'.", file=sys.stderr)
        print(f"  Valid values: {', '.join(STEERING_CONTEXT_VALUES)}", file=sys.stderr)
        sys.exit(1)
    _yaml_set(f'spec.{repo}.steering-context', mode)


def should_inject_steering(branch, spec_name, default_branch):
    """Determine whether steering context should be injected for this session.

    Args:
        branch: Current git branch name
        spec_name: Associated spec name (or None)
        default_branch: Default branch name (e.g. 'main')

    Returns:
        bool: True if steering should be injected
    """
    mode = get_steering_context()
    if mode == 'manual':
        return False
    if mode == 'always':
        return True
    is_default = (branch == default_branch)
    if mode == 'any-branch':
        return not is_default
    # spec-branch (default): inject when spec is associated on a non-default branch
    return not is_default and spec_name is not None


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
        key = _branch_key(branch)
        value = _yaml_get(f'spec.{repo}.branches.{key}.project')
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
    key = _branch_key(branch)
    _yaml_set(f'spec.{repo}.branches.{key}.project', name)


def remove_branch_project(branch):
    """Remove branch project override from dev.yaml."""
    repo = get_repo_name()
    if not repo or not branch:
        return
    key = _branch_key(branch)
    _yaml_unset(f'spec.{repo}.branches.{key}.project')


def get_branch_project(branch=None):
    """Get branch-level project override (no fallback to repo default).

    Unlike get_project(), this returns None if no branch override is set,
    rather than falling back to the repo default or repo name.

    Args:
        branch: Branch name. If None, uses current branch.

    Returns:
        str or None: Branch project override, or None if not set
    """
    if branch is None:
        branch = get_current_branch()
    repo = get_repo_name()
    if not repo or not branch:
        return None
    key = _branch_key(branch)
    value = _yaml_get(f'spec.{repo}.branches.{key}.project')
    return value if value else None


# --- JIRA project ---

def get_jira_project():
    """Get JIRA project key from dev.yaml.

    Returns:
        str or None: JIRA project key, or None if not configured.
    """
    repo = get_repo_name()
    if not repo:
        return None
    return _yaml_get(f'spec.{repo}.jira-project') or None


def set_jira_project(key):
    """Set JIRA project key in dev.yaml."""
    repo = get_repo_name()
    if not repo:
        return
    _yaml_set(f'spec.{repo}.jira-project', key)


# --- Tracker preference ---

def get_tracker_preference():
    """Get tracker preference from dev.yaml.

    Returns:
        str or None: One of 'ask', 'github', 'jira', or None if not configured.
    """
    repo = get_repo_name()
    if not repo:
        return None
    return _yaml_get(f'spec.{repo}.tracker-preference') or None


def set_tracker_preference(value):
    """Set tracker preference in dev.yaml."""
    repo = get_repo_name()
    if not repo:
        return
    _yaml_set(f'spec.{repo}.tracker-preference', value)


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


def display_branch(key):
    """Convert a dev.yaml branch key to a display-friendly branch name.

    Clone-scoped trunk keys (e.g. 'dev2::main') are stripped to just the
    branch name ('main') for human-readable output. Feature branch keys are
    returned unchanged.

    Args:
        key: dev.yaml branch key (output of _branch_key)

    Returns:
        str: Display-friendly branch name
    """
    if '::' in key:
        return key.split('::', 1)[1]
    return key


def _branch_key(branch):
    """Return the dev.yaml branch key for a given branch name.

    Delegates to branchkey.branch_key -- the shared helper also used by
    the statusline (which can't import speclib without pulling ruamel.yaml).

    For trunk branches (main/master/develop), the key is clone-scoped
    (e.g. dev2::main) so multiple clones on the same trunk branch keep
    independent spec/project/context state. For feature branches, the
    branch name alone is the key.
    """
    key = _branch_key_impl(branch)
    if branch in TRUNK_BRANCHES and key == branch:
        print(f"Warning: could not determine clone directory for trunk branch '{branch}'", file=sys.stderr)
    return key


def clear_branch_cache():
    """Clear the cached branch name so the next get_current_branch() re-reads git."""
    global _branch_cache, _branch_resolved
    _branch_cache = None
    _branch_resolved = False


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
    key = _branch_key(branch)
    value = _yaml_get(f'spec.{repo}.branches.{key}.spec')
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
    key = _branch_key(branch)
    _yaml_set(f'spec.{repo}.branches.{key}.spec', spec_name)
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
    key = _branch_key(branch)
    _yaml_unset(f'spec.{repo}.branches.{key}.spec')
    return True


def get_all_associations():
    """Get all spec-branch associations from dev.yaml.

    Returns:
        dict: Mapping of dev.yaml branch key -> spec name. Keys are raw YAML
              keys (e.g. 'dev2::main' for clone-scoped trunk branches, or
              'feature-x' for feature branches). Use display_branch() to
              extract the git branch name for comparison or display.
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

    A valid project has at least one of: specs/, ctx/, steering/
    """
    spec_dir = os.path.expandvars(get_spec_repo_directory())
    candidate = Path(spec_dir) / name
    if not candidate.is_dir():
        return False
    return (candidate / 'specs').is_dir() or (candidate / 'ctx').is_dir() or (candidate / 'steering').is_dir()


_NAME_PATTERN = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')


def _validate_name(value, field_label):
    """Validate a name value against the allowed pattern.

    Args:
        value: The name string to validate.
        field_label: Human-readable label for error messages (e.g., 'project', 'spec', 'context').

    Returns:
        True if valid.

    Raises:
        SystemExit if invalid.
    """
    if not _NAME_PATTERN.match(value):
        print(f"Error: Invalid {field_label} name '{value}'.", file=sys.stderr)
        print(f"  Names must match: {_NAME_PATTERN.pattern}", file=sys.stderr)
        sys.exit(1)
    return True


def _parse_field(s):
    """Parse a single field from composite format.

    Returns None (keep) for empty string, '-' (clear) for dash, or the value.
    """
    if not s:
        return None
    if s == '-':
        return '-'
    return s


def _parse_ctx_field(s):
    """Parse the context field from composite format.

    Returns:
        tuple: (context_list, mode)
        - ([], None) -- empty: keep current
        - ([], 'clear') -- '-': clear all
        - ([refs], 'set') -- plain refs: replace all
        - ([refs], 'add') -- +prefixed refs: add to existing
        - ([refs], 'remove') -- -prefixed refs: remove from existing
    """
    if not s:
        return [], None
    if s == '-':
        return [], 'clear'

    items = [c.strip() for c in s.split(',') if c.strip()]
    if not items:
        return [], None

    add_items = []
    remove_items = []
    plain_items = []
    for item in items:
        if item.startswith('+'):
            add_items.append(item[1:].strip())
        elif item.startswith('-'):
            remove_items.append(item[1:].strip())
        else:
            plain_items.append(item)

    if add_items and not remove_items and not plain_items:
        return add_items, 'add'
    if remove_items and not add_items and not plain_items:
        return remove_items, 'remove'
    if plain_items and not add_items and not remove_items:
        return plain_items, 'set'

    print("Error: Cannot mix +prefixed, -prefixed, and plain context refs", file=sys.stderr)
    print("Use all +prefixed (add), all -prefixed (remove), or all plain (replace)", file=sys.stderr)
    sys.exit(1)


def parse_composite_spec(value):
    """Parse composite spec format.

    Three forms:
        Bare name (no colons) -- set spec only:
            'spec2'              -> (None, 'spec2', [], None)      keep:set:keep

        Single colon -- spec:context (project unchanged):
            'auth:billing,gw.shared' -> (None, 'auth', [billing,gw.shared], set)
            'auth:+ctx3'         -> (None, 'auth', [ctx3], add)    keep:set:add
            'auth:-ctx3'         -> (None, 'auth', [ctx3], remove) keep:set:remove

        Two colons -- project:spec:context (each field independent):
            '::ctx1,ctx2'        -> (None, None, [ctx1,ctx2], set)  keep:keep:set
            '::+ctx3'            -> (None, None, [ctx3], add)       keep:keep:add
            '::-ctx3'            -> (None, None, [ctx3], remove)    keep:keep:remove
            ':spec2:'            -> (None, 'spec2', [], None)       keep:set:keep
            ':spec2:ctx1'        -> (None, 'spec2', [ctx1], set)    keep:set:set
            'proj:spec2:'        -> ('proj', 'spec2', [], None)     set:set:keep
            'proj:spec2:-'       -> ('proj', 'spec2', [], clear)    set:set:clear
            'proj::'             -> ('proj', None, [], None)        set:keep:keep
            '-:-:-'              -> ('-', '-', [], clear)            clear:clear:clear
            '-:-:'               -> ('-', '-', [], None)            clear:clear:keep
            '-::'                -> ('-', None, [], None)           clear:keep:keep

        Bare '-' is rejected:
            '-'                  -> Error: suggest ':-:'

    Each position in the two-colon form is independently:
    - Omitted (empty) = keep current value
    - '-' = clear the value
    - value = set to this value

    Context items can be prefixed with + (add) or - (remove).

    Returns:
        tuple: (project, spec, contexts, ctx_mode)
        - project: None (keep), '-' (clear), or str (set)
        - spec: None (keep), '-' (clear), or str (set)
        - contexts: list of context refs (without +/- prefixes)
        - ctx_mode: None (keep), 'clear', 'set', 'add', 'remove'
    Raises:
        SystemExit on invalid input
    """
    if ':' not in value:
        # Bare '-' is ambiguous -- suggest qualified form
        if value == '-':
            print("Error: Bare '-' is ambiguous. Use ':-:' to clear the spec association.", file=sys.stderr)
            sys.exit(1)
        # Bare arg: set spec name
        project, spec, contexts, ctx_mode = None, _parse_field(value), [], None
    else:
        parts = value.split(':', 2)

        if len(parts) == 3:
            # Three-part format: project:spec:ctx
            project = _parse_field(parts[0])
            spec = _parse_field(parts[1])
            contexts, ctx_mode = _parse_ctx_field(parts[2])
        else:
            # Two-part format (1 colon) -- spec:context
            spec_part = parts[0]
            ctx_part = parts[1]
            if not spec_part:
                print(f"Error: Single-colon form requires a spec name before the colon.", file=sys.stderr)
                print(f"  Use ':<spec>:<ctx>' or '::<ctx>' for the two-colon form.", file=sys.stderr)
                sys.exit(1)
            project = None
            spec = _parse_field(spec_part)
            contexts, ctx_mode = _parse_ctx_field(ctx_part)

    # Validate all names atomically before returning
    if project is not None and project != '-':
        _validate_name(project, 'project')
    if spec is not None and spec != '-':
        _validate_name(spec, 'spec')
    for ctx_ref in contexts:
        if '.' in ctx_ref:
            ctx_project, ctx_name = ctx_ref.split('.', 1)
            _validate_name(ctx_project, 'context project')
            _validate_name(ctx_name, 'context name')
        else:
            _validate_name(ctx_ref, 'context')

    return project, spec, contexts, ctx_mode


def apply_spec_state(old_project, old_spec, old_contexts, project, spec, contexts, ctx_mode):
    """Compute new state from old state and parsed spec input. Pure function -- no I/O.

    Args:
        old_project: Current project (str or None)
        old_spec: Current spec name (str or None)
        old_contexts: Current context list (list of str)
        project: Parsed project field: None (keep), '-' (clear), or str (set)
        spec: Parsed spec field: None (keep), '-' (clear), or str (set)
        contexts: Parsed context refs (list of str, without +/- prefixes)
        ctx_mode: None (keep), 'clear', 'set', 'add', 'remove'

    Returns:
        tuple: (new_project, new_spec, new_contexts)
    """
    # Project
    if project is None:
        new_project = old_project
    elif project == '-':
        new_project = None
    else:
        new_project = project

    # Spec
    if spec is None:
        new_spec = old_spec
    elif spec == '-':
        new_spec = None
    else:
        new_spec = spec

    # Contexts
    if ctx_mode is None:
        new_contexts = list(old_contexts)
    elif ctx_mode == 'clear':
        new_contexts = []
    elif ctx_mode == 'set':
        new_contexts = list(contexts)
    elif ctx_mode == 'add':
        new_contexts = list(old_contexts) + [r for r in contexts if r not in old_contexts]
    elif ctx_mode == 'remove':
        new_contexts = [r for r in old_contexts if r not in contexts]
    else:
        new_contexts = list(old_contexts)

    return new_project, new_spec, new_contexts


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

    key = _branch_key(branch)
    value = _yaml_get(f'spec.{repo}.branches.{key}.ctx')
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
    key = _branch_key(branch)
    ctx_str = ','.join(contexts)
    _yaml_set(f'spec.{repo}.branches.{key}.ctx', ctx_str)
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

    Format: [<project>.]<name>
    - 'steering' -> <doc-root>/steering/ (or steering.md)
    - anything else -> <doc-root>/ctx/<name>/
    - project.name -> resolves against that project's doc root

    Args:
        ref: Context reference string
        project: Optional project override

    Returns:
        Path: Resolved path (directory preferred over file)
    """
    root = doc_root_for_project(project) if project else doc_root()

    if '.' in ref:
        team_override, name = ref.split('.', 1)
        root = doc_root_for_project(team_override)
    else:
        name = ref

    if name == 'steering':
        base = root / 'steering'
    else:
        base = root / 'ctx' / name

    if base.is_dir():
        return base
    md_file = base.with_suffix('.md')
    if md_file.is_file():
        return md_file
    return base


def parse_spec_and_ctx(argv):
    """Parse spec composite format from argv.

    Supports:
      spec-name                      -> (None, 'spec-name', [], None)
      project:spec:ctx1,ctx2         -> ('project', 'spec', ['ctx1','ctx2'], 'set')
      ::+ctx1                        -> (None, None, ['ctx1'], 'add')
      ::-ctx1                        -> (None, None, ['ctx1'], 'remove')
      -:-:-                          -> ('-', '-', [], 'clear')
      spec,ctx1,ctx2                 -> (None, 'spec', ['ctx1','ctx2'], 'set') (legacy comma)

    Returns:
        tuple: (project, spec, contexts, ctx_mode)
        - project: None (keep), '-' (clear), or str (set)
        - spec: None (keep), '-' (clear), or str (set)
        - contexts: list of context refs (without +/- prefixes)
        - ctx_mode: None (keep), 'clear', 'set', 'add', 'remove'
    """
    args = argv[1:]
    positional = None

    i = 0
    while i < len(args):
        if not args[i].startswith('--'):
            positional = args[i]
            i += 1
        else:
            i += 1

    project = None
    spec = None
    contexts = []
    ctx_mode = None

    if positional:
        if positional == '-':
            print("Error: Bare '-' is not a valid spec name. Use ':-:' to clear the spec association.", file=sys.stderr)
            sys.exit(1)
        if ':' in positional:
            project, spec, contexts, ctx_mode = parse_composite_spec(positional)
        else:
            # Bare spec or legacy comma format
            comma_parts = [p.strip() for p in positional.split(',') if p.strip()]
            spec = _parse_field(comma_parts[0])
            if len(comma_parts) > 1:
                contexts = comma_parts[1:]
                ctx_mode = 'set'

    # Deduplicate preserving order
    seen = set()
    deduped = []
    for ref in contexts:
        if ref not in seen:
            seen.add(ref)
            deduped.append(ref)

    return project, spec, deduped, ctx_mode
