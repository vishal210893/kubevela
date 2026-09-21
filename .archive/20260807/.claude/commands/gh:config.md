---
description: View or modify GitHub configuration
model: sonnet
context: fork
argument-hint: --set key value --unset key
---

## Arguments

- **--set key value** (optional): Set a config value (e.g., --set gh-issue-repo 'owner/repo')
- **--unset key** (optional): Remove a config value (e.g., --unset gh-issue-repo)

## Your task

Execute the script to view or modify github configuration:

```bash
CC=1 $WSROOT/.claude/scripts/gh-config --set key value --unset key
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Show current config values or confirm set/unset operation. Display all GitHub settings in a clean format.

**Examples:**
```
GitHub config:
  gh-issue-repo: gwre-pdo/ai-dev
```

```
OK: Set gh-issue-repo = gwre-pdo/ai-dev
```

```
OK: Unset gh-issue-repo
```

```
No GitHub config set. Use --set to configure.
```

