# Check Spec Location Before Searching

**When to use this rule**: Before searching for specs, opening spec files, or
referencing spec file paths.

## Problem

The same spec name can exist under multiple projects (e.g. `build` exists in
both `dev` and `appmgr`). Specs do NOT live in `.dev/specs/`. Specs live at
`<spec-repo-directory>/<project>/specs/<spec>/`, and which project applies
depends on the current branch. Guessing the project from the spec name alone
is the most common cause of "file not found" errors and edits applied to the
wrong project.

## Discovery Process (in order -- stop at the first hit)

### Step 1: Check the injected SessionStart context FIRST

If a `# SPEC LOCATION` block is present in the conversation, it is the answer:

```
# SPEC LOCATION
Project: appmgr
Spec: build
Root: /workspaces/src/specs/appmgr/specs/build/
Config: ~/.dev/dev.yaml (authoritative source)
```

That `Root` is the absolute path to the spec directory. Use it directly. Do
not run any commands or filesystem searches -- the hook already resolved it.

### Step 2: Read `~/.dev/dev.yaml` (authoritative source)

If no SPEC LOCATION block was injected (e.g. the branch has no associated
spec, or you need to confirm), read `~/.dev/dev.yaml` directly. Project and
spec are resolved by this 3-tier lookup, applied in order, first match wins:

1. Branch override: `spec.<repo>.branches.<branch>.project` and `.spec`
2. Repo default: `spec.<repo>.project`
3. Repo name (fallback)

Example for branch `dev5::main`:
```yaml
spec:
  ai-dev:
    branches:
      dev5::main:
        project: appmgr     # branch override beats repo default
        spec: build
    project: dev            # repo default (only used when no branch override)
```
Resolved: project=`appmgr`, spec=`build`, root=`<spec-repo-directory>/appmgr/specs/build/`.

### Step 3: Run `/spec` for a formatted view

`/spec` (no args) prints the resolved project (with resolution source), spec
name, path, and contexts for the current branch. Use this when you want a
human-readable summary or want to verify your reading of `dev.yaml`.

### Step 4: If nothing is configured

Run `/spec:setup`. This validates the specs repo and sets the project name.

## Spec name vs spec location

A spec is identified by `<project>/<spec-name>`, not by `<spec-name>` alone.
Two specs with the same name in different projects are different specs.
Always resolve the project before doing anything spec-related -- never assume.

## Forbidden shortcuts

- Do NOT guess the project from the repo name. The repo name is only the
  fallback when no branch override and no repo default are set.
- Do NOT search the filesystem (`find`, `grep`, `Explore`) for a spec without
  first resolving the project. You will pick up the wrong copy.
- Do NOT skip Step 1. The SPEC LOCATION header is injected for exactly this
  purpose -- using it costs zero tokens, while filesystem searches cost many.
