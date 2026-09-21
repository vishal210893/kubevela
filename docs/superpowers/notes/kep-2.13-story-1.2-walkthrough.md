# Addon Controller — Implementation Walkthrough (Story 1.2)

> **KubeVela Addon Controller — Story 1.2 (GWCP-101808) Implementation Walkthrough.**
> Pair-programming session for *"Complete AddonStatus structure with conditions, inventory, and source-digest fields"* under KEP-2.13 (parent epic GWCP-100436). Builds on story 1.1 (GWCP-101806). Verified against `apis/core.oam.dev/v1beta1/` in `github.com/kubevela/kubevela` on 2026-06-02.

Notion mirror: https://www.notion.so/373857335f2781cc8202eb19501b61f2

---

## TL;DR

Fills in everything missing from `AddonStatus` so downstream reconciler / drift correction / source resolve / finalizer stories have a stable contract. 10 new fields, 5 new types, 6 condition string constants. Eight implementation steps, all green. Stacks on top of story 1.1's commit on the same branch.

| Step | What it covers |
|---|---|
| 1 | Six scalar `AddonStatus` fields (timestamps, version info, app pointer, healthy flag) |
| 2 | `resolvedSourceDigest` + OCI manifest digest concept |
| 3 | `conditions []metav1.Condition` + six condition type string constants |
| 4 | `AddonResourceRef` + `AddonInstalledResources` (staleness diff inventory) |
| 5 | `AddonInclude` (per-category install knobs for the `addon` component type) |
| 6 | `AddonModuleStatus` + `AddonModuleLineStatus` (KEP-2.20 forward-compat placeholders) |
| 7 | Run `go generate`, verify deterministic output |
| 8 | `go build` + `go vet` verification |

---

## Questions you asked during the session

Verbatim, with pointers to where each is answered.

| # | Question | Where answered |
|---|---|---|
| Q1 | *"status.installedResources can you give the structure of this and how comparing take. a rough idea may be"* | Step 4 — *"Show the structure and how the comparison (staleness diff) works"* |
| Q2 | *"explain this: The inventory is always one cycle behind. A resource applied in reconcile N appears in the snapshot used by reconcile N+1…"* | Step 4 — *"The inventory is always one cycle behind — what does that mean?"* |
| Q3 | *"AddonInstalledResources is the addon-wide inventory of resources the controller applied at the last reconcile. Used by the staleness diff. Will it contain data of every resource which addon create? Give an example of pre-filled YAML data."* | Step 4 — *"Will `installedResources` contain every resource the addon creates?"* |
| Q4 | *"not able to understand this part: Why an array of conditions instead of separate boolean fields"* | Step 3 — *"Why an array of conditions instead of separate boolean fields?"* |
| Q5 | *"explain this with example using humanizer skill. AddonInclude controls which addon asset categories…"* | Step 5 body — four concrete examples (default, skip operator, definitions-only, explicit-true) |
| Q6 | *"okay now can you explain step 6 and 7 in similay way"* | Step 6 (`AddonModuleStatus` / `AddonModuleLineStatus` with YAML walkthrough) and Step 7 (generator output, idempotency, noise handling) |

---

## Step 1 — Scalar `AddonStatus` fields

Six simple-typed fields added to `AddonStatus`. No new types needed; just `string`, `*metav1.Time`, and `bool`.

| Field | Type | Purpose |
|---|---|---|
| `LastReconciledAt` | `*metav1.Time` | Wall-clock timestamp of last reconcile — "is the controller stuck?" diagnostics. |
| `InstalledVersion` | `string` | Addon version actually running. Compared with `spec.version` to detect drift / upgrade triggers. |
| `InstalledRegistry` | `string` | The registry that provided the installed version. |
| `AvailableUpgrade` | `string` | Set in tracking + Manual mode when a newer version is found. Cleared on apply. |
| `ApplicationName` | `string` | Name of the owned Application in `vela-system` (typically `addon-{name}`). |
| `ApplicationHealthy` | `bool` | Quick boolean indicator; transition time / reason live on the `ApplicationHealthy` condition. |

> **Pointer vs value for timestamps.** `LastReconciledAt` is `*metav1.Time`, not a value type. Reason: the zero value of `metav1.Time` marshals to `null` in JSON, which is ugly. Nil + `omitempty` cleanly omits the field. Standard Kubernetes convention (see `Pod.Status.StartTime *metav1.Time`).

### Populated example (fluxcd running healthy)

```yaml
status:
  phase: running
  observedGeneration: 3
  lastReconciledAt: "2026-06-02T13:45:12Z"
  installedVersion: v1.2.0
  installedRegistry: KubeVela
  applicationName: addon-fluxcd
  applicationHealthy: true
  # availableUpgrade absent because spec.version is pinned (exact tag)
```

### Populated example (tracking mode with an upgrade waiting)

```yaml
status:
  phase: running
  observedGeneration: 5
  lastReconciledAt: "2026-06-02T14:00:00Z"
  installedVersion: v1.2.0
  installedRegistry: KubeVela
  availableUpgrade: v1.4.0       # constraint resolved to a newer version
  applicationName: addon-fluxcd
  applicationHealthy: true
```

The second example shows what *Manual* tracking mode looks like: a newer version exists, the controller has noted it, but `installedVersion` is still the old one. Operator decides when to bump `spec.version`.

---

## Step 2 — `resolvedSourceDigest` + the digest concept

One `string` field, but worth the teaching moment.

### OCI manifest digest — what it actually is

When the controller fetches an addon from an OCI registry (Harbor, ECR, GHCR, etc.), it doesn't fetch raw files. It fetches an **OCI artifact**: a manifest plus layers. The registry hashes the manifest JSON with SHA-256 and serves the result as the artifact's identity: `sha256:abc123def456...`. That's the manifest digest.

Two important properties:

- **Content-addressable.** Computed *from* the content. Same content → same digest, byte-for-byte, anywhere.
- **Tamper-evident.** Change one bit in the manifest or any referenced layer, the digest changes. No way to keep it stable while modifying the artifact.

That's what makes the field useful: the controller asks the registry "has `aws-s3:v1.2.0` changed?". A different digest means the artifact actually changed (someone moved a tag, force-pushed a layer). Same digest means nothing changed — skip the full download and re-render from the local cache.

### Git sources

A Git commit SHA is also content-addressable (SHA hashing the tree + parent + message). Same role, different backend. For Git-sourced addons the field stores the full commit SHA. The controller writes whatever it resolved; readers just compare strings.

### Populated example (OCI source)

```yaml
status:
  phase: running
  installedVersion: v1.2.0
  installedRegistry: KubeVela
  resolvedSourceDigest: "sha256:9ba8c7f29d1e6a4f5b3c2e8d7a6b9f0e1c2d3a4b5c6d7e8f90a1b2c3d4e5f6a7"
```

On each reconcile the controller does a cheap HEAD request to the registry, asks "what's the manifest digest for `aws-s3:v1.2.0` right now?", and compares against `resolvedSourceDigest`. Same digest → skip the full download; different digest → the tag was moved or the artifact mutated, re-fetch and re-render.

### Populated example (Git source)

```yaml
status:
  phase: running
  installedVersion: v1.2.0
  resolvedSourceDigest: "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
```

For Git, the digest is the full commit SHA. Same compare logic, different backend.

---

## Step 3 — Conditions field + six type constants

### What `metav1.Condition` is

```go
type Condition struct {
    Type               string             // e.g. "Ready", "SourceResolved"
    Status             ConditionStatus    // "True", "False", "Unknown"
    LastTransitionTime metav1.Time
    Reason             string             // short CamelCase code
    Message            string             // human-readable description
    ObservedGeneration int64
}
```

Standard apimachinery struct. Every modern Kubernetes type uses it for multi-faceted status reporting.

### The six condition types declared

| Type | True when... | Status of writes in 1.2 slice |
|---|---|---|
| `Ready` | Rollup: all modules synced, all enabled lines have aux ready + definitions applied | **Active** (writers ship in slice) |
| `SourceResolved` | Source artifact fetched, digest resolved. False = registry unreachable. | **Active** |
| `ApplicationHealthy` | Owned Application reached `Ready=True` | **Active** |
| `AuxiliaryReady` | All enabled API line aux resources reported `Ready` via kstatus | Reserved (writes deferred) |
| `ModulesSynced` | All modules evaluated, definitions applied without error this cycle | Reserved (writes deferred) |
| `DefinitionConflict` | Definitions exist on cluster under a different owner (failure mode) | Reserved (writes deferred) |

Why declare all six even though only three get written? **Forward-compatibility.** When auxiliary-readiness logic lands in a follow-up epic, it just starts writing to the existing `AddonConditionAuxiliaryReady` constant. No string-mismatch errors, no rename churn.

### Q4 — Why an array of conditions instead of separate boolean fields?

**Old way — separate boolean fields:**

```yaml
status:
  phase: running
  ready: true
  sourceResolved: true
  applicationHealthy: true
  auxiliaryReady: false
```

**Modern way — array of conditions:**

```yaml
status:
  phase: running
  conditions:
    - type: SourceResolved
      status: "True"
      lastTransitionTime: "2026-06-02T10:00:00Z"
      reason: ResolveSucceeded
      message: "fetched digest sha256:abc... from registry KubeVela"
    - type: AuxiliaryReady
      status: "False"
      lastTransitionTime: "2026-06-02T10:02:30Z"
      reason: WaitingForXRDs
      message: "XRD bucket.aws-s3.crossplane.io still in NotEstablished"
```

Three benefits drive the choice:

**1. Extensibility.** Adding `AuxiliaryReady` later means defining a new string constant; the Go struct does not change. Old clients that don't know about the new condition simply ignore the new entry. With booleans, every new aspect is a new struct field and a schema bump.

**2. Transition tracking.** A bool `ready: false` tells you nothing about *when* or *why*. A condition carries `lastTransitionTime`, `reason` (machine-parseable code), and `message` (human description). Debugging "why has this been broken for 5 minutes?" is now answerable from `kubectl get` alone.

**3. Tooling.** `kubectl wait --for=condition=Ready` works across every Kubernetes type that uses conditions. ArgoCD / Flux health checks understand them natively. With booleans you'd hand-roll all of that per CRD.

The cost is a slightly more verbose JSON output — worth it for the introspection benefits.

### Why string constants and not a typed enum

`metav1.Condition.Type` is just `string`. A typed wrapper would convert at every call site. Plus standard Kubernetes practice is plain string constants (`corev1.PodReady`, `appsv1.DeploymentAvailable`). We follow the convention.

---

## Step 4 — `AddonResourceRef` + `AddonInstalledResources`

### The two types

```go
type AddonInstalledResources struct {
    Definitions     []AddonResourceRef
    VelaQLViews     []AddonResourceRef
    ConfigTemplates []AddonResourceRef
    Schemas         []AddonResourceRef
    Packages        []AddonResourceRef
}

type AddonResourceRef struct {
    Name         string
    Kind         string
    Deprecated   bool   // KEP-2.20 lifecycle marker
    DeprecatedAt string // RFC3339 timestamp
}
```

Five lists, one per metadata category. Each entry is a 4-tuple but the last two are usually empty unless the deprecation lifecycle has marked the resource.

### Three subtle design choices

**Why `name + kind` (no GVK, no UID).** The inventory only needs to identify a resource *within the addon's own scope*. Group is implied by the category bucket (definitions are in `core.oam.dev`, views are in `velaql.oam.dev`, etc.). Namespace is implied (metadata resources all live in `vela-system`; definitions are cluster-scoped). So `(name, kind)` is unique within a category.

**Why deprecation markers on the ref.** KEP-2.20 marks individual resources as deprecated. Carrying the marker on the ref keeps the inventory self-contained — one read of `status.installedResources` tells you "installed and deprecated" without joining a side-table.

**Why no top-level `Auxiliary` bucket.** Auxiliary resources (Crossplane XRDs/Compositions) are per-API-line, not addon-wide. They live in `AddonModuleLineStatus.AuxiliaryResources` (step 6). Addon-wide metadata is just definitions + views + configTemplates + schemas + packages.

### Q1 — Show the structure and how the comparison (staleness diff) works

**Populated YAML example** (fluxcd after install):

```yaml
status:
  installedResources:
    definitions:
      - name: helm-release
        kind: ComponentDefinition
      - name: git-source
        kind: ComponentDefinition
      - name: notification
        kind: TraitDefinition
    velaQLViews:
      - name: flux-status
        kind: View
    configTemplates:
      - name: git-credentials
        kind: ConfigTemplate
    schemas:
      - name: helm-release-schema
        kind: ConfigMap
    packages: []
```

**The diff per reconcile:**

```
Snapshot A = status.installedResources (last reconcile's record)
Snapshot B = freshly rendered set from addon source

for each category:
    stale = items in A but not in B
    new   = items in B but not in A
    same  = items in both

    if category is Views/ConfigTemplates/Schemas:
        hard-delete stale items   # metadata, safe to remove

    if category is Definitions/Auxiliary:
        skip delete                # runtime deps; deprecation lifecycle handles removal

    apply (SSA) new + same items   # idempotent

status.installedResources = B
```

**Walkthrough.** v1.0.0 ships with `flux-status` View and `git-credentials` ConfigTemplate. v1.1.0 renames the View to `flux-overview` and removes `git-credentials`.

Diff in the cycle that first renders v1.1.0:

- `flux-status` View → stale → hard-delete.
- `git-credentials` ConfigTemplate → stale → hard-delete.
- `flux-overview` View → new → SSA apply.

### Q2 — "The inventory is always one cycle behind" — what does that mean?

It is about the **snapshot basis**, not about a delay in detecting changes.

The diff uses a stored snapshot (`status.installedResources`), not a live cluster query. The snapshot was written at the *end* of the previous reconcile. So in cycle N+1, the diff reads what cycle N recorded.

**Trace of a rename:**

```
Cycle N (last cycle on old source):
  previous = [oldView]    # from N-1's snapshot
  current  = [oldView]    # source unchanged
  diff: nothing stale
  status.installedResources = [oldView]

[ source rename committed; spec.version bumped; reconcile fires ]

Cycle N+1 (first cycle on new source):
  previous = [oldView]    # from N's snapshot
  current  = [newView]    # rendered from new source
  diff: oldView stale, newView new
  apply newView (SSA), hard-delete oldView   # cleanup happens HERE
  status.installedResources = [newView]
```

Cleanup is **immediate** — in the cycle that first renders the change. The "one cycle behind" framing refers to the fact that the diff basis was *recorded* one reconcile ago.

**Practical implication.** Reading `status.installedResources` externally always shows the previous reconcile's end state, not the current. Same as any Kubernetes status field. Not a defect, just snapshot semantics.

### Q3 — Will `installedResources` contain every resource the addon creates?

No. Curated subset — addon-wide *metadata* resources only.

| Resource type | In `installedResources`? | Tracked elsewhere |
|---|---|---|
| Definitions (Component/Trait/etc.) | **Yes** — `definitions` bucket | — |
| VelaQL Views | **Yes** — `velaQLViews` bucket | — |
| ConfigTemplates | **Yes** | — |
| UI Schemas | **Yes** | — |
| CUE packages (future) | **Yes** | — |
| The owned Application itself | **No** | `status.applicationName` |
| Operator Deployment / RBAC / CRDs (from `resources/`) | **No** | The Application's ResourceTracker GC manages those |
| Auxiliary (Crossplane XRDs / Compositions) | **No** | `status.modules[].lines[].auxiliaryResources` |

Mental model: `installedResources` is the **staleness-diff inventory for metadata only**. The Application controller handles its own children via ResourceTracker; auxiliary lives per API line.

---

## Step 5 — `AddonInclude`

Seven optional `*bool` knobs for cherry-picking which asset categories install when an addon is consumed via the `addon` component type (addon-of-addons composition).

### Default-include semantics

| Value in YAML | Meaning |
|---|---|
| Field absent / `null` | Use default (include the category) |
| `true` | Explicit include (same effect as absent) |
| `false` | Skip this category |

Only write the categories you want to skip. Everything else gets installed.

### Why `*bool` (not `bool`)

A plain `bool`'s zero value is `false`. Go's JSON decoder fills missing fields with zero values, so if you wrote `include: { resources: false }` the controller would see `{Definitions: false, ConfigTemplates: false, …, Resources: false, Auxiliary: false}` — every category opted out.

With `*bool`, zero value is `nil`. Now "unset" and "explicit false" are distinguishable: `nil = use default (include)`, `*false = explicit skip`.

Standard Kubernetes pattern whenever those two states need different meanings.

### Concrete examples

**Default behavior (no include block):**

```yaml
spec:
  components:
    - name: aws-s3
      type: addon
      properties:
        version: v1.3.0
```

Everything ships.

**Skip the operator (Crossplane already installed elsewhere):**

```yaml
spec:
  components:
    - name: postgres
      type: addon
      properties:
        version: v2.1.4
        include:
          resources: false   # skip operator install
```

Definitions + Compositions still ship; the owned Application for the operator is not created.

**Definitions-only (catalogue mode):**

```yaml
spec:
  components:
    - name: aws-s3
      type: addon
      properties:
        version: v1.3.0
        include:
          resources: false
          auxiliary: false
          views: false
          schemas: false
          configTemplates: false
```

Only the ComponentDefinitions / TraitDefinitions land. Use case: a curated API surface with infrastructure provisioned separately.

**Explicit `true` (rare, but valid — used for intent-documenting):**

```yaml
spec:
  components:
    - name: observability
      type: addon
      properties:
        version: v3.0.1
        include:
          definitions: true       # explicit, same as omitting (still installed)
          schemas: false          # the only category we are actually opting out of
```

Functionally identical to writing just `schemas: false` and leaving `definitions:` out. You'd add the `true` lines only when you want the YAML to *document intent* ("yes, we deliberately want definitions"). Mostly stylistic.

---

## Step 6 — `AddonModuleStatus` + `AddonModuleLineStatus`

### The nesting

```
AddonStatus
   └─ Modules: []AddonModuleStatus       # one per module directory
         └─ Lines: []AddonModuleLineStatus  # one per API line subdirectory
```

A module like `modules/aws-s3/` with `v1/` and `v2/` lines produces one `AddonModuleStatus{Name: "aws-s3"}` carrying two `AddonModuleLineStatus` entries.

### Per-line fields

| Field | What it carries |
|---|---|
| `APIVersion` | Line tag (`v1`, `v2`, ...) |
| `Enabled` | Whether `_version.cue` `enabled:` expression resolved to true against cluster context |
| `Deprecated` | KEP-2.20 deprecation lifecycle flag |
| `DeprecationReason` | Free-form explanation |
| `AuxiliaryResources` | The list of auxiliary resources applied for this line |
| `ResolvedSourceVersion` | For lines that `source` an external module, which version was pulled |
| `Message` | Free-form info text |

**Auxiliary lives per line, not at the addon-wide level** — which is why `AddonInstalledResources` has no `auxiliary` bucket at the top.

### Concrete YAML example

```yaml
status:
  modules:
    - name: aws-s3
      lines:
        - apiVersion: v1
          enabled: true
          deprecated: false
          resolvedSourceVersion: v1.4.0
          auxiliaryResources:
            - name: xbuckets.aws-s3.crossplane.io
              kind: CompositeResourceDefinition
            - name: bucket-composition-v1
              kind: Composition
        - apiVersion: v2
          enabled: true
          deprecated: false
          resolvedSourceVersion: v2.0.0-beta.1
          auxiliaryResources:
            - name: xbuckets.aws-s3.crossplane.io
              kind: CompositeResourceDefinition
            - name: bucket-composition-v2
              kind: Composition

    - name: aws-rds
      lines:
        - apiVersion: v1
          enabled: false
          deprecated: false
          message: "Crossplane AWS provider not installed; line skipped per _version.cue"
```

Readable at a glance: `aws-s3` has two coexisting API lines; `aws-rds` is disabled because the AWS provider isn't on this cluster (context-aware behaviour surfaced via the `Message` field).

### Why declare these now

Forward compatibility. The story 1.2 reconciler does not write to `modules`. When KEP-2.20 work lands and the controller starts populating per-module state, downstream consumers (CLI status, VelaUX, dashboards) already have the data shape. Future writes are purely additive — no consumer breaks.

For addons that use only the `definitions/` directory, `status.modules` stays empty. `omitempty` keeps it out of the JSON entirely.

---

## Step 7 — Run `go generate`

### What ran

```bash
(cd /workspaces/Open_Source/kubevela/apis && go generate ./...)
```

Triggers the `//go:generate` directive in `apis/generate.go`:

```go
//go:generate go run -tags generate sigs.k8s.io/controller-tools/cmd/controller-gen \
    object:headerFile=../hack/boilerplate.go.txt \
    paths=./... \
    crd:crdVersions=v1,generateEmbeddedObjectMeta=true \
    output:artifacts:config=../config/crd/base
```

Three outputs from one invocation:

1. **`object:...`** — writes DeepCopy methods into `zz_generated.deepcopy.go`.
2. **`crd:...`** — emits CRD YAML manifests with the full OpenAPI schema.
3. **`output:artifacts:config=...`** — puts CRD YAML into `config/crd/base/` (intermediate; story 1.3 dispatches to Helm).

### What got generated for our types

Example — `AddonInstalledResources`:

```go
func (in *AddonInstalledResources) DeepCopyInto(out *AddonInstalledResources) {
    *out = *in
    if in.Definitions != nil {
        in, out := &in.Definitions, &out.Definitions
        *out = make([]AddonResourceRef, len(*in))
        copy(*out, *in)
    }
    // ... identical block for VelaQLViews, ConfigTemplates, Schemas, Packages
}

func (in *AddonInstalledResources) DeepCopy() *AddonInstalledResources {
    if in == nil {
        return nil
    }
    out := new(AddonInstalledResources)
    in.DeepCopyInto(out)
    return out
}
```

The per-slice `make + copy` dance enforces the "no shared pointers" guarantee.

Root types (`Addon`, `AddonList`) additionally get `DeepCopyObject() runtime.Object`, which satisfies the `runtime.Object` interface used by `client.Get(ctx, key, obj)`.

### Idempotency verification

Ran twice, compared MD5:

```
5624f5083d34565eef4a87d5a6febf7c  zz_generated.deepcopy.go   ← first run
5624f5083d34565eef4a87d5a6febf7c  zz_generated.deepcopy.go   ← second run
```

Identical → deterministic generator → AC6 satisfied ("subsequent runs produce no diff").

### Noise in unrelated packages

Each run also touched `apis/core.oam.dev/{common,condition,v1alpha1}/zz_generated.deepcopy.go` with tiny import-formatting differences. These are pre-existing artifacts from a `controller-gen` version mismatch in the repo (different contributors have different binaries installed). Reverted each time:

```bash
git restore apis/core.oam.dev/common/zz_generated.deepcopy.go \
            apis/core.oam.dev/condition/zz_generated.deepcopy.go \
            apis/core.oam.dev/v1alpha1/zz_generated.deepcopy.go
```

Keeps the diff scoped to our actual work.

---

## Step 8 — Build + vet

| Check | Result |
|---|---|
| `go build ./apis/core.oam.dev/v1beta1/...` | OK |
| `go build ./pkg/oam/... ./pkg/addon/...` | OK (downstream consumers compile) |
| `go vet ./apis/core.oam.dev/v1beta1/...` | OK |
| `make lint` (run from user's environment) | OK (38 linters, 0 issues after standard exclusions) |

---

## Final state on disk

| File | Status |
|---|---|
| `apis/core.oam.dev/v1beta1/addon_types.go` | Modified — +10 status fields, +5 new types, +6 condition string constants |
| `apis/core.oam.dev/v1beta1/zz_generated.deepcopy.go` | Modified — generated DeepCopy methods for all new types |

No other files touched. Branch: `feat/kep-2.13-addon-types` (story 1.2 stacks on top of story 1.1's commit on the same branch).

---

## Open items at handoff

- Duet commit (Vishal author, Vaibhav committer).
- Update Jira GWCP-101808 AC7 to drop the dedicated test-file requirement (same call as story 1.1 — no other CRD type in the directory ships a `_types_test.go` for deepcopy/enum verification).
- Push branch.
- Open upstream PR against `kubevela/kubevela:master` (after story 1.1's PR merges or rebased onto master).

---

## Sources verified against

- Jira: [GWCP-101808 — Complete AddonStatus structure with conditions, inventory, and source-digest fields](https://guidewirejira.atlassian.net/browse/GWCP-101808)
- Parent epic: [GWCP-100436 — KubeVela KEP-2.13 Declarative Addon Lifecycle](https://guidewirejira.atlassian.net/browse/GWCP-100436)
- Story 1.1 reference: [GWCP-101806](https://guidewirejira.atlassian.net/browse/GWCP-101806) and its walkthrough page on Notion.
- KEP-2.13: `design/vela-core/keps/2.13-addons/README.md` (commit `021a233`), §API Changes — Addon CR Status (lifecycle fields).
- `controller-runtime`: `sigs.k8s.io/controller-runtime`.
- `apimachinery`: `k8s.io/apimachinery/pkg/apis/meta/v1` (`Condition`, `Time`).
- KubeVela repo: `github.com/kubevela/kubevela` — `apis/core.oam.dev/v1beta1/addon_types.go`.
- Last verified: **2026-06-02**.

---

## Audit notes

- All eight implementation steps captured with the same pair-programming discipline used in story 1.1.
- Six user questions (Q1–Q6) recorded verbatim near the top with pointers to their answers.
- Each step has at least one populated YAML example to ground the type concretely.
- Decision to skip `_types_test.go` mirrors story 1.1; Jira AC7 update is pending at handoff.
- The `config/crd/base/core.oam.dev_addons.yaml` produced by `go generate` is *not* committed on this branch — Helm-chart-ready CRD YAML packaging is story 1.3.
