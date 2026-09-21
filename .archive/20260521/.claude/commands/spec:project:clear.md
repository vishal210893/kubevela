---
description: Clear branch project override
model: haiku
allowed-tools: Bash($WSROOT/.claude/scripts/spec-project-clear:*)
---

## Your task

Execute the script to clear branch project override:

```bash
CC=1 $WSROOT/.claude/scripts/spec-project-clear
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm the branch project override was cleared. Show what the project now falls back to (repo default or repo name).

**Examples:**
```
Cleared project override for branch 'feature-x'
Project now: dev (repo default)
```

```
No project override set for branch 'feature-x' (nothing to clear)
```

