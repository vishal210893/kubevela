---
description: Display commit history
model: haiku
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/git-log)
---

## Your task

Execute the script to display commit history:

```bash
CC=1 $WSROOT/.claude/scripts/git-log
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Start with a branch relationship summary: show commits ahead/behind main, ahead/behind origin/main, and ahead/behind your remote tracking branch if it exists. Then display recent commits in scannable format showing hash, date, author, message, and branch pointers.

**Examples:**
```
Branch: feature-auth
  5 commits ahead of main
  2 commits ahead of origin/main
  0 commits ahead of origin/feature-auth (up to date)

abc1234 2024-03-15 John feat: add auth (HEAD -> feature-auth)
def5678 2024-03-14 Jane fix: bug (origin/mai
```

```
main)"
```

