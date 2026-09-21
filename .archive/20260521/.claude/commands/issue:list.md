---
description: List GitHub issues
model: haiku
argument-hint: [filter]
---

## Arguments

- **[filter]** (optional): Filter by label (P1, bug, feature), assignee (@username), or state (open, closed, all)

## Your task

Execute the script to list github issues:

```bash
CC=1 $WSROOT/.claude/scripts/gh-list.py [[filter]]
```
