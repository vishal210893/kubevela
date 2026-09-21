---
description: Interactive wizard for the ai-harness pipeline. Configures GitHub labels (risk:*, review:*) and scaffolds a starter .harness.yaml.
allowed-tools:
  - AskUserQuestion
  - Bash
  - Read
  - Write
---

## Your task

Interactive setup wizard for a repository adopting the ai-harness pipeline. The wizard
has two independent modes; the user can run either or both in a single session.

The wizard MUST be interactive. Do NOT infer answers from defaults. Do NOT pick
"Recommended" on the user's behalf. Always call AskUserQuestion and wait.

### Step 1: Ask what to configure

Call AskUserQuestion to ask the user what they want to do.

**Question 1:**
- question: "What do you want to configure?"
- header: "Harness Setup"
- multiSelect: true
- options:
  1. **Labels** - Create the six risk:* and review:* labels in this repo via `gh label create --force`.
  2. **Scaffold .harness.yaml** - Drop a starter .harness.yaml at the repo root with the assess-risk / code-review / reviewer-brief sections.

STOP. Wait for the answer before proceeding.

### Step 2: Labels mode

If "Labels" was selected, create (or update) these six labels in the current repo by
running each command below. Use `--force` so the command succeeds even when the label
already exists.

```bash
gh label create "risk:critical"          --color b60205 --description "Risk tier: critical"            --force
gh label create "risk:high"              --color d93f0b --description "Risk tier: high"                --force
gh label create "risk:medium"            --color fbca04 --description "Risk tier: medium"              --force
gh label create "risk:low"               --color 0e8a16 --description "Risk tier: low"                 --force
gh label create "review:request-changes" --color b60205 --description "Code review: changes requested" --force
gh label create "review:approved"        --color 0e8a16 --description "Code review: approved"          --force
```

Report the result of each call on its own line. If `gh` is not authenticated or the
user is not in a repo with a remote, surface that error and stop the labels step.

### Step 3: Scaffold mode

If "Scaffold .harness.yaml" was selected:

1. Check whether `.harness.yaml` already exists in the repo root.

2. If it exists, call AskUserQuestion:
   - question: "A .harness.yaml already exists at the repo root. Overwrite?"
   - header: "Overwrite?"
   - options:
     1. **No** - Keep the existing file (recommended).
     2. **Yes** - Overwrite with the starter template.

   STOP. Wait for the answer. If the user picks **No**, skip to Step 4.

3. Copy the canonical starter template to `.harness.yaml` at the repo root.
   The template is shipped by `harness.ci` (which `harness.dev` extends), so it
   lives at `$WSROOT/.claude/files/harness.starter.yaml` whenever harness.dev is
   installed. This is the SINGLE source of truth -- the template was previously
   inlined here, but that caused drift against the schema. Do NOT re-inline it.

   Prefer the locally installed file; fall back to the canonical raw GitHub URL
   if the local file is missing (e.g. older install layout). Run exactly one of
   these via the Bash tool:

   ```bash
   # Resolve WSROOT (the workspace root that holds .claude/). If WSROOT is unset,
   # fall back to $HOME -- profile install lands .claude/ under the user's home.
   STARTER_LOCAL="${WSROOT:-$HOME}/.claude/files/harness.starter.yaml"
   STARTER_URL="https://raw.githubusercontent.com/gwre-pdo/ai-dev/main/ns/harness/capabilities/ci/src/claude/files/harness.starter.yaml"

   if [ -f "$STARTER_LOCAL" ]; then
       cp "$STARTER_LOCAL" .harness.yaml
       echo "Copied starter from $STARTER_LOCAL"
   else
       curl -fsSL "$STARTER_URL" -o .harness.yaml
       echo "Downloaded starter from $STARTER_URL"
   fi
   ```

   The starter pins the `yaml-language-server` schema reference on line 1 and
   uses the canonical `assess-risk.categories.<tier>` shape. Do NOT edit the
   starter from inside this command -- change the canonical file at
   `ns/harness/capabilities/ci/src/claude/files/harness.starter.yaml` and
   rebuild + install instead.

4. After writing, print:
   ```
   Wrote .harness.yaml -- run /harness:validate to verify it parses against the schema.
   ```

### Step 4: Summary

Print a short summary of what was done (which modes ran, label results, whether the
scaffold was written/skipped/overwritten). Do not run /harness:validate automatically;
suggest it.
