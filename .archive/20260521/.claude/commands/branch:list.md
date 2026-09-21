---
description: List all branches
model: haiku
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/branch-list)
---

## Your task

Execute the script to list all branches:

```bash
CC=1 $WSROOT/.claude/scripts/branch-list
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** List all branches clearly. Show current branch, tracking info, and recent commit. Format for easy scanning.

**Examples:**
```
* feature-auth    abc1234 [origin/feature-auth] feat: add auth
  main            def5678 [origin/main] fix: bug
```

