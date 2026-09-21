---
description: Merge PR with cleanup
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/pr-merge:*)
argument-hint: [pr-number] [--admin] [--no-squash]
---

## Arguments

- **[pr-number]** (optional): PR number (defaults to current branch's PR)
- **[--admin]** (optional): Bypass PR requirements (requires admin permissions)
- **[--no-squash]** (optional): Use regular merge instead of squash merge

**IMPORTANT:** If no arguments are provided, run the script with no arguments. Do NOT ask the user - the script will use defaults.

**IMPORTANT:** Optional flags ([--admin], [--no-squash]) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to merge pr with cleanup:

```bash
CC=1 $WSROOT/.claude/scripts/pr-merge [[pr-number]] [[--admin]] [[--no-squash]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm merge. Show merge type, cleanup actions. Note if branch was updated before merge and if default branch was updated.

**Examples:**
```
[OK] Merged PR #123
Squash merged (commits combined)
[OK] Deleted remote branch
[OK] Updated local {default_branch}
```

```
[OK] Merged PR #123
⚠ Branch was behind - updated before merge
Squash merged (commits combined)
[OK] Deleted remote branch
[OK] Updated local {default_branch}
```

