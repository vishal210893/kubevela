---
description: Create a new context directory
model: opus
allowed-tools: [Bash($WSROOT/.claude/scripts/ctx-create:*), Read, Write, Glob, Grep]
argument-hint: <name>
---

## Arguments

- **<name>** (required): Context name (e.g. auth, billing, data-export)

**IMPORTANT:** If the user did not provide <name>, you MUST ask them for it before executing the script.

## Your task

Execute the script to create a new context directory:

```bash
CC=1 $WSROOT/.claude/scripts/ctx-create <name>
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** A new context directory was created at the path shown in the output.

Now analyze the codebase to populate it with useful documents. Read relevant source files,
configuration, and existing docs to understand this area, then write one or more markdown
files inside the context directory. Organize by topic -- for example:

- `overview.md` -- What this project/area does and why it exists
- `architecture.md` -- Key classes, modules, data flow, dependencies
- `conventions.md` -- Patterns, naming rules, error handling specific to this area
- `key-files.md` -- Important file paths with brief descriptions

Or use a single `context.md` if the area is small. Use your judgement on how many files
to create based on the complexity of the area.

Write in a factual, concise style. Focus on what an agent needs to know to work
effectively in this area. Avoid duplicating steering docs (project-wide info) or
spec docs (feature-specific info).

After writing, suggest adding it to the branch context: /spec:ctx:add <name>

**Examples:**
```
[OK] Created context 'auth' at /workspaces/src/specs/dev/ctx/auth/

[Analyzes codebase and writes context documents into the directory]
```

