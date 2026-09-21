---
description: Add context items to current branch
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/ctx-add:*)
argument-hint: <context>...
---

## Arguments

- **<context>...** (required): Comma-separated context refs: steering, auth, team2:billing

**IMPORTANT:** If the user did not provide <context>..., you MUST ask them for it before executing the script.

## Your task

Execute the script to add context items to current branch:

```bash
CC=1 $WSROOT/.claude/scripts/ctx-add <context>...
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm which contexts were added. Show resolved paths.

**Examples:**
```
[OK] Added 2 context(s) to branch 'feature-auth'

  + steering -> .dev/steering/
  + auth -> .dev/context/auth.md

Current contexts: steerin
```

```
auth"
```

