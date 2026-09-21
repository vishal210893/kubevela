---
description: Rename current branch
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/branch-rename *)
argument-hint: <new-name>
---

## Arguments

- **<new-name>** (required): New name for the current branch

**IMPORTANT:** If the user did not provide <new-name>, you MUST ask them for it before executing the script.

## Your task

Execute the script to rename current branch:

```bash
CC=1 $WSROOT/.claude/scripts/branch-rename <new-name>
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm rename. Show old and new names. Note if remote was updated.

**Examples:**
```
[OK] Renamed branch 'feture-auth' to 'feature-auth'
[OK] Updated remote tracking
```

