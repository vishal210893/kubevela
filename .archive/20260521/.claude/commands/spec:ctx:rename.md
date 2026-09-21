---
description: Rename a context directory
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/ctx-rename:*)
argument-hint: <old-name> <new-name>
---

## Arguments

- **<old-name>** (required): Current context name
- **<new-name>** (required): New context name

**IMPORTANT:** If the user did not provide <old-name>, <new-name>, you MUST ask them for these values before executing the script.

## Your task

Execute the script to rename a context directory:

```bash
CC=1 $WSROOT/.claude/scripts/ctx-rename <old-name> <new-name>
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm the rename. Show old and new paths. Note that branch context refs are NOT updated automatically -- branches referencing the old name should update with /spec:ctx.

**Examples:**
```
[OK] Renamed context 'auth' -> 'authentication'

  /workspaces/src/specs/dev/ctx/auth.md -> /workspaces/src/specs/dev/ctx/authentication.md

Note: Update branch refs with /spec:ctx if needed
```

