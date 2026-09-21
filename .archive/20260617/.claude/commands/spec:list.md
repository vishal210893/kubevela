---
description: List all specs with branch/worktree status
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/spec-list)
---

## Your task

Execute the script to list all specs with branch/worktree status:

```bash
CC=1 $WSROOT/.claude/scripts/spec-list
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Display specs in a formatted table showing name, associated branch, and worktree path. Include totals.

**Examples:**
```
Specs
═════

Name              Branch              Worktree
────              ──────              ────────
feature-auth      feature-auth        -
user-settings     user-settings       ../repo-user-settings/

Total: 2 specs
```

