"""devyaml.py - Shared library for reading/writing ~/.dev/dev.yaml.

Uses ruamel.yaml for round-trip comment/key-order/formatting preservation
and fcntl.flock() for concurrent write safety (prevents corruption when
statusline hook and a config command run simultaneously).

Usage:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
    from devyaml import get, set, unset, register_defaults, register_repo_defaults

    # Register defaults for a global category (call once at module level)
    register_defaults('statusline', {
        'theme': 'dark',
        'show-model': True,
        'client-id': None,   # None = no default, omitted from materialization
    })

    # Register defaults for a per-repo category
    register_repo_defaults('spec', lambda repo: {
        'spec-repo-directory': '$WSROOT/specs',
        'project': repo,
    })

    # Read value (triggers default materialization)
    theme = get('statusline.theme', 'dark')
    branch_prefix = get(f'git.{repo}.branch-prefix')  # triggers repo defaults
    spec = get(f'spec.{repo}.branches.{branch}.spec')  # triggers repo defaults

    # Write value (creates nested structure as needed)
    set('statusline.theme', 'light')
    set(f'git.{repo}.branch-prefix', 'sclaussen')

    # Remove key
    unset('statusline.theme')

    # Per-repo/branch helpers (return dict or {})
    repo_cfg = get_repo_section('git', 'ai-dev')
    branch_cfg = get_branch_section('spec', 'ai-dev', 'sc/my-feature')

Dot-path rules:
    - Separator is '.' (dot)
    - Repo names and branch names must not contain dots
    - Branch names may contain slashes (e.g., 'sc/my-feature') - these are
      treated as a single path component since they don't contain dots

Default materialization:
    - Global categories: triggered when get() finds a missing top-level section
    - Per-repo categories: triggered when get() finds a missing repo section
      within a per-repo category (e.g., spec.<repo>, git.<repo>)
    - Only defaults with non-None values are materialized
    - Per-branch data is never pre-materialized; created on demand
"""

import fcntl
import io
import os
from contextlib import contextmanager
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

DEV_YAML_PATH = Path.home() / '.dev' / 'dev.yaml'

# Categories that use per-repo structure - never pre-materialized
_PER_REPO_CATEGORIES = {'git', 'gh', 'spec', 'meeting'}

# Registry: category -> {key: default_value}  (None = no default)
_defaults_registry: dict = {}

# Registry: category -> callable(repo_name) -> {key: default_value}
_repo_defaults_registry: dict = {}

# Shared YAML instance configured for round-trip preservation
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False
_yaml.width = 4096  # Avoid wrapping long values


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_defaults(category: str, defaults_dict: dict) -> None:
    """Register the default schema for a category.

    Args:
        category: Top-level YAML key (e.g., 'statusline', 'voice').
        defaults_dict: Mapping of key -> default_value.
            None values mean "no default" and are excluded from
            materialization.
    """
    _defaults_registry[category] = defaults_dict


def register_repo_defaults(category: str, defaults_fn) -> None:
    """Register a function that returns per-repo defaults.

    When get() accesses a per-repo path (e.g., 'spec.toolbar.project')
    and the repo section doesn't exist, defaults_fn is called with the
    repo name and the returned defaults are written to dev.yaml.

    Args:
        category: Top-level YAML key (e.g., 'spec', 'git', 'gh').
        defaults_fn: Callable(repo_name: str) -> dict mapping
            key -> default_value. None values are excluded.
    """
    _repo_defaults_registry[category] = defaults_fn


# ---------------------------------------------------------------------------
# Low-level file I/O with locking
# ---------------------------------------------------------------------------

@contextmanager
def _locked_file():
    """Open dev.yaml with an exclusive lock.

    Yields the open binary file handle (seeked to position 0).
    Releases the lock and closes the file on exit.
    """
    DEV_YAML_PATH.parent.mkdir(parents=True, exist_ok=True)
    f = open(str(DEV_YAML_PATH), 'a+b')
    fcntl.flock(f, fcntl.LOCK_EX)
    try:
        f.seek(0)
        yield f
    finally:
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _parse(f) -> CommentedMap:
    """Parse dev.yaml from an open file handle (positioned at 0)."""
    f.seek(0)
    raw = f.read()
    content = raw.decode('utf-8') if raw else ''
    if not content.strip():
        return CommentedMap()
    data = _yaml.load(io.StringIO(content))
    return data if data is not None else CommentedMap()


def _dump(f, data: CommentedMap) -> None:
    """Write data to dev.yaml via an open file handle (truncate + write)."""
    buf = io.StringIO()
    _yaml.dump(data, buf)
    f.seek(0)
    f.truncate()
    f.write(buf.getvalue().encode('utf-8'))


# ---------------------------------------------------------------------------
# Default materialization
# ---------------------------------------------------------------------------

def _has_concrete_defaults(category: str) -> bool:
    """Return True if category has at least one non-None registered default."""
    defaults = _defaults_registry.get(category, {})
    return any(v is not None for v in defaults.values())


def _materialize_defaults(category: str) -> None:
    """Write concrete defaults for a category to dev.yaml if section missing.

    Only runs for categories that:
    - Have registered defaults with at least one non-None value
    - Are not per-repo categories (git, gh, spec, meeting)
    """
    if category in _PER_REPO_CATEGORIES:
        return
    if not _has_concrete_defaults(category):
        return

    defaults = _defaults_registry.get(category, {})
    concrete = {k: v for k, v in defaults.items() if v is not None}
    if not concrete:
        return

    with _locked_file() as f:
        data = _parse(f)
        if category in data:
            return  # Already materialized by another process
        data[category] = CommentedMap()
        for k, v in concrete.items():
            data[category][k] = v
        _dump(f, data)


def _materialize_repo_defaults(category: str, repo: str) -> None:
    """Write per-repo defaults to dev.yaml if the repo section is missing.

    Called automatically by get() when accessing a per-repo path
    (e.g., 'spec.toolbar.project') and no repo section exists.
    """
    if category not in _repo_defaults_registry:
        return

    defaults_fn = _repo_defaults_registry[category]
    defaults = defaults_fn(repo)
    concrete = {k: v for k, v in defaults.items() if v is not None}
    if not concrete:
        return

    with _locked_file() as f:
        data = _parse(f)
        # Re-check under lock
        if category in data and repo in data[category]:
            return  # Already materialized by another process
        if category not in data:
            data[category] = CommentedMap()
        if repo not in data[category]:
            data[category][repo] = CommentedMap()
        for k, v in concrete.items():
            if k not in data[category][repo]:
                data[category][repo][k] = v
        _dump(f, data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_config() -> dict:
    """Return the full dev.yaml as a plain dict (no locking, snapshot read)."""
    if not DEV_YAML_PATH.exists():
        return {}
    with open(str(DEV_YAML_PATH), 'r') as f:
        data = _yaml.load(f)
    return data if data is not None else {}


def get(dotpath: str, default=None):
    """Read a nested value from dev.yaml by dot-separated path.

    Triggers default materialization for the top-level category if the
    section is missing and defaults are registered.

    Args:
        dotpath: Dot-separated path, e.g. 'statusline.theme',
                 'spec.ai-dev.branches.sc/my-feature.spec'.
                 Dots separate path components; slashes in names are fine.
        default: Value to return if not found (default: None).

    Returns:
        The value at the path, or default if not found.
    """
    parts = dotpath.split('.')
    category = parts[0]

    # Trigger materialization if global category section is missing
    if category in _defaults_registry and category not in _PER_REPO_CATEGORIES:
        data = read_config()
        if category not in data:
            _materialize_defaults(category)

    # Trigger per-repo materialization if repo section is missing
    if category in _PER_REPO_CATEGORIES and len(parts) >= 2:
        repo = parts[1]
        if category in _repo_defaults_registry:
            data = read_config()
            if category not in data or repo not in data.get(category, {}):
                _materialize_repo_defaults(category, repo)

    data = read_config()
    current = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def set(dotpath: str, value) -> None:  # noqa: A001
    """Write a value to dev.yaml at the given dot-separated path.

    Creates intermediate dicts as needed. Preserves all other keys.

    Args:
        dotpath: Dot-separated path, e.g. 'statusline.theme'.
        value: Value to store. Booleans, ints, and strings are supported.
    """
    parts = dotpath.split('.')

    with _locked_file() as f:
        data = _parse(f)
        _set_nested(data, parts, value)
        _dump(f, data)


def unset(dotpath: str) -> bool:
    """Remove a key from dev.yaml at the given dot-separated path.

    Args:
        dotpath: Dot-separated path, e.g. 'statusline.theme'.

    Returns:
        True if the key was found and removed, False if it didn't exist.
    """
    parts = dotpath.split('.')

    with _locked_file() as f:
        data = _parse(f)
        removed = _del_nested(data, parts)
        if removed:
            _dump(f, data)
    return removed


def get_repo_section(category: str, repo: str) -> dict:
    """Return the repo-scoped config dict (category.<repo>).

    Args:
        category: Top-level key, e.g. 'git', 'gh', 'spec'.
        repo: Repo name, e.g. 'ai-dev'.

    Returns:
        Dict of config values for this repo, or {} if not found.
    """
    data = read_config()
    return dict(data.get(category, {}).get(repo, {}))


def get_branch_section(category: str, repo: str, branch: str) -> dict:
    """Return the branch-scoped config dict (category.<repo>.branches.<branch>).

    Args:
        category: Top-level key, e.g. 'spec', 'meeting'.
        repo: Repo name, e.g. 'ai-dev'.
        branch: Branch name, e.g. 'sc/my-feature'.

    Returns:
        Dict of config values for this branch, or {} if not found.
    """
    data = read_config()
    return dict(
        data.get(category, {})
            .get(repo, {})
            .get('branches', {})
            .get(branch, {})
    )


# ---------------------------------------------------------------------------
# Path navigation helpers
# ---------------------------------------------------------------------------

def _set_nested(data: CommentedMap, parts: list, value) -> None:
    """Navigate to the nested location and set value, creating dicts as needed."""
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = CommentedMap()
        current = current[part]
    current[parts[-1]] = value


def _del_nested(data: CommentedMap, parts: list) -> bool:
    """Navigate to the nested location and delete the key. Returns True if found."""
    current = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        return False
    del current[parts[-1]]
    return True
