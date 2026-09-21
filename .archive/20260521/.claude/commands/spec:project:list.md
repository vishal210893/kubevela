---
description: List available projects
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/spec-project-list)
---

## Your task

Execute the script to list available projects:

```bash
CC=1 $WSROOT/.claude/scripts/spec-project-list
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Display projects in a formatted list showing name and spec/subsystem counts. Mark the current project with an asterisk.

**Examples:**
```
Projects
==========

  * dev (current)
    platform
    billing

Current: dev
```

