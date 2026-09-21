---
description: Push current branch to remote
model: haiku
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/git-push:*)
---

## Your task

Execute the script to push current branch to remote:

```bash
CC=1 $WSROOT/.claude/scripts/git-push
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm push succeeded. Show branch and remote.

**Examples:**
```
[OK] Pushed 'feature-auth' to origin
```

