---
description: Approve pull request
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/pr-approve:*)
argument-hint: [pr-number]
---

## Arguments

- **[pr-number]** (optional): PR number to approve (defaults to current branch's PR)

**IMPORTANT:** If no arguments are provided, run the script with no arguments. Do NOT ask the user - the script will use defaults.

## Your task

Execute the script to approve pull request:

```bash
CC=1 $WSROOT/.claude/scripts/pr-approve [[pr-number]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm approval. Simple and direct.

**Examples:**
```
[OK] Approved PR #123
```

