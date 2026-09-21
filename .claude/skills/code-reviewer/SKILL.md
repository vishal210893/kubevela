---
name: code-reviewer
description: >
  Multi-agent code review orchestrator. Spawns parallel review perspectives via AWS Bedrock
  (default, zero context cost) or local Claude agents (opt-in). Produces a prioritized,
  deduplicated REVIEW.md.
  Use when: reviewing a commit, reviewing a PR, code review, scrutinize changes,
  find issues, audit code, pre-merge review.
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - Write
  - Edit
  - Agent
user-invocable: true
---

# Multi-Agent Code Review

The review system is implemented in the `/review` command. All dispatch mechanics, engine selection, context gathering, synthesis instructions, and flag documentation live there.

**To run a review:** Use `/review` (see `.claude/commands/review.md`).

**Personas directory:** Review personas are stored in `personas/` within this skill directory. These are loaded at runtime by the dispatch scripts (`review-cli.py` and `review-bedrock.py`) from the SDD personas directory. The `consistency-checker.md` persona in this directory is used for Converse-engine-only consistency checking.
