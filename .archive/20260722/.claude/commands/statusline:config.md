---
description: View or modify statusline configuration
model: sonnet
context: fork
argument-hint: --set key value --unset key
---

## Arguments

- **--set key value** (optional): Set a config value (e.g., --set theme dark, --set show-model false)
- **--unset key** (optional): Remove a config value, reverting to default (e.g., --unset show-model)

## Your task

Execute the script to view or modify statusline configuration:

```bash
CC=1 $WSROOT/.claude/scripts/statusline-config --set key value --unset key
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Show current config values or confirm set/unset operation. For show output, display the values list in order; append ' (default)' when source is default so unset settings are visible. If warnings are present, show each warning after the config.

**Examples:**
```
Statusline config:
  theme: dark
  display-format: compact (default)
  model-format: compact
  show-model: true
  show-profile: true
  show-profile-version: true (default)
  show-container-version: true
  show-claude-code-version: true
  show-context-percentage: true
  show-usage: true
  show-project: true
  show-context: true
  show-git-branch: true
  show-spec: true
  show-path: true
  show-path-wsroot-shorthand: true
```

```
Set theme = dark
```

```
Unset show-model (reverts to default: true)
```

```
No statusline config set. All segments use defaults (enabled).
```

