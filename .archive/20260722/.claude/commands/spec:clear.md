---
description: Reset all branch-scoped spec settings (project, spec, context)
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/spec-clear *)
---

## Your task

Execute the script to reset all branch-scoped spec settings (project, spec, context):

```bash
CC=1 $WSROOT/.claude/scripts/spec-clear
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm what was cleared. Show the reset summary.

**Examples:**
```
Reset branch 'feature-auth'

  Cleared spec: feature-auth
  Cleared project: platform
  Cleared contexts: steerin
```

```
auth

Branch now uses default settings."
```

```
Nothing to reset on branch 'main' (no branch overrides set)
```

