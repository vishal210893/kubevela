# Review Before Commit

**When to use this rule**: When the user asks you to commit changes, stage and commit, or run `/git:commit`.

## Rule

Before creating a git commit, suggest running `/review` first if a review has not already been run in this session. Do not block the commit -- suggest the review and let the user decide.

## How to suggest

Check the scope of staged/unstaged changes and recommend the appropriate depth:

| Change scope | Suggested flag | Why |
|-------------|----------------|-----|
| 1-3 files, bug fix or typo | `/review --quick` | 4 perspectives, fast pass |
| 4-10 files, standard feature work | `/review --standard` | 7 perspectives |
| New skill, large feature, 10+ files, security-sensitive | `/review --deep` | 12 perspectives, maximum coverage |
| Targeted review needed | `/review --pick` or `--agents` | Choose specific perspectives |

## Example suggestion

> Before committing, I'd recommend running a review to catch issues early:
>
> ```
> /review --quick
> ```
>
> This is a small change so a quick pass (4 agents) should be sufficient. Want me to run it, or go ahead with the commit?

## When NOT to suggest

- The user already ran `/review` in this session and no new changes were made since
- The commit is only updating REVIEW.md itself
- The user has explicitly said to skip the review (e.g., "just commit it", "commit without review")
- The changes are non-code files only (e.g., only top-level README.md or CONTRIBUTING.md) -- NOTE: SKILL.md, test-cases.yaml, CLAUDE.md, and any file under a skills/ or capabilities/ directory are NOT exempt; always suggest review when these files change
