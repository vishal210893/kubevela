---
name: spec-driven-development
description: Spec-driven development workflow. Use this skill when users want to create, manage, or work with feature specifications, plan implementations using requirements/design/tasks, or structure complex features with formal documentation.
license: MIT
---

# Spec-Driven Development (SDD)

SDD is a structured approach to feature development that transforms ideas into formal specifications before implementation. Instead of jumping from idea to code, you walk through requirements, design, and tasks -- producing traceable, reviewable documentation that lives alongside (or near) your code.

## Getting Started

Run `/spec:setup` to configure SDD for your repository. It validates that the shared specs repo exists at `$WSROOT/specs` and prompts for your project name.

If you haven't cloned the specs repo yet:
```
git clone https://github.com/gwre-pdo/specs $WSROOT/specs
```

## Key Concepts

### Repository Layout

Specs live in a shared repository at `$WSROOT/specs`, organized by project. Each code repo maps to a project name:

```
$WSROOT/specs/<project>/
  steering/        # Project identity (auto-loaded every session)
  ctx/             # Long-lived component docs
  specs/           # Short-lived feature specs
```

Run `/spec:project <name>` to switch projects (useful in monorepos).

Advanced users can override the defaults with `/spec:config` for alternative layouts (collocated specs, dedicated specs repo, etc.), but the shared model is recommended.

### Configuration Properties

Configuration is stored in `~/.dev/dev.yaml` under the `spec` section:

| Key | Default | Description |
|-----|---------|-------------|
| `spec.<repo>.spec-repo-directory` | `$WSROOT/specs` | Path to shared specs repo |
| `spec.<repo>.project` | repo name | Repo-wide default project name |
| `spec.<repo>.branches.<branch>.spec` | -- | Spec associated with a branch |
| `spec.<repo>.branches.<branch>.ctx` | -- | Contexts associated with a branch |
| `spec.<repo>.branches.<branch>.project` | -- | Branch-scoped project override |

### Doc Root

The doc root is the resolved base directory for all your documentation: `<spec-repo-directory>/<project>/`. Inside it you always find the same structure:

```
<doc-root>/
  steering/        # Steering context (architecture, conventions)
  ctx/             # Long-lived component docs (auth, billing, etc.)
  specs/           # Short-lived feature specs
```

### Steering Context vs Context vs Specs

**Steering context** (`steering/`) is your project's top-level documentation -- architecture decisions, coding conventions, product overview. It is loaded using the reserved name `steering` in context commands.

**Context** (`ctx/`) is long-lived documentation for specific components like `auth`, `billing`, or `data-export`. Context docs persist and accumulate knowledge over time, surviving long after individual specs are completed.

**Specs** (`specs/`) are short-lived, feature-scoped documentation containing requirements, design, and tasks. They are created when work begins and deleted when complete. Git history preserves them.

### Flexible Structure

Every documentation node -- steering, subsystem, or spec -- can be either a single `.md` file or a directory of `*.md` files. Start simple with `auth.md`, then promote to `auth/` with multiple files as the docs grow. No migration needed. When resolving, directory takes precedence over file.

### Context Addressing

Context items use the format `[project:]name`. Examples:

- `steering` -- your project's steering context (reserved name)
- `auth` -- context named "auth" from your default project
- `platform:billing` -- context "billing" from the platform project
- `platform:steering` -- steering context from the platform project

The name `steering` is always reserved for the steering directory. All other names resolve under `ctx/`.

### Updating Context Documents

When the user asks to "update the auth context" or "add notes to the billing context", resolve the context path and edit the files directly. Context docs are meant to be updated as knowledge accumulates.

**Resolution:** Use `resolve_context_path(ref)` from `speclib.py` to find the filesystem path. It checks `ctx/`, `context/`, and `subsystems/` in order. The result is a `Path` object that may be a file (`auth.md`) or directory (`auth/`).

**Workflow:**

1. Resolve the path: `<doc-root>/ctx/<name>` (file or directory)
2. If it's a directory, read the existing `.md` files inside it to understand current content
3. Edit or create files as needed -- preserve the existing structure and voice
4. If the context doesn't exist yet, create it as `<doc-root>/ctx/<name>.md` (single file) or `<doc-root>/ctx/<name>/` (directory with multiple files) based on scope

**Examples of user requests:**

- "Update the auth context with the new RBAC design" -- resolve `auth`, read existing docs, add/edit RBAC content
- "Create a context doc for the payment gateway" -- create `<doc-root>/ctx/payment-gateway.md`
- "Add error handling patterns to the API context" -- resolve `api`, append error handling section

Context docs should be written in the same style as steering docs: factual, concise, focused on what an agent needs to know to work in that area. Avoid duplicating information that belongs in specs (which are short-lived) or steering (which is project-wide).

## Command Reference

### Configuration

| Command | Description |
|---------|-------------|
| `/spec:setup` | Interactive wizard to configure SDD repository settings |
| `/spec:config` | View or modify configuration. `--set key value` to set, `--unset key` to remove. Keys: `spec-repo-directory`, `project` |
| `/spec:project` | Show current project (with resolution source). |
| `/spec:project <name>` | Set branch-scoped project override (error if not found) |
| `/spec:project:clear` | Clear branch project override, fall back to default |
| `/spec:project:list` | List available projects with spec/context counts |

### Spec Management

| Command | Description |
|---------|-------------|
| `/spec` | Show current spec association for the branch |
| `/spec:list` | List all specs with branch and worktree status |
| `/spec <name> [--context refs]` | Associate existing spec with current branch (defaults to branch name). `--context` sets branch contexts in the same step. |
| `/spec:clear` | Disassociate spec from current branch, keeps spec directory |
| `/spec:create <name>` | Create spec and associate with current branch. Use `<name>` or `<issue>:<name>` format |
| `/spec:rename <new-name>` | Rename current branch's spec directory |
| `/spec:remove [name]` | Remove spec directory and all branch associations (git history preserves content) |
| `/spec:prune` | Clean up orphaned spec-branch associations for deleted branches |
| `/spec:status` | Show detailed completion status of current branch's spec |

### Document Generation

| Command | Description |
|---------|-------------|
| `/spec:requirements` | Generate or refine `requirements.md` using EARS notation |
| `/spec:design` | Generate or refine `design.md` (reads requirements first) |
| `/spec:tasks` | Generate or refine `tasks.md` (reads requirements and design first) |
| `/spec:interview` | Interactive Q&A to identify gaps, then updates spec docs |
| `/spec:playback` | Generate or refine `playback.md` with persona-based usage narratives (reads requirements, design, and tasks first) |
| `/spec:brainstorm` | Run parallel brainstorming sessions |
| `/spec:impl` | Execute tasks from tasks.md |
| `/spec:steering` | Analyze codebase and generate steering documents (product.md, tech.md, structure.md) |
| `/spec:swarm` | Swarm review of current spec |
| `/spec:verify` | Verify implementation against spec |

### EARS Notation (Required for All Acceptance Criteria)

Every acceptance criterion in `requirements.md` MUST use EARS (Easy Approach to Requirements Syntax). EARS eliminates ambiguity by using structured trigger-response patterns.

**Patterns:**

| Pattern | Syntax | When to Use |
|---------|--------|-------------|
| Event-driven | `WHEN [event] THE SYSTEM SHALL [action]` | Something happens and the system must respond |
| Conditional | `IF [condition] THEN THE SYSTEM SHALL [action]` | A precondition determines behavior |
| State-driven | `WHILE [state] THE SYSTEM SHALL [action]` | Ongoing behavior during a sustained state |
| Combined | `WHEN [event] AND [condition] THE SYSTEM SHALL [action]` | Multiple triggers |
| Ubiquitous | `THE SYSTEM SHALL [action]` | Always-on constraints (use sparingly) |

**Example:**

```markdown
### Requirement 1: User Authentication

**User Story:** As a developer, I want to log in with my GitHub account, so that I can access the CLI without a separate password.

#### Acceptance Criteria

1. WHEN the user runs `dev login` THE SYSTEM SHALL open a browser to the GitHub OAuth page
2. WHEN authentication succeeds THE SYSTEM SHALL store the token securely in the user's config
3. IF the stored token is expired THEN THE SYSTEM SHALL prompt the user to re-authenticate
4. WHILE the user is authenticated THE SYSTEM SHALL include the token in all API requests
5. WHEN the user runs `dev logout` THE SYSTEM SHALL remove the stored token
```

**Rules:**
- Use numbered lists (`1.` `2.` `3.`) for acceptance criteria — never checkboxes or tables
- Every criterion must use one of the five EARS patterns above
- Keep criteria atomic: one observable behavior per criterion
- Reference criteria as "Requirement N, criteria M" in design and tasks

### Task Format (Required for tasks.md)

Every task in `tasks.md` MUST include these metadata fields:

| Field | Required | Description |
|-------|----------|-------------|
| **ID** | Yes | Unique identifier, e.g. `task-1.1` |
| **BlockedBy** | Yes | Dependency — `task-X.Y` or `none` for root tasks |
| **Agent** | No | Suggested agent type (e.g. `general-purpose`, `architect`, `chief-programmer`) |
| **File** | Yes | Path to primary file being changed |
| **Change** | Yes | What to modify |
| **Outcome** | Yes | Expected result |
| **Context** | Yes | Requirements refs, patterns, test criteria for autonomous execution |

**Example:**

```markdown
- [ ] **Task 2.1**: Add OAuth token storage
  - **ID**: `task-2.1`
  - **BlockedBy**: `task-1.1`
  - **Agent**: `chief-programmer`
  - **File**: `src/auth/token-store.ts`
  - **Change**: Implement secure token persistence using keychain API
  - **Outcome**: Tokens survive CLI restarts, encrypted at rest
  - **Context**: Requirement 1, criteria 2. Follow existing config store pattern in `src/config/`.
```

### Dependencies and Parallelism (MANDATORY)

**This section is non-negotiable. Every `tasks.md` MUST include all three elements below. Tasks without explicit dependency information are useless — the implementer cannot know what to do first, what can run in parallel, or what is blocked.**

#### 1. BlockedBy on every task

- Every task MUST have a `BlockedBy` field
- Use `BlockedBy: none` for root tasks that can start immediately
- Use `BlockedBy: task-X.Y` (or comma-separated list) for dependent tasks
- Tasks with the same `BlockedBy` value CAN execute in parallel

#### 2. Dependency diagram (REQUIRED)

After all tasks, include an ASCII dependency diagram showing the full execution graph. This diagram makes the critical path and parallelism opportunities immediately visible.

```
Task 1.1 ──┬──▶ Task 2.1 ──┬──▶ Task 3.1
            ├──▶ Task 2.2 ──┤
            └──▶ Task 2.3 ──┘
```

#### 3. Execution summary (REQUIRED)

After the diagram, include a plain-text summary that spells out:
- Which tasks can run in parallel at each stage
- What the critical path is
- Total number of serial stages

**Example:**

```markdown
## Execution Summary

- **Stage 1** (serial): Task 1.1 — must complete first
- **Stage 2** (parallel): Tasks 2.1, 2.2, 2.3 — all independent, run simultaneously
- **Stage 3** (serial): Task 3.1 — depends on all Stage 2 tasks
- **Critical path**: 3 serial stages
```

This summary is the first thing an implementer reads to plan their work. Without it, they must reverse-engineer the execution order from individual BlockedBy fields scattered across the document.

### Context (Branch Refs)

| Command | Description |
|---------|-------------|
| `/spec:ctx` | Show contexts for current branch |
| `/spec:ctx <refs>` | Set contexts for current branch (error if any not found) |
| `/spec:ctx:add <refs>` | Add context items to current branch |
| `/spec:ctx:clear` | No args = clear all; with args = clear specific refs |
| `/spec:ctx:list` | List all available contexts |
| `/spec:ctx:prune` | Clean up orphaned context associations |

### Context (Directory Lifecycle)

| Command | Description |
|---------|-------------|
| `/spec:ctx:create <name>` | Create a new context directory |
| `/spec:ctx:rename <old> <new>` | Rename a context directory |
| `/spec:ctx:remove <name>` | Delete a context directory |

## Workflows

### Basic Workflow

```
/spec:create 123:auth-feature     # Create spec, fetch GitHub issue #123
/spec:interview                    # Refine requirements interactively
/spec:requirements                 # Generate formal requirements
/spec:design                       # Generate design
/spec:tasks                        # Generate implementation tasks
/spec:playback                     # Generate stakeholder-facing usage narratives

# ... do the work ...

/spec:remove                       # Remove spec dir, git history preserves it
```

### Working with GitHub Issues

Use the colon format `<issue>:<name>` to link a spec to a GitHub issue. The issue content gets fetched and seeded into `requirements.md`:

```
/spec:create 456:billing-refactor  # Fetches issue #456, creates spec
```

If you don't have an issue, just use a plain name:

```
/spec:create cleanup-validators    # No issue, just a name
```

### Working Directly in the Specs Repo

When working inside `$WSROOT/specs` itself (e.g., to manage steering docs or review specs), set the spec-repo-directory to the current repo and choose a project:

```
/spec:config --set spec-repo-directory .
/spec:config --set project platform
```

### Multi-Project Workflow (Monorepos)

Switch projects as needed:

```
/spec:project platform            # Switch to platform project
/spec:project billing             # Switch to billing project
```

Then use context commands to load docs from your project and others:

```
/spec:ctx:add steering,auth             # Your project's steering context + auth context
/spec:ctx:add payments:billing          # Cross-project: payments project's billing context
/spec:ctx                               # See what's loaded
/spec:ctx:list                          # See all available contexts
```

### Switching Projects

Use `/spec:project` to view or change which project you're working on:

```
/spec:project                    # Show current project (with resolution source)
/spec:project platform            # Set branch-scoped override to platform
/spec:project:clear              # Clear override, fall back to default
/spec:project:list               # List all available projects with counts
/spec:config --set project dev   # Change repo-wide default project
```

### Adding Context to a Branch

Context is branch-scoped. When you switch branches, the loaded context changes automatically.

```
/spec:ctx steering,auth,data-export           # Set exact context list for this branch
/spec:create 789:export-api             # Create spec with context already loaded

# Or do both in one step:
/spec export-api --context steering,auth,data-export

# Later, on a different branch:
/spec:ctx:add steering,billing               # Append to existing context
```

## Spec Lifecycle

Specs are intentionally transient:

```
created  -->  active  -->  completed (removed)
```

1. **Created** -- `/spec:create` makes the directory and template files, associates with a branch
2. **Active** -- You generate and refine requirements, design, and tasks. The spec is your working document.
3. **Completed** -- `/spec:remove` removes the directory and association. Git history preserves everything.

## Doc Root Reference

The doc root is always: `<spec-repo-directory>/<project>/`

Specs are at: `<spec-repo-directory>/<project>/specs/<spec-name>/`

By default, `spec-repo-directory` is `$WSROOT/specs` and `project` falls back to the repo name.

Inside every doc root, the structure is always:

```
<doc-root>/
  steering/        # or steering.md -- auto-loaded every session via SessionStart hook
  ctx/             # contains <name>/ or <name>.md entries
  specs/           # contains <spec-name>/ directories
```

The `steering/` directory is special: its contents are **always** injected at the start of every Claude session (regardless of branch). Use `/spec:steering` to generate or refresh the steering documents. Typical files:

- `product.md` -- Project purpose, target users, key features
- `tech.md` -- Technology stack, libraries, build conventions
- `structure.md` -- Directory layout, naming patterns, architecture overview
- `constitution.md` -- Immutable project principles (optional; injected into all spec generation commands)

## Dev YAML Storage

Configuration is stored in `~/.dev/dev.yaml` under the `spec` section:

| Key | Example | Set via |
|-----|---------|---------|
| `spec.<repo>.spec-repo-directory` | `$WSROOT/specs` | `/spec:config`, `/spec:setup` |
| `spec.<repo>.project` | `dev` | `/spec:config`, `/spec:setup` |
| `spec.<repo>.branches.<branch>.spec` | `auth-feature` | `/spec <name>`, `/spec:create` |
| `spec.<repo>.branches.<branch>.ctx` | `steering,auth` | `/spec:ctx <refs>`, `/spec:ctx:add` |
| `spec.<repo>.branches.<branch>.project` | `platform` | `/spec:project <name>` |

### Project Lookup

```
1. spec.<repo>.branches.<branch>.project    # branch override (any branch)
2. spec.<repo>.project                      # repo-wide default
3. get_repo_name()                            # fallback = repo name
```

- `/spec:project <name>` -- always writes branch override
- `/spec:project:clear` -- clears branch override, falls back to default
- `/spec:config --set project <name>` -- sets repo-wide default
