---
description: Interactive setup for GitHub configuration
model: haiku
allowed-tools:
  - AskUserQuestion
  - Bash
---

## Your task

Configure GitHub settings through an interactive wizard using AskUserQuestion.

### Step 1: Read current config

Run this command to check existing configuration:
```bash
CC=1 $WSROOT/.claude/scripts/gh-config
```

Parse the JSON output to identify any current values for use as defaults in the questions below.

### Step 2: Ask GitHub settings

Using AskUserQuestion, ask 1 question:

**Question 1:**
- question: "Which GitHub repository for issues? (owner/repo format)"
- header: "GH Repo"
- options:
  1. **{current value if set, otherwise 'gwre-pdo/ai-dev'}** - Use as issue repository
  2. **Current repo** - Auto-detect from current git remote
  3. **None** - No cross-repo issue tracking (use current repo by default)
- multiSelect: false

### Step 3: Apply configuration

Map answers to config values and run the appropriate commands:

- If user selected a specific repo: `CC=1 $WSROOT/.claude/scripts/gh-config --set issue-repo <owner/repo>`
- If "Current repo": `CC=1 $WSROOT/.claude/scripts/gh-config --unset issue-repo` (let it auto-detect)
- If "None": `CC=1 $WSROOT/.claude/scripts/gh-config --unset issue-repo`

### Step 4: Show summary

Run this to display the final configuration:
```bash
CC=1 $WSROOT/.claude/scripts/gh-config
```

Display the result as a clean summary of all configured values.
