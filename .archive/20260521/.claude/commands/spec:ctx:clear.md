---
description: Clear contexts from current branch
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/ctx-clear:*)
argument-hint: [context...]
---

## Arguments

- **[context...]** (optional): Comma-separated context refs to remove. If omitted, removes ALL contexts.

## Your task

Execute the script to clear contexts from current branch:

```bash
CC=1 $WSROOT/.claude/scripts/ctx-clear [[context...]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm which contexts were removed.

**Examples:**
```
Removed 1 context from branch 'feature-auth'

  Removed: auth
  Remaining: steering
```

```
Cleared all contexts from branch 'feature-auth'

  Removed: steerin
```

```
auth"
```

