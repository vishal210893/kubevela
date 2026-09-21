---
description: Interactive wizard to configure SDD repository settings
model: haiku
allowed-tools:
  - AskUserQuestion
  - Bash
---

## Your task

Configure Spec-Driven Development (SDD) settings through an interactive wizard using AskUserQuestion.

### Step 1: Gather defaults

Run these commands to gather defaults:

```bash
ls -d $WSROOT/specs 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

```bash
git remote get-url origin 2>/dev/null | sed 's/.*\///' | sed 's/\.git$//' | tr '[:upper:]' '[:lower:]'
```

```bash
ls -d $WSROOT/specs/*/ 2>/dev/null | xargs -I{} basename {} | sort
```

If `$WSROOT/specs` does NOT exist, display this message and stop:

```
Specs repository not found at $WSROOT/specs

Clone the shared specs repository first:
  git clone https://github.com/gwre-pdo/specs $WSROOT/specs

Then re-run /spec:setup
```

If it exists, continue to Step 2.

### Step 2: Ask SDD settings

Using AskUserQuestion, ask both questions in a single call:

**Question 1:**
- question: "Where is your shared specs repository cloned?"
- header: "Specs repo"
- options:
  1. **$WSROOT/specs (Recommended)** - Default location: $WSROOT/specs
  2. **$WSROOT/specs/{repo-name}** - Nested under repo name: $WSROOT/specs/{repo-name}
- multiSelect: false

**Question 2:**
- question: "What project name in the specs repo contains the steering/ctx/specs directories?"
- header: "Project"
- options: Build the options list as follows. Always include at least 2 options:
  1. **{repo-name} (Recommended)** - Specs stored in {specs-repo}/{repo-name}/
  2. If existing project directories were found in Step 1, include up to 2 as additional options with description "Specs stored in {specs-repo}/{name}/"
  3. If no existing projects, add **dev** as second option with description "Specs stored in {specs-repo}/dev/"
- multiSelect: false

### Step 3: Apply configuration

Using the user's answers from Step 2, set config values. If the user picked "Other" for either question, use the custom text they provided.

```bash
CC=1 $WSROOT/.claude/scripts/spec-config --set spec-repo-directory '<selected-specs-repo>'
CC=1 $WSROOT/.claude/scripts/spec-config --set project '<selected-project>'
```

Create the directory structure:

```bash
mkdir -p <selected-specs-repo>/<selected-project>/{steering,ctx,specs}
```

### Step 4: Show summary

Display what was configured:

```
SDD configured for <project>

  Specs repo:  <specs-repo>
  Project:     <project>
  Spec root:   <specs-repo>/<project>/

Directories:
  <specs-repo>/<project>/steering/
  <specs-repo>/<project>/ctx/
  <specs-repo>/<project>/specs/

Next steps:
  - Generate steering docs: /spec:steering
  - Create a spec: /spec:create <name>
  - Switch project (branch override): /spec:project <name>
  - Change repo default: /spec:config --set project <name>
```
