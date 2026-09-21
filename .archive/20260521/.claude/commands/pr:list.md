---
description: List all pull requests
model: haiku
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/pr-list)
---

## Your task

Execute the script to list all pull requests:

```bash
CC=1 $WSROOT/.claude/scripts/pr-list
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** List all PRs. Show number, title, author, status. Format for scanning.

**Examples:**
```
#123  Add authentication     johndoe  open
#122  Fix login bug         janedoe  open
```

