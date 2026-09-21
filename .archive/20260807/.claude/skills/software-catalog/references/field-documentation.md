# software-catalog.yaml Field Documentation

Source: https://guidewireconfluence.atlassian.net/wiki/spaces/ISC/pages/1319796886/
Last refreshed: 2026-03-26

This file is the authoritative local reference for software-catalog.yaml fields.
Run `/software-catalog:refresh-spec` to update it from Confluence.

---

## Required Fields

All 20 fields below must be present in every software-catalog.yaml.

### ServiceId

Unique identifier for the service.

- Format: `AID-<servicename>` (e.g., `AID-PL-e2epolnodbdar1`)
- Treated as a stable key in Brinqa -- do not change after initial commit even if the project is renamed
- Must stay stable across renames

### CheckmarxProjectName

Project name used for SkiShield/Checkmarx scans.

- Required for SkiShield scans on Nova and non-Nova projects
- Use a valid service or relevant name -- values like `None` or `NA` are invalid
- Use `_none_` (exactly) only if you do not plan to run SkiShield scans
- WARNING: SkiShield will fail without a valid CheckmarxProjectName

### ServiceName

Name of the application or service.

- Must match pattern: `^([a-zA-Z0-9]+)$`
- Alphanumeric only -- no spaces, hyphens, underscores, or special characters
- Used for Polaris Catalog registration

### ServiceStatus

Current operational status of the application.

- Supported values: `Active`, `Inactive`
- Use `Inactive` if the app is decommissioned; otherwise use `Active`

### RepoUrl

HTTP/HTTPS URL of the repository.

- Example: `https://github.com/gwre-pdo/my-service.git`
- Must be the HTTPS form (not SSH)

### JiraProjectKey

Jira project key for this service.

- Examples: `GWCP`, `DE`, `ISC`

### CIUrl

TeamCity, GitHub Actions, or other CI URL.

- Use `None` if the project has no CI pipeline

### DepartmentCode

Numeric department code for your team.

- Example: `275`

### ApplicationOwner

Owner of this service -- typically the team lead or L1 for the pod.

- Example: `Sunnyvale`

### PodOwner

Name of the pod that owns this application.

- Must be lowercase
- Hyphens allowed (e.g., `sunnyvale`, `cloud-platform`)
- Do NOT include `pod-` prefix
- Do NOT include spaces
- Must match the pod entry in PODIQ (https://podiq.int.ccs.guidewire.net/) and the POD Directory

### BusinessOwner

Business owner -- typically the VP (L3) of the pod.

- Example: `Anoop Gopalakrishnan`
- Use single quotes if the name contains spaces: `'Anoop Gopalakrishnan'`

### Type

Type of application.

- Examples: `Microservice`, `Web App`, `Prototype`, `Library`, `Test Scripts`
- Free-form field

### ProductFamily

Product family this service belongs to.

- Supported values: `gwcp`, `lob-tooling`, `app-platform`, `digital-framework`, `insurance-now`, `data-platform`, `content-assembly`, `integrations`, `ads`, `others`

### ReleaseCadence

How often this service is released.

- Supported values: `continuously`, `bi-weekly`, `monthly`, `ski release`
- Use `continuously` for projects released as needed

### AppInCloudOrSelfManaged

Deployment model.

- Supported values: `Cloud`, `SelfManaged`

### Exposure

Whether the service is customer-facing.

- Supported values: `internal`, `external`
- `external` = customer-facing
- `internal` = not customer-facing
- Determines whether a service can be taken down without affecting customers

### GwreApplicationsDependentOn

Runtime services this application depends on.

- Examples: `Nova`, `Jutro`, `Both`, `None`
- Free-form but should reflect actual runtime dependencies

### BusinessRisk

Business risk level.

- Supported values: `Critical`, `High`, `Medium`, `Low`

### SecurityRisk

Security risk level.

- Supported values: `Critical`, `High`, `Medium`, `Low`

### EmergencyContact

Emergency contact information.

- Provide as a PagerDuty service directory link
- Example: `'https://guidewire.pagerduty.com/service-directory/PEH3JO1'`
- Use single quotes (value contains slashes and special characters)

---

## Optional Fields

These fields may be omitted. Include them when applicable.

### Description

Brief description of what the service does.

- Example: `'Payment processing microservice for cloud billing.'`

### ExternalBusinessName

Customer-facing name for the service, if different from ServiceName.

### GwreApplicationsProvidesIntegrationTo

Other Guidewire services that consume this service's APIs.

- Examples: `Nova`, `Jutro`, `Both`, `None`
- Leave blank if no integrations

### SlackChannelName

Slack channel for support or notifications.

- Do NOT start with `#`
- Example: `nova-community`
- Used by SkiShield to send scan notifications

### ContactEmail

Team distribution list or contact email.

- Example: `'dl-owning-team@guidewire.com'`

### ServiceLifecycleStatus

Lifecycle stage of the service.

- Supported values: `Development`, `Production`, `Decommissioned`
- Use `Decommissioned` only if the app is decommissioned in both production and non-production environments

### ExcludeScanner

Scanner types to exclude from this repo.

- Supported values: `IaC`, `SCA`, `SAST`, `ImageScan`
- Can specify a single value; check Confluence for multi-value syntax

---

## Formatting Rules

- Use single quotes around any value containing spaces, slashes, or special characters
  - Example: `BusinessOwner: 'Anoop Gopalakrishnan'`
  - Example: `EmergencyContact: 'https://guidewire.pagerduty.com/service-directory/PEH3JO1'`
- Do not use `None` or `NA` for CheckmarxProjectName -- use `_none_` if no scans planned
- ServiceName must be alphanumeric only (no hyphens, no underscores)
- PodOwner must be lowercase with no "pod-" prefix and no spaces

---

## Field Order (canonical)

Follow this order in the generated file:

1. ServiceId
2. CheckmarxProjectName
3. ServiceName
4. Description (optional)
5. ServiceStatus
6. ExternalBusinessName (optional)
7. RepoUrl
8. JiraProjectKey
9. CIUrl
10. DepartmentCode
11. ApplicationOwner
12. PodOwner
13. BusinessOwner
14. Type
15. ProductFamily
16. ReleaseCadence
17. AppInCloudOrSelfManaged
18. Exposure
19. GwreApplicationsDependentOn
20. GwreApplicationsProvidesIntegrationTo (optional)
21. BusinessRisk
22. SecurityRisk
23. EmergencyContact
24. SlackChannelName (optional)
25. ContactEmail (optional)
26. ServiceLifecycleStatus (optional)
27. ExcludeScanner (optional)
