---
description: Rename spec directory
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/spec-rename:*)
argument-hint: <new-name>
---

## Arguments

- **<new-name>** (required): New name for the spec

**IMPORTANT:** If the user did not provide <new-name>, you MUST ask them for it before executing the script.

## Your task

Execute the script to rename spec directory:

```bash
CC=1 $WSROOT/.claude/scripts/spec-rename <new-name>
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm the rename operation. Show old and new paths. Note that branch/worktree names are NOT changed.

**Examples:**
```
[OK] Renamed spec 'old-name' -> 'new-name'

Updated:
  .dev/specs/old-name/ -> .dev/specs/new-name/

Note: Branch and worktree names unchanged
```

