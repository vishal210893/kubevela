---
description: Remove branch locally and remotely (safe delete only)
model: haiku
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/branch-remove:*)
argument-hint: [name]
---

## Arguments

- **[name]** (optional): Branch name to delete (defaults to current branch)

**IMPORTANT:** If no arguments are provided, run the script with no arguments. Do NOT ask the user - the script will use defaults.

## Your task

Execute the script to remove branch locally and remotely (safe delete only):

```bash
CC=1 $WSROOT/.claude/scripts/branch-remove [[name]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm deletion. Show what was deleted (local, remote). Note if switched branches first.

**Examples:**
```
[OK] Deleted branch 'feature-auth'
[OK] Switched to main
[OK] Deleted local branch
[OK] Deleted remote branch
```

