---
description: Create spec directory structure in current branch
model: opus
allowed-tools: Bash($WSROOT/.claude/scripts/spec-create:*)
argument-hint: [project:]name[:ctx1,ctx2]
---

## Arguments

- **[project:]name[:ctx1,ctx2]** (optional): Spec name in composite format. Use issue:name format (e.g., 123:auth) to seed from GitHub issue

## Your task

Execute the script to create spec directory structure in current branch:

```bash
CC=1 $WSROOT/.claude/scripts/spec-create [[project:]name[:ctx1,ctx2]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm spec creation. Show the spec name, location, branch association, and list files created. If seeded from GitHub issue, mention the issue number and title. If contexts were set, show them too. Suggest running /spec:interview to refine requirements.

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

```
[OK] Created spec '199-git-integration' from GitHub issue #199

Details:
  Location: .dev/specs/199-git-integration/
  Branch: main
  Associated: Yes (stored in dev.yaml)
  Source: GitHub Issue #199 - Add issue integration

Files created:
  - requirements.md (seeded from issue)
  - design.md
  - tasks.md

Next steps:
  - Refine requirements: /spec:interview
  - Generate design: /spec:design
```

