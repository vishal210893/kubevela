---
description: List all available contexts
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/spec-ctx-list)
---

## Your task

Execute the script to list all available contexts:

```bash
CC=1 $WSROOT/.claude/scripts/spec-ctx-list
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Display available contexts in a formatted list showing type, name, file count, and whether active on current branch.

**Examples:**
```
Available Contexts
==================

  steering    (3 files) [active]
  auth        (2 files)
  payments    (1 file)

3 available | 1 active on branch 'feature-auth'
```

