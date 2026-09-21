---
description: Clean up orphaned context associations
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/ctx-prune)
---

## Your task

Execute the script to clean up orphaned context associations:

```bash
CC=1 $WSROOT/.claude/scripts/ctx-prune
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Show which context associations were kept vs removed. Display summary with counts.

**Examples:**
```
Checking context associations...

Found 3 branches with contexts:
  [OK] feature-auth: steerin
```

```
auth (branch exists)
  [--] old-branch: steering (branch deleted)

Removed contexts from 1 orphaned branch
Kept 1 branch with contexts"
```

