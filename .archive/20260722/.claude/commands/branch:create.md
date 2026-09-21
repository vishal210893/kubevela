---
description: Create new branch and push to remote
allowed-tools: Bash($WSROOT/.claude/scripts/branch-create *)
argument-hint: <name> --description|-d <text> --spec project:spec:context,...|spec --impl|-i --pr|-p --poll|-o --fix|-f --merge|-m
---

## Arguments

- **<name>** (required): Branch name
- **--description|-d <text>** (optional): What to implement (used by --impl to know what to build)
- **--spec project:spec:context,...|spec** (optional): Spec name or qualified spec (see docs/guides/spec-parameter.md)
- **--impl|-i** (optional): Implement the feature after branch creation
- **--pr|-p** (optional): Create PR after implementation
- **--poll|-o** (optional): Poll CI checks after PR creation
- **--fix|-f** (optional): Auto-fix CI failures (implies --poll)
- **--merge|-m** (optional): Merge PR after CI passes (implies --fix --pr --impl)

**IMPORTANT:** If the user did not provide <name>, you MUST ask them for it before executing the script.

**IMPORTANT:** Optional flags (--impl|-i, --pr|-p, --poll|-o, --fix|-f, --merge|-m) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to create new branch and push to remote:

```bash
CC=1 $WSROOT/.claude/scripts/branch-create <name> --description|-d <text> --spec project:spec:context,...|spec --impl|-i --pr|-p --poll|-o --fix|-f --merge|-m
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm branch creation. Show what it branched from. Note if pushed to remote.
If spec was associated or created, show spec status. If prefix was applied, show it.
Remind user to rename session with: /rename <branch-name>.
If pipeline flags are present in JSON output, execute them in order:
1. impl: The "description" field is the user's implementation request -- use it as your
   primary guidance for what to build. If a spec is associated, also read its
   requirements.md, design.md, and tasks.md for detailed context. Make all necessary
   code changes, run builds (node dev.js capability build <name> && node dev.js profile
   build if capabilities changed), commit, and push. Update docs and release notes
   if applicable. REQUIRED: also update tests (add/update in the relevant test/
   directory), the current spec if one is associated, and context docs (consult
   the Contexts table in steering/memory.md, update affected ctx/<name>/design.md
   or ctx/<name>.md in the specs repo).
2. pr/poll/fix/merge: Invoke /git:sync --pr, passing through applicable flags
   (--poll if poll, --fix if fix, --merge if merge). git-sync handles the full
   pipeline: commit, push, create PR, poll CI, auto-fix failures, and admin merge.

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

