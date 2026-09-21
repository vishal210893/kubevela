---
description: Create a new context directory
model: sonnet
context: fork
allowed-tools: [Bash($WSROOT/.claude/scripts/spec-ctx-create *), Read, Write, Glob, Grep]
argument-hint: <name>
---

## Arguments

- **<name>** (required): Context name (e.g. auth, billing, data-export)
- **--file** (optional): Create as a flat file (ctx/<name>.md) instead of a directory with a seed <name>.md inside

**IMPORTANT:** If the user did not provide <name>, you MUST ask them for it before executing the script.

## Your task

Execute the script to create a new context directory:

```bash
CC=1 $WSROOT/.claude/scripts/spec-ctx-create <name>
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** A new context was created at the path shown in the output.

If a directory was created, it already contains a seed file named `<name>.md` (e.g.
`auth/auth.md`). If --file was used, the path is a single flat markdown file.

Now analyze the codebase to populate the context with useful content. Read relevant
source files, configuration, and existing docs to understand this area, then write
the content into the existing file(s).

For directory contexts: start by filling in the seed `<name>.md` file. If the area
is large enough to warrant multiple files, add siblings alongside it and organize
by topic -- for example:

- `overview.md` -- What this project/area does and why it exists
- `architecture.md` -- Key classes, modules, data flow, dependencies
- `conventions.md` -- Patterns, naming rules, error handling specific to this area
- `key-files.md` -- Important file paths with brief descriptions

Do NOT invent a `context.md` -- the seed file is already named `<name>.md`.

Write in a factual, concise style. Focus on what an agent needs to know to work
effectively in this area. Avoid duplicating steering docs (project-wide info) or
spec docs (feature-specific info).

After writing, suggest adding it to the branch context: /spec ::+<name>

**Examples:**
```
[OK] Created context 'auth' at /workspaces/src/specs/dev/ctx/auth/ (seeded auth.md)

[Analyzes codebase and writes into auth.md and any additional sibling files]
```

