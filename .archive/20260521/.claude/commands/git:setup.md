---
description: Interactive setup for git workflow configuration
model: haiku
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

Using AskUserQuestion, ask all 4 questions in a single call:

**Question 1:**
- question: "What branch prefix for your branch names? (e.g., 'jsmith' produces jsmith/feature-name)"
- header: "Prefix"
- options:
  1. **{current value if set, otherwise the user.name from git config}** - Use as branch prefix
  2. **None** - No prefix on branch names
- multiSelect: false

**Question 2:**
- question: "Which issue tracker do you want to use?"
- header: "Tracker"
- options:
  1. **gh** - GitHub Issues
  2. **None** - No issue tracker integration
- multiSelect: false

**Question 3:**
- question: "Include issue numbers in branch names?"
- header: "Issue #"
- options:
  1. **No (Recommended)** - No issue number in branch names
  2. **Yes** - Branch names include issue number (e.g., prefix/123/feature-name)
- multiSelect: false

**Question 4:**
- question: "Include spec names in branch names?"
- header: "Spec name"
- options:
  1. **No (Recommended)** - No spec name in branch names
  2. **Yes** - Branch names include spec name (e.g., prefix/spec-name)
- multiSelect: false

### Step 3: Apply configuration

Map answers to config values and run the appropriate commands:

- **branch-prefix**: `CC=1 $WSROOT/.claude/scripts/git-config --set branch-prefix <value>` (skip if "None", unset if previously set)
- **issue-tracker**: `CC=1 $WSROOT/.claude/scripts/git-config --set issue-tracker gh` (skip if "None", unset if previously set)
- **issue-in-branch**: `CC=1 $WSROOT/.claude/scripts/git-config --set issue-in-branch true|false`
- **spec-in-branch**: `CC=1 $WSROOT/.claude/scripts/git-config --set spec-in-branch true|false`

For skipped values that had previous config: `CC=1 $WSROOT/.claude/scripts/git-config --unset <key>`

If the user chose **gh** for issue tracker, suggest running `/gh:setup` to configure the GitHub repository for issues.

### Step 4: Show summary

Run this to display the final configuration:
```bash
CC=1 $WSROOT/.claude/scripts/git-config
```

Display the result as a clean summary of all configured values.
