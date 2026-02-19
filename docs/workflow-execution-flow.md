# KubeVela: Application Workflow Execution Flow

## Overview

This document describes the internal execution flow in KubeVela when an `Application` CR is created or updated. It explains how **components**, **traits**, and **policies** are parsed, and how the **workflow engine** then drives the actual deployment of resources to Kubernetes clusters.

---

## High-Level Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        Application CR (kubectl apply)                           │
│                                                                                 │
│  spec:                                                                          │
│    components:                                                                  │
│      - name: my-app                                                             │
│        type: webservice          ← ComponentDefinition                          │
│        properties: { image: ... }                                               │
│        traits:                                                                  │
│          - type: scaler          ← TraitDefinition                              │
│    policies:                                                                    │
│      - name: staging             ← PolicyDefinition                             │
│        type: topology                                                           │
│    workflow:                     ← WorkflowStepDefinition                       │
│      steps:                                                                     │
│        - name: deploy            ← explicit OR auto-generated                   │
│          type: deploy                                                           │
└────────────────────────────┬────────────────────────────────────────────────────┘
                             │ triggers watch event
                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│            Application Controller  (Reconciler.Reconcile)                       │
│            pkg/controller/core.oam.dev/v1beta1/application/                     │
│            application_controller.go:106                                        │
└──────┬───────────────────────────────────────────────────────────────────────── ┘
       │
       │  Step 1: Parse
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      AppFile Generation (parser.go:87)                          │
│                                                                                 │
│   GenerateAppFile()                                                             │
│   ├── parseComponents()   → loads ComponentDefinition CUE templates            │
│   │      for each component:                                                    │
│   │        makeComponent() → LoadTemplate() → resolve TraitDefinitions          │
│   │                                                                             │
│   ├── parseWorkflowSteps() → loads WorkflowStepDefinition templates            │
│   │      loadWorkflowToAppfile()                                                │
│   │        if no workflow defined → auto-generate apply-component steps         │
│   │                                                                             │
│   └── parsePolicies()    → loads PolicyDefinition templates                    │
│          resolve external policy references                                     │
│          distinguish internal vs external policies                              │
│                                                                                 │
│   Result: Appfile {                                                             │
│     ParsedComponents, ParsedPolicies, WorkflowSteps,                           │
│     RelatedComponentDefinitions, RelatedTraitDefinitions,                       │
│     RelatedWorkflowStepDefinitions, RelatedPolicyDefinitions                   │
│   }                                                                             │
└──────┬──────────────────────────────────────────────────────────────────────────┘
       │
       │  Step 2: Revision
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│              ApplicationRevision (revision.go:85)                               │
│                                                                                 │
│   PrepareCurrentAppRevision()                                                   │
│   ├── gatherRevisionSpec()  → snapshot all definitions into revision            │
│   ├── compute hash          → deduplicate revisions                             │
│   └── FinalizeAndApplyAppRevision() → create/update ApplicationRevision CR     │
│                                                                                 │
│   ApplicationRevision CR stored in Kubernetes etcd for auditing & rollback     │
└──────┬──────────────────────────────────────────────────────────────────────────┘
       │
       │  Step 3: Apply Policies
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        Policy Application (apply.go:461)                        │
│                                                                                 │
│   ApplyPolicies()                                                               │
│   ├── GeneratePolicyManifests()  → render policy CUE templates                 │
│   └── Dispatch() → ResourceKeeper → kubectl apply                              │
│                                                                                 │
│   Policy types (examples):                                                      │
│   ┌─────────────────┬──────────────────────────────────────────────────────┐   │
│   │ topology        │ target cluster(s) / namespace(s) for deployment       │   │
│   │ override        │ patch component properties per environment            │   │
│   │ replication     │ create replicated components with different keys      │   │
│   │ apply-once      │ skip re-apply if resource already exists              │   │
│   │ garbage-collect │ how to clean up removed resources                     │   │
│   └─────────────────┴──────────────────────────────────────────────────────┘   │
└──────┬──────────────────────────────────────────────────────────────────────────┘
       │
       │  Step 4: Build Workflow
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│              GenerateApplicationSteps (generator.go:70)                         │
│                                                                                 │
│   1. generateWorkflowInstance()                                                 │
│      ├── Convert Appfile.WorkflowSteps → WorkflowInstance                      │
│      ├── Copy existing workflow status (for resume/retry)                       │
│      └── Set phase: Executing / Suspended / Terminated                         │
│                                                                                 │
│   2. Inject RuntimeParams (callbacks wired to OAM logic)                       │
│      ├── ComponentApply     → applyComponentFunc()  (generator.go:306)         │
│      ├── ComponentRender    → renderComponentFunc() (generator.go:259)         │
│      ├── ComponentHealthCheck → checkComponentHealth() (generator.go:271)      │
│      ├── KubeHandlers.Apply → h.Dispatch()                                     │
│      └── KubeHandlers.Delete, ConfigFactory, KubeClient                        │
│                                                                                 │
│   3. generator.GenerateRunners()                                                │
│      ├── Load step CUE template from ApplicationRevision                       │
│      └── StepConvertor: apply-component → builtin-apply-component              │
│                                                                                 │
│   Output: WorkflowInstance + []TaskRunner (one per workflow step)              │
└──────┬──────────────────────────────────────────────────────────────────────────┘
       │
       │  Step 5: Execute Workflow
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│              Workflow Executor  (github.com/kubevela/workflow)                   │
│              executor.New(workflowInstance).ExecuteRunners(runners)             │
│                                                                                 │
│   Execution Modes:                                                              │
│   ┌─────────────────────────────────────────────────────────────────────────┐  │
│   │  StepByStep (default)  ─ sequential, one step at a time                │  │
│   │  DAG                   ─ parallel where DependsOn allows it            │  │
│   └─────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│   For each TaskRunner:                                                          │
│   ┌─────────────────────────────────────────────────────────────────────────┐  │
│   │  Load step CUE template                                                 │  │
│   │  Evaluate CUE with parameter values + runtime context                  │  │
│   │  Call provider functions (oam.#ApplyComponent / multicluster.#Deploy)  │  │
│   │  Return: output (workload), outputs (traits), status                   │  │
│   └─────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│   Step States: pending → executing → succeeded / failed / skipped / waiting    │
└──────┬──────────────────────────────────────────────────────────────────────────┘
       │
       │  Step 6: Update Status
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│              Application Status Update                                          │
│                                                                                 │
│   app.Status.Workflow          → workflow phase + per-step states              │
│   app.Status.Services          → per-component health & traits                 │
│   app.Status.AppliedResources  → all resources created/updated                 │
│                                                                                 │
│   If all steps succeed → phase: Running                                        │
│   If any step fails   → phase: WorkflowFailed                                  │
│   If suspended        → phase: WorkflowSuspending                              │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Step-by-Step Breakdown

### Step 1 — Parsing: AppFile Generation

**Files:** `pkg/appfile/parser.go`, `pkg/appfile/appfile.go`

When `Reconcile()` is called, the first major operation is converting the `Application` spec into an in-memory `Appfile` object that carries all resolved templates.

```
Parser.GenerateAppFile(ctx, app)
│
├─ Check if PublishVersion matches latest cached revision
│    └─ If yes → use cached revision (fast path, skip re-parse)
│
└─ GenerateAppFileFromApp(ctx, app)
     │
     ├─ parseComponents()
     │    For each app.Spec.Components:
     │      makeComponent(comp)
     │        └─ LoadTemplate(compType)           ← fetch ComponentDefinition CUE
     │             For each trait in comp.Traits:
     │               LoadTemplate(traitType)       ← fetch TraitDefinition CUE
     │      appFile.ParsedComponents = append(...)
     │      appFile.RelatedComponentDefinitions[compType] = def
     │      appFile.RelatedTraitDefinitions[traitType]    = def
     │
     ├─ parseWorkflowSteps()
     │    loadWorkflowToAppfile()
     │      If app.Spec.Workflow != nil → use explicit steps
     │      Else                        → ApplyComponentWorkflowStepGenerator
     │                                     (auto-creates one apply-component step per component)
     │      For each step:
     │        LoadTemplate(stepType)              ← fetch WorkflowStepDefinition CUE
     │      appFile.WorkflowSteps = steps
     │      appFile.RelatedWorkflowStepDefinitions[stepType] = def
     │
     └─ parsePolicies()
          LoadExternalPoliciesForWorkflow()        ← resolve ref-objects policies
          For each app.Spec.Policies:
            LoadTemplate(policyType)               ← fetch PolicyDefinition CUE
          appFile.ParsedPolicies = policies
          appFile.RelatedPolicyDefinitions[type]  = def
```

**Appfile struct** (simplified from `pkg/appfile/appfile.go:160`):

```go
type Appfile struct {
    Name, Namespace          string
    ParsedComponents         []*Component                         // rendered component data
    ParsedPolicies           []*Component                         // rendered policy data
    WorkflowSteps            []WorkflowStep                       // ordered step list
    WorkflowMode             *WorkflowExecuteMode                 // DAG or StepByStep
    RelatedComponentDefinitions  map[string]*ComponentDefinition
    RelatedTraitDefinitions      map[string]*TraitDefinition
    RelatedWorkflowStepDefinitions map[string]*WorkflowStepDefinition
    RelatedPolicyDefinitions     map[string]*PolicyDefinition
}
```

---

### Step 2 — ApplicationRevision

**File:** `pkg/controller/core.oam.dev/v1beta1/application/revision.go`

```
PrepareCurrentAppRevision()
├─ gatherRevisionSpec()         ← snapshot ALL definitions (component, trait, policy, workflow CUE)
├─ hash(revisionSpec)           ← content-addressable deduplication
├─ currentAppRevIsNew()         ← compare hash with latest stored revision
└─ FinalizeAndApplyAppRevision()
     └─ Create / Update ApplicationRevision CR in Kubernetes
```

Every `Application` mutation that changes component, trait, policy, or workflow definitions creates a new `ApplicationRevision`. This allows:
- **Rollback** to any previous revision
- **Workflow re-execution** detection (changed hash → restart workflow)
- **Definition snapshots** so running workloads aren't affected by definition upgrades

---

### Step 3 — Policy Application

**File:** `pkg/controller/core.oam.dev/v1beta1/application/apply.go:461`

Policies are applied to the cluster **before** workflow execution. They configure _how_ the workflow engine will operate (which clusters to target, how to override component properties, etc.).

```
ApplyPolicies()
├─ Appfile.GeneratePolicyManifests()       ← render policy CUE templates → Unstructured resources
└─ h.Dispatch(ctx, policyResources)
     └─ ResourceKeeper.Dispatch()
          └─ apply.Applicator.Apply()      ← kubectl-style server-side apply
```

---

### Step 4 — Workflow Instance & Task Runners

**File:** `pkg/controller/core.oam.dev/v1beta1/application/generator.go`

#### 4a. WorkflowInstance creation

```go
// generator.go:156
instance := &wfTypes.WorkflowInstance{
    Steps: af.WorkflowSteps,    // from parsed Appfile
    Mode:  af.WorkflowMode,     // DAG or StepByStep
    Status: copyWorkflowStatusToInstance(app, af.WorkflowMode),
}
```

#### 4b. RuntimeParams injection

The workflow engine is generic and knows nothing about OAM. KubeVela wires in callbacks:

```
oamprovidertypes.WithRuntimeParams(ctx, RuntimeParams{
    ComponentApply:       h.applyComponentFunc(appParser, af)
    ComponentRender:      h.renderComponentFunc(appParser, af)
    ComponentHealthCheck: h.checkComponentHealth(appParser, af)
    KubeHandlers: {
        Apply:  h.Dispatch     ← apply resources to cluster
        Delete: h.Delete       ← delete resources from cluster
    }
    App, AppLabels, Appfile, KubeClient, ConfigFactory
})
```

#### 4c. StepConvertor

```
apply-component (OAM abstract type)
      │
      └─ converted to ──► builtin-apply-component (internal CUE template)
```

This conversion happens because the external `apply-component` WorkflowStepDefinition is user-facing, while `builtin-apply-component` is the actual internal CUE implementation.

---

### Step 5 — Workflow Execution

**Engine:** `github.com/kubevela/workflow/pkg/executor`

The executor iterates over `TaskRunner`s. Each runner corresponds to one workflow step.

#### Execution of `deploy` step

```
deploy.cue template
│
├─ if parameter.auto == false → builtin.#Suspend (wait for manual approval)
│
└─ multicluster.#Deploy
     │
     └─ deployWorkflowStepExecutor.Deploy()     (providers/multicluster/deploy.go)
          │
          ├─ selectPolicies(parameter.Policies)
          │    └─ filter from af.Policies by name
          │
          ├─ loadComponents()
          │    └─ call ComponentRender callback for each component
          │
          ├─ GetPlacementsFromTopologyPolicies()
          │    └─ determine target clusters & namespaces
          │
          ├─ overrideConfiguration(policies, components)
          │    └─ apply override policy patches to component properties
          │
          ├─ ReplicateComponents(policies, components)
          │    └─ expand components with replication policy keys
          │
          └─ applyComponents(components, placements, parallelism)
               │
               └─ For each placement × component:
                    ├─ checkComponentHealth()   ← skip re-apply if already healthy (apply-once)
                    ├─ fill inputs from upstream component outputs
                    └─ ComponentApply callback  ← actual apply to cluster
```

#### Execution of `apply-component` step

```
builtin-apply-component.cue template
│
└─ oam.#ApplyComponent & { $params: parameter }
     │
     └─ ApplyComponent() provider    (providers/oam/apply.go:72)
          │
          ├─ lookUpCompInfo(parameter)   ← extract component name, cluster, namespace
          │
          └─ params.ComponentApply()    ← callback = h.applyComponentFunc()
               │
               ├─ prepareWorkloadAndManifests()
               │    ├─ ParseComponentFromRevisionAndClient()
               │    └─ GenerateComponentManifest()   ← evaluate component CUE template
               │
               ├─ renderComponentsAndTraits()
               │    ├─ Apply trait patches to workload
               │    └─ Return: readyWorkload, readyTraits ([]*unstructured.Unstructured)
               │
               ├─ checkSkipApplyWorkload()   ← skip workload if apply-once satisfied
               │
               ├─ [Multi-stage dispatch if feature gate enabled]
               │    ├─ Stage 0 PreDispatch:  traits with stage=pre
               │    ├─ Stage 1 Default:      workload + default traits
               │    └─ Stage 2 PostDispatch: traits with stage=post (only if healthy)
               │
               ├─ Dispatch()              ← h.Dispatch() → ResourceKeeper → cluster
               │
               ├─ collectHealthStatus()   ← query resource health from cluster
               │
               └─ Return: workload, traits, isHealthy
```

After `ApplyComponent()` returns:

```
builtin-apply-component.cue:
  output:  apply.$returns.output          ← workload object (for downstream steps)
  outputs: apply.$returns.outputs[name]   ← trait objects by name
  if !healthy → params.Action.Wait("wait healthy")   ← re-queue step
```

---

### Step 6 — Resource Dispatch & Tracking

**Files:** `pkg/resourcekeeper/dispatch.go`, `pkg/resourcekeeper/resourcekeeper.go`

```
AppHandler.Dispatch(ctx, client, cluster, creator, resources...)
│
└─ ResourceKeeper.Dispatch(ctx, manifests, applyOpts)
     │
     ├─ AdmissionCheck()            ← validate against admission rules
     ├─ PreDispatchDryRun()         ← optional dry-run before apply
     ├─ ResourceTracker.Track()     ← record resource in ResourceTracker CR
     └─ apply.Applicator.Apply()    ← server-side apply to Kubernetes API
          └─ Creates/Updates the actual workload & trait resources in cluster
```

**ResourceTracker CR** maintains a registry of all resources owned by an Application. This enables:
- Garbage collection of orphaned resources (deleted components)
- Accurate status reporting
- Cross-cluster resource tracking

---

## Workflow Step Auto-Generation

When `app.Spec.Workflow` is **not defined**, KubeVela auto-generates steps based on policies present:

```
No explicit workflow defined
│
├─ Has topology policies?
│    Yes → DeployWorkflowStepGenerator
│           For each topology policy:
│             generate deploy step with { policies: [overrides..., topology] }
│
├─ Has ref-objects components or override policies only?
│    Yes → Single deploy step with override policies
│
└─ Default case → ApplyComponentWorkflowStepGenerator
        For each app.Spec.Components:
          generate apply-component step {
            name: comp.Name
            type: "apply-component"
            properties: { component: comp.Name }
            dependsOn: comp.DependsOn
          }
```

---

## Component-to-Resource Rendering Detail

```
Component Spec (YAML)
        │
        ▼
ComponentDefinition (CUE template)
        │
        ▼
CUE Evaluation Context
  ├─ parameter: { image, replicas, ... }   ← from Component.properties
  ├─ context.name, context.namespace       ← from Application metadata
  └─ context.appName, context.appRevision
        │
        ▼
ComponentManifest
  ├─ ComponentOutput          ← main workload (Deployment, StatefulSet, etc.)
  └─ ComponentOutputsAndTraits
       ├─ Trait[0] output     ← e.g. HorizontalPodAutoscaler (from ScalerTrait CUE)
       ├─ Trait[1] output     ← e.g. Ingress (from IngressTrait CUE)
       └─ ...

Trait Rendering:
  TraitDefinition CUE template evaluated with:
    ├─ parameter: trait properties
    ├─ context.output: the workload object above
    └─ patches applied back to workload (e.g. add labels, update replicas)
```

---

## Multi-Stage Trait Dispatch (Feature Gate: MultiStageComponentApply)

Traits can specify a dispatch stage in their definition:

```
Stage 0 — PreDispatch
  Applied BEFORE workload.
  Use case: ConfigMaps, Secrets that the workload depends on.

Stage 1 — DefaultDispatch  (default for all traits)
  Applied WITH workload in the same API call batch.
  Use case: HPAs, PodDisruptionBudgets.

Stage 2 — PostDispatch
  Applied AFTER workload becomes healthy.
  Use case: Canary rules, traffic policies that need healthy pods first.
```

Health gate between stages:

```
PreDispatch traits applied
        │
        ▼
Workload + Default traits applied
        │
        ▼
collectHealthStatus()
  ├─ healthy? → PostDispatch traits applied
  └─ not healthy → Action.Wait() → reconciler re-queues → retry next cycle
```

---

## Key File Reference

| Concern | File | Key Symbol |
|---------|------|-----------|
| Reconcile entry point | `pkg/controller/core.oam.dev/v1beta1/application/application_controller.go` | `Reconciler.Reconcile()` L106 |
| AppFile parsing | `pkg/appfile/parser.go` | `Parser.GenerateAppFile()` L87 |
| AppFile struct | `pkg/appfile/appfile.go` | `Appfile` L160 |
| Component manifest render | `pkg/appfile/appfile.go` | `GenerateComponentManifest()` L293 |
| Revision management | `pkg/controller/.../revision.go` | `PrepareCurrentAppRevision()` L85 |
| Policy dispatch | `pkg/controller/.../apply.go` | `ApplyPolicies()` L461 |
| Workflow step generation | `pkg/controller/.../generator.go` | `GenerateApplicationSteps()` L70 |
| Workflow instance creation | `pkg/controller/.../generator.go` | `generateWorkflowInstance()` L156 |
| Component apply callback | `pkg/controller/.../generator.go` | `applyComponentFunc()` L306 |
| Component render callback | `pkg/controller/.../generator.go` | `renderComponentFunc()` L259 |
| Health check callback | `pkg/controller/.../generator.go` | `checkComponentHealth()` L271 |
| Multi-stage dispatcher | `pkg/controller/.../dispatcher.go` | `generateDispatcher()` |
| Resource dispatch | `pkg/resourcekeeper/dispatch.go` | `Dispatch()` L60 |
| ResourceKeeper interface | `pkg/resourcekeeper/resourcekeeper.go` | `ResourceKeeper` L39 |
| OAM apply provider | `pkg/workflow/providers/oam/apply.go` | `ApplyComponent()` L72 |
| Deploy step provider | `pkg/workflow/providers/multicluster/deploy.go` | `Deploy()` L90 |
| builtin apply CUE | `pkg/workflow/template/static/builtin-apply-component.cue` | `apply: oam.#ApplyComponent` |
| deploy step CUE | `vela-templates/definitions/internal/workflowstep/deploy.cue` | `deploy: multicluster.#Deploy` |
| Step auto-generation | `pkg/workflow/step/generator.go` | `ApplyComponentWorkflowStepGenerator` L83 |
| Deploy step auto-gen | `pkg/workflow/step/generator.go` | `DeployWorkflowStepGenerator` L137 |

---

## End-to-End Example: `webservice` Component with `scaler` Trait

```
1. User applies Application with:
     components:
       - name: frontend
         type: webservice
         properties: { image: nginx, port: 80 }
         traits:
           - type: scaler
             properties: { replicas: 3 }

2. Reconciler starts:
   - GenerateAppFile()
       parseComponents():
         Load webservice ComponentDefinition CUE
         Load scaler TraitDefinition CUE
         Store in ParsedComponents[0]
       parseWorkflowSteps():
         No explicit workflow → auto-generate
         ApplyComponentWorkflowStepGenerator creates:
           WorkflowStep{ name: "frontend", type: "apply-component" }

3. PrepareCurrentAppRevision():
   Snapshot webservice + scaler definitions → ApplicationRevision CR

4. ApplyPolicies():
   No policies → no-op

5. GenerateApplicationSteps():
   WorkflowInstance.Steps = [{ name: "frontend", type: "builtin-apply-component" }]
   inject callbacks: ComponentApply, ComponentRender, etc.
   GenerateRunners() → [TaskRunner for "frontend"]

6. ExecuteRunners():
   Runner for "frontend":
     Load builtin-apply-component.cue
     Call oam.#ApplyComponent
       → applyComponentFunc("frontend")
           prepareWorkloadAndManifests():
             Evaluate webservice CUE → Deployment{image:nginx, port:80}
             Evaluate scaler CUE → HPA{replicas:3}, patch Deployment
           renderComponentsAndTraits():
             readyWorkload = Deployment
             readyTraits   = [HPA]
           Dispatch([Deployment, HPA]) → kubectl apply to cluster
           collectHealthStatus():
             Deployment available? Check pod readiness
             isHealthy = true

7. Application Status:
   phase: Running
   services:
     - name: frontend
       healthy: true
       traits:
         - type: scaler
           healthy: true
   appliedResources:
     - group: apps, resource: deployments, name: frontend
     - group: autoscaling, resource: horizontalpodautoscalers, name: frontend
```

---

## Reconciliation Loop and Re-queue

The controller uses controller-runtime's reconcile pattern. After `ExecuteRunners()` returns:

```
workflowState = Succeeded → Application phase: Running (done, no re-queue unless spec changes)
workflowState = Executing → Application phase: RunningWorkflow (re-queue after backoff)
workflowState = Suspended → Application phase: WorkflowSuspending (wait for resume)
workflowState = Failed    → Application phase: WorkflowFailed (re-queue with error)
workflowState = Terminated → Application phase: WorkflowTerminated (no re-queue)
```

Individual step `Action.Wait()` (e.g., waiting for component health) causes the executor to return `Executing`, which re-queues the reconciliation. On next reconcile, the workflow resumes from the same step (status is preserved in `workflowInstance.Status`).
