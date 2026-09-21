---
description: Show or set contexts for current branch
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/ctx:*)
argument-hint: [context...]
---

## Arguments

- **[context...]** (optional): Comma-separated context refs to set (replaces existing). If omitted, shows current contexts.

## Your task

Execute the script to show or set contexts for current branch:

```bash
CC=1 $WSROOT/.claude/scripts/ctx [[context...]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** If showing (get): display contexts in a formatted list. If setting: confirm which contexts were set.

**Examples:**
```
Contexts for branch 'feature-auth'

  steering     -> .dev/steering/        (2 files)
  auth         -> .dev/context/auth/    (1 file)

Total: 2 contexts
```

```
Set 2 context(s) on branch 'feature-auth' (replaced previous)

  steering -> .dev/steering/
  auth -> .dev/subsystems/auth.md
```

