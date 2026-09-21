---
description: Classify changes by risk tier using the same algorithm as CI
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/code-risk *)
argument-hint: [pr-number] [--action] [--all] [--action] [--action]
---

## Arguments

- **[pr-number] [--action] [--all]** (optional): PR number to classify (omit for local branch changes). Use --action to trigger CI workflow. Use --action --all to reclassify all open non-draft PRs.
- **[--action]** (optional): Trigger the CI risk classifier workflow instead of running locally
- **[--action]** (optional): Trigger the CI risk classifier workflow instead of running locally

**IMPORTANT:** Optional flags ([--action], [--action]) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to classify changes by risk tier using the same algorithm as ci:

```bash
CC=1 $WSROOT/.claude/scripts/code-risk [pr-number] [--action] [--all] [--action] [--action]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Parse the JSON output and present the risk classification:
- Tier (LOW/MEDIUM/HIGH/CRITICAL) with score
- Total lines changed and file count
- Files grouped by risk tier (low/medium/high/critical)
- Any unmatched files: these are checked-in files with no matching pattern in
  .harness.yaml. Everything in the repo is relevant -- .gitignore is what removes
  noise. Unmatched files default to high risk. Use /code:setup to add glob
  patterns to .harness.yaml so they are classified at the correct tier.
- Custom script results if any ran (abstain = script found no reason to
  change the tier; a tier value = script overrides to that tier)

**Examples:**
```
Risk: HIGH (score: 63) (local changes)
Reason: score 63: base=63 (high
```

```
size=+0
```

```
scripts=+0
Lines: 150
```

```
Files: 5

  high:
    .github/workflows/pr.yaml
  low:
    docs/guide.md

Scripts: (none configured)"
```

