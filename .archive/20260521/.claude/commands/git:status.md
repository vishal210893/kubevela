---
description: View repository status
model: haiku
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/git-status)
---

## Your task

Execute the script to view repository status:

```bash
CC=1 $WSROOT/.claude/scripts/git-status
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Summarize repository state for quick decision-making. Group changes by type. Flag anything blocking a commit (conflicts, unmerged files). Keep it scannable.

**Examples:**
```
M  README.md
M  src/auth.js
?? test.log
```

```
M  package.json
 M src/index.js
?? .env
?? logs/
```

