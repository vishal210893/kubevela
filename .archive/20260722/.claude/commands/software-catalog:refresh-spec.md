---
description: Re-fetch software-catalog.yaml field spec from Confluence and update local reference
model: sonnet
context: fork
allowed-tools:
  - Read
  - Write
  - mcp__confluence__getConfluencePage
---
## Context

- Current reference: !`cat $WSROOT/.claude/skills/software-catalog/references/field-documentation.md 2>/dev/null || echo NOT_FOUND`

## Your task

Refresh the embedded field specification for the software-catalog capability by fetching
the latest documentation from Confluence.

---

### Step 1 -- Fetch the latest spec from Confluence

Use `mcp__confluence__getConfluencePage` with:
- `cloudId`: `guidewireconfluence.atlassian.net`
- `pageId`: `1319796886`
- `contentFormat`: `markdown`

If the tool is unavailable or returns an error:
- Inform the user that the Confluence MCP must be authenticated
- Instruct them to run `/mcp` in Claude Code and authenticate the Confluence server
- Stop here

---

### Step 2 -- Parse the fetched content

Extract from the Confluence page:

1. **Required fields** -- list all field names under the "Required Information" or "Required fields" section
2. **Optional fields** -- list all field names under the "Optional Information" or "Optional fields" section
3. **Field details** -- for each field:
   - Description / purpose
   - Format constraints (e.g., alphanumeric only, lowercase, specific pattern)
   - Supported enum values if listed (e.g., [Active, Inactive])
   - Special cases or warnings (e.g., SkiShield fails without valid CheckmarxProjectName)
4. **Sample template** -- the full YAML block from the "Sample Template" section

---

### Step 3 -- Compare with current reference

Read the current `$WSROOT/.claude/skills/software-catalog/references/field-documentation.md`
(shown in Context above, may be NOT_FOUND on first run).

Identify:
- New fields added since last fetch
- Fields removed
- Enum values changed (added or removed options)
- Description or constraint changes

---

### Step 4 -- Write updated reference

Overwrite `$WSROOT/.claude/skills/software-catalog/references/field-documentation.md`
with freshly structured content (see field-documentation.md format described in the skill).

Also update `$WSROOT/.claude/skills/software-catalog/assets/software-catalog.template.yaml`
with the latest sample template from the page.

---

### Step 5 -- Report changes

Display a summary:
- If first-time fetch: "Spec initialized from Confluence (page last updated: <date>)"
- Otherwise, list each change:
  - "New field: <FieldName> -- <description>"
  - "Removed field: <FieldName>"
  - "Changed enum for <FieldName>: added [<values>], removed [<values>]"
  - "No changes detected" if identical

Remind the user that the updated spec will take effect on the next `/software-catalog` run.
