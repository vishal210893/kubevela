---
description: Show current branch, switch to existing, or create from description
model: sonnet
context: fork
allowed-tools: [Bash($WSROOT/.claude/scripts/branch *), Bash($WSROOT/.claude/scripts/branch-create *)]
argument-hint: [name] --spec project:spec:context,...|spec --impl|-i --pr|-p --poll|-o --fix|-f --merge|-m
---

## Arguments

- **[name]** (optional): Branch name to switch to, or natural language description to create from. If omitted, shows current branch.
- **--spec project:spec:context,...|spec** (optional): Spec name or qualified spec (see docs/guides/spec-parameter.md)
- **--impl|-i** (optional): Implement the feature after branch creation
- **--pr|-p** (optional): Create PR after implementation
- **--poll|-o** (optional): Poll CI checks after PR creation
- **--fix|-f** (optional): Auto-fix CI failures (implies --poll)
- **--merge|-m** (optional): Merge PR after CI passes (implies --fix --pr --impl)

**IMPORTANT:** Optional flags (--impl|-i, --pr|-p, --poll|-o, --fix|-f, --merge|-m) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to show current branch, switch to existing, or create from description:

```bash
CC=1 $WSROOT/.claude/scripts/branch [name] --spec project:spec:context,...|spec --impl|-i --pr|-p --poll|-o --fix|-f --merge|-m
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Handle based on "mode" in JSON output:

mode=get: Display current branch name.

mode=switch: Confirm branch switch. If spec_status is present, show it
  (indicates the --spec flag updated the branch's spec association).
  Remind to rename session.

mode=create: YOU MUST CALL /branch:create. This is not optional.
  Step 1: Generate a short kebab-case branch name (2-3 words max, e.g. "fix-auth-bug")
    from the description. Do NOT slugify the full description.
  Step 2: IMMEDIATELY call /branch:create with the generated name, passing through:
    --description (the FULL original description text from the JSON),
    --spec if present in JSON, and ALL pipeline flags from the JSON flags object.
  branch-create handles the entire pipeline from there. You are done after step 2.
  If you do not call /branch:create the branch will not exist and everything fails.

**Examples:**
```
Current branch: main
```

```
[OK] Switched to branch 'feature-auth'

Tip: Rename this session to match: /rename feature-auth
```

```
[OK] Created branch 'sclaussen/add-auth-logging' from origin/main (prefix: sclaussen)
[OK] Pushed to remote with upstream tracking

Tip: Rename this session to match: /rename sclaussen/add-auth-logging
```

