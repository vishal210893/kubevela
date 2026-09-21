---
allowed-tools: Bash, Read
description: Combined risk + review pre-PR gate. Default when user asks to check/review changes, evaluate PR readiness, or assess risk. Use code:risk for classification only, code:review for review only, code:setup to configure .harness.yaml.
model: opus
context: fork
argument-hint: [pr-number] [--fix] [--action] [-r l|m|h|c]
---
Run a full pre-PR gate: risk classification followed by code review.

Parse $ARGUMENTS for:
- An optional PR number (digits only)
- `--fix` flag (passed through to code:review)
- `--action` flag (trigger CI workflows instead of running locally)
- `--risk` or `-r` followed by `l|m|h|c` (developer self-assessment)

`--action` and `--fix` are mutually exclusive. Error if both provided.

## Action mode

If `--action` is present:
1. PR number is required. Error if not provided.
2. Re-trigger the advanced code review for the PR. The review (risk tiering +
   Claude review + reviewer brief) runs in `gwre-pdo/ai-harness`, started by an
   `advanced-code-review` repository dispatch. That dispatch is fired
   server-side by `caller-advanced-code-review.yaml` (which holds the
   `secrets.GH_TOKEN` PAT and the `L3`/`RUNNER_LABEL` repo vars), so re-run it
   through that workflow's `workflow_dispatch` entry:
   ```bash
   gh workflow run caller-advanced-code-review.yaml --ref main -f pr_number=<N>
   ```
3. Print: "Re-triggered advanced code review for PR #N -- results will appear on the PR (posted by ai-harness)."
4. Do not run local risk or review. Return immediately.

## Step 1: Risk classification

Run `/code:risk`, passing the PR number if provided.

Present the risk tier and score.

## Step 2: Code review

Run `/code:review`, passing the PR number and `--fix` flag if provided.

Present the review findings.

## Step 3: Developer risk label

If `--risk` or `-r` was provided:
- Map the value: `l`=low, `m`=medium, `h`=high, `c`=critical
- If a PR number was provided, apply the label:
  ```bash
  gh pr edit <pr-number> --add-label "dev-risk:<tier>"
  ```
- If local-only mode (no PR number), note the assessment in output but skip labeling.

## Step 4: Synthesize

Combine both results into a single summary:

```
## Pre-PR Check: <branch or PR #N>

### Risk
- Score: <N> (<TIER>)
- Developer assessment: <tier> (or "none")
- Reason: <reason>
- Lines: <N>, Files: <N>

### Review
- High: N, Medium: N, Low: N
- <top high/medium findings>

### Verdict
PASS -- risk is <tier>, no high-severity issues
  or
FAIL -- <reason(s)>
```

**PASS** when: risk tier is low or medium AND no [high] or [critical] review issues.

**FAIL** when: risk is high or critical, OR any [high]/[critical] review issue found.
