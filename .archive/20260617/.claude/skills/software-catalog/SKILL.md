---
name: software-catalog
description: Generate or update software-catalog.yaml for a Guidewire repository.
  This skill should be used when the user asks to create a software-catalog.yaml,
  asks about ISC catalog compliance, wants to add catalog metadata to a repo, or
  asks what fields are required for the software catalog.
---

# Software Catalog Generator

Generates a compliant `software-catalog.yaml` at the repository root, required by
Guidewire ISC for all repos regardless of whether they run security scans.

Full field specification is in `references/field-documentation.md`.
The sample template is in `assets/software-catalog.template.yaml`.

## Workflow

### 1. Check for existing file

```bash
cat $WSROOT/software-catalog.yaml 2>/dev/null || echo NOT_FOUND
```

If found, show contents and ask whether to update or regenerate.

### 2. Auto-detect from git

```bash
git -C $WSROOT remote get-url origin 2>/dev/null
```

Derive:
- `RepoUrl` -- HTTPS form of origin (convert SSH if needed, strip `.git`)
- `ServiceName` suggestion -- repo name, alphanumeric only (`^[a-zA-Z0-9]+$`)
- `ServiceId` suggestion -- `AID-<repo-name>`
- `pod_hint` -- leading word before first hyphen in repo name

### 3. Cross-repo discovery (tiered)

Build a `discovered` map of field -> most-frequent-value by searching for existing
`software-catalog.yaml` files from the same team. Use these as pre-populated defaults
in prompts, labelled with the source repo.

Tier 1 -- Local siblings:
```bash
find "$(dirname $WSROOT)" -maxdepth 2 -name "software-catalog.yaml" \
  ! -path "$WSROOT/software-catalog.yaml" 2>/dev/null | head -20
```

Tier 2 -- GitHub team membership (if GH_TOKEN available):
```bash
gh api /user/teams --paginate
```
Search: `filename:software-catalog.yaml team:<org>/<slug>` via mcp__github__search_code

Tier 3 -- Repo name hint fallback (if Tier 2 failed):
Search: `filename:software-catalog.yaml <pod_hint> in:file org:<org>`

Tier 4 -- Broad org search (if < 3 files found total):
Search: `filename:software-catalog.yaml org:gwre-pdo` and `org:gwre-non-pdo`

Skip tiers silently if tools/credentials are unavailable.

### 4. Interactive collection

Collect all required fields in 5 AskUserQuestion groups. Show discovered suggestions
as pre-selected options labeled with their source repo. See `references/field-documentation.md`
for full field specs, enum values, and constraints.

Groups:
1. Service Identity: ServiceId, ServiceName, CheckmarxProjectName, ServiceStatus, Description
2. Ownership: ApplicationOwner, PodOwner, BusinessOwner, DepartmentCode, JiraProjectKey
3. CI and Classification: CIUrl, Type, ProductFamily, ReleaseCadence, AppInCloudOrSelfManaged
4. Risk and Dependencies: Exposure, GwreApplicationsDependentOn, BusinessRisk, SecurityRisk, EmergencyContact
5. Optional fields: ExternalBusinessName, GwreApplicationsProvidesIntegrationTo, SlackChannelName, ContactEmail, ServiceLifecycleStatus, ExcludeScanner

### 5. Write and commit

Write to `$WSROOT/software-catalog.yaml`. Single-quote values with spaces or special
characters. Follow field order from `assets/software-catalog.template.yaml`.

Offer to commit:
```bash
git -C $WSROOT add software-catalog.yaml
git -C $WSROOT commit -m "Add software-catalog.yaml for ISC compliance"
```

## Keeping the spec current

When the ISC spec changes, run `/software-catalog:refresh-spec` to re-fetch the
Confluence page and update `references/field-documentation.md`. Requires Confluence
MCP authenticated.
