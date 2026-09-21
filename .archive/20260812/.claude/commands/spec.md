---
description: Show or set current spec association
model: sonnet
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/spec *)
argument-hint: [spec | spec:context | project:spec:context]
---

## Arguments

- **spec | spec:context | project:spec:context** (optional): Qualified spec format. Bare name sets spec. Single colon sets spec+context. Two colons: each position omit=keep, '-'=clear, value=set. Context items can be +prefixed (add) or -prefixed (remove).

## Your task

Execute the script to show or set current spec association:

```bash
CC=1 $WSROOT/.claude/scripts/spec [spec | spec:context | project:spec:context]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** If showing (get): display project (with resolution source), spec name, path, and contexts for the branch. If setting: confirm each change made (project, spec, contexts). Show branch name in each confirmation.

**Examples:**
```
Spec 'auth' on branch 'sclaussen/680/feature/auth'
  Path: /workspaces/src/specs/dev/specs/auth/
  Project: dev (repo name)
  Contexts: steerin
```

```
auth

Format: /spec spec | spec:context | project:spec:context (see docs/guides/spec-parameter.md)"
```

```
No spec associated with branch 'main'
  Project: dev (repo name)

Format: /spec spec | spec:context | project:spec:context (see docs/guides/spec-parameter.md)
```

```
[OK] Associated spec 'feature-auth' with branch 'feature-auth'
[OK] Set 2 context(s): steerin
```

```
auth"
```

```
[OK] Cleared spec from branch 'feature-auth'
```

```
[OK] Added context(s): logging
```

```
[OK] Set project 'alm' on branch 'feature-auth'
[OK] Associated spec 'billing' with branch 'feature-auth'
```

