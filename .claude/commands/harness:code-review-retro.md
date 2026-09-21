---
description: Scan merged PRs for unresolved med/low review issues and open follow-up PRs
model: opus
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/harness-code-review-retro *)
argument-hint: [--days N] [--dry-run] [--severity med|low|both]
---

## Your task

Execute the script to scan merged prs for unresolved med/low review issues and open follow-up prs:

```bash
CC=1 $WSROOT/.claude/scripts/harness-code-review-retro
```
