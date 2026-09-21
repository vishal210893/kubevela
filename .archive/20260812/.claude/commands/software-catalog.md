---
description: Interactively generate or update software-catalog.yaml
model: sonnet
allowed-tools:
  - AskUserQuestion
  - Bash(git *)
  - Bash(gh *)
  - Bash(find *)
  - Bash(cat *)
  - Read
  - Write
  - mcp__github__search_code
  - mcp__github__get_file_contents
  - mcp__confluence__getConfluencePage
---

## Context

- Skill reference: !`ls $WSROOT/.claude/skills/software-catalog/references/field-documentation.md 2>/dev/null && echo FOUND || echo NOT_FOUND`
- Existing catalog: !`cat $WSROOT/software-catalog.yaml 2>/dev/null || echo NOT_FOUND`
- Git remote: !`git -C $WSROOT remote get-url origin 2>/dev/null || echo NOT_FOUND`

## Your task

Generate or update `software-catalog.yaml` at the root of this repository.
Read `$WSROOT/.claude/skills/software-catalog/references/field-documentation.md` for the complete field specification before proceeding.

---

### Step 1 -- Check for existing file

If `software-catalog.yaml` was found in Context above (not NOT_FOUND):
- Display the current content
- Ask the user (AskUserQuestion):
  - "Update it interactively" -- re-prompt all fields with current values as defaults
  - "Regenerate from scratch" -- start fresh
  - "Exit" -- stop here

---

### Step 2 -- Auto-detect fields from git

Parse the git remote URL from Context above.

Derive:
- `RepoUrl`: convert SSH remote to HTTPS form if needed
  - `git@github.com:gwre-pdo/myrepo.git` -> `https://github.com/gwre-pdo/myrepo`
  - HTTPS remotes: strip trailing `.git`
- `repo_name`: last path segment of the URL (e.g., `myrepo`)
- `org_name`: second-to-last segment (e.g., `gwre-pdo`)
- `ServiceName` suggestion: `repo_name` lowercased, keeping only alphanumeric characters (`^[a-zA-Z0-9]+$`)
- `ServiceId` suggestion: `AID-<repo_name>` (lowercase, hyphens preserved)
- `pod_hint`: leading word before first hyphen in `repo_name` (e.g., `sunnyvale-myrepo` -> `sunnyvale`). If no hyphen, use full `repo_name`.

---

### Step 3 -- Cross-repo discovery for ownership defaults

Search for existing `software-catalog.yaml` files from the same team. Build a `discovered` map of field -> most-frequent-value across all found files. Track which repo each value came from.

**Tier 1: Local sibling scan (always run)**
```bash
find "$(dirname $WSROOT)" -maxdepth 2 -name "software-catalog.yaml" \
  ! -path "$WSROOT/software-catalog.yaml" 2>/dev/null | head -20
```
Read each found file with the Read tool. Record field values.

**Tier 2: GitHub team membership search (run if GH_TOKEN available)**
```bash
gh api /user/teams --paginate 2>/dev/null
```
If successful, extract team slugs. For each slug, use `mcp__github__search_code` with query:
```
filename:software-catalog.yaml team:<org_name>/<slug>
```
Fetch up to 5 file contents per team using `mcp__github__get_file_contents`. Parse field values.

**Tier 3: Repo name hint fallback (if Tier 2 failed or returned 0 results)**
Use `mcp__github__search_code` with query:
```
filename:software-catalog.yaml <pod_hint> in:file org:<org_name>
```
Fetch up to 5 results. Parse field values.

**Tier 4: Broad org search (if total files found so far < 3)**
Use `mcp__github__search_code` with queries:
```
filename:software-catalog.yaml org:gwre-pdo
filename:software-catalog.yaml org:gwre-non-pdo
```
Fetch up to 5 files total. Parse field values.

**Aggregation**: For each field, pick the most frequently occurring value across all discovered files. Note the source repo name for each suggestion.

Skip any tier silently if the required tool or credential is unavailable.

---

### Step 4 -- Interactive field collection

Present fields in 4 grouped AskUserQuestion prompts. For each field that has a discovered suggestion, show it as the first (pre-selected) option with a label like `<value> (from <repo-name>)`. Always offer an "Other / enter manually" escape.

**Group 1 -- Service Identity**

Ask for:
- `ServiceId` -- format: `AID-<servicename>`, must be stable. Default: auto-detected suggestion.
- `ServiceName` -- alphanumeric only, no spaces/special chars, matches `^([a-zA-Z0-9]+)$`. Default: normalized repo name.
- `CheckmarxProjectName` -- use `_none_` only if no SkiShield scans planned; "None" or "NA" are invalid.
- `ServiceStatus` -- radio: [Active, Inactive]
- `Description` -- optional, brief description of what the service does

**Group 2 -- Ownership**

Ask for:
- `ApplicationOwner` -- typically team lead or L1. Show discovered suggestion with source.
- `PodOwner` -- lowercase, hyphens allowed, no "pod-" prefix, no spaces. Must match PODIQ entry. Show discovered suggestion.
- `BusinessOwner` -- typically VP (L3). Show discovered suggestion.
- `DepartmentCode` -- numeric code. Show discovered suggestion.
- `JiraProjectKey` -- e.g., GWCP, DE

**Group 3 -- CI and Classification**

Ask for:
- `CIUrl` -- TeamCity or GHA URL, or "None" if no CI
- `Type` -- e.g., Microservice, Library, Web App, Prototype, Test Scripts
- `ProductFamily` -- radio: [gwcp, lob-tooling, app-platform, digital-framework, insurance-now, data-platform, content-assembly, integrations, ads, others]
- `ReleaseCadence` -- radio: [continuously, bi-weekly, monthly, ski release]
- `AppInCloudOrSelfManaged` -- radio: [Cloud, SelfManaged]

**Group 4 -- Risk and Dependencies**

Ask for:
- `Exposure` -- radio: [internal, external]. External = customer-facing.
- `GwreApplicationsDependentOn` -- e.g., Nova, Jutro, Both, None. Show discovered suggestion.
- `BusinessRisk` -- radio: [Critical, High, Medium, Low]
- `SecurityRisk` -- radio: [Critical, High, Medium, Low]
- `EmergencyContact` -- PagerDuty URL. Show discovered suggestion with source.

**Group 5 -- Optional fields (skippable)**

Ask in a single prompt whether the user wants to fill optional fields, and if yes, collect:
- `ExternalBusinessName`, `GwreApplicationsProvidesIntegrationTo`, `SlackChannelName` (no leading #), `ContactEmail`, `ServiceLifecycleStatus` [Development, Production, Decommissioned], `ExcludeScanner` [IaC, SCA, SAST, ImageScan]

---

### Step 5 -- Write file

Generate the YAML content following the field order from the template (ServiceId first, ExcludeScanner last).

Rules:
- Use single quotes around any value containing spaces, slashes, or special characters
- Omit optional fields that were left blank
- Do not add comments unless the user included them

Write to `$WSROOT/software-catalog.yaml` using the Write tool.

Display the final file content to the user.

---

### Step 6 -- Offer commit

Ask the user (AskUserQuestion):
- "Commit now" -- run: `git -C $WSROOT add software-catalog.yaml && git -C $WSROOT commit -m "Add software-catalog.yaml for ISC compliance"`
- "Stage only" -- run: `git -C $WSROOT add software-catalog.yaml`
- "Skip" -- leave the file unstaged

Report the result.
