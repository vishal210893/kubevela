---
description: Generate or refine tasks document
model: opus
allowed-tools: [Bash($WSROOT/.claude/scripts/spec-tasks), Read, Write]
---

## Your task

Execute the script to generate or refine tasks document:

```bash
CC=1 $WSROOT/.claude/scripts/spec-tasks
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Based on the script output, generate or refine the spec's tasks.md (path shown in script output).

Read requirements.md and design.md first if they exist to inform the task breakdown.
If tasks.md exists (existing_content provided), refine and expand it.
If it doesn't exist, generate a new one.

REQUIRED STRUCTURE for every task:

### Phase N: [Phase Name]

- [ ] **Task N.M**: [Title]
  - **ID**: `task-N.M`
  - **BlockedBy**: `task-X.Y` | `none`
  - **Agent**: `general-purpose` | `architect` | `chief-programmer` | `Explore` | etc.
  - **File**: `[path/to/primary/file]`
  - **Change**: [What to modify]
  - **Outcome**: [Expected result]
  - **Context**: [Requirements refs, patterns to follow, test criteria]

MANDATORY FIELDS on every task (no exceptions):
- **ID** — unique identifier (e.g. `task-1.1`)
- **BlockedBy** — ALWAYS present. Use `none` for root tasks with no dependencies. This makes parallelism explicit: tasks sharing the same BlockedBy value can execute simultaneously.
- **File** — path to the primary file being changed
- **Change** — what to modify
- **Outcome** — expected result after the task is done
- **Context** — references to requirements (Requirement N, criteria M), design patterns, test criteria. Enough detail for an agent to execute autonomously.

OPTIONAL FIELD:
- **Agent** — suggested agent type based on the nature of the work:
  - `Explore` — research, codebase exploration, understanding existing patterns
  - `architect` / `chief-architect` — system design, component boundaries, API design
  - `chief-programmer` — complex implementation, refactoring, code-level design
  - `general-purpose` — standard implementation tasks, file edits, scripting
  - `testability-reviewer` — test strategy, test gaps, boundary conditions
  - `security-reviewer` — security audit, threat modeling, input validation
  - `api-designer` — API surface review, CLI commands, configuration schemas
  - Omit if the task is straightforward and `general-purpose` is obvious

REQUIRED SECTIONS (all three must be present):

1. **Implementation Tasks** — Grouped by phase with checkboxes and full metadata
2. **Dependency Diagram** — ASCII diagram showing task execution order and parallelism (see below)
3. **Completion Criteria** — Definition of done

DEPENDENCY DIAGRAM — MUST be included after all phases. Show fan-out (parallel),
fan-in (convergence), and independent tracks. Example:

```
Task 1.1 (setup) ──┬──▶ Task 2.1 (auth module) ──┬──▶ Task 4.1 (integration tests)
                    │                               │
                    ├──▶ Task 2.2 (API routes)  ────┤
                    │                               │
                    └──▶ Task 2.3 (DB schema)  ─────┘

Task 1.2 (config) ──────▶ Task 3.1 (docs) ──────────▶ Task 4.2 (final review)
```

Parallelism: Tasks 2.1, 2.2, 2.3 can execute simultaneously (all BlockedBy: task-1.1)
Parallelism: Tasks 1.1, 1.2 can execute simultaneously (both BlockedBy: none)
Convergence: Task 4.1 waits for 2.1 + 2.2 + 2.3
Critical path: 1.1 -> 2.1 -> 4.1 -> 4.2

After the diagram, explicitly list:
- **Parallel opportunities**: which tasks can run simultaneously and why
- **Critical path**: the longest chain of sequential dependencies

FORMAT UPGRADE for existing tasks.md:
If existing_content is provided and tasks lack ID/BlockedBy metadata,
reformat ALL tasks to this dependency model. Preserve task content and intent
but add proper ID, BlockedBy, Agent, File, Change, Outcome, Context fields.
Analyze task ordering to infer dependencies (earlier phases block later ones,
tasks within a phase are often parallel).

GUIDELINES:
- Each task should be completable in one agent session
- Include specific file paths
- Tasks should map to requirements (reference Requirement N, criteria M in Context)
- Use checkboxes for tracking
- Tasks with the same BlockedBy can run in parallel — design task breakdown to maximize parallelism
- Include enough Context that an agent can execute the task autonomously
- Group related changes by file/module when possible to minimize context switching

If constitution_content is provided, treat it as immutable project principles.
Ensure all tasks comply with those principles (e.g., if constitution requires tests,
ensure test tasks are included).

REQUIRED SUMMARY after writing/updating:
- Total tasks: [count]
- Total phases: [count]
- Parallel opportunities: [list which task groups can run simultaneously]
- Critical path: [longest sequential chain, with length]
- Example: "Parallel: Tasks 2.1, 2.2, 2.3 can run simultaneously after 1.1 | Critical path: 1.1 -> 2.1 -> 4.1 (3 tasks)" 

**Examples:**
```
[OK] Created tasks.md for spec 'feature-auth'

Structure:
  - Phase 1: Setup (2 tasks)
  - Phase 2: Core Implementation (3 task
```

```
all parallel)
  - Phase 3: Testing (2 tasks)
  - Phase 4: Docs & Review (1 task)

Total: 8 tasks across 4 phases
Parallel opportunities: Tasks 2.1
```

```
2.2
```

```
2.3 (after 1.1) | Tasks 1.1
```

```
1.2 (root)
Critical path: 1.1 -> 2.1 -> 3.1 -> 4.1 (4 tasks)"
```

