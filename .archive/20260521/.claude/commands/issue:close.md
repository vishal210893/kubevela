---
description: Close GitHub issue
model: haiku
argument-hint: <issue-number> [comment]
---

## Arguments

- **<issue-number> [comment]** (required): Issue number and optional closing comment

**IMPORTANT:** If the user did not provide <issue-number> [comment], you MUST ask them for it before executing the script.

## Your task

Execute the script to close github issue:

```bash
CC=1 $WSROOT/.claude/scripts/issue-close <issue-number> [comment]
```
