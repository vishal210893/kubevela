---
description: Comment on GitHub issue
model: haiku
argument-hint: <issue-number> <message>
---

## Arguments

- **<issue-number> <message>** (required): Issue number and comment message

**IMPORTANT:** If the user did not provide <issue-number> <message>, you MUST ask them for it before executing the script.

## Your task

Execute the script to comment on github issue:

```bash
CC=1 $WSROOT/.claude/scripts/issue-comment <issue-number> <message>
```
