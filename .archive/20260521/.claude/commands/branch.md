---
description: Show current branch or switch to existing branch
model: haiku
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/branch:*)
argument-hint: [name]
---

## Arguments

- **[name]** (optional): Branch name to switch to. If omitted, shows current branch. Errors if branch doesn't exist.

## Your task

Execute the script to show current branch or switch to existing branch:

```bash
CC=1 $WSROOT/.claude/scripts/branch [[name]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** If showing (get): display the current branch name. If switching: confirm branch switch. Then remind them to rename the session.

**Examples:**
```
Current branch: main
```

```
[OK] Switched to branch 'feature-auth'

Tip: Rename this session to match: /rename feature-auth
```

