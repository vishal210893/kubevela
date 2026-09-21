---
description: View or modify git workflow configuration
model: haiku
context: fork
argument-hint: [--set key value] [--unset key]
---

## Arguments

- **[--set key value]** (optional): Set a config value (e.g., --set branch-prefix 'sclaussen')
- **[--unset key]** (optional): Remove a config value (e.g., --unset branch-prefix)

## Your task

Execute the script to view or modify git workflow configuration:

```bash
CC=1 $WSROOT/.claude/scripts/git-config [[--set key value]] [[--unset key]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Show current config values or confirm set/unset operation. Display all git workflow settings in a clean format.

**Examples:**
```
Git workflow config:
  branch-prefix: sclaussen
  issue-tracker: gh
  issue-in-branch: false
  spec-in-branch: false
```

```
[OK] Set branch-prefix = sclaussen
```

```
[OK] Unset branch-prefix
```

```
No git workflow config set. Use --set to configure.
```

