---
description: Commit (if changes), pull (merge) from remote tracking branch, and push in one operation
model: sonnet
allowed-tools: Bash($WSROOT/.claude/scripts/git-sync:*)
argument-hint: [message]
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

## Your task

Execute the script to commit (if changes), pull (merge) from remote tracking branch, and push in one operation:

```bash
CC=1 $WSROOT/.claude/scripts/git-sync "<generated-message>" --body "<generated-body>"
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Confirm sync succeeded. Show commit hash and message if changes were committed, merge/pull status, and push confirmation. Keep it concise but complete.

**Examples:**
```
[OK] Created commit abc1234: feat: add auth
[OK] Merged from origin/feature-branch
[OK] Pushed to origin
```

```
[OK] Created commit abc1234
feat: add authentication

Files changed: 3
[OK] Merged from origin/main
[OK] Pushed to origin
```

```
[OK] Merged from origin/main
[OK] Pushed to origin
```

