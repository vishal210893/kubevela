# Architecture

**Analysis Date:** 2026-03-27

## Pattern Overview

**Overall:** Kubernetes Operator (controller-runtime based) implementing the OAM (Open Application Model) specification

**Key Characteristics:**
- Single binary (`vela-core`) running multiple controllers in one manager
- Declarative reconciliation of Application CRs through a multi-phase pipeline
- ResourceTracker pattern for cross-namespace resource ownership (instead of owner references)
- CUE-based templating engine for extensible definitions (components, traits, policies, workflow steps)
- Multi-cluster support via cluster-gateway
- Feature gate system for progressive feature rollout

## Core CRDs

**Application** (`core.oam.dev/v1beta1`):
- Primary user-facing CR
- Defined in: `apis/core.oam.dev/v1beta1/application_types.go`
- Contains: Components, Policies, Workflow
- Status tracks: phase, services health, workflow status, applied resources, revision

**ResourceTracker** (`core.oam.dev/v1beta1`):
- Cluster-scoped CR for tracking resources managed by an Application
- Defined in: `apis/core.oam.dev/v1beta1/resourcetracker_types.go`
- Types: `root` (lifecycle of app), `versioned` (per-generation), `component-revision`
- Stores `ManagedResource` entries with optional compressed data
- Supports gzip and zstd compression for large resource sets

**ComponentDefinition, TraitDefinition, PolicyDefinition, WorkflowStepDefinition** (`core.oam.dev/v1beta1`):
- Extensibility CRDs containing CUE templates
- Defined in: `apis/core.oam.dev/v1beta1/componentdefinition_types.go`, etc.
- Each has a corresponding DefinitionRevision for version pinning

**ApplicationRevision** (`core.oam.dev/v1beta1`):
- Snapshot of rendered application state per generation
- Defined in: `apis/core.oam.dev/v1beta1/applicationrevision_types.go`

**Policy** (`core.oam.dev/v1alpha1`):
- Policy type definitions for garbage collection, apply-once, shared-resource, etc.
- Defined in: `apis/core.oam.dev/v1alpha1/`

## Controllers

**Application Controller** (primary):
- Location: `pkg/controller/core.oam.dev/v1beta1/application/application_controller.go`
- Reconciles `Application` CRs through the full lifecycle
- Watches: `Application` (primary), `ResourceTracker` (delete-only trigger), `PolicyDefinition` (cache invalidation)
- Event filtering: ignores status-only updates, workflow step changes, managed field changes

**Definition Controllers:**
- ComponentDefinition: `pkg/controller/core.oam.dev/v1beta1/core/components/componentdefinition/componentdefinition_controller.go`
- TraitDefinition: `pkg/controller/core.oam.dev/v1beta1/core/traits/traitdefinition/traitdefinition_controller.go`
- PolicyDefinition: `pkg/controller/core.oam.dev/v1beta1/core/policies/policydefinition/policydefinition_controller.go`
- WorkflowStepDefinition: `pkg/controller/core.oam.dev/v1beta1/core/workflow/workflowstepdefinition/workflowstepdefinition_controller.go`
- All registered via: `pkg/controller/core.oam.dev/v1beta1/setup.go`

## Application Reconciliation Flow

The Application controller reconciles through these phases (defined in `apis/core.oam.dev/common/types.go`):

1. **Starting** - Fetch Application, check controller requirements, handle finalizers
2. **Policy Transforms** - Apply Application-scoped policy transforms (labels, annotations, spec modifications)
3. **Rendering** - Parse Application via `appfile.NewApplicationParser` then `GenerateAppFile()`
4. **Revision** - Prepare and apply ApplicationRevision via `handler.PrepareCurrentAppRevision()` / `FinalizeAndApplyAppRevision()`
5. **Policy Generation** - Apply policies via `handler.ApplyPolicies()`
6. **Workflow Execution** - Generate workflow steps via `handler.GenerateApplicationSteps()`, execute via `executor.ExecuteRunners()`
7. **Health Evaluation** - After workflow succeeds, evaluate component health via `evalStatus()`
8. **PostDispatch Traits** - Apply traits that depend on runtime state (feature-gated: `MultiStageComponentApply`)
9. **State Keep** - Re-apply managed resources to prevent configuration drift (disabled when `ApplyOnce` feature gate is on)
10. **Garbage Collection** - Clean up old ResourceTrackers, ApplicationRevisions, component revisions

**Phase transitions** (from `common.ApplicationPhase`):
`starting` -> `rendering` -> `generatingPolicy` -> `runningWorkflow` -> `running`/`unhealthy`/`workflowSuspending`/`workflowTerminated`/`workflowFailed`

## Key Abstractions

**AppHandler** (`pkg/controller/core.oam.dev/v1beta1/application/`):
- Orchestrates the reconciliation pipeline
- Holds current app revision, resource keeper, services status
- Files: `apply.go` (dispatch), `generator.go` (step generation), `revision.go` (revision management), `dispatcher.go` (resource dispatch), `application_policies.go` (policy application)

**Appfile / Parser** (`pkg/appfile/`):
- Parses Application spec into internal representation
- Resolves component/trait/policy definitions
- Renders CUE templates with user parameters
- Key files: `parser.go`, `appfile.go`, `template.go`

**ResourceKeeper** (`pkg/resourcekeeper/resourcekeeper.go`):
- Interface for dispatching, deleting, and garbage-collecting resources
- Methods: `Dispatch()`, `Delete()`, `GarbageCollect()`, `StateKeep()`, `ContainsResources()`
- Manages root, current, history, and component-revision ResourceTrackers
- Enforces policies: apply-once, garbage-collect, shared-resource, take-over, read-only, resource-update
- Key files: `dispatch.go`, `delete.go`, `gc.go`, `statekeep.go`, `cache.go`

**ResourceTracker utilities** (`pkg/resourcetracker/`):
- Helpers for creating and listing ResourceTrackers associated with an Application

**Workflow Engine** (`pkg/workflow/`):
- Generates workflow step runners from Application spec
- Providers supply step implementations: `providers/oam/`, `providers/multicluster/`, `providers/helm/`, `providers/terraform/`, `providers/config/`
- Uses external `github.com/kubevela/workflow` library for execution
- Key file: `workflow.go`, `step/`, `template/`

## ResourceTracker Pattern

Instead of using Kubernetes owner references (which don't work cross-namespace or cross-cluster), KubeVela uses the ResourceTracker pattern:

1. **Root RT** - Persists for the lifetime of the Application. Resources here survive upgrades.
2. **Versioned RT** - Created per Application generation. Old versioned RTs are garbage-collected.
3. **Component Revision RT** - Tracks ControllerRevision objects for components.

The Application controller watches ResourceTracker delete events (via `EnqueueRequestsFromMapFunc`) to trigger reconciliation when resources are externally deleted. RT labels (`app.oam.dev/name`, `app.oam.dev/namespace`) map back to the owning Application.

Finalizer `app.oam.dev/resource-tracker` on the Application ensures all ResourceTrackers and their managed resources are cleaned up before Application deletion completes.

## Multi-Cluster Architecture

- Initialization: `pkg/multicluster/cluster_management.go` via `multicluster.Initialize()`
- Uses cluster-gateway pattern for API server proxying to managed clusters
- Cluster info bootstrap: `multicluster.InitClusterInfo()` at startup
- Cluster metrics: optional collection via `ClusterMetricsMgr`
- Context-based cluster targeting: resources dispatched to specific clusters by setting cluster context
- Virtual cluster support: `pkg/multicluster/virtual_cluster.go`
- Helm chart templates: `charts/vela-core/templates/cluster-gateway/`

## Webhooks

**Location:** `pkg/webhook/core.oam.dev/`
**Registration:** `pkg/webhook/core.oam.dev/register.go` called from `cmd/core/app/server.go:prepareRun()`

**Application Webhooks:**
- Mutating: `pkg/webhook/core.oam.dev/v1beta1/application/mutating_handler.go`
- Validating: `pkg/webhook/core.oam.dev/v1beta1/application/validating_handler.go`
- Validation logic: `pkg/webhook/core.oam.dev/v1beta1/application/validation.go`
- Immutability checks: `pkg/webhook/core.oam.dev/v1beta1/application/immutable.go`

**Definition Webhooks:**
- ComponentDefinition: `pkg/webhook/core.oam.dev/v1beta1/componentdefinition/`
- TraitDefinition: `pkg/webhook/core.oam.dev/v1beta1/traitdefinition/`
- PolicyDefinition: `pkg/webhook/core.oam.dev/v1beta1/policydefinition/`
- WorkflowStepDefinition: `pkg/webhook/core.oam.dev/v1beta1/workflowstepdefinition/`

## Sharding Architecture

KubeVela supports horizontal scaling via controller sharding:

- **Master shard**: runs webhooks, scheduling, and all controllers
- **Worker shards**: run only the Application controller for assigned Applications
- Configuration: `cmd/core/app/server.go:prepareRunInShardingMode()`
- Shard assignment via labels/annotations on Application resources
- Feature gates: `DisableWebhookAutoSchedule`, `ValidateComponentWhenSharding`

## Feature Gates

Defined in `pkg/features/controller_features.go`. Key gates:

| Gate | Default | Purpose |
|------|---------|---------|
| `MultiStageComponentApply` | true | PostDispatch traits (batch dispatch by stage) |
| `ApplyOnce` | false | Disable state-keep, metadata-only ResourceTrackers |
| `PreDispatchDryRun` | true | Dry-run before resource dispatch |
| `EnableGlobalPolicies` | false | Auto-discover global PolicyDefinitions |
| `EnableApplicationScopedPolicies` | false | Application-scoped policy execution |
| `GzipResourceTracker` / `ZstdResourceTracker` | false | RT compression |
| `AuthenticateApplication` | false | Application authentication |
| `ValidateDefinitionPermissions` | false | RBAC validation for definitions |
| `EnableCueValidation` | false | Strict CUE parameter validation |

## Error Handling

**Strategy:** Condition-based status reporting with requeue

**Patterns:**
- Negative conditions set via `endWithNegativeCondition()` which patches status and returns error for requeue
- Condition types: `Parsed`, `Revision`, `Policy`, `Render`, `Workflow`, `Ready` (defined in `apis/core.oam.dev/common/types.go`)
- ResourceKeeper errors trigger GC retry with backoff (`baseGCBackoffWaitTime = 3s`)
- Workflow execution uses its own backoff mechanism via `workflowExecutor.GetBackoffWaitTime()`

## Cross-Cutting Concerns

**Logging:** `klog/v2` with structured logging via `klog.InfoS()`, `klog.ErrorS()`; trace context via `monitorContext`
**Metrics:** Prometheus metrics in `pkg/monitor/metrics/`; application reconcile histograms, workflow duration, GC timing
**Authentication:** `pkg/auth/` - impersonating round tripper for user identity propagation
**Validation:** CUE-based schema validation in webhooks + runtime validation during rendering
**Caching:** Custom cache builder in `pkg/cache/` for Application, ApplicationRevision, ResourceTracker; policy scope index for global policy lookup

## Entry Points

**Controller binary:**
- Location: `cmd/core/main.go` -> `cmd/core/app/server.go`
- `NewCoreCommand()` creates cobra command
- `run()` -> `syncConfigurations()` -> `setupMultiCluster()` -> `createControllerManager()` -> `setupControllers()` -> `manager.Start()`

**CLI plugin:**
- Location: `cmd/plugin/main.go`

**Pre-start hooks:**
- CRD validation: `cmd/core/app/hooks/crdvalidation/crd_validation_hook.go`
- Provider registry bootstrap: `cmd/core/app/bootstrap.go`

---

*Architecture analysis: 2026-03-27*
