---
name: spec-driven-development
description: Spec-driven development workflow. Use this skill when users want to create, manage, or work with feature specifications, plan implementations using requirements/design/tasks, or structure complex features with formal documentation.
license: MIT
---

# Spec-Driven Development (SDD)

For the narrative guide, read `@docs/spec.md`. This file is the technical reference: decision rules, schemas, command signatures, and hard constraints.

## Hard Rules

**Never change working directory to the specs repo.** Specs live at `$WSROOT/specs` (a sibling git repo). Access spec files via absolute paths. Do not `cd` there. Do not `os.chdir()` there. Use `git -C <path>` for git ops in the spec repo.

**Never write/edit/delete files in the spec repo without explicit user instruction.** Reading spec files for context is fine. Modifying them requires an unambiguous request in the current turn ("update the requirements", "edit ctx/auth"). Session context, branch state, or prior command output is NOT sufficient permission.

**Import `TRUNK_BRANCHES` from `speclib.py`.** Never inline `{'main', 'master', 'develop'}`.

**Never reference namespace-specific commands** (e.g. `/ccs:*`) in the spec capability. The `capabilities/spec` capability is namespace-agnostic.

## Doc Root

```
<spec-repo-directory>/<project>/
  steering/    # steering docs; memory.md always injected, rest conditional
  ctx/         # long-lived subsystem docs; <name>/ or <name>.md
  specs/       # short-lived feature docs; <spec-name>/
```

- Default `spec-repo-directory`: `$WSROOT/specs`
- Default `project`: git repo name
- `steering` is a reserved context name -- always resolves to `steering/`, not `ctx/steering/`
- Every node (steering, context, spec) may be a single `.md` file OR a directory of `*.md` files. When both exist, directory wins.

## Configuration

Stored in `~/.dev/dev.yaml` under `spec.<repo>`:

| Key | Set via | Purpose |
|-----|---------|---------|
| `spec-repo-directory` | `/spec:config`, `/spec:setup` | Path to specs repo |
| `project` | `/spec:config`, `/spec:setup` | Default project name |
| `steering-context` | `/spec:config`, `/spec:setup` | When to auto-inject steering docs |
| `branches.<branch>.spec` | `/spec <name>`, `/spec:create` | Branch-to-spec association |
| `branches.<branch>.ctx` | `/spec ::<refs>`, `/spec ::+<refs>` | Branch's attached contexts |
| `branches.<branch>.project` | `/spec <name>::` | Branch-scoped project override |

**Project lookup order:** branch override -> repo default -> git repo name.

### Steering Auto-Injection Modes

`memory.md` is ALWAYS injected, unconditionally, every session. The other steering files inject per `steering-context`:

| Mode | Inject steering docs when... |
|------|------------------------------|
| `spec-branch` (default) | Branch is non-default AND a spec is associated |
| `any-branch` | Branch is non-default |
| `always` | Every session |
| `manual` | Never auto-inject; user loads with `/spec ::+steering` |

## Context Addressing

Format: `[project.]name`.

- `auth` -- context "auth" from current project
- `platform.billing` -- context "billing" from `platform` project
- `steering` -- reserved; resolves to `steering/` in current project
- `platform.steering` -- resolves to `steering/` in `platform` project

## Updating Context Documents

When a user explicitly asks to update a context ("update the auth context", "add notes to billing"):

1. Resolve the path: `<doc-root>/ctx/<name>` (file or directory)
2. If a directory, read existing files to understand structure and voice
3. Edit or create files -- preserve existing style
4. If the context does not exist, create `<doc-root>/ctx/<name>.md` (small) or `<doc-root>/ctx/<name>/` (multi-file)

Context voice: factual, concise, focused on what another agent needs to know. Do not duplicate spec content (short-lived) or steering content (project-wide).

## Spec Parameter Grammar

Two forms -- see `docs/guides/spec-parameter.md` for full reference.

**Bare spec name** (no colons): always refers to a spec in current project.

**Qualified form** (`project:spec:context`): set any combination in one op. Omit a field to leave unchanged; use `-` to clear.

| Pattern | Effect |
|---------|--------|
| `spec-name` | Set spec |
| `::ctx1,ctx2` | Replace contexts |
| `::+ctx` | Add context |
| `::-ctx` | Remove one context |
| `::-` | Clear all contexts |
| `proj::` | Set branch project override |
| `-::` | Clear project override |
| `-:-:-` | Clear everything |

## Command Reference

### Setup & config

| Command | Purpose |
|---------|---------|
| `/spec:setup` | Interactive wizard |
| `/spec:config [--set key value]` | View or modify config |
| `/spec` | Show current spec, project, contexts |
| `/spec:project:list` | List projects with spec/context counts |

### Spec lifecycle

| Command | Purpose |
|---------|---------|
| `/spec:create <name>` | Create spec dir and associate with branch |
| `/spec <name>` | Associate existing spec with branch |
| `/spec :-:` | Disassociate spec (keep directory) |
| `/spec:clear` | Reset all branch-scoped settings |
| `/spec:list` | List all specs with branch/worktree status |
| `/spec:rename <new>` | Rename current spec directory |
| `/spec:remove [name]` | Delete spec directory |
| `/spec:prune` | Clean orphaned associations and stale ctx refs |

### Document generation

| Command | Reads | Writes | Notes |
|---------|-------|--------|-------|
| `/spec:requirements` | constitution.md | requirements.md | EARS notation mandatory |
| `/spec:design` | requirements.md, constitution.md | design.md | |
| `/spec:tasks` | requirements.md, design.md, constitution.md | tasks.md | Must include BlockedBy + diagram + execution summary |
| `/spec:playback` | all three | playback.md | Persona narratives |
| `/spec:interview` | all | all | Interactive Q&A, updates docs |
| `/spec:impl [id|range]` | all | checks off tasks.md | Loops until all tasks done or range exhausted |
| `/spec:verify` | all + diff | report | Task completion, requirements traceability, design coherence, cross-artifact consistency |
| `/spec:steering` | codebase | product/tech/structure.md | Regenerate steering docs |

### Multi-agent

| Command | Purpose |
|---------|---------|
| `/spec:brainstorm [topic] [--sessions N] [--personas N] [--keep] [--spec <name>]` | Parallel generative agents; synthesize to `brainstorm.md`. If `topic` omitted, brainstorms around current spec. |
| `/spec:swarm [focus] [--sessions N] [--personas N] [--keep]` | Parallel review agents; focus weights persona selection (e.g. `security`, `design`, `testability`). |

**Persona roster** (for `--personas` selection): visionary, pragmatist, critic, analyst, user-advocate, contrarian, optimizer, historian, provocateur, strategist, chief-architect, chief-programmer, delivery-manager, synthesizer, simplifier, requirements-analyst, api-designer, security-reviewer, ops-reviewer, testability-reviewer, devils-advocate, architect.

Persona files live at `$WSROOT/.claude/skills/spec-driven-development/references/personas/<name>.md`.

Preferred personas:
- Brainstorm: visionary, contrarian, provocateur, strategist, historian, pragmatist, optimizer, analyst, user-advocate, synthesizer.
- Swarm: chief-architect, security-reviewer, devils-advocate, testability-reviewer, delivery-manager, chief-programmer, ops-reviewer, requirements-analyst, simplifier, api-designer.

`--personas 1` = different persona per session (maximize diversity). `--personas > 1` = same persona set per session (internal debate).

### Contexts

| Command | Purpose |
|---------|---------|
| `/spec ::<refs>` | Set contexts for branch (error if any ref not found) |
| `/spec ::+<refs>` | Append contexts to branch |
| `/spec ::-<ref>` | Remove one context from branch |
| `/spec ::-` | Clear all contexts from branch |
| `/spec:ctx:list` | List all contexts across projects |
| `/spec:ctx:create <name>` | Create a context directory |
| `/spec:ctx:rename <old> <new>` | Rename a context |
| `/spec:ctx:remove <name>` | Delete a context directory |

## EARS Notation (required in requirements.md)

| Pattern | Syntax | Use When |
|---------|--------|----------|
| Event | `WHEN [event] THE SYSTEM SHALL [action]` | System must respond to something |
| Conditional | `IF [condition] THEN THE SYSTEM SHALL [action]` | Precondition determines behavior |
| State | `WHILE [state] THE SYSTEM SHALL [action]` | Sustained state behavior |
| Combined | `WHEN [event] AND [condition] THE SYSTEM SHALL [action]` | Multiple triggers |
| Ubiquitous | `THE SYSTEM SHALL [action]` | Always-on constraint (use sparingly) |

Rules:
- Numbered lists (`1.` `2.`) for acceptance criteria. Never checkboxes or tables.
- One observable behavior per criterion.
- Reference criteria as "Requirement N, criteria M" in design/tasks.

## Task Format (required in tasks.md)

Every task MUST include:

| Field | Required | Description |
|-------|----------|-------------|
| ID | Yes | `task-N.N` |
| BlockedBy | Yes | `task-X.Y` or `none` |
| Agent | No | Suggested agent type |
| File | Yes | Primary file changed |
| Change | Yes | What to modify |
| Outcome | Yes | Expected result |
| Context | Yes | Requirement refs, patterns, test criteria |

### Dependencies and parallelism -- MANDATORY

Every `tasks.md` MUST include ALL THREE:

1. **BlockedBy on every task.** `none` for root tasks; `task-X.Y` or comma-separated list otherwise. Same `BlockedBy` value = parallel-safe.
2. **ASCII dependency diagram** after all tasks showing the execution graph.
3. **Execution summary** listing parallel stages, critical path, and total stage count.

Tasks without this metadata are non-conforming. `/spec:tasks` generates all three; do not strip them when editing.

## Memory Commands

| Command | Updates |
|---------|---------|
| `/harness:memory-update` | Full: contexts, specs, codebase map |
| `/harness:memory-code` | Codebase map only |
| `/harness:memory-spec` | Context and spec indexes only |

Run `memory-spec` after creating/renaming/removing specs or contexts. Run `memory-code` after structural changes to the repo. Run `memory-update` periodically.

## Working Inside `$WSROOT/specs` Itself

When editing the specs repo directly (e.g., cleaning up steering docs):

```
/spec:config --set spec-repo-directory .
/spec:config --set project <project-name>
```

## Decision Rules

**Should I spec this at all?**
- Small bug fix, typo, obvious refactor -> no.
- Touches multiple components, multiple people, or multiple sessions -> yes.

**Brainstorm or straight to requirements?**
- Solution space uncertain -> `/spec:brainstorm` first.
- Clear idea of what to build -> straight to `/spec:requirements`.

**Swarm when?**
- After first draft of requirements+design, before tasks.
- Again after `/spec:tasks` if tasks triggered design rewrites.
- Optional final pass with `--keep` as a record.

**Promote to context when?**
- Content would still be relevant to explain to a new engineer 6+ months after the spec ships -> move it from the spec into `ctx/`.
- Before `/spec:remove`, extract enduring architecture/gotchas into the relevant ctx.

**Granularity fallback: go coarser.** Start with fewer, broader requirements/tasks. Refine only if implementation surfaces ambiguity.
