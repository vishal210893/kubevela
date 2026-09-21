---
description: Poll PR status until checks complete
model: sonnet
allowed-tools: [Bash($WSROOT/.claude/scripts/pr-poll:*), Bash(npm test:*), Bash(git add:*), Bash(git commit:*), Bash(git push:*), Bash(gh run view:*), Read, Edit, Glob, Grep]
argument-hint: [pr-number] [--admin-auto-merge] [--delete-branch] [--fix]
---

## Pre-execution: Generate Required Arguments

Before running the script, generate the following argument values:

### pr-number (generate if not provided by user)

Run these commands to gather context:
```bash
git branch --show-current
```
```bash
gh pr list --head $(git branch --show-current) --json number -q '.[0].number'
```

Use this prompt to generate the value:
> Determine the PR number to poll.
> If there's a PR for the current branch, use that number.
> If no PR exists, report that no PR was found.

## Arguments

- **[--admin-auto-merge]** (optional): Merge with admin authority when checks pass (bypasses branch protection, implies --delete-branch)
- **[--delete-branch]** (optional): Delete branch after successful merge (implied by --admin-auto-merge)
- **[--fix]** (optional): Auto-fix CI failures (up to 20 attempts). When CI fails, analyze errors, apply fixes, verify locally, and push.

**IMPORTANT:** Optional flags ([--admin-auto-merge], [--delete-branch], [--fix]) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to poll pr status until checks complete:

```bash
CC=1 $WSROOT/.claude/scripts/pr-poll [[--admin-auto-merge]] [[--delete-branch]] [[--fix]] "<generated-pr-number>"
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Format the polling result based on the status:
- If all checks passed: show success, review status, mergeable status, and suggest /pr:merge
- If checks failed: show ERROR ANALYSIS with check name, error summary, root cause, and recommendation
- If admin merge succeeded: show "[OK] Merged PR #N with admin authority"
- If admin merge failed: show the error and suggest /pr:merge as fallback
- If --fix was used and succeeded: show fix summary with attempt count

IMPORTANT: If --fix is provided and CI fails, enter the autonomous fix loop:
1. Analyze failed checks from the output (logs, affected files, error type)
2. Read affected files and make code changes to fix issues
3. Run failing tests locally: npm test -- <pattern> (verify before pushing)
4. If local tests pass: git add -A && git commit -m "fix: address CI failure (attempt N)" && git push
5. Poll again by re-running this command
6. Repeat until success or max attempts (20) reached
7. Report what was fixed in each attempt

**Examples:**
```
[OK] All checks passed! (1m 30s)

PR #123 is ready to merge
Reviews: [OK] Approved (2)
Mergeable: [OK] Yes

Run `/pr:merge 123` to merge now
```

```
[OK] All checks passed! (1m 30s)
[OK] Merged PR #123 with admin authority
```

```
[--] CI/CD failed (2m 15s)

ERROR ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━━

Check: CI/CD
Error: Test failed

Root cause:
  Assertion error in test_user_count

Recommendation:
  Fix the failing test
```

```
[OK] All checks passed! (8m 45s)
[OK] Fixed after 2 attempts

Fixes applied:
  Attempt 1: Fixed linting errors in src/utils.ts
  Attempt 2: Fixed failing assertion in tests/utils.test.ts

PR #123 is ready to merge
```

