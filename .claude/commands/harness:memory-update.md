---
allowed-tools: Bash, Read
description: Update all sections of steering/memory.md. Default when user asks to refresh memory, update the codebase map, or sync everything. Use memory:code for dev2 only, memory:spec for specs only.
argument-hint: [--repo | --spec]
---

Parse $ARGUMENTS:
- `--repo`: run `/memory:code` only
- `--spec`: run `/memory:spec` only
- (no flag): run both in sequence

## Both (default)

1. Run `/memory:code` to update `## dev2`.
2. Run `/memory:spec` to update `## Specs` and `## Contexts`.
3. Report combined summary:
   ```
   [OK] Updated all sections of steering/memory.md
     ## dev2: updated
     ## Specs: updated
     ## Contexts: updated
   ```

## --repo only

Run `/memory:code`. Report its output.

## --spec only

Run `/memory:spec`. Report its output.
