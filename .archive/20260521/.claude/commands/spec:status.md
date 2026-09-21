---
description: Show status of current spec
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/spec-status)
---

## Your task

Execute the script to show status of current spec:

```bash
CC=1 $WSROOT/.claude/scripts/spec-status
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Display spec status with file existence, task completion progress, and branch associations. Use checkmarks and progress indicators.

**Examples:**
```
Spec: feature-auth
═══════════════════

Files:
[OK] requirements.md
[OK] design.md
[ ] tasks.md

Tasks: 3/5 complete (60%)

Branch: feature-auth (associated)
```

