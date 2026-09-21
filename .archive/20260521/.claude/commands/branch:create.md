---
description: Create new branch and push to remote
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/branch-create:*)
argument-hint: <name> [--spec [project:]spec[:ctx1,ctx2]] [--impl]
---

## Arguments

- **<name>** (required): Branch name
- **--spec [project:]spec[:ctx1,ctx2]** (optional): Spec to create or associate with the branch, in composite format
- **[--impl]** (optional): Begin implementation immediately after branch creation

**IMPORTANT:** If the user did not provide <name>, you MUST ask them for it before executing the script.

**IMPORTANT:** Optional flags ([--impl]) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to create new branch and push to remote:

```bash
CC=1 $WSROOT/.claude/scripts/branch-create <name> [--spec [project:]spec[:ctx1,ctx2]] [[--impl]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm branch creation. Show what it branched from. Note if pushed to remote. If spec was associated or created, show spec status. If prefix was applied, show it. Remind user to rename session with: /rename <branch-name>. IMPORTANT: If impl_requested is true in the output, immediately begin implementing the feature described in the spec context - do not wait for user input.

**Examples:**
```
[OK] Created branch 'feature-auth' from origin/main
[OK] Pushed to remote with upstream tracking

Tip: Rename this session to match: /rename feature-auth
```

```
[OK] Created branch 'sclaussen/feature-auth' from origin/main (prefix: sclaussen)
[OK] Pushed to remote with upstream tracking

Tip: Rename this session to match: /rename sclaussen/feature-auth
```

```
[OK] Created branch 'feature-auth' from origin/main
[OK] Pushed to remote with upstream tracking
[OK] Created spec 'auth' and associated with branch

Tip: Rename this session to match: /rename feature-auth
```

