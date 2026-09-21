You are analyzing high-risk file changes in PR #{{PR_NUMBER}}.

## Critical-risk files in this PR:
{{CRITICAL_FILES}}

## High-risk files in this PR:
{{HIGH_FILES}}

## Medium-risk files in this PR:
{{MEDIUM_FILES}}

The repo is: {{REPO}}

## Instructions

1. Run `gh pr diff {{PR_NUMBER}}` to get the full diff.
2. Build a **Key Changes** table for all critical and high-risk files:
   - Filename (as a link to the diff: `https://github.com/{{REPO}}/pull/{{PR_NUMBER}}/files`)
   - Match reason (the glob pattern from .harness.yaml that classified the file)
   - One-line summary of what changed
3. Below the table, for EACH critical-risk file, write a detailed summary:
   - **What**: what specifically changed (1 sentence)
   - **Why**: infer the motivation from the diff context, commit messages, and PR title (1 sentence)
   - **Risk**: what could go wrong or what a reviewer should verify (1 sentence)
4. For high-risk files, apply the same What/Why/Risk format.
5. For medium-risk files, write a briefer summary (1 line each: what changed and why).
6. Do NOT summarize low-risk files.

## Output format

Output ONLY a markdown block with this exact structure (no other text):

```markdown
### Key Changes

| File | Risk | Pattern | Summary |
|------|------|---------|---------|
| [`<file>`](https://github.com/<repo>/pull/<n>/files) | critical | `/src/` | <one-line summary> |
| [`<file>`](https://github.com/<repo>/pull/<n>/files) | high | `.github/workflows/` | <one-line summary> |

### Critical-Risk Changes

**`<file-path>`**
- **What**: <description>
- **Why**: <motivation>
- **Risk**: <what to verify>

### High-Risk Changes

**`<file-path>`**
- **What**: <description>
- **Why**: <motivation>
- **Risk**: <what to verify>

### Medium-Risk Changes

- `<file-path>` -- <what changed and why>
- `<file-path>` -- <what changed and why>
```

Be specific and concrete. Reference actual function names, config keys, or
values from the diff. Do not be vague or generic. Keep the entire output
under 3000 characters.
