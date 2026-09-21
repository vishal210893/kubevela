---
description: Create or use issue, create branch, and drive implementation pipeline
model: opus
allowed-tools: [Bash($WSROOT/.claude/scripts/issue *), Bash($WSROOT/.claude/scripts/pr-create *), Bash($WSROOT/.claude/scripts/pr-poll *), Bash($WSROOT/.claude/scripts/git-sync *), Bash(gh issue *), Bash(git *), Bash(npm test *), Bash(gh run view *), Read, Edit, Glob, Grep]
argument-hint: [title] --spec [project.][name][:ctx1,ctx2] --body text --impl|-i --pr|-p --poll|-o --fix|-f --merge|-m
---

## Pre-execution: Generate Required Arguments

Before running the script, generate the following argument values:

### qualifier (always generate)

Use this prompt to generate the value:
> Based on the issue title, generate a short dash-cased qualifier for the branch name.
> Examples: 'add-auth', 'fix-login', 'update-deps'
> Keep it short (2-4 words max), lowercase, dashes between words.

## Arguments

- **title** (optional): Issue title (for creating new issues). Omit to use an existing issue instead.
- **--spec [project.][name][:ctx1,ctx2]** (optional): Spec in composite format to create or associate with the branch. Spec can be empty (e.g., project::ctx1,ctx2) to set only project and/or contexts.
- **--body text** (optional): Issue body (for new issues only)
- **--impl|-i** (optional): Begin implementation immediately after setup
- **--pr|-p** (optional): After implementation, commit and create a PR (requires --impl)
- **--poll|-o** (optional): Poll CI checks after PR creation (implies --pr)
- **--fix|-f** (optional): Auto-fix CI failures (up to 30 attempts, implies --poll)
- **--merge|-m** (optional): Admin merge + delete branch after CI passes (implies --fix --poll --pr --impl)

**IMPORTANT:** Optional flags (--impl|-i, --pr|-p, --poll|-o, --fix|-f, --merge|-m) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to create or use issue, create branch, and drive implementation pipeline:

```bash
CC=1 $WSROOT/.claude/scripts/issue [title] --spec [project.][name][:ctx1,ctx2] --body text --impl|-i --pr|-p --poll|-o --fix|-f --merge|-m --qualifier "<generated-qualifier>"
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm issue creation/fetch (show number and URL), branch creation (show full name), and spec status if applicable. Remind user to rename session: /rename <branch-name>

Pipeline stages (execute in order based on output flags):
1. impl: If impl_started is true, implement the feature using issue_context. After completing
   implementation: (1) Verify spec exists and is associated with branch, (2) Update relevant
   docs if needed, (3) Generate/update tests, (4) Update docs/release-notes.md,
   (5) Build: node dev.js capability build && node dev.js profile build
2. pr/poll/fix/merge: If pr_requested is true, invoke /pr-create once passing through applicable
   flags (--poll if poll_requested, --fix if fix_requested, --merge if merge_requested).
   pr-create handles the full pipeline: commit, push, create PR, poll CI, auto-fix failures,
   and admin merge. Do NOT invoke /pr-poll separately -- pr-create handles it when given the flags.
   Note: --merge implies --fix and --poll. If --fix is provided (or implied via
   --merge), and CI fails, the fix loop is handled by the pr-create/pr-poll output prompt.

**Examples:**
```
OK Created issue #123: Add authentication flow
  https://github.com/owner/repo/issues/123
OK Created branch 'sclaussen/add-auth' from origin/main (prefix: sclaussen)
OK Pushed to remote with upstream tracking

Tip: Rename this session to match: /rename sclaussen/add-auth
```

```
OK Using existing issue #456: Fix login timeout
  https://github.com/owner/repo/issues/456
OK Created branch 'sclaussen/fix-login' from origin/main (prefix: sclaussen)
OK Pushed to remote with upstream tracking

Tip: Rename this session to match: /rename sclaussen/fix-login
```

