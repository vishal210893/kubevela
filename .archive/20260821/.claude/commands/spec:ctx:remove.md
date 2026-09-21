---
description: Delete a context directory
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/spec-ctx-remove *)
argument-hint: <name>
---

## Arguments

- **<name>** (required): Context name to delete

**IMPORTANT:** If the user did not provide <name>, you MUST ask them for it before executing the script.

## Your task

Execute the script to delete a context directory:

```bash
CC=1 $WSROOT/.claude/scripts/spec-ctx-remove <name>
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm deletion. Show what was deleted. Remind that git history preserves the content.

**Examples:**
```
[OK] Deleted context 'auth'

  Deleted: /workspaces/src/specs/dev/ctx/auth/

Git history preserves the content.
```

