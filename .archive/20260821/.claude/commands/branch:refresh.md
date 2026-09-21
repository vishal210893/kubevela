---
description: Merge latest default branch into current branch
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/branch-refresh *)
---

## Your task

Execute the script to merge latest default branch into current branch:

```bash
CC=1 $WSROOT/.claude/scripts/branch-refresh
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm merge of default branch succeeded. Show how many commits are ahead of default branch.

**Examples:**
```
[OK] Merged origin/{default_branch} into 'feature-auth'
5 commits ahead
```

