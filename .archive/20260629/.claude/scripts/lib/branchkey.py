"""branchkey.py - Shared dev.yaml branch-key helper.

Computes the dev.yaml key for a given git branch. Lives in a standalone
module (no ruamel.yaml / devyaml dependency) so perf-sensitive callers
like the statusline can import it on every invocation without pulling
in the full config-I/O stack.

For trunk branches (main/master/develop), the key is clone-scoped:
    <clone-basename>::<branch>  (e.g. dev2::main)

This lets multiple clones of the same repo on the same trunk branch
maintain independent spec/project/context associations under
spec.<repo>.branches.<key> in dev.yaml.

For feature branches, the plain branch name is the key.
"""

import subprocess
from pathlib import Path


TRUNK_BRANCHES = frozenset({'main', 'master', 'develop'})


def _git_root():
    """Return the git repo root Path, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None


def branch_key(branch):
    """Return the dev.yaml branch key for a given branch name."""
    if branch in TRUNK_BRANCHES:
        root = _git_root()
        if root:
            return f'{root.name}::{branch}'
    return branch
