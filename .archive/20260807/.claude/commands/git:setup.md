---
description: Interactive setup for git workflow configuration
allowed-tools:
  - AskUserQuestion
  - Bash
---

## Your task

Configure git workflow settings through an interactive wizard using AskUserQuestion.

### Step 1: Read current config

Run this command to check existing configuration:
```bash
CC=1 $WSROOT/.claude/scripts/git-config
```

Parse the JSON output to identify any current values for use as defaults in the questions below.

### Step 2: Ask main settings

STOP. You must call AskUserQuestion now. Do NOT proceed to Step 3 or apply any
configuration until the user has answered these questions. Do not infer answers
from defaults or pick Recommended options on the user's behalf.

Using AskUserQuestion, ask these questions in a single call:

**Question 1:**
- question: "What branch prefix for your branch names? (e.g., 'jsmith' produces jsmith/feature-name)"
- header: "Prefix"
- options:
  1. **{current value if set, otherwise the user.name from git config}** - Use as branch prefix
  2. **None** - No prefix on branch names
- multiSelect: false

**Question 2:**
- question: "Include issue numbers in branch names? (only affects /issue)"
- header: "Issue #"
- options:
  1. **No (Recommended)** - No issue number in branch names
  2. **Yes** - Branch names include issue number (e.g., prefix/123/feature-name)
- multiSelect: false

**Question 3:**
- question: "Include spec names in branch names? (only affects /issue)"
- header: "Spec"
- options:
  1. **No (Recommended)** - No spec name in branch names
  2. **Yes** - Branch names include spec name (e.g., prefix/spec-name or prefix/123/spec-name)
- multiSelect: false

**Question 4:**
- question: "Default pipeline level when running /git:sync on a branch? This determines how far the automation goes without needing explicit flags."
- header: "Pipeline"
- options:
  1. **none (Recommended)** - Just commit, pull, and push. No PR created unless you pass flags.
  2. **pr** - Automatically create a PR after sync
  3. **poll** - Create PR and poll CI checks (-o)
  4. **fix** - Create PR, poll CI, and auto-fix failures (-f)
- multiSelect: false

### Step 3: Apply configuration

Map answers to config values and run the appropriate commands:

- **branch-prefix**: `CC=1 $WSROOT/.claude/scripts/git-config --set branch-prefix <value>` (skip if "None", unset if previously set)
- **issue-in-branch**: `CC=1 $WSROOT/.claude/scripts/git-config --set issue-in-branch true|false`
- **spec-in-branch**: `CC=1 $WSROOT/.claude/scripts/git-config --set spec-in-branch true|false`
- **pipeline-default**: `CC=1 $WSROOT/.claude/scripts/git-config --set pipeline-default <value>`

For skipped values that had previous config: `CC=1 $WSROOT/.claude/scripts/git-config --unset <key>`

Suggest running `/gh:setup` to configure the GitHub repository for issues.

### Step 4: Show summary

Run this to display the final configuration:
```bash
CC=1 $WSROOT/.claude/scripts/git-config
```

Display the result as a clean summary of all configured values.
