---
description: Commit (if changes), pull (merge) from remote tracking branch, push, and optionally create PR, poll CI, fix, and merge
allowed-tools: [Bash($WSROOT/.claude/scripts/git-sync *), Bash(npm test *), Bash(git add *), Bash(git commit *), Bash(git push *), Bash(gh pr create *), Bash(gh pr view *), Bash(gh pr merge *), Bash(gh run view *), Read, Edit, Glob, Grep]
argument-hint: [message] --title [title] --pr|-p --poll|-o --fix|-f --merge|-m
---

## Pre-execution: Generate Required Arguments

Before running the script, generate the following argument values:

### message (generate if not provided by user)

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

### body (always generate)

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

### title (generate if not provided by user, only when --pr, --fix, or --merge is requested)

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

### description (always generate, only when --pr, --fix, or --merge is requested)

Run these commands to gather context:
```bash
git log origin/HEAD..HEAD --format='%H %s'
```
```bash
git diff origin/HEAD...HEAD --stat
```
```bash
git rev-parse --abbrev-ref HEAD
```

Use this prompt to generate the value:
> Analyze all commits in this branch and generate a PR description.
> 
> Format:
> ## Why
> <What problem or issue motivated this change. Check the branch name for issue numbers
> (e.g. issue-123, fix/GW-456, feature/gh-789). Reference it if found. Check commit
> messages for ticket references. If no motivation is clear, write "No motivation provided.">
> 
> ## Summary
> - Key changes (bullet points)
> 
> ## Testing
> - How to test these changes

**IMPORTANT:** Skip generating `title` and `description` entirely (no generation, no inclusion in the command) when none of --pr, --fix, or --merge was requested by the user.

## Arguments

- **--pr|-p** (optional): Create PR after sync
- **--poll|-o** (optional): Poll CI checks after push (main) or PR creation (branch)
- **--fix|-f** (optional): Auto-fix CI failures (implies --poll)
- **--merge|-m** (optional): Land the PR after CI passes -- enqueues in the merge queue when the base branch has one, else admin merge (branch only, implies --fix --poll --pr)

**IMPORTANT:** Optional flags (--pr|-p, --poll|-o, --fix|-f, --merge|-m) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to commit (if changes), pull (merge) from remote tracking branch, push, and optionally create pr, poll ci, fix, and merge:

```bash
CC=1 $WSROOT/.claude/scripts/git-sync --pr|-p --poll|-o --fix|-f --merge|-m "<generated-message>" --body "<generated-body>" --title "<generated-title>" --description "<generated-description>"
```

**Note:** Omit `--title "<generated-title>"` and `--description "<generated-description>"` from the command if none of --pr, --fix, or --merge was requested.


## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm sync success. Show commit (if any), merge, and push results.

If a PR was created, show PR number, title, and URLs (PR, issue if linked, actions).
Show URLs BEFORE any polling progress.

If polling results are present, show the outcome:
- Success: check count, duration, review status, mergeable status
- Failure: failed check names, error summaries, root cause
- If the PR was ENQUEUED (base branch has a merge queue): "[OK] PR #N added to
  the merge queue for '<base>' (it merges once the queue's checks pass)". The PR
  is NOT merged yet -- do not report it as merged and do not delete the branch.
- If admin merge succeeded (no merge queue on the base branch):
  "[OK] Merged PR #N with admin authority"
- If the merge/enqueue failed: show error and suggest: gh pr merge --squash --delete-branch N

CRITICAL -- AUTONOMOUS FIX LOOP (100% OF THE TIME)

If --fix is provided (or implied via --merge / -m) and CI fails, you MUST
enter the autonomous fix loop. DO NOT stop to ask the user for approval.
DO NOT present options. DO NOT wait for confirmation. DO NOT report "CI
failed, what should we do?" -- the user already authorized the fix loop
by passing --fix / --merge / -m. Asking again is a process failure.

Enter the loop immediately. 100% of the time.

This applies EVEN WHEN:
- The failure looks pre-existing on main (still fix it; your branch carries it)
- The failure looks unrelated to your diff (still fix it; CI is the gate)
- You already tried to reproduce locally and it passed (still fix it; CI is
  authoritative for the merge decision; a local-green CI-red gap IS the bug)
- The failure looks "flaky" or "environmental" (still fix it; if it's truly
  flaky, add determinism; if it's environmental, fix the environmental
  assumption in the test or the code)
- Fixing it needs a small adjacent change outside your original diff (still
  fix it; do the minimum change that makes CI green)
- You think admin-merge would be faster (it isn't your call to bypass CI;
  admin-merge is only appropriate when the user explicitly requests it in
  the current turn)

The ONLY reasons to exit the loop without fixing:
- The fix requires a destructive operation (drop table, rm -rf, force push) --
  surface the plan and ask first
- Max attempts (20) reached -- report what was tried and stop
- The failing check is a non-code gate (manual approval, external service
  outage) -- report and stop

Autonomous fix loop:
1. Analyze failed checks from the output (logs, affected files, error type)
2. Read affected files and make code changes to fix issues
3. Run failing tests locally: npm test -- <pattern> (verify before pushing)
4. If local tests pass (OR you can't reproduce locally but have a
   well-reasoned fix): re-run /git:sync with the same pipeline flags
   (--fix, or --merge if merge was requested). This commits the fix,
   pushes, and re-polls automatically.
5. Repeat until success or max attempts (20) reached
6. Report what was fixed in each attempt

**Examples:**
```
[OK] Committed abc1234: feat: add auth
[OK] Merged from origin/feature
[OK] Pushed to origin/feature
```

```
[OK] Committed abc1234: feat: add auth
[OK] Merged from origin/feature
[OK] Pushed to origin/feature
[OK] Created PR #123

URLs:
 PR: https://github.com/owner/repo/pull/123
 Actions: https://github.com/owner/repo/actions/runs/12345

[OK] All checks passed (1m 45s)
[OK] Merged PR #123 with admin authority
```

