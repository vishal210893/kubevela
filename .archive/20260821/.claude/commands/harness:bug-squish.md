---
description: Find and fix low-effort bugs surfaced by prior code reviews
model: opus
allowed-tools: Bash($WSROOT/.claude/scripts/harness-bug-squish *)
argument-hint: [--days N] [--dry-run]
---

## Your task

Execute the script to find and fix low-effort bugs surfaced by prior code reviews:

```bash
CC=1 $WSROOT/.claude/scripts/harness-bug-squish
```
