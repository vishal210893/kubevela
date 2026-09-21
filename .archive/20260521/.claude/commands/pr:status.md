---
description: Show PR status with checks and reviews
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/pr-status:*)
argument-hint: [pr-number]
---

## Arguments

- **[pr-number]** (optional): PR number (defaults to current branch's PR)

**IMPORTANT:** If no arguments are provided, run the script with no arguments. Do NOT ask the user - the script will use defaults.

## Your task

Execute the script to show pr status with checks and reviews:

```bash
CC=1 $WSROOT/.claude/scripts/pr-status [[pr-number]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Show complete PR state: status, author, mergeable, reviews, checks. Highlight blockers.

**Examples:**
```
PR #123: Add authentication
Status: open
Mergeable: [OK] Yes
Reviews: [OK] Approved (2)
Checks: [OK] All passing (5/5)
```

