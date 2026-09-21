# Review Reference

This file contains templates, detailed procedures, and output formats used by the `/review` command.
Claude reads this file on demand during review execution — it is NOT a command file.

---

## Priority Definitions

Both individual perspectives and the synthesizer use this scheme. Perspectives tag findings with P0–P3 during their review. The synthesizer normalizes and resolves disagreements during deduplication.

| Level | Label | Definition | Examples |
|-------|-------|------------|----------|
| **P0** | Critical — must fix before merge | The code is broken, dangerous, or will cause immediate harm | Unhandled exception on common path; SQL injection / XSS / credential in source; data corruption or silent data loss; breaking public API contract without migration |
| **P1** | Significant — should fix before merge | Will cause problems under known or likely conditions, or creates expensive-to-fix design debt | Bug producing wrong results under edge cases; race condition or resource leak; misleading names/comments that will cause future bugs; missing validation at system boundary; API design flaw costly to change post-merge |
| **P2** | Recommended — improves the PR | The code works but could be better — cleaner, smaller, more testable, or more focused | Dead code / unused functions or imports; scope creep (not needed for this PR's goal); over-engineering / premature abstraction; missing test coverage for new paths; inconsistency with codebase patterns |
| **P3** | Note — optional | Subjective preference or minor improvement opportunity | Naming or style preferences; alternative approaches that are roughly equivalent; documentation polish; minor refactoring |

**Key distinctions:**
- **P0 vs P1:** IS broken now vs WILL cause problems under known conditions
- **P1 vs P2:** Correctness or design debt vs "works but could be better"
- **P2 vs P3:** Objective improvement vs subjective preference

---

## Context Assembly Instructions

Context assembly varies by engine. **CLI engine** perspectives have full tool access (Read, Bash, Glob, Grep, WebFetch) and explore files dynamically, so they need a lighter seed context. **Converse engine** and **local** perspectives have no tool access and need the full pre-compiled context.

### Which steps to run by engine

| Step | CLI engine | Converse / local |
|------|-----------|-----------------|
| 1a. File list + diff | Yes | Yes |
| 1b. Read all changed files in full | **Skip** — agents read dynamically | Yes |
| 1c. Repository structure | **Skip** — agents browse with Glob and `ls` | Yes |
| 1d. Git metadata | Yes | Yes |
| 1e. Surrounding context | **Skip** — agents explore dynamically | Yes |
| 1f. Cross-reference analysis | **Skip** — agents use Grep to verify refs dynamically | Yes |
| 1g. Assemble context block | Yes (minimal: diff + file list + git metadata) | Yes (full) |

**Mixed engine reviews** (e.g., `--model opus-4.6,nova-pro`): Gather the FULL context (Converse path) since at least one model needs it. CLI-engine perspectives receive the same context but will also explore beyond it with tools.

### 1a. Get the file list and diff

For a commit:
```bash
git show --stat <commit>
git diff <commit>^..<commit>
```

For a branch:
```bash
git diff --name-only main...HEAD
git diff main...HEAD
```

### 1b. Read all changed files in full

**Skip this step for CLI engine** — perspectives read files dynamically via tools. For Converse and local engines: do not skip this step.

Perspectives need complete file contents, not just diffs. Read every changed file. If there are more than 20 files, prioritize:
1. New files (most likely to have issues)
2. Script/executable files (security-sensitive)
3. Configuration files (high-impact)

**Exclude binary files from context.** Do not read or include files like `.png`, `.jpg`, `.jar`, `.exe`, `.dll`, `.so`, `.woff`, `.pdf`, `.zip`, or any file that `git diff` marks as `Binary files ... differ`. Instead, note them in the context as:
```
### <filename> (binary — skipped, N bytes)
```

### 1c. Gather repository structure

```bash
# Top-level directory listing
ls -1 $WSROOT/

# For each directory containing a changed file, list its contents:
ls -1 <parent-dir>/
```

Format as a compact tree in the context block. Keep to 3 levels of depth. For large directories (>20 entries), show a count instead of listing every file (e.g., `scripts/ (49 files)`).

### 1d. Gather git metadata

```bash
# Current working tree state (shows deleted, untracked, modified files)
git status --short

# Files deleted in recent history (catches "file was deleted but docs still reference it")
git log --diff-filter=D --name-only --pretty=format: -20 | sort -u

# For branch reviews: file disposition showing Added/Modified/Deleted
git diff --name-status main...HEAD
```

### 1e. Read surrounding context

**Skip this step for CLI engine** — perspectives explore dynamically via tools.

- `CLAUDE.md` or `README.md` for project conventions
- Any related test files
- Files that import/depend on the changed code

### 1f. Cross-reference analysis

Run the cross-reference analyzer to detect broken references in changed files and documentation:

```bash
$WSROOT/.claude/scripts/review-xref.py --repo-root "$WSROOT" --files <changed-file-list> --include-docs
```

This script scans for slash-command references, backtick-quoted file paths, markdown links, Python imports, and YAML path references. It verifies each against the filesystem and produces a structured report of broken references.

**If the script is not available**, do the scan manually:
1. **Slash commands in docs:** Scan CLAUDE.md and README.md for `/command-name` references. For each, check if `.claude/commands/<command-name>.md` exists using Glob.
2. **File paths in changed files:** Scan changed files for backtick-quoted file paths (e.g., `` `.claude/scripts/foo.py` ``). For each, check if the path exists relative to the repo root.
3. **Manifest entries:** If `deploy-manifest.yaml` or similar registries are in scope or referenced, check that declared entries have corresponding directories/files.

Include all broken references in the context. If none are found, include: `No broken references detected.`

### 1g. Assemble the review context block

Format all gathered context into a single text block:

```
## Review Target: <REVIEW_TARGET>

## Changed Files:
<REVIEW_FILES list>

## Repository Structure:
<targeted directory tree — top-level + expanded directories containing changed files>

## Git Status:
<git status --short output>
### Recently Deleted Files (last 20 commits):
<git log --diff-filter=D --name-only --pretty=format: -20 | sort -u>

## Diff:
<REVIEW_DIFF>

## File Contents:
### <filename>
<full file contents>
...

## Cross-Reference Notes:
<broken references found during scan, or "No broken references detected.">

## Project Context:
<CLAUDE.md conventions, repo structure>
```

This assembled context is piped via stdin to `review-cli.py` (CLI engine), `review-bedrock.py` (Converse engine), or included in each agent prompt (local mode). For CLI engine, the context is minimal — only diff, file list, and git metadata (steps 1a, 1d). Steps 1b, 1c, 1e, and 1f are skipped because CLI perspectives have full tool access (Read, Bash, Glob, Grep, WebFetch) and explore dynamically. Omit the "Repository Structure", "File Contents", "Cross-Reference Notes", and "Project Context" sections from CLI engine context.

---

## Bedrock Tool Compatibility

Most Claude Code built-in tools work on Bedrock — but **do NOT use `--bare`**, which silently strips Glob, Grep, Write, Edit, and WebFetch. Use `--strict-mcp-config` instead to avoid loading MCP server tools (which bloat context) while keeping all built-in tools available. Verified on Opus 4.6 (`us.anthropic.claude-opus-4-6-v1`), April 2026.

| Tool | Bedrock (no `--bare`) | Bedrock (`--bare`) | Local (Agent tool) |
|------|:--------------------:|:-----------------:|:-----------------:|
| Read | ✅ | ✅ | ✅ |
| Bash | ✅ | ✅ | ✅ |
| Glob | ✅ | ❌ stripped | ✅ |
| Grep | ✅ | ❌ stripped | ✅ |
| Write | ✅ | ❌ stripped | ✅ |
| Edit | ✅ | ❌ stripped | ✅ |
| WebFetch | ✅ | ❌ stripped | ✅ |
| WebSearch | ❌ not on Bedrock | ❌ | ✅ |

### Why not `--bare`?

`--bare` is documented as "minimal mode" that skips hooks, plugins, CLAUDE.md, and keychain reads. On Bedrock, it also strips most built-in tools down to only Read and Bash. This was discovered empirically — the stripping is silent (no error, tools just don't appear). Use `--strict-mcp-config` instead: it prevents MCP server tools from loading (avoiding ~20K tokens of MCP tool schemas in context) while keeping all built-in tools available.

### Why no WebSearch on Bedrock?

WebSearch is a server-side tool (`server_tool_use`) executed by Anthropic's search infrastructure. Bedrock routes inference through AWS, not Anthropic's servers, so Anthropic's server-side tools are unavailable. This is documented by Anthropic: web search is supported on the Claude API, Microsoft Foundry, and Google Vertex AI, but not Amazon Bedrock. Source: [Anthropic web search tool docs](https://platform.claude.com/docs/en/docs/build-with-claude/tool-use/web-search-tool).

### Other notes

- **`--disallowedTools` enforces, `--allowedTools` does not:** With `--permission-mode bypassPermissions`, only `--disallowedTools` restricts Bash commands. The `--allowedTools` flag is not enforced.
- **Model version matters:** Opus 4.1 on Bedrock has a thinking-block format error on multi-turn tool use. Opus 4.6+ works correctly.
- **WebFetch for security references:** Since WebSearch is unavailable, security perspectives can use WebFetch to look up specific URLs (e.g., OWASP pages, CVE databases) when given a known URL.

---

## Agent Prompt Template (local mode)

For each selected perspective, launch an Agent tool call with `subagent_type: "general-purpose"`:

```
Review [TARGET] from a [PERSPECTIVE_NAME] perspective.

## Your Persona
[Embedded persona description for this perspective — derived from the perspective registry]

## Your Focus
[Focus description: what this perspective examines]

## Files changed:
[REVIEW_FILES list]

## Project context:
[Key conventions from CLAUDE.md]

## Instructions:
- Read all changed files listed above before analyzing
- For each finding: severity (P0/P1/P2/P3), file:line, description, fix
- Be thorough — flag everything, even minor concerns
- Note positive patterns too (not just problems)
```

**Custom agents (local mode):** Launch an Agent tool call with:
- `subagent_type: "<agent-name>"` (e.g., `subagent_type: "caveman"`) — Claude Code loads the full agent definition from `.claude/agents/<name>.md` automatically
- Prompt includes: diff + file list + project context + review output format instructions (persona is loaded by the framework, not embedded in prompt)

Agent tool calls (built-in and custom) are dispatched in **capped waves**, not all at once — launch at most `--max-parallel` agents (default 3) per message and wait for each wave to finish before starting the next. See the "Local dispatch (--local)" section of `/review` for the wave algorithm. This protects memory-constrained hosts from being overwhelmed.

---

## Consistency Checker (Converse engine only)

**Only dispatch when using the Converse engine** (non-Claude models or `--engine converse`). CLI engine perspectives already have tool access and verify their own references — no separate consistency checker needed.

In the **same parallel batch** as the Converse Bash calls, launch one additional local Agent for cross-reference and consistency validation. This agent runs concurrently with all other perspectives — no sequential bottleneck.

It costs ~20-40K session tokens (one agent) but catches structural issues that static-context models cannot detect.

Before building the prompt, read the persona file and extract the body (everything after the YAML frontmatter closing `---`):

```bash
cat $WSROOT/.claude/skills/code-reviewer/personas/consistency-checker.md
```

Then launch an Agent tool call with:
- `subagent_type: "general-purpose"`
- `description: "Cross-reference consistency check"`

**Prompt template:**
```
You are a consistency checker reviewing [REVIEW_TARGET].

## Your Persona
[Body of $WSROOT/.claude/skills/code-reviewer/personas/consistency-checker.md — everything after the YAML frontmatter]

## Changed Files
[REVIEW_FILES list]

## Instructions
- Focus ONLY on cross-reference/consistency issues — Bedrock agents cover code quality,
  security, and architecture.
- For each finding: priority (P0/P1/P2), file:line, what is referenced, what's wrong, fix.
- Use Read, Glob, Grep tools extensively. Do NOT speculate — verify every claim.
```

Include the consistency checker's output in synthesis alongside Bedrock/local perspective outputs. Label its findings as `Flagged by: consistency-checker (local)`.

---

## Synthesis Instructions

The synthesizer must:
- **Deduplicate** — many perspectives find the same issues. Group by unique issue, note consensus count.
- **Prioritize** — apply the **Priority Definitions** from the section above. Normalize each perspective's rankings to the shared P0–P3 scheme. If perspectives disagree on priority, use the definitions to resolve: P0 = IS broken now, P1 = WILL cause problems, P2 = works but could be better, P3 = subjective preference.
- **Resolve contradictions** between perspectives (e.g., "remove this code" vs "fix this code")
- **Note consensus** — issues flagged by more perspectives are more likely real
- **Label sources** — for each finding, list which perspectives flagged it (e.g., "security-reviewer [nova-pro], architect [nova-pro]")
- **Equal weight** — treat all model findings equally regardless of source model
- Treat consistency checker findings with equal weight. Label them as `Flagged by: consistency-checker (local)`.

**Synthesizer output format** — for each finding:
- **ID**: P0-1, P1-1, etc.
- **One-line summary**
- **Consensus**: N/M perspectives flagged this (where M is total perspectives in this review)
- **Flagged by**: list of perspective names (with model alias if multi-model)
- **File(s)**: specific paths and line numbers
- **What's wrong**: clear description
- **Why it matters**: impact
- **Fix**: concrete recommendation

---

## REVIEW.md Output Format

Write the synthesized report to a `REVIEW.md` file at the repository root.

```markdown
# Code Review: [REVIEW_TARGET]

**Date:** YYYY-MM-DD
**Reviewers:** N perspectives on [model(s)] [or N local Claude agents]
**Scope:** [commit/branch/files reviewed]

## Summary

[2-3 sentence overview: what was reviewed, key theme, blocking issues count]

---

## P0 -- MUST FIX ([count] issues)

### P0-1: [one-line summary]
**Consensus:** N/M perspectives
**Flagged by:** [perspective names]
**File:** `path/to/file` line(s) NN
[What's wrong, why it matters, recommended fix]

---

## P1 -- SHOULD FIX ([count] issues)
...

## P2 -- RECOMMENDED ([count] issues)
...

## P3 -- MINOR ([count] issues)
...

## Positive Observations
[What's done well — important for morale and to avoid all-negative reviews]
```

**Reviewers line variations:**

Bedrock (default):
```
**Reviewers:** N perspectives via <model(s)> + consistency-checker (local): security, architecture, ...
```

Local mode:
```
**Reviewers:** N perspectives (local Claude agents) + consistency-checker: security, architecture, ...
```

Multi-model:
```
**Reviewers:** N perspectives x M models (nova-pro, llama3-3) + consistency-checker (local): security, architecture, ...
```

---

## Special Handling

### Shell scripts
Always include security and ops perspectives. Check for:
- Unquoted variables, injection risks
- `set -e` interactions with arithmetic and pipelines
- Trap handlers and cleanup
- Portable syntax (bash vs POSIX)
- Executable permission bits

### Binary files
Flag any committed binaries (`.class`, `.jar`, `.exe`, `.dll`, `.so`). Check:
- Is there a source file that produces this binary?
- Is there a build step that makes the binary redundant?
- Can the binary be verified against its source?

### Skill files (this repo)
When reviewing skills in the skills directory, also check:
- Structure compliance (SKILL.md + docs/ + examples/)
- Frontmatter validity (name, description, allowed-tools)
- References to shared docs exist
- Examples are realistic and tested

### Configuration / YAML / JSON
Include api-designer for schema consistency and ops perspectives for deployment impact.
