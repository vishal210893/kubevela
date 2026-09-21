---
description: Show or set the current project
model: haiku
allowed-tools: Bash($WSROOT/.claude/scripts/spec-project:*)
argument-hint: [project]
---

## Arguments

- **[project]** (optional): Project name to switch to. If omitted, shows current project. Errors if project doesn't exist.

## Your task

Execute the script to show or set the current project:

```bash
CC=1 $WSROOT/.claude/scripts/spec-project [[project]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** If showing (get): display the current project name and its source (branch override, repo default, or repo name fallback). If setting: confirm the project was set, and report any spec/ctx that were cleared (omit if none were cleared).

**Examples:**
```
Current project: dev (repo default)
```

```
Current project: platform (branch override for 'feature-x')
```

```
Current project: ai-dev (repo name fallback)
```

```
Switched to project 'platform'
  Cleared spec: my-feature
  Cleared ctx: steerin
```

```
auth"
```

```
Switched to project 'platform' (no spec or ctx to clear)
```

