---
description: Fetch and checkout PR branch for review
model: haiku
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/pr-pull:*)
argument-hint: <pr-number>
---

## Arguments

- **<pr-number>** (required): PR number to checkout

**IMPORTANT:** If the user did not provide <pr-number>, you MUST ask them for it before executing the script.

## Your task

Execute the script to fetch and checkout pr branch for review:

```bash
CC=1 $WSROOT/.claude/scripts/pr-pull <pr-number>
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm PR checkout. Show PR number, branch, author, title. Remind to rename session.

**Examples:**
```
[OK] Checked out PR #123
Branch: feature-auth
Author: johndoe
Title: Add authentication

Tip: Rename session: /rename feature-auth
```

