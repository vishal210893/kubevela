---
description: Configure SDD repository settings
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/spec-config *)
argument-hint: --set key value --unset key
---

## Arguments

- **--set key value** (optional): Set a config value (keys: spec-repo-directory, project, jira-project, steering-context)
- **--unset key** (optional): Remove a config value

## Your task

Execute the script to configure sdd repository settings:

```bash
CC=1 $WSROOT/.claude/scripts/spec-config --set key value --unset key
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Display the configuration result. For --set/--unset, confirm what changed. With no args, show all current config values and resolved doc root. If a branch project override is active, mention it.

**Examples:**
```
SDD Configuration
==================

  spec-repo-directory:  $WSROOT/specs
  project:              dev (repo default)
    branch override:    platform (branch 'feature-x')

  Spec root: /workspaces/src/specs/dev/
```

```
[OK] Set project = dev
```

