---
description: Commit, push, and create PR in one command
model: sonnet
allowed-tools: [Bash($WSROOT/.claude/scripts/git-commit-push-pr:*), Bash(npm test:*), Bash(git add:*), Bash(git commit:*), Bash(git push:*), Bash(gh run view:*), Read, Edit, Glob, Grep]
argument-hint: [commit-message] [--pr-title title] [--admin-auto-merge] [--delete-branch] [--poll] [--fix] [--switch]
---

## Pre-execution: Generate Required Arguments

Before running the script, generate the following argument values:

### commit-message (generate if not provided by user)

Run these commands to gather context:
```bash
git status
```
```bash
git diff HEAD
```
```bash
git log --oneline -10
```

Use this prompt to generate the value:
> Analyze the changes and generate a commit subject line.
> 
> Format: conventional commit format (feat:/fix:/refactor:/docs:/test:), max 50 chars
> Guidelines:
> - Concise, imperative mood, no period
> - Summarize what changed

### commit-body (always generate)

Run these commands to gather context:
```bash
git status
```
```bash
git diff HEAD
```
```bash
git log --oneline -10
```

Use this prompt to generate the value:
> Analyze the changes and generate a commit body if the change warrants explanation.
> 
> Return empty string if change is self-explanatory from subject line.
> Otherwise, explain what and why (not how), wrap at 72 chars.
> 
> Guidelines:
> - Skip body for trivial changes (typo fixes, formatting, simple additions)
> - Include body for: new features, bug fixes with context, refactors, breaking changes
> - Focus on motivation and context, not implementation details

### pr-title (generate if not provided by user)

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

### pr-description (always generate)

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
- **[--poll]** (optional): Poll CI/CD checks until completion (no auto-merge)
- **[--fix]** (optional): Auto-fix CI failures (up to 30 attempts). Requires --poll or --admin-auto-merge.
- **[--switch]** (optional): After PR is created, switch to main branch and git pull

**IMPORTANT:** Optional flags ([--admin-auto-merge], [--delete-branch], [--poll], [--fix], [--switch]) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to commit, push, and create pr in one command:

```bash
CC=1 $WSROOT/.claude/scripts/git-commit-push-pr [[--admin-auto-merge]] [[--delete-branch]] [[--poll]] [[--fix]] [[--switch]] "<generated-commit-message>" --commit-body "<generated-commit-body>" --pr-title "<generated-pr-title>" --pr-description "<generated-pr-description>"
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Show all three operations completed: commit, push, and PR creation. Display commit hash, PR number, and title.
- ALWAYS show URLs section with Issue URL (if exists), PR URL, and Actions URL (always show Actions URL!)
- Note: --admin-auto-merge (-a) now implies --poll and --fix
- If -a flag used, show polling progress and merge result or error analysis
- If --fix was used and succeeded: show fix summary with attempt count
- If switched_to_main is true: show "Switched to 'main' and pulled latest changes"

IMPORTANT: If --fix is provided (or implied via -a), and CI fails, enter the autonomous fix loop:
1. Analyze failed checks from the output (logs, affected files, error type)
2. Read affected files and make code changes to fix issues
3. Run failing tests locally: npm test -- <pattern> (verify before pushing)
4. If local tests pass: git add -A && git commit -m "fix: address CI failure (attempt N)" && git push
5. Poll again using /pr:poll <pr-number>
6. Repeat until success or max attempts (30) reached
7. Report what was fixed in each attempt

**Examples:**
```
[OK] Committed abc1234: feat: add user authentication
[OK] Pushed to origin
[OK] Created PR #123: Add user authentication feature

URLs:
🎫 Issue: https://github.com/owner/repo/issues/199
📋 PR: https://github.com/owner/repo/pull/123
🔄 Actions: https://github.com/owner/repo/actions/runs/12345
```

```
[OK] Committed abc1234: feat: add user authentication
[OK] Pushed to origin
[OK] Created PR #123: Add user authentication feature

URLs:
🎫 Issue: https://github.com/owner/repo/issues/199
📋 PR: https://github.com/owner/repo/pull/123
🔄 Actions: https://github.com/owner/repo/actions/runs/12345

[OK] All checks passed (1m 45s)
[OK] Merged PR #123 with admin authority
```

```
[OK] Committed abc1234: feat: add user authentication
[OK] Pushed to origin
[OK] Created PR #123: Add user authentication feature

URLs:
📋 PR: https://github.com/owner/repo/pull/123
🔄 Actions: https://github.com/owner/repo/actions/runs/12345

[OK] All checks passed! (10m 30s)
[OK] Fixed after 3 attempts

Fixes applied:
  Attempt 1: Fixed linting errors in src/auth.ts
  Attempt 2: Fixed type error in src/utils.ts
  Attempt 3: Fixed failing test in tests/auth.test.ts

PR #123 is ready to merge
```

