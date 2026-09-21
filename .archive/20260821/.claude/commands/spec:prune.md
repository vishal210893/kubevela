---
description: Clean up orphaned spec-branch associations
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/spec-prune)
---

## Your task

Execute the script to clean up orphaned spec-branch associations:

```bash
CC=1 $WSROOT/.claude/scripts/spec-prune
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Show which associations were kept vs removed. Display summary with counts.

**Examples:**
```
Checking spec-branch associations...

Found 3 associations:
  [OK] feature-auth -> feature-auth (branch exists)
  [--] old-branch -> old-spec (branch deleted)

Removed 1 orphaned association
Kept 1 association
```

