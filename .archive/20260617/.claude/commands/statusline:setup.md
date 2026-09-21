---
description: Interactive setup for statusline configuration
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

STOP. You must call AskUserQuestion now. Do NOT proceed to Step 3 or apply any
configuration until the user has answered these questions. Do not infer answers
from defaults or pick Recommended options on the user's behalf.

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
CC=1 $WSROOT/.claude/scripts/statusline-config --set model-format compact
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-model true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-profile true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-profile-version true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-container-version true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-claude-code-version true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-context-percentage true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-context-bar true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-usage true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-project true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-git-branch true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-spec true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-context true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-path true
CC=1 $WSROOT/.claude/scripts/statusline-config --set show-path-wsroot-shorthand true
CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-warning 30
CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-critical 60
CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-warning-1m 15
CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-critical-1m 40
CC=1 $WSROOT/.claude/scripts/statusline-config --set usage-cache-ttl 120
CC=1 $WSROOT/.claude/scripts/statusline-config --set usage-projection-display 50
CC=1 $WSROOT/.claude/scripts/statusline-config --set usage-projection-warning 80
CC=1 $WSROOT/.claude/scripts/statusline-config --set usage-projection-critical 100
```

If the user selects "Custom", continue to Step 3.

### Step 3: Ask settings (left-to-right statusline order)

Questions follow the statusline display order: `Model [profile | container-ver | claude-code-ver | context% | usage% | branch-section] /path`

Using AskUserQuestion, ask all 5 questions in a single call:

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
  1. **Yes (Recommended)** - Display model name like 'Opus 4.7 1M XHI'
  2. **No** - Hide model name
- multiSelect: false

**Question 3b:**
- question: "Which model name format?"
- header: "Model Format"
- options:
  1. **Compact (Recommended)** - 'O47 1M+' (single-letter family + dotless version + glued effort suffix: l/m/h, + for xhigh, ++ for max)
  2. **Full** - 'Opus 4.7 1M XHI' (family + version + 3-letter effort)
- multiSelect: false

**Question 4:**
- question: "Show profile name in statusline?"
- header: "Profile"
- options:
  1. **Yes (Recommended)** - Display profile name like 'standard'
  2. **No** - Hide profile name
- multiSelect: false

**Question 4b:**
- question: "Show profile version next to the profile name?"
- header: "Profile Version"
- options:
  1. **Yes (Recommended)** - Display profile version like 'standard 1.18.0'
  2. **No** - Hide profile version
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

**Question 7b:**
- question: "Show visual context usage bar in statusline?"
- header: "Context Bar"
- options:
  1. **Yes (Recommended)** - Display visual bar like '[@@@@@@@@!!] 41%'
  2. **No** - Show percentage only without bar
- multiSelect: false

**Question 8:**
- question: "Show API usage percentage and reset timer in statusline?"
- header: "Usage %"
- options:
  1. **Yes (Recommended)** - Display usage % like '13% ↻2h34m'
  2. **No** - Hide usage info
- multiSelect: false

**Question 9:**
- question: "Show spec project name in statusline?"
- header: "Project"
- options:
  1. **Yes (Recommended)** - Display project name like 'appmgr' before spec/branch
  2. **No** - Hide project name
- multiSelect: false

**Question 10:**
- question: "Show loaded branch contexts in statusline?"
- header: "Contexts"
- options:
  1. **Yes (Recommended)** - Display context names like 'steering|auth' before branch
  2. **No** - Hide loaded contexts
- multiSelect: false

Then ask these 2 questions in a third AskUserQuestion call:

**Question 11:**
- question: "Show spec association with branch?"
- header: "Spec"
- options:
  1. **Yes (Recommended)** - Display spec name and arrow before branch like 'auth -> branch'
  2. **No** - Hide spec info, show branch only
- multiSelect: false

**Question 12:**
- question: "Show git branch and status in statusline?"
- header: "Git"
- options:
  1. **Yes (Recommended)** - Display branch, uncommitted changes, and spec info
  2. **No** - Hide git info
- multiSelect: false

### Step 3b: Ask threshold settings

Using AskUserQuestion, ask all four threshold questions in a single call:

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

**Question (1M Warning Threshold):**
- question: "When using Opus 1M, at what usage % should the context indicator turn yellow (warning)?"
- header: "1M Warning %"
- options:
  1. **{current value or 15} (Recommended)** - Current setting
  2. **10** - Earlier warning
  3. **20** - Later warning
  4. **25** - Much later warning
- multiSelect: false

**Question (1M Critical Threshold):**
- question: "When using Opus 1M, at what usage % should the context indicator turn red (critical)?"
- header: "1M Critical %"
- options:
  1. **{current value or 40} (Recommended)** - Current setting
  2. **30** - Earlier critical alert
  3. **50** - Later critical alert
  4. **60** - Much later critical alert
- multiSelect: false

### Step 3c: Ask usage projection settings

Using AskUserQuestion, ask all 3 usage projection questions in a single call:

**Question (Projection Display):**
- question: "At what projected usage % should the projection appear in the statusline?"
- header: "Projection Display %"
- options:
  1. **{current value or 50} (Recommended)** - Current setting
  2. **30** - Show projection earlier
  3. **40** - Slightly earlier
  4. **60** - Later display
  5. **70** - Much later display
- multiSelect: false

**Question (Projection Warning):**
- question: "At what projected usage % should the projection turn gold (warning)?"
- header: "Projection Warning %"
- options:
  1. **{current value or 80} (Recommended)** - Current setting
  2. **60** - Earlier warning
  3. **70** - Slightly earlier warning
  4. **90** - Later warning
- multiSelect: false

**Question (Projection Critical):**
- question: "At what projected usage % should the projection turn red (critical)?"
- header: "Projection Critical %"
- options:
  1. **{current value or 100} (Recommended)** - Current setting
  2. **80** - Earlier critical alert
  3. **90** - Slightly earlier critical alert
  4. **120** - Later critical alert
- multiSelect: false

### Step 4: Ask path settings

Using AskUserQuestion, ask both path questions in a single call:

**Question 13:**
- question: "Show working directory path in statusline?"
- header: "Path"
- options:
  1. **Yes (Recommended)** - Display current path like '/workspaces/src/repo'
  2. **No** - Hide path
- multiSelect: false

**Question 14:**
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
- **model-format**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set model-format full|compact`
- **show-profile**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-profile true|false`
- **show-profile-version**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-profile-version true|false`
- **show-container-version**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-container-version true|false`
- **show-claude-code-version**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-claude-code-version true|false`
- **show-context-percentage**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-context-percentage true|false`
- **show-context-bar**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-context-bar true|false`
- **show-usage**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-usage true|false`
- **show-project**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-project true|false`
- **show-git-branch**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-git-branch true|false`
- **show-spec**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-spec true|false`
- **show-context**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-context true|false`
- **show-path**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-path true|false`
- **show-path-wsroot-shorthand**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set show-path-wsroot-shorthand true|false`
- **context-threshold-warning**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-warning <value>`
- **context-threshold-critical**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-critical <value>`
- **context-threshold-warning-1m**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-warning-1m <value>`
- **context-threshold-critical-1m**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set context-threshold-critical-1m <value>`
- **usage-cache-ttl**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set usage-cache-ttl <value>`
- **usage-projection-display**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set usage-projection-display <value>`
- **usage-projection-warning**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set usage-projection-warning <value>`
- **usage-projection-critical**: `CC=1 $WSROOT/.claude/scripts/statusline-config --set usage-projection-critical <value>`

### Step 6: Show summary

Run this to display the final configuration:
```bash
CC=1 $WSROOT/.claude/scripts/statusline-config
```

Display the result as a clean summary of all configured values. Add a note that the statusline will refresh automatically.
