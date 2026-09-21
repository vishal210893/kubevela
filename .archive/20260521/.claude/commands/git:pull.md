---
description: Fetch and merge changes from remote
model: haiku
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/git-pull)
---

## Your task

Execute the script to fetch and merge changes from remote:

```bash
CC=1 $WSROOT/.claude/scripts/git-pull
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Show what was pulled. Summarize changes (files, insertions, deletions). Note if fast-forward or merge.

**Examples:**
```
[OK] Pulled changes from origin/feature
2 files change
```

```
15 insertions(+)
```

```
3 deletions(-)"
```

