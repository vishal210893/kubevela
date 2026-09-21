---
description: Disassociate spec from current branch
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/spec-clear:*)
---

## Your task

Execute the script to disassociate spec from current branch:

```bash
CC=1 $WSROOT/.claude/scripts/spec-clear
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm the spec disassociation. Show what was removed.

**Examples:**
```
[OK] Disassociated spec 'feature-auth' from branch 'feature-auth'

The spec directory remains at .dev/specs/feature-auth/
```

