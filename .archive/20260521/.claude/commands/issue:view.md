---
description: View GitHub issue details
model: haiku
argument-hint: <issue-number>
---

## Arguments

- **<issue-number>** (required): Issue number or URL to view

**IMPORTANT:** If the user did not provide <issue-number>, you MUST ask them for it before executing the script.

## Your task

Execute the script to view github issue details:

```bash
CC=1 $WSROOT/.claude/scripts/gh-view.py <issue-number>
```
