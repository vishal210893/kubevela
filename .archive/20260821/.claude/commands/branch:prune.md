---
description: Prune merged branches (incl. squash-merged PRs) and stale tracking refs
model: sonnet
context: fork
---

## Your task

Execute the script to prune merged branches (incl. squash-merged prs) and stale tracking refs:

```bash
CC=1 $WSROOT/.claude/scripts/branch-prune
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Show branches that were pruned (remote and local separately). List protected branches that were skipped.

**Examples:**
```
[OK] Pruned 2 remote branches: feature-ol
```

```
fix-bug
[OK] Cleaned up 2 local branches: feature-old
```

```
fix-bug
Protected (kept): main"
```

```
No merged branches to prune. [OK] Cleaned up stale tracking refs
```

