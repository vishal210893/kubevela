---
description: Remove a spec directory
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/spec-remove *)
argument-hint: [name]
---

## Arguments

- **[name]** (optional): Spec name to remove (defaults to current branch's spec)

**IMPORTANT:** If no arguments are provided, run the script with no arguments. Do NOT ask the user - the script will use defaults.

## Your task

Execute the script to remove a spec directory:

```bash
CC=1 $WSROOT/.claude/scripts/spec-remove [name]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm the spec was removed. Show what was deleted.

**Examples:**
```
[OK] Removed spec 'feature-auth'

Deleted:
  Directory: .dev/specs/feature-auth/
  Association: branch 'feature-auth'
```

