# Codebase Structure

**Analysis Date:** 2026-03-27

## Directory Layout

```
kubevela/
├── apis/                    # CRD type definitions (API types)
├── bin/                     # Compiled binaries (gitignored)
├── charts/                  # Helm chart for deploying KubeVela
├── cmd/                     # Binary entry points
├── config/                  # Kustomize CRD manifests
├── design/                  # Design documents
├── docs/                    # Documentation and examples
├── e2e/                     # CLI-focused E2E tests (legacy)
├── hack/                    # Build and development scripts
├── makefiles/               # Makefile includes
├── pkg/                     # Core library code
├── references/              # CLI references and SDK generation
├── test/                    # E2E and integration tests
├── vela-templates/          # CUE definition templates
├── version/                 # Version information
├── Dockerfile               # Controller container image
├── Dockerfile.cli           # CLI container image
├── Makefile                 # Build system entry point
├── go.mod                   # Go module definition
└── .golangci.yml            # Linter configuration
```

## Directory Purposes

**`apis/`** - Kubernetes API type definitions:
- `apis/core.oam.dev/v1beta1/` - Primary API version (Application, ResourceTracker, ComponentDefinition, etc.)
- `apis/core.oam.dev/v1alpha1/` - Alpha API types (policy specs: ApplyOnce, GarbageCollect, SharedResource, etc.)
- `apis/core.oam.dev/common/` - Shared types (ApplicationComponent, AppStatus, ApplicationPhase, etc.)
- `apis/core.oam.dev/condition/` - Condition types for status reporting
- `apis/types/` - Constants and type aliases (cluster names, event reasons, etc.)

**`cmd/`** - Binary entry points:
- `cmd/core/main.go` - Controller manager entry point
- `cmd/core/app/server.go` - Server setup, manager creation, controller registration
- `cmd/core/app/bootstrap.go` - Provider registry initialization
- `cmd/core/app/config/` - Configuration structs for all subsystems (webhook, kubernetes, multicluster, etc.)
- `cmd/core/app/options/` - CLI flag parsing and CoreOptions struct
- `cmd/core/app/hooks/` - Pre-start validation hooks
- `cmd/plugin/main.go` - CLI plugin entry point

**`pkg/`** - Core library (see detailed breakdown below)

**`charts/vela-core/`** - Helm chart:
- `Chart.yaml` - Chart metadata
- `values.yaml` - Default configuration values
- `crds/` - CRD YAML manifests (13 CRDs)
- `templates/kubevela-controller.yaml` - Controller deployment
- `templates/_helpers.tpl` - Template helpers
- `templates/defwithtemplate/` - Built-in definition templates (webservice, worker, task, helmchart, traits, etc.)
- `templates/admission-webhooks/` - Webhook configuration (mutating, validating, cert management)
- `templates/cluster-gateway/` - Multi-cluster gateway resources
- `templates/velaql/` - VelaQL query templates

**`config/`** - Kustomize resources:
- `config/crd/` - CRD base manifests for kustomize

**`test/`** - Test suites:
- `test/e2e-test/` - Primary E2E tests (Ginkgo)
- `test/e2e-multicluster-test/` - Multi-cluster E2E tests
- `test/e2e-addon-test/` - Addon E2E tests
- `test/mock/` - Mock servers (e.g., Nacos)

**`vela-templates/`** - CUE templates:
- `vela-templates/definitions/` - Built-in component, trait, workflow step definitions
- `vela-templates/registry/` - Registry templates

**`hack/`** - Development utilities:
- `hack/e2e/` - E2E test helper scripts
- `hack/crd/` - CRD generation utilities
- `hack/docgen/` - Documentation generation
- `hack/cuegen/` - CUE code generation
- `hack/sdk/` - SDK generation

## Key Packages in `pkg/`

**`pkg/controller/`** - Controller implementations:
- `pkg/controller/core.oam.dev/v1beta1/application/` - **Application controller** (main reconciler)
  - `application_controller.go` - Reconciler, Setup, event filters, finalizer handling
  - `apply.go` - Resource dispatch logic
  - `generator.go` - Workflow step generation
  - `revision.go` - ApplicationRevision management
  - `dispatcher.go` - Resource dispatch implementation
  - `workflow.go` - Workflow restart handling
  - `application_policies.go` - Application-scoped policy transforms
  - `application_policy_cache.go` - Policy rendering cache
  - `policy_scope_index.go` - In-memory index of PolicyDefinitions by scope
  - `policy_validation.go` - Policy validation logic
  - `policy_dryrun.go` - Policy dry-run support
  - `assemble/` - Resource assembly from CUE output
  - `suite_test.go` - Test suite setup with envtest
- `pkg/controller/core.oam.dev/v1beta1/core/` - Definition controllers
  - `components/componentdefinition/` - ComponentDefinition controller
  - `traits/traitdefinition/` - TraitDefinition controller
  - `policies/policydefinition/` - PolicyDefinition controller
  - `workflow/workflowstepdefinition/` - WorkflowStepDefinition controller
  - `revison.go` - Shared DefinitionRevision logic
  - `requirement.go` - Controller version requirement logic
- `pkg/controller/core.oam.dev/v1beta1/setup.go` - Registers all controllers
- `pkg/controller/common/` - Shared controller config (re-sync period, log levels)
- `pkg/controller/utils/` - Controller utility functions

**`pkg/resourcekeeper/`** - Resource lifecycle management:
- `resourcekeeper.go` - Interface definition and constructor
- `dispatch.go` - Resource dispatch to clusters
- `delete.go` - Resource deletion
- `gc.go` - Garbage collection logic
- `gc_rev.go` - ApplicationRevision garbage collection
- `statekeep.go` - Configuration drift prevention
- `cache.go` - Resource cache
- `admission.go` - Admission control for resource ownership
- `componentrevision.go` - Component revision management
- `options.go` - GC options (disable flags, limits)

**`pkg/resourcetracker/`** - ResourceTracker CRUD utilities

**`pkg/appfile/`** - Application parsing and CUE rendering:
- `parser.go` - Application parser (resolves definitions, renders CUE)
- `appfile.go` - Appfile struct (parsed application representation)
- `template.go` - Template resolution
- `helm/` - Helm chart rendering
- `dryrun/` - Dry-run support
- `validate.go` - Application validation

**`pkg/workflow/`** - Workflow engine:
- `workflow.go` - Workflow status conversion, helpers
- `step/` - Workflow step implementation
- `template/` - Workflow step template rendering
- `operation/` - Workflow operations (restart, suspend, resume)
- `providers/` - Step implementation providers:
  - `oam/` - OAM resource operations (apply-component, read-object, etc.)
  - `multicluster/` - Multi-cluster operations
  - `helm/` - Helm operations
  - `terraform/` - Terraform operations
  - `config/` - Configuration operations
  - `legacy/` - Legacy provider compatibility
  - `types/` - Provider type definitions

**`pkg/webhook/`** - Admission webhooks:
- `core.oam.dev/register.go` - Webhook registration
- `core.oam.dev/v1beta1/application/` - Application mutating + validating webhooks
- `core.oam.dev/v1beta1/componentdefinition/` - ComponentDefinition webhooks
- `core.oam.dev/v1beta1/traitdefinition/` - TraitDefinition webhooks
- `core.oam.dev/v1beta1/policydefinition/` - PolicyDefinition webhooks
- `core.oam.dev/v1beta1/workflowstepdefinition/` - WorkflowStepDefinition webhooks
- `utils/` - Shared webhook utilities

**`pkg/multicluster/`** - Multi-cluster support:
- `cluster_management.go` - Cluster client initialization
- `cluster_metrics_management.go` - Cluster metrics collection
- `virtual_cluster.go` - Virtual cluster support
- `utils.go` - Multi-cluster utilities
- `errors.go` - Multi-cluster error types

**`pkg/oam/`** - OAM constants and utilities:
- `labels.go` - Label/annotation constants (`app.oam.dev/*`)
- `types.go` - OAM type definitions
- `var.go` - Global variables (SystemDefinitionNamespace)
- `util/` - OAM utility functions

**`pkg/cue/`** - CUE language integration
**`pkg/definition/`** - Definition resolution and management
**`pkg/policy/`** - Policy implementation helpers
**`pkg/features/`** - Feature gate definitions (`controller_features.go`)
**`pkg/monitor/`** - Metrics and monitoring (`metrics/`, `watcher/`)
**`pkg/auth/`** - Authentication and impersonation
**`pkg/cache/`** - Custom informer cache configuration
**`pkg/addon/`** - Addon management
**`pkg/registry/`** - Provider registry for dependency injection
**`pkg/velaql/`** - VelaQL query language
**`pkg/builtin/`** - Built-in operations
**`pkg/config/`** - Configuration management
**`pkg/schema/`** - Schema utilities
**`pkg/rollout/`** - Rollout support
**`pkg/utils/`** - General utilities (`apply/`, `common/`, `errors/`)
**`pkg/generated/`** - Generated client code
**`pkg/logging/`** - Logging utilities (color writer)
**`pkg/component/`** - Component utilities

## Key File Locations

**Entry Points:**
- `cmd/core/main.go`: Controller manager binary
- `cmd/core/app/server.go`: Server initialization and startup
- `cmd/plugin/main.go`: CLI plugin binary

**Configuration:**
- `cmd/core/app/options/options.go`: All CLI flags and CoreOptions
- `cmd/core/app/config/`: Individual config structs per subsystem
- `pkg/features/controller_features.go`: Feature gate definitions
- `charts/vela-core/values.yaml`: Helm chart defaults

**Core Logic:**
- `pkg/controller/core.oam.dev/v1beta1/application/application_controller.go`: Main reconciler
- `pkg/resourcekeeper/resourcekeeper.go`: Resource lifecycle interface
- `pkg/appfile/parser.go`: Application parsing
- `pkg/workflow/workflow.go`: Workflow engine integration

**API Types:**
- `apis/core.oam.dev/v1beta1/application_types.go`: Application CR
- `apis/core.oam.dev/v1beta1/resourcetracker_types.go`: ResourceTracker CR
- `apis/core.oam.dev/common/types.go`: Shared types (AppStatus, phases, conditions)

**Testing:**
- `test/e2e-test/suite_test.go`: E2E test suite setup
- `test/e2e-test/application_test.go`: Application E2E tests
- `pkg/controller/core.oam.dev/v1beta1/application/suite_test.go`: Integration test suite

## Naming Conventions

**Files:**
- Snake case: `application_controller.go`, `resource_tracker_types.go`
- Test files: `*_test.go` co-located with source
- Suite files: `suite_test.go` for Ginkgo test suites

**Directories:**
- API group mirroring: `core.oam.dev/v1beta1/` mirrors the API group structure
- Lowercase with hyphens for chart templates: `defwithtemplate/`, `admission-webhooks/`

**Go Packages:**
- Match directory name: `package application`, `package resourcekeeper`
- Version in path: `v1beta1`, `v1alpha1`

## Where to Add New Code

**New Controller:**
- Implementation: `pkg/controller/core.oam.dev/v1beta1/core/<category>/<name>/`
- Register in: `pkg/controller/core.oam.dev/v1beta1/setup.go`
- Tests: co-located `*_test.go` files with `suite_test.go`

**New API Type:**
- Types: `apis/core.oam.dev/<version>/<type>_types.go`
- Run: `make generate && make manifests` after changes
- CRD YAML: auto-generated to `charts/vela-core/crds/`

**New Workflow Provider:**
- Implementation: `pkg/workflow/providers/<provider_name>/`
- Register in: `pkg/workflow/providers/compiler.go`

**New Feature Gate:**
- Definition: `pkg/features/controller_features.go`
- Add to `defaultFeatureGates` map

**New Webhook:**
- Handler: `pkg/webhook/core.oam.dev/v1beta1/<resource>/`
- Register in: `pkg/webhook/core.oam.dev/register.go`
- Chart template: `charts/vela-core/templates/admission-webhooks/`

**New Built-in Definition:**
- CUE template: `vela-templates/definitions/`
- Chart template: `charts/vela-core/templates/defwithtemplate/<name>.yaml`

**New Policy Type:**
- Spec: `apis/core.oam.dev/v1alpha1/<policy>_policy_types.go`
- ResourceKeeper integration: `pkg/resourcekeeper/`

**New E2E Test:**
- Test file: `test/e2e-test/<feature>_test.go`
- Test data: `test/e2e-test/testdata/`
- Follow Ginkgo `Describe/It/By` patterns from existing tests

**Utility Functions:**
- General utilities: `pkg/utils/`
- OAM-specific: `pkg/oam/util/`
- Apply utilities: `pkg/utils/apply/`

## Special Directories

**`charts/vela-core/crds/`:**
- Purpose: CRD YAML manifests deployed via Helm
- Generated: Yes (from API types via controller-gen)
- Committed: Yes

**`pkg/generated/`:**
- Purpose: Generated Kubernetes client code
- Generated: Yes (via code-generator)
- Committed: Yes

**`bin/`:**
- Purpose: Compiled binaries
- Generated: Yes (via `go build`)
- Committed: No (gitignored)

**`vela-templates/definitions/`:**
- Purpose: Built-in CUE definition templates
- Generated: No (hand-written CUE)
- Committed: Yes

**`.planning/`:**
- Purpose: Project planning documents
- Generated: By analysis tools
- Committed: Yes

---

*Structure analysis: 2026-03-27*
