---
description: Interactive setup for statusline configuration
model: haiku
allowed-tools:
  - AskUserQuestion
  - Bash
---

## Your task

Configure statusline settings through an interactive wizard using AskUserQuestion.

### Step 1: Read current config

Run this command to check existing configuration:
```bash
CC=1 $WSROOT/.claude/scripts/statusline-config
```

Parse the JSON output to identify any current values for use as defaults in the questions below.

### Step 2: Ask setup mode

Using AskUserQuestion, ask this question first:

**Question 1:**
- question: "Do you want to use default statusline settings or customize each option?"
- header: "Setup Mode"
- options:
  1. **Default (Recommended)** - Use all default settings (reset any customizations)
  2. **Custom** - Configure each statusline option individually
- multiSelect: false

If the user selects "Default", set all config keys to their default values and skip to Step 5 (Show summary). Use these commands to reset all settings:

```bash
CC=1 $WSROOT/.claude/scripts/statusline-config --set theme dark
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-model true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-profile true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-container-version true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-claude-code-version true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-context-percentage true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-project true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-git-branch true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-spec true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-context true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-path true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-path-wsroot-shorthand true
CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-warning 30
CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-critical 60
```

If the user selects "Custom", continue to Step 3.

### Step 3: Ask settings (left-to-right statusline order)

Questions follow the statusline display order: `[Model] [profile | container-ver | claude-code-ver | context% | branch-section] /path`

Using AskUserQuestion, ask all 4 questions in a single call:

**Question 2:**
- question: "Which terminal color theme?"
- header: "Theme"
- options:
  1. **Dark (Recommended)** - Optimized for dark terminal backgrounds
  2. **Light** - Optimized for light terminal backgrounds
- multiSelect: false

**Question 3:**
- question: "Show model name in statusline?"
- header: "Model"
- options:
  1. **Yes (Recommended)** - Display model name like '[Opus 4.6]'
  2. **No** - Hide model bracket
- multiSelect: false

**Question 4:**
- question: "Show profile name in statusline?"
- header: "Profile"
- options:
  1. **Yes (Recommended)** - Display profile name like 'standard'
  2. **No** - Hide profile name
- multiSelect: false

**Question 5:**
- question: "Show container version in statusline?"
- header: "Container"
- options:
  1. **Yes (Recommended)** - Display container version like '0.7.13' with update indicator
  2. **No** - Hide container version
- multiSelect: false

Then ask all 4 of these questions in a second AskUserQuestion call:

**Question 6:**
- question: "Show Claude Code version in statusline?"
- header: "CC Version"
- options:
  1. **Yes (Recommended)** - Display Claude version like '2.1.15'
  2. **No** - Hide Claude version
- multiSelect: false

**Question 7:**
- question: "Show context usage percentage in statusline?"
- header: "Context %"
- options:
  1. **Yes (Recommended)** - Display context % like '27%'
  2. **No** - Hide context %
- multiSelect: false

**Question 8:**
- question: "Show spec project name in statusline?"
- header: "Project"
- options:
  1. **Yes (Recommended)** - Display project name like 'appmgr' before spec/branch
  2. **No** - Hide project name
- multiSelect: false

**Question 9:**
- question: "Show loaded branch contexts in statusline?"
- header: "Contexts"
- options:
  1. **Yes (Recommended)** - Display context names like 'steering|auth' before branch
  2. **No** - Hide loaded contexts
- multiSelect: false

Then ask these 2 questions in a third AskUserQuestion call:

**Question 10:**
- question: "Show spec association with branch?"
- header: "Spec"
- options:
  1. **Yes (Recommended)** - Display spec name and arrow before branch like 'auth -> branch'
  2. **No** - Hide spec info, show branch only
- multiSelect: false

**Question 11:**
- question: "Show git branch and status in statusline?"
- header: "Git"
- options:
  1. **Yes (Recommended)** - Display branch, uncommitted changes, and spec info
  2. **No** - Hide git info
- multiSelect: false

### Step 3b: Ask threshold settings

Using AskUserQuestion, ask both threshold questions in a single call:

**Question (Warning Threshold):**
- question: "At what usage % should the context indicator turn yellow (warning)?"
- header: "Warning %"
- options:
  1. **{current value or 26} (Recommended)** - Current setting
  2. **20** - Earlier warning
  3. **30** - Slightly later warning
  4. **40** - Later warning
- multiSelect: false

**Question (Critical Threshold):**
- question: "At what usage % should the context indicator turn red (critical)?"
- header: "Critical %"
- options:
  1. **{current value or 60} (Recommended)** - Current setting
  2. **50** - Earlier critical alert
  3. **70** - Later critical alert
  4. **80** - Much later critical alert
- multiSelect: false

### Step 4: Ask path settings

Using AskUserQuestion, ask both path questions in a single call:

**Question 12:**
- question: "Show working directory path in statusline?"
- header: "Path"
- options:
  1. **Yes (Recommended)** - Display current path like '/workspaces/src/repo'
  2. **No** - Hide path
- multiSelect: false

**Question 13:**
- question: "Use shorthand notation for workspace root in path?"
- header: "Path Style"
- options:
  1. **Yes (Recommended)** - Replace $WSROOT with '//' to show '//dev2'
  2. **No** - Show full path like '/workspaces/src/dev2'
- multiSelect: false

### Step 5: Apply configuration

Map answers to config values and run the appropriate commands:

- **theme**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set theme dark|light`
- **show-model**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-model true|false`
- **show-profile**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-profile true|false`
- **show-container-version**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-container-version true|false`
- **show-claude-code-version**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-claude-code-version true|false`
- **show-context-percentage**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-context-percentage true|false`
- **show-project**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-project true|false`
- **show-git-branch**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-git-branch true|false`
- **show-spec**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-spec true|false`
- **show-context**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-context true|false`
- **show-path**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-path true|false`
- **show-path-wsroot-shorthand**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-path-wsroot-shorthand true|false`
- **context-threshold-warning**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-warning <value>`
- **context-threshold-critical**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-critical <value>`

### Step 6: Show summary

Run this to display the final configuration:
```bash
CC=1 $WSROOT/.claude/scripts/statusline-config
```

Display the result as a clean summary of all configured values. Add a note that the statusline will refresh automatically.
