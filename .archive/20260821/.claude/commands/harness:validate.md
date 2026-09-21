---
description: Validate this repo's .harness.yaml against the canonical JSON schema using check-jsonschema (uvx).
allowed-tools:
  - Bash
  - Read
---

## Your task

Validate the repository's `.harness.yaml` against the canonical JSON schema shipped
by the `harness.dev` capability.

### Step 1: Locate inputs

1. Resolve the repo root:
   ```bash
   REPO_ROOT="$(git rev-parse --show-toplevel)"
   ```
   If `git rev-parse` fails, report "Not inside a git repository" and stop.

2. Resolve the schema path. The schema is shipped by the `harness.ci` capability
   (which `harness.dev` extends) and installed alongside this command:
   ```bash
   SCHEMA="$WSROOT/.claude/files/harness.schema.yaml"
   ```
   If `$SCHEMA` does not exist, fall back to the raw URL:
   `https://raw.githubusercontent.com/gwre-pdo/ai-dev/main/ns/harness/capabilities/ci/src/claude/files/harness.schema.yaml`

3. Confirm `.harness.yaml` exists at `$REPO_ROOT/.harness.yaml`. If missing, print:
   ```
   No .harness.yaml found at <REPO_ROOT>. Run /harness:setup to scaffold a starter.
   ```
   and stop with a non-zero exit code intent.

### Step 2: Run check-jsonschema

Invoke check-jsonschema via uvx. It supports YAML inputs directly via the
`--instance-type yaml` flag (which loads PyYAML on the fly):

```bash
uvx --quiet check-jsonschema --schemafile "$SCHEMA" "$REPO_ROOT/.harness.yaml"
```

`check-jsonschema` auto-detects YAML from the `.yaml` extension. Capture both stdout
and stderr. The tool prints validation errors with file path and JSON pointer
locations (e.g. `$.code-review.models.default`); pass them through verbatim so the
user sees line/path context.

### Step 3: Report

- On success (exit 0): print
  ```
  OK: .harness.yaml validates against the harness.dev schema.
  ```
- On failure: print the raw check-jsonschema output, then a one-line summary:
  ```
  FAIL: .harness.yaml has validation errors -- see above.
  ```
  Do not attempt to auto-fix.

Exit with check-jsonschema's exit code so callers can chain this command.
