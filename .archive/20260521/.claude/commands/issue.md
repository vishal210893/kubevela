---
description: Create or use issue, create branch, and drive implementation pipeline
model: sonnet
allowed-tools: [Bash($WSROOT/.claude/scripts/issue:*), Bash($WSROOT/.claude/scripts/git-commit-push-pr:*), Bash($WSROOT/.claude/scripts/pr-poll:*), Bash(gh issue:*), Bash(git:*), Bash(npm test:*), Bash(gh run view:*), Read, Edit, Glob, Grep]
argument-hint: [title] [--number N] [--spec [project:]name] [--body text] [--impl] [--pr] [--admin-auto-merge] [--delete-branch] [--poll] [--fix]
---

## Pre-execution: Generate Required Arguments

Before running the script, generate the following argument values:

### qualifier (always generate)

Use this prompt to generate the value:
> Based on the issue title, generate a short dash-cased qualifier for the branch name.
> Examples: 'add-auth', 'fix-login', 'update-deps'
> Keep it short (2-4 words max), lowercase, dashes between words.

## Arguments

- **title** (optional): Issue title (for creating new issues). Mutually exclusive with --number.
- **--number N** (optional): Existing issue number. Mutually exclusive with title.
- **--spec [project:]name** (optional): Spec name to create or associate with the branch.
- **--body text** (optional): Issue body (for new issues only)
- **--impl** (optional): Begin implementation immediately after setup
- **--pr** (optional): After implementation, commit and create a PR (requires --impl)
- **[--admin-auto-merge]** (optional): Poll CI/CD, auto-fix failures, merge with admin on success (implies --pr --poll --fix --delete-branch)
- **[--delete-branch]** (optional): Delete branch after successful merge (implied by --admin-auto-merge)
- **[--poll]** (optional): Poll CI/CD checks after PR creation (implies --pr, no auto-merge)
- **[--fix]** (optional): Auto-fix CI failures (up to 30 attempts, implies --poll). Requires --poll or --admin-auto-merge.

**IMPORTANT:** Optional flags (--impl, --pr, [--admin-auto-merge], [--delete-branch], [--poll], [--fix]) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to create or use issue, create branch, and drive implementation pipeline:

```bash
CC=1 $WSROOT/.claude/scripts/issue [title] [--number N] [--spec [project:]name] [--body text] [--impl] [--pr] [[--admin-auto-merge]] [[--delete-branch]] [[--poll]] [[--fix]] --qualifier "<generated-qualifier>"
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm issue creation/fetch (show number and URL), branch creation (show full name), and spec status if applicable. Remind user to rename session: /rename <branch-name>

Pipeline stages (execute in order based on output flags):
- If impl_started is true: Implement the feature using issue_context. After completing implementation: (1) Verify spec exists and is associated with branch, (2) Update relevant docs if needed, (3) Generate/update tests, (4) Update docs/release-notes.md, (5) Build: node dev.js capability build && node dev.js profile build
- If pr_requested is true: After implementation is complete, run CC=1 $WSROOT/.claude/scripts/git-commit-push-pr "<commit-message>" --pr-title "<pr-title>" --pr-description "<pr-description>" [include --admin-auto-merge if admin_auto_merge_requested is true] [include --delete-branch if delete_branch_requested is true] [include --poll if poll_requested is true] [include --fix if fix_requested is true]. Auto-generate the commit message, PR title, and PR description from the implementation changes. This single script handles commit, push, PR creation, polling, and auto-fixing.
Note: --admin-auto-merge (-a) implies --poll and --fix. If --fix is provided (or implied via -a), and CI fails, enter the autonomous fix loop: analyze failures, fix code, run local tests, commit and push, re-poll.

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

