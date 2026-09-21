---
description: Show or set current spec association
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/spec:*)
argument-hint: [[project:]spec[:ctx1,ctx2]]
---

## Arguments

- **[[project:]spec[:ctx1,ctx2]]** (optional): Spec name in composite format to associate (defaults to showing current). Errors if spec doesn't exist.

**IMPORTANT:** If no arguments are provided, run the script with no arguments. Do NOT ask the user - the script will use defaults.

## Your task

Execute the script to show or set current spec association:

```bash
CC=1 $WSROOT/.claude/scripts/spec [[[project:]spec[:ctx1,ctx2]]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** If showing (get): display the current spec association for the branch. If setting: confirm the spec association. Show spec name, branch, and storage location. If contexts were set, show them too.

**Examples:**
```
Spec 'auth' on branch 'sclaussen/680/feature/auth'
  Path: /workspaces/src/specs/dev/specs/auth/
```

```
No spec associated with branch 'main'
```

```
OK Associated spec 'feature-auth' with branch 'feature-auth'

Details:
  Branch: feature-auth
  Spec: .dev/specs/feature-auth/
  Stored: dev.yaml spec.ai-dev.branches.feature-auth.spec
```

