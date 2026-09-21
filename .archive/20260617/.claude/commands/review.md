---
description: Multi-agent code review — Claude on Bedrock with tool access, zero session context cost (spawns parallel review perspectives)
model: opus
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep, Agent]
argument-hint: "[<commit-hash>|HEAD|--branch|--staged|--files <paths>] [--quick|--standard|--deep] [--agents <names>] [--pick] [--focus <areas>] [--model <alias>] [--engine cli|converse] [--local] [--keep-reviews] [--list-agents] [--effort low|medium|high|max] [--profile <name>] [--region <region>]"
---

## Perspective Registry

**This is the single source of truth for all perspective data.** When displaying perspectives (picker, --list-agents, or any user-facing list), you MUST read from this table. Do NOT generate names from memory or training data. Do NOT paraphrase. Copy EXACTLY.

| # | Key | Focus alias | Description | Packs |
|---|-----|-------------|-------------|-------|
| 1 | security-reviewer | security | Security vulnerabilities, OWASP, threat modeling | quick, standard, deep |
| 2 | architect | architecture | Component boundaries, coupling, scalability | standard, deep |
| 3 | chief-architect | system-design | System decomposition, integration patterns, evolution | deep |
| 4 | ops-reviewer | ops | Deployability, error handling, rollback, portability | standard, deep |
| 5 | chief-programmer | code-quality | Bugs, edge cases, naming, patterns, correctness | quick, standard, deep |
| 6 | devils-advocate | — | Hidden assumptions, failure modes, what's missing | quick, standard, deep |
| 7 | testability-reviewer | testing | Missing tests, untestable designs, boundary conditions | standard, deep |
| 8 | simplifier | — | Over-engineering, YAGNI, unnecessary complexity | deep |
| 9 | user-advocate | — | Usability, learnability, developer experience | deep |
| 10 | api-designer | — | Interface consistency, naming, error contracts | deep |
| 11 | critic | — | Risks, second-order consequences, sweep | quick, deep |
| 12 | requirements-analyst | requirements | Missing requirements, implicit assumptions, completeness | standard, deep |
| 13 | strategist | strategy | Technology bets, build-vs-buy, tech debt | (on-demand) |
| 14 | delivery-manager | delivery | Work sequencing, dependencies, critical path | (on-demand) |
| 15 | analyst | analysis | Evidence-based trade-offs, data gaps | (on-demand) |

Keys match persona filenames exactly. Focus aliases are shorter alternatives for `--focus`. Both are accepted by `--agents` and `--focus`.

**Pack membership:**
- `--quick` (4): security-reviewer, chief-programmer, devils-advocate, critic — fast sweep, broad coverage
- `--standard` (7): security-reviewer, architect, ops-reviewer, chief-programmer, devils-advocate, testability-reviewer, requirements-analyst — specialist depth (critic is in quick but not standard by design; standard trades sweep for focused analysis)
- `--deep` (12): security-reviewer, architect, chief-architect, ops-reviewer, chief-programmer, devils-advocate, testability-reviewer, simplifier, user-advocate, api-designer, critic, requirements-analyst

`strategist` (#13), `delivery-manager` (#14), and `analyst` (#15) are not in any pack — select them via `--agents`, `--pick`, or `--focus`. All 15 perspectives are available via these flags regardless of pack membership.

---

## Context Budget Warning (--local only)

**Only show this warning when the user specifies `--local`.** The default CLI engine and Converse engine both run out-of-process on Bedrock — zero session context cost.

> **Heads up:** Local Claude agent reviews consume significant session context. `--quick` (4 agents) is moderate, `--standard` (7 agents) is substantial, and `--deep` (12 agents) will use most of your remaining context window. Consider using the default Bedrock mode instead (drop `--local`) for zero context cost.

## Early exit: --list-agents

If `--list-agents` is present, display the Perspective Registry table above in this format and exit immediately. Do NOT run a review, do NOT show the context warning.

```
Available review perspectives (15):

  Pack perspectives (included in --quick / --standard / --deep):
    #   Perspective            Focus key          Packs               Description
    [rows 1-12 from the Perspective Registry table above]

  On-demand perspectives (select via --agents, --pick, or --focus):
    [rows 13-15 from the Perspective Registry table above]

Packs: --quick (4), --standard (7), --deep (12)
Select any perspective: --agents security,critic  |  --pick  |  --focus security,ops
Default model: inherits session model (override with --model <alias> or REVIEW_MODEL env var)
```

Then stop. Do not proceed with any review.

---

## STEP 1: Perspective Selection (DO THIS FIRST)

**THIS IS THE FIRST THING YOU DO.** Before scope detection, before reading files, before anything else — determine which perspectives the user wants. If they haven't told you, ASK THEM.

**Decision tree:**

1. **User specified `--quick`, `--standard`, or `--deep`?** -> Use that pack. Skip to Step 2.
2. **User specified `--agents <names>` or `--focus <areas>`?** -> Use those. Skip to Step 2.
3. **Otherwise -> STOP and show the picker. Wait for the user to select.**

**You MUST NOT proceed past this step without a confirmed set of perspectives.** Do not infer a pack from the user's prompt. Do not default to any pack. Do not start scope detection, file reading, or Bedrock calls until the user has selected perspectives.

### Natural language interpretation

Users often describe what they want in plain English instead of flags. Map their intent:

| User says | Flags |
|-----------|-------|
| "review this" / "review my changes" | (auto-detect scope, show picker — CLI on Bedrock default) |
| "quick review" / "fast review" / "just a quick pass" | `--quick` |
| "standard review" / "normal review" | `--standard` |
| "thorough review" / "deep review" / "full review" | `--deep` |
| "review with nova" / "use nova" | `--model nova-pro` (Converse engine + quality warning) |
| "just use nova and llama" / "both models" | `--model nova-pro,llama3-3` (Converse engine + warning) |
| "use opus" / "review with opus" | `--model opus-4.6` (CLI engine) |
| "use static context" / "no tools" | `--engine converse` (legacy path) |
| "review locally" / "use local agents" / "run in session" | `--local` (show picker — no pack specified) |
| "quick local review" | `--local --quick` |
| "just check security" / "only security" | `--focus security` |
| "I want security and ops perspectives" | `--focus security,ops` |
| "review with the simplifier and critic" | `--agents simplifier,critic` |
| "run 3 agents - devils advocate, chief architect, and simplifier" | `--agents devils-advocate,system-design,simplifier` |
| "let me pick the agents" / "I want to choose" | `--pick` |
| "use 5 agents" / "run 5 perspectives" | `--pick` (show picker, user selects 5) |
| "run 2 agents focusing on security and architecture" | `--agents security,architecture` |
| "what agents are available?" / "list agents" / "show perspectives" | `--list-agents` |
| "review using my caveman agent along with security and critic" | `--agents caveman,security,critic` (custom + built-in) |
| "use my compliance-auditor for this review" | `--agents compliance-auditor` (custom agent) |
| "keep the individual reviews" / "save the raw reviews" / "don't delete the reviews" | `--keep-reviews` |
| "use max effort" / "maximum reasoning" / "think harder" / "ultrathink" | `--effort max` |

**IMPORTANT: Unless the user explicitly names a pack (quick/standard/deep), specific perspectives, or focus areas, you MUST show the interactive picker before dispatching any review.** Do not silently default to a pack — the user chooses which perspectives to run.

### --agents: Select perspectives (and custom agents) by name

When `--agents <name1>,<name2>,...` is present:

1. Parse the comma-separated list, trimming whitespace around each name.
2. Match each name against the Perspective Registry using flexible matching (case-insensitive, partial names, abbreviations — e.g., "sec" -> security, "arch" -> ask to clarify architect vs chief-architect).
3. **Custom agents:** Names that don't match any built-in perspective are checked as custom agents:
   - Check `$WSROOT/.claude/agents/<name>.md` (project-level, checked first)
   - Check `~/.claude/agents/<name>.md` (user-global)
   - If found, read the file. Parse YAML frontmatter (`name`, `description`) and body (persona text).
   - If not found, display an error:
     > Agent `<name>` not found. Checked:
     > - `$WSROOT/.claude/agents/<name>.md`
     > - `~/.claude/agents/<name>.md`
     >
     > Create the agent file or use a built-in perspective.
     Then abort.
4. If any name is **ambiguous** among built-in perspectives, ask the user to clarify.
5. If any name matches **neither** a built-in perspective nor a custom agent file, display an error:
   > Error: Unrecognized name(s): `<invalid-names>`
   >
   > Built-in perspectives: security-reviewer, architect, chief-architect, ops-reviewer, chief-programmer, devils-advocate, testability-reviewer, simplifier, user-advocate, api-designer, critic, requirements-analyst, strategist, delivery-manager, analyst
   Then abort the review.
6. Deduplicate resolved perspectives and inform the user if duplicates were removed.
7. If a pack flag is also present, warn that it is ignored and proceed with `--agents` only.

**Custom agents** run alongside built-in perspectives in the same review. On Bedrock (default), the agent file's body is passed as `--persona`. On local (`--local`), the agent is spawned with its own `subagent_type` so Claude Code loads the full definition automatically.

### --focus: Select perspectives by focus area

When `--focus <area1>,<area2>,...` is present:

1. Parse the comma-separated focus keys, trimming whitespace.
2. Match each key against the Key column of the Perspective Registry using flexible matching (case-insensitive, partial matches, abbreviations).
3. If any key is **ambiguous**, ask the user to clarify.
4. If any key **cannot be resolved**, display an error:
   > Error: Unrecognized focus area(s): `<invalid-keys>`
   >
   > Valid keys: security-reviewer, architect, chief-architect, ops-reviewer, chief-programmer, devils-advocate, testability-reviewer, simplifier, user-advocate, api-designer, critic, requirements-analyst, strategist, delivery-manager, analyst
   > Focus aliases: security, architecture, system-design, ops, code-quality, testing, requirements, strategy, delivery, analysis
   Then abort the review.
5. Map each resolved focus key to its corresponding perspective via the registry.
6. Spawn only the mapped perspectives. Pack flags are ignored with a warning.

### --pick: Interactive perspective picker

When `--pick` is present (or when no selection flags are provided — the default):

1. Display the Perspective Registry table above as a numbered list in this format:
   ```
   Available review perspectives:
   -- Pack perspectives (included in --quick / --standard / --deep) --
     1. Security Reviewer      [security]        — Security vulnerabilities, OWASP, threat modeling
     ...
     12. Requirements Analyst   [requirements]     — Missing requirements, implicit assumptions, completeness
   -- On-demand perspectives --
     13. Strategist             [strategy]         — Technology bets, platform evolution, build-vs-buy
     14. Delivery Manager       [delivery]         — Work sequencing, dependencies, critical path, scope
     15. Analyst                [analysis]         — Evidence-based trade-offs, data gaps, quantitative grounding

   Shortcuts: q (quick/4), s (standard/7), d (deep/12)

   Enter perspective numbers (e.g., 1,3,5), names, or a shortcut:
   ```
   **You MUST include ALL 15 entries from the Perspective Registry. If you display fewer than 15, re-read the table.**
2. If this picker was triggered by NLP with pre-suggested perspectives, append a suggestion line:
   ```
   Suggested based on your request: 1 (Security Reviewer), 2 (Architect)
   Press enter to confirm, or enter different numbers/names:
   ```
   If the user presses enter with no input, use the suggested perspectives.
3. Parse the user's response — accept comma-separated numbers, names, focus keys, or a mix. Accept shortcuts as single letters (`q`, `s`, `d`) or full words (`quick`, `standard`, `deep`).
4. Validate all entries against the registry (flexible matching applies).
5. If any entry is **invalid** (out of range number, unresolvable name): re-display the list with an error note and ask again.
6. If the user enters an **empty response** (no suggestions active): re-display the list and ask again.
7. Deduplicate and inform the user if duplicates were removed.

### Mutual exclusivity and flag precedence

| Combination | Behavior |
|-------------|----------|
| `--agents` + `--pick` | Error: "--agents and --pick are mutually exclusive." |
| `--agents` + `--focus` | Warn: `--focus` ignored — `--agents` overrides. |
| `--pick` + `--focus` | Warn: `--focus` ignored — the picker lets you choose directly. |

**Flag precedence:**

| Flags present | Perspectives selected |
|---------------|----------------------|
| (none) | Interactive picker |
| `--quick` | Quick 4 (pack) |
| `--standard` | Standard 7 (pack) |
| `--deep` | Deep 12 (pack) |
| `--agents a,b,c` | Exactly a, b, c |
| `--pick` | User-selected |
| `--focus x,y` | Mapped from x, y |

**Input handling:**
- Match perspective names and focus keys **flexibly**: case-insensitive, whitespace-trimmed, partial names and abbreviations accepted (e.g., "sec" -> security, "arch" -> ask to clarify architect vs chief-architect, "sys" -> system-design).
- When a name is **ambiguous**, ask the user to clarify rather than guess or reject.
- **Deduplicate** duplicate selections and inform the user which duplicates were removed.

## STEP 2: Model & Engine Resolution

**After the user has confirmed their perspective selection** (from Step 1), determine which model and dispatch engine to use. Skip this if `--local` is specified.

### Model Resolution

**Resolution order (first match wins):**
1. `--model <alias>` flag — use that model
2. `REVIEW_MODEL` environment variable
3. **Inherit from the current session model:**
   - If you are running as **opus** -> use `opus-4.6`
   - If you are running as **sonnet** -> use `sonnet-4.6`
   - If you are running as **haiku** -> use `haiku-4.5` — warn: "Note: Haiku produces lower-quality reviews than sonnet or opus."

**Multiple models:** `--model a,b` -> each model runs ALL selected perspectives (cross-model diversity).

### Engine Resolution

After resolving the model, determine the dispatch engine:

1. `--engine converse` flag -> force Converse API engine (all models, no tool access)
2. `--local` flag -> local Agent tool dispatch
3. **No `--engine` flag (default) -> auto-detect by model family:**
   - **Claude models** (sonnet-\*, opus-\*, haiku-\*) -> **CLI engine** (`review-cli.py` — claude -p on Bedrock with tool access)
   - **Non-Claude models** (nova-\*, llama\*, pixtral-\*, gpt-oss-\*) -> **Converse engine** (`review-bedrock.py` — static context). Show warning:

> **Note:** Using **{model}** via Bedrock Converse API (static context, no tool access). For maximum quality, omit `--model` to use Claude with full tool access.

Tell the user which model and engine were resolved before proceeding:
> Engine: **cli** — running **opus-4.6** on Bedrock with tool access (inherited from session). Override with `--model <alias>`.

### Effort Resolution

**Resolution order (first match wins):**
1. `--effort <level>` flag or NLP equivalent ("ultrathink", "max effort", etc.) — use that level
2. **Inherit from the current session's effort level** — if you are running at a specific effort level (check for a system reminder like "reasoning effort level: high"), pass that same level to each subprocess
3. If no effort level is set anywhere, omit `--effort` entirely (subprocesses use their default)

## STEP 3: Determine Review Scope

Parse the user's arguments to determine what to review.

If no argument provided, auto-detect:
```bash
git status --short
```
```bash
git rev-list --count main..HEAD
```
```bash
git log --oneline -3
```

Then determine scope:
- If there are staged changes: review staged changes
- If `git rev-list --count main..HEAD` is > 0: review the branch diff
- Otherwise: review the latest commit

If argument provided, map it:

| Argument | Scope | How to get changes |
|----------|-------|--------------------|
| `<commit-hash>` | That specific commit | `git show --stat <hash>` + `git diff <hash>^..<hash>` |
| `--staged` | Staged changes only | `git diff --cached` |
| `--branch` | Current branch vs main | `git log main..HEAD` + `git diff main...HEAD` |
| `--files path1 path2` | Specific files | Read the named files |
| `HEAD` or no arg | Latest commit or branch (auto-detect) | See auto-detect above |
| PR number | Pull request | `gh pr diff <number>` |

### Capture scope variables

```
REVIEW_TARGET  = description of what is being reviewed (e.g., "commit cb1b715")
REVIEW_FILES   = list of changed files
REVIEW_DIFF    = the full diff content
OUTPUT_PATH    = repository root (always)
```

## Preflight Check

Before dispatching any Bedrock review, verify AWS credentials and model access:

```bash
$WSROOT/.claude/scripts/<engine-script> --preflight --model <resolved-model> [--region <region>] [--profile <profile>]
```

**Always pass `--model`** with the model resolved in Step 2. This tests actual Bedrock invocation (both streaming and Converse APIs), not just STS credentials. Without it, preflight falls back to a default model which may not match what you're dispatching.

Use `review-cli.py` for CLI engine, `review-bedrock.py` for Converse engine. Parse the JSON result:

- **Success** (`"ok": true`): Proceed.
- **Error** (`"error"` key present): Show the error and the `suggestion` field (if present) to the user, and offer:
  1. **Run locally instead** — switch to `--local` mode (uses session context)
  2. **Switch to alternate engine** — if `converse_ok` is true, try `--engine converse`
  3. **Abort** — stop the review entirely

**Skip preflight when `--local` is specified** — no Bedrock access is needed.

## Execution

**Always invoke dispatch scripts as direct executables** (e.g., `$WSROOT/.claude/scripts/review-cli.py`), never via `python3`. The scripts manage their own dependencies via their uv shebang.

### 1. Gather context

Read `$WSROOT/.claude/data/review-reference.md` § "Context Assembly Instructions" for the detailed gathering procedure (steps 1a-1g). Follow the engine-conditional table there to determine which steps to run.

### 2. Launch review perspectives in parallel

All perspectives launch simultaneously. Save context to temp file first:

```bash
mkdir -p .reviews && cat > .reviews/review-context.txt <<'REVIEW_CONTEXT'
<ASSEMBLED_CONTEXT>
REVIEW_CONTEXT
```

> **CRITICAL — heredoc quoting:** The `<<'REVIEW_CONTEXT'` delimiter is **single-quoted** to prevent shell expansion of metacharacters in diffs. You MUST paste the assembled context directly as literal text into the heredoc body. **NEVER** use `$(cat "$FILE")` or any command substitution inside the heredoc.

#### CLI dispatch (Claude models on Bedrock — default)

For each selected perspective, launch a Bash call:

```bash
$WSROOT/.claude/scripts/review-cli.py \
  --focus "<focus-key>" \
  --target "<REVIEW_TARGET>" \
  --reviews-dir .reviews \
  [--model <alias>] \
  [--effort <level>] \
  [--region <region>] \
  [--profile <profile>] < .reviews/review-context.txt
```

Launch ALL calls as **separate background Bash calls** (`run_in_background: true`). No `--model` needed when inheriting session model.

> **Why temp file + redirect:** Avoids duplicating context across N heredocs (saves ~94% of context tokens).
>
> **Why input redirect (not pipe):** Use `< .reviews/review-context.txt`, NOT `cat ... | script`. Piping can serialize execution when multiple calls share stdin.
>
> **Why run_in_background:** Claude Code has a concurrency limit on foreground Bash calls (~6). Background calls bypass this limit and all launch immediately.

**Multi-model (Claude models):** For each model in `--model a,b`, launch a separate Bash call per perspective per model.

#### Converse dispatch (non-Claude models or --engine converse)

```bash
$WSROOT/.claude/scripts/review-bedrock.py \
  --model <alias> \
  --focus "<focus-key>" \
  --target "<REVIEW_TARGET>" \
  --reviews-dir .reviews \
  [--region <region>] \
  [--profile <profile>] < .reviews/review-context.txt
```

Launch each perspective as a **separate background Bash call** (`run_in_background: true`).

**Mixed-engine dispatch:** When `--model opus-4.6,nova-pro` is specified, Claude models dispatch via CLI engine and non-Claude models dispatch via Converse engine. All run in the same parallel batch. Results persist to the same `.reviews/` directory.

#### Custom agents on Bedrock

For custom agents resolved from `.claude/agents/`, pass the agent file body as `--persona` and the agent name as `--focus`:

```bash
# CLI engine:
$WSROOT/.claude/scripts/review-cli.py \
  --focus "<agent-name>" \
  --persona "<body text from .claude/agents/<name>.md>" \
  --target "<REVIEW_TARGET>" \
  --reviews-dir .reviews \
  [--model <alias>] [--region <region>] [--profile <profile>] < .reviews/review-context.txt

# Converse engine:
$WSROOT/.claude/scripts/review-bedrock.py \
  --model <alias> \
  --focus "<agent-name>" \
  --persona "<body text from .claude/agents/<name>.md>" \
  --target "<REVIEW_TARGET>" \
  --reviews-dir .reviews \
  [--region <region>] [--profile <profile>] < .reviews/review-context.txt
```

#### Local dispatch (--local)

Read `$WSROOT/.claude/data/review-reference.md` § "Agent Prompt Template (local mode)" for the prompt template. Launch all Agent tool calls in a single parallel batch.

#### Consistency checker (Converse engine only)

Read `$WSROOT/.claude/data/review-reference.md` § "Consistency Checker" for dispatch instructions.

#### Handling results

**CLI engine and Converse engine:** Parse JSON output from each Bash call:
- Success: `{"model_alias": "...", "review_content": "...", "token_usage": {...}}` — extract `review_content`
- Error: `{"error": "..."}` — log and skip, don't fail the review

Both engines produce identical `.reviews/REVIEW-*.md` files and `.result-*.json` sidecars. The synthesizer reads them interchangeably.

**Local mode:** Agent outputs are returned directly as text. **Default: paste each Agent tool result into the synthesizer prompt inline — do not write to disk UNLESS the combined outputs won't fit in one prompt (rare; only matters past ~50KB total) or the user asked to preserve per-perspective files (e.g., `--keep-reviews`).** In those cases, write each perspective to `.reviews-local/REVIEW-local-{focus}.md` and instruct the synthesizer to Read them. **The directory MUST be `.reviews-local/` (never `.reviews/`, which is reserved for Bedrock-path outputs).** Subagents can only see files or their own prompt — they do NOT see the orchestrator's conversation context, which is the only reason file-writing is ever necessary in local mode.

**Session persistence:** When `--reviews-dir .reviews` is used, each Bedrock call writes a `REVIEW-{alias}-{focus}.md` file and a `.result-{alias}-{focus}.json` metadata sidecar to `.reviews/`. These persist across session interruptions.

### 3. Synthesize

After all perspectives complete, launch a **synthesizer agent** using `subagent_type: "synthesizer"`.

**CLI engine and Converse engine:** Instruct the synthesizer to: **"Use Glob to find all `.reviews/REVIEW-*.md` files, then Read each one. Each file contains a review from a perspective (filename: `REVIEW-{model}-{focus}.md`). Include these findings with equal weight."**

**Local mode:** Include all Claude agent review outputs directly in the synthesizer prompt. If you used the optional file-based fallback above, instruct the synthesizer to **"Use Glob to find all `.reviews-local/REVIEW-local-*.md` files, then Read each one."** Do NOT mix the two — pick one and stick to it for a given run.

Read `$WSROOT/.claude/data/review-reference.md` § "Synthesis Instructions" for the deduplication rules, priority scheme, and output format to embed in the synthesizer prompt.

### 4. Write REVIEW.md

Read `$WSROOT/.claude/data/review-reference.md` § "REVIEW.md Output Format" for the report structure.

Write the synthesized report to a `REVIEW.md` file at the repository root.

### 5. Present summary to user

Show a concise summary:
```
Review complete: N findings (X critical, Y significant, Z recommended)
Execution: Bedrock (<model>) | Perspectives: [list]

Top issues:
  P0-1: [one-line summary]
  P0-2: [one-line summary]
  P1-1: [one-line summary]

Full report: REVIEW.md

Fix the issues? [Y/n]
```

If the user says yes: work through P0 findings first, then P1. For each finding, propose a concrete fix and apply it after user confirmation.

## No Re-Review Loop

**After fixing findings, do NOT re-run the review.** The review is advisory, not a gate. The cycle of review -> fix -> re-review -> find new issues -> fix -> re-review is an endless loop that exhausts context. Run the review once, fix the P0/P1 findings, and move on.

### Cleanup

After writing REVIEW.md and presenting results, **delete the intermediate per-perspective output directory** — `.reviews/` for Bedrock runs, `.reviews-local/` for local runs that used the file-based fallback:

```bash
# Bedrock path (CLI or Converse engine)
find .reviews -type f -delete 2>/dev/null; rmdir .reviews 2>/dev/null

# Local path (only if you wrote per-perspective files to .reviews-local/)
find .reviews-local -type f -delete 2>/dev/null; rmdir .reviews-local 2>/dev/null
```

If `--keep-reviews` is present, skip cleanup and leave the directory intact. Useful for debugging synthesis quality or inspecting individual model outputs. The flag applies uniformly to both `.reviews/` and `.reviews-local/`.

### Session recovery

If a review session was interrupted (e.g., context window ran out, connection dropped), check `.reviews/` (Bedrock) or `.reviews-local/` (local file-based fallback) for existing results before re-running. Each completed Bedrock call leaves a `.result-{alias}-{focus}.json` sidecar with `"status": "completed"` or `"status": "failed"`. Read the review content from the corresponding `REVIEW-{alias}-{focus}.md` files. Only re-dispatch perspectives that have no sidecar file. To start fresh, delete the directory.

## Engine Selection Quick Reference

| User intent | Flags | Engine | Script |
|-------------|-------|--------|--------|
| Default (best quality) | (none) | CLI | `review-cli.py` |
| Specific Claude model | `--model sonnet` | CLI | `review-cli.py` |
| Non-Claude model | `--model nova-pro` | Converse (+ warning) | `review-bedrock.py` |
| Force legacy path | `--engine converse` | Converse | `review-bedrock.py` |
| Local agents | `--local` | Local | Agent tool |
| Mixed models | `--model opus-4.6,nova-pro` | CLI + Converse | Both scripts |
