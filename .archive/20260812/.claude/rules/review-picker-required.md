# Perspective Picker Is Required

**When to use this rule**: Every time `/review` is invoked or the user asks for a code review.

## Rule

You MUST NOT choose review perspectives on behalf of the user. If the user did not explicitly specify which perspectives to use, you MUST show the interactive picker and wait for their selection before proceeding.

## What counts as "explicitly specified"

ONLY these count — the user must have literally said or typed one of:
- A pack name: "quick", "standard", "deep" (or the flag `--quick`, `--standard`, `--deep`)
- Specific perspective names: "security-reviewer and critic", `--agents security-reviewer,critic`
- Focus areas: "just security", `--focus security` (aliases resolve to canonical keys)
- "let me pick" / `--pick`

## What does NOT count

These do NOT count as perspective selection — you must still show the picker:
- "review this" / "review the readme" / "review my changes" — NO pack specified
- "can you do a review?" — NO pack specified
- "review using my scott profile" — specifies profile, NOT perspectives
- Mentioning a scope (file, commit, branch) — scope is NOT perspective selection
- Your own judgment about what's appropriate for the scope size — NEVER infer a pack

## Why

Users don't want 4-12 review perspectives chosen for them without consent. The perspectives consume AWS resources and produce findings the user didn't ask for. Let the user decide.

## Examples

**WRONG:**
```
User: "review the readme"
Claude: "I'll run a quick review (4 perspectives)..."  <-- WRONG, user didn't say "quick"
```

**WRONG:**
```
User: "review my changes using my scott profile"
Claude: "Launching standard review (7 perspectives)..."  <-- WRONG, user didn't say "standard"
```

**CORRECT:**
```
User: "review the readme"
Claude: "Which perspectives would you like to run?
  1. Security Reviewer — ...
  2. Architect — ...
  ...
  Shortcuts: q (quick/4), s (standard/7), d (deep/12)
  Enter numbers, names, or a shortcut:"
```

**CORRECT (user specified a pack):**
```
User: "quick review of the readme"
Claude: "Running quick pack (4 perspectives: security, code-quality, devils-advocate, critic)..."
```
