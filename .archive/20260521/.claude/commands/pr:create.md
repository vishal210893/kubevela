---
description: Create pull request
model: sonnet
allowed-tools: [Bash($WSROOT/.claude/scripts/pr-create:*), Bash(npm test:*), Bash(git add:*), Bash(git commit:*), Bash(git push:*), Bash(gh run view:*), Read, Edit, Glob, Grep]
argument-hint: [title] [--admin-auto-merge] [--delete-branch] [--poll] [--fix]
---

## Pre-execution: Generate Required Arguments

Before running the script, generate the following argument values:

### title (generate if not provided by user)

Run these commands to gather context:
```bash
git log origin/HEAD..HEAD --format='%H %s'
```
```bash
git diff origin/HEAD...HEAD --stat
```

Use this prompt to generate the value:
> Analyze all commits in this branch and generate a PR title.
> One line summarizing the changes (max 72 chars).

### description (always generate)

Run these commands to gather context:
```bash
git log origin/HEAD..HEAD --format='%H %s'
```
```bash
git diff origin/HEAD...HEAD --stat
```

Use this prompt to generate the value:
> Analyze all commits in this branch and generate a PR description.
> 
> Format:
> ## Summary
> - Key changes (bullet points)
> 
> ## Testing
> - How to test these changes

## Arguments

- **[--admin-auto-merge]** (optional): Poll CI/CD, auto-fix failures, merge with admin on success (implies --poll --fix --delete-branch)
- **[--delete-branch]** (optional): Delete branch after successful merge (implied by --admin-auto-merge)
- **[--poll]** (optional): Poll CI/CD (every 30s, 30min timeout) without auto-merge
- **[--fix]** (optional): Auto-fix CI failures (up to 20 attempts). Requires --poll or --admin-auto-merge.

**IMPORTANT:** Optional flags ([--admin-auto-merge], [--delete-branch], [--poll], [--fix]) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to create pull request:

```bash
CC=1 $WSROOT/.claude/scripts/pr-create [[--admin-auto-merge]] [[--delete-branch]] [[--poll]] [[--fix]] "<generated-title>" --description "<generated-description>"
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm PR creation. Show PR number and title. Then ALWAYS show URLs section:
- Issue URL (if linked via branch name)
- PR URL (always)
- Actions URL (always)

If --poll or --admin-auto-merge used, show URLs BEFORE polling progress.
Note: --admin-auto-merge implies --poll --fix
- If --fix was used and succeeded: show fix summary with attempt count

IMPORTANT: If --fix is provided with --poll or --admin-auto-merge, and CI fails, enter the autonomous fix loop:
1. Analyze failed checks from the output (logs, affected files, error type)
2. Read affected files and make code changes to fix issues
3. Run failing tests locally: npm test -- <pattern> (verify before pushing)
4. If local tests pass: git add -A && git commit -m "fix: address CI failure (attempt N)" && git push
5. Poll again using /pr:poll <pr-number>
6. Repeat until success or max attempts (20) reached
7. Report what was fixed in each attempt

**Examples:**
```
[OK] Created PR #123: Add authentication

URLs:
📋 PR: https://github.com/owner/repo/pull/123
```

```
[OK] Created PR #123: Add authentication

URLs:
🎫 Issue: https://github.com/owner/repo/issues/199
📋 PR: https://github.com/owner/repo/pull/123
🔄 Actions: https://github.com/owner/repo/actions/runs/12345

[OK] All checks passed (1m 45s)
[OK] Merged PR #123 with admin authority
```

```
[OK] Created PR #123: Add authentication

URLs:
📋 PR: https://github.com/owner/repo/pull/123
🔄 Actions: https://github.com/owner/repo/actions/runs/12345

[OK] All checks passed! (8m 45s)
[OK] Fixed after 2 attempts

Fixes applied:
  Attempt 1: Fixed linting errors in src/auth.ts
  Attempt 2: Fixed failing test in tests/auth.test.ts

PR #123 is ready to merge
```

