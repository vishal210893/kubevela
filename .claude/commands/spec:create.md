---
description: Create spec directory structure in current branch
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/spec-create *)
argument-hint: [spec | proj:spec | proj:spec:ctx1,ctx2]
---

## Arguments

- **[spec | proj:spec | proj:spec:ctx1,ctx2]** (optional): Composite spec target. Bare name sets spec only. 'proj:spec' sets branch project override and spec. 'proj:spec:ctx1,ctx2' also sets contexts. Defaults to the current branch name if omitted.

**IMPORTANT:** If no arguments are provided, run the script with no arguments. Do NOT ask the user - the script will use defaults.

## Your task

Execute the script to create spec directory structure in current branch:

```bash
CC=1 $WSROOT/.claude/scripts/spec-create [spec | proj:spec | proj:spec:ctx1,ctx2]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm spec creation. Show the spec name, location, branch association, and list files created. Suggest running /spec:interview to refine requirements.

**Examples:**
```
[OK] Created spec 'feature-auth'

Details:
  Location: .dev/specs/feature-auth/
  Branch: feature-auth
  Associated: Yes (stored in dev.yaml)

Files created:
  - requirements.md
  - design.md
  - tasks.md

Next steps:
  - Refine requirements: /spec:interview
  - Generate requirements: /spec:requirements
```

