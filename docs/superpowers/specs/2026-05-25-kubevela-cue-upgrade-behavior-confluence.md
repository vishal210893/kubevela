# KubeVela 1.10 → 1.11 Upgrade Behaviour Across CUE Breaking Changes

**Author:** Investigation conducted on 2026-05-25 against KubeVela 1.10.6 (CUE 0.9.2) and 1.11.0-alpha.3 (CUE 0.14.1), with live cluster verification.

**Audience:** Platform operators planning the upgrade, definition authors curating ComponentDefinitions, on-call engineers triaging post-upgrade incidents.

---

## 1. TL;DR

- KubeVela 1.11 bumps the embedded `cuelang.org/go` library from **v0.9.2 to v0.14.1**. Some CUE syntax that was valid in 0.9.2 is no longer accepted or has been deprecated in 0.14.1 — most notably `list1 + list2` for list concatenation, which must become `list.Concat([list1, list2])`.
- **Existing workloads keep running.** ResourceTracker holds the rendered manifest as a zstd-compressed byte cache, and StateKeep replays those bytes through the plain Kubernetes client. The data plane is unaffected by the upgrade.
- **The control plane silently rots.** When the new engine hits CUE syntax that was valid pre-upgrade but is no longer accepted, the error is logged during health collection at `application_controller.go:905` and discarded. `services[*].healthy` retains its pre-upgrade value forever. `vela status` and `kubectl get app` show green while the controller errors every reconcile cycle.
- **Fixing the CD alone does not unfreeze the App.** The ApplicationRevision is keyed off the App's spec hash, not the CD's. You must also force a new revision via `app.oam.dev/publishVersion` bump, App spec edit (only effective if publishVersion is unset), or `app.oam.dev/autoUpdate: "true"` (which switches the equality check to include CDs).
- **The reliable kubectl-only post-upgrade check** is on the ComponentDefinition itself, not the Application:
  ```bash
  kubectl get componentdefinition -A \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.status=="False")].message}{"\n"}{end}'
  ```
- Three upstream bugs compound to make the failure unobservable: health-check error swallow, `loggingApply` ordering, and the `ValidateUndeclaredParameters` feature gate missing from the Helm chart.

---

## 2. Background

| Component | KubeVela 1.10.6 | KubeVela 1.11.0-alpha.3 |
|---|---|---|
| `cuelang.org/go` | v0.9.2 | v0.14.1 |
| CRD schema | v1beta1 | v1beta1 (compatible) |
| Controller image | `oamdev/vela-core:v1.10.6` | `oamdev/vela-core:v1.11.0-alpha.3` |
| Validating webhook | Validates against CUE 0.9.2 | Validates against CUE 0.14.1 |

The CUE upgrade is a single Go-module bump in the controller binary. CRDs, CR objects, and stored ApplicationRevisions are all schema-compatible across the upgrade.

---

## 3. Quick reference

### 3.1 Scenario matrix

**Setup assumed for every row below:**

- The KubeVela controller has been upgraded from 1.10.x (CUE 0.9.2) to 1.11.x (CUE 0.14.1). The new binary is running.
- ComponentDefinitions and Applications in the cluster were authored under the old CUE engine. Some of those CDs use CUE patterns that were valid in 0.9.2 but are no longer accepted by 0.14.1 (the canonical example: `parameter.left + parameter.right` for list concatenation, which must become `list.Concat([...])`).
- The rendered workload (Deployment / ConfigMap / etc.) was created before the upgrade and is still running.
- Stored `ApplicationRevision` objects still carry the pre-upgrade CD snapshot inside them, byte-for-byte.

In other words: nothing on the data plane has changed; everything in the control plane is now running against a stricter CUE engine that disagrees with the snapshots it has to work with.

> **A note on terminology.** When this document refers to a "pre-upgrade CD" or "pre-upgrade-CUE" pattern, it means a ComponentDefinition that was applied to the cluster under KubeVela 1.10.x with CUE 0.9.2 — at the time it was applied it was perfectly valid, was admitted by the old webhook, and the rendered workload has been running correctly ever since. After the controller is upgraded to 1.11.x (CUE 0.14.1), the same CUE text in that CD is no longer accepted by the new engine. The CD itself did not change; only the engine that evaluates it did. We use "pre-upgrade CD" rather than "broken CD" to make this clear — it was never wrong, just incompatible with the newer engine after the upgrade.

The rows below describe what happens when you take a specific action (or take no action) on this cluster.

| # | Scenario | Workload running? | Status reported correctly? | Verification |
|---|---|---|---|---|
| 1 | Take no action — let the controller reconcile on its own | Yes (RT replay) | **No** — stays at last pre-upgrade value (`true`) | Log error every reconcile, status never updates |
| 2 | Delete the rendered workload by hand (drift correction test) | Yes — sub-second in normal state; periodic-tick fallback when the new engine rejects the pre-upgrade CUE | Stale-for-a-missing-resource only in the pre-upgrade-CD case | CM recreated within 1 sec in normal state; ~periodic-tick gap when the CUE no longer compiles |
| 3 | Edit the existing App's spec while its CD is still in the pre-upgrade form (not yet rewritten for the new engine) | n/a — webhook rejects the spec change | n/a | `kubectl apply` returns Forbidden with CUE error inline; underlying resource untouched |
| 4 | Try to create a new App that uses a CD whose CUE has a compile-time break | n/a — the CD itself is rejected at admission if you try to (re)create it | n/a | `validating.componentdefinitions` webhook denies CD admission with the CUE error |
| 4b | Try to create a new App that uses a CD with an evaluation-time-only error (CD admission passes, App admission fails) | n/a — App rejected at create | n/a | `validating.applications` webhook denies App admission when parameters bind |
| 5 | Create a new App against a CD that compiles and evaluates fine but renders a logically wrong manifest (the "S3 short-circuit" case — no controller will reconcile the rendered CR) | External resource never created | **Reports `healthy=true` falsely** — default health check only asks "does the resource exist?" | FakeBucket CR exists, no controller reconciles it, App is green |
| 6 | Rewrite the pre-upgrade CD to be 0.14-compatible, leave the existing App alone | Yes — **the same workload object that has been running since pre-upgrade keeps running, unchanged**. The new CD content is dormant in a new `DefinitionRevision` but no App uses it. | **Still wrong** — App keeps replaying the frozen pre-upgrade ApplicationRevision (which still has the pre-upgrade CD snapshotted inside it) until a new revision rolls | Same CUE error in controller logs every reconcile after the CD rewrite |
| 7 | Rewrite the pre-upgrade CD + bump `app.oam.dev/publishVersion` on the existing App | Yes — **same workload object identity (same name, UID, creationTimestamp), patched in place via three-way merge to reflect the new CD's output**. Not a delete-and-recreate. | Correct | Clean reconcile, error gone, new ApplicationRevision created from the rewritten CD; underlying workload's field values updated to match the new render |
| 8 | Update the CD on an App that already has `app.oam.dev/autoUpdate: "true"` set — any kind of CD change (ConfigMap data, Deployment `replicas: 2 → 5`, field additions in the template, etc.) | Yes; the workload reflects the new CD content automatically | Correct | New AppRev created automatically; the underlying workload is patched (e.g., a Deployment with `replicas: 2` scales to `5`); RT object name stays unchanged but its compressed cache is rewritten in place with the new manifest |

### 3.2 Frequently asked questions

**Q1. After a KubeVela upgrade breaks the CUE in an existing CD, can I trust the App's reported status?**

No. `services[*].healthy` keeps whatever value it had before the upgrade (usually `true`) because the controller logs the CUE error and returns void at `application_controller.go:905`, so the field never gets rewritten. To check whether the App is actually in this failing state, look at the corresponding ComponentDefinition's `Synced=False` condition.

**Q2. Does the running workload itself get disrupted during reconcile after the upgrade?**

No. ResourceTracker holds the rendered manifest as a zstd-compressed blob; `StateKeep` replays those bytes through the plain Kubernetes client with no CUE involved. With a normal CD, drift correction is event-driven (sub-second). With a pre-upgrade CD post-upgrade, recovery falls back to the periodic resync (default 5 min, configurable).

**Q3. After fixing the pre-upgrade CD, does the App's calculated status fix itself?**

No. The App keeps replaying its frozen pre-upgrade ApplicationRevision (which still has the pre-upgrade CD baked into it) until a new ApplicationRevision is created. You need to bump `app.oam.dev/publishVersion`, edit the App spec (only works if no publishVersion is set), or have `autoUpdate: "true"` on the App already.

**Q4. When a CD is updated, does the RT's cached manifest get regenerated — even if only the template body changed and parameters did not?**

With `autoUpdate: "true"` on the App, yes. `spec.compression.data` is rewritten in-place to the new CD output regardless of whether parameters changed. The RT object's name and outer labels stay frozen at the original revision, which is misleading at a glance — decode the blob to see the rollover. Apps pinned to a specific DefinitionRevision (via `app.oam.dev/revision-only` or `definitionRevision: name@v1`) skip the rollover entirely.

**Q5. If I try to create a new Application that references a CD whose CUE no longer compiles under the new engine, does the webhook reject it?**

Yes, at the ComponentDefinition admission layer. `kubectl apply` of a CD using `parameter.left + parameter.right` is denied with `admission webhook ... denied the request: Addition of lists is superseded by list.Concat`. The CD itself never reaches the cluster, so no consuming App can be built against it.

**Q6. What if the CD compiles fine but evaluates wrong only when parameters are bound (string + int, missing required field, constraint violation)?**

The validator cannot substitute parameters that do not exist at CD admission time, so this class of error passes the CD webhook and surfaces only at Application admission, when the consuming App's properties are bound and the template actually evaluates. The user is still blocked from creating the App, but the rejection is at a different layer with the App's name on it. Useful for triage: admission failures on Apps while the CD looks accepted indicate this case.

**Q7. What about the "S3 short-circuit" case — a CD whose CUE compiles and evaluates fine but renders a logically wrong manifest?**

Neither webhook catches it. KubeVela's default health check just asks "does the resource exist?" — and it does, because the controller successfully rendered a CR object and posted it to the API. The external action that would provision the actual S3 bucket never fires, but the App reports `healthy=true` indefinitely because the CR is there. The only honest signal is checking the underlying external resource directly, or writing a custom `status.healthPolicy` that inspects the CR's own `.status` for completion markers.

**Q8. Editing an existing App's spec while its CD has a CUE break — does the underlying resource change?**

No. The webhook re-validates the CD's CUE on UPDATE and rejects the spec change at admission, so no new ApplicationRevision is created and `StateKeep` keeps replaying the previous one. The underlying resource is untouched. The only signal is the `kubectl` error from `apply`, so any CI pipeline that ignores apply exit codes will think the update succeeded.

---

## 4. Behaviour by user action

This section walks through each user-visible action and what actually happens on the cluster.

### 4.1 The upgrade itself

You run `helm upgrade` or `vela install --version=v1.11.0-alpha.3`. The controller pod restarts on the new image. The old controller pod terminates cleanly. The new pod comes up healthy.

**What changes immediately:** the running controller binary, linked against CUE v0.14.1.

**What does not change:** CRDs, CR objects, ApplicationRevisions, ResourceTrackers, rendered workloads. All preserved as-is.

**What you see in `kubectl get app -A`:** every Application still reports its pre-upgrade phase and health. Usually `phase=running, healthy=true`.

### 4.2 The next reconcile (within 5 minutes by default)

The controller dequeues each Application for periodic reconciliation. For an App whose CD now has a CUE break:

1. `appParser.GenerateAppFile()` succeeds — the AppFile is built from the frozen ApplicationRevision snapshot, which still has the old CD text inside.
2. The dispatcher's `healthCheck` runs first. This calls `collectHealthStatus → collectWorkloadHealthStatus → comp.EvalStatus → health.GetStatus`, which compiles **only** the `status.healthPolicy` CUE (not the workload template).
3. If the workload template would also be needed (for `getTemplateContext`, which reads the live workload's status), the template compilation runs through `velacuex.WorkloadCompiler.Get().CompileString()` against CUE 0.14.1 — and fails with the syntax error.
4. The error propagates up and reaches `applyComponentHealthToServices` at `application_controller.go:928-943`, which does:
   ```go
   if err != nil {
       ctx.Error(err, "Failed to collect health status")
   } else if status != nil {
       handler.services[idx].Healthy = status.Healthy
       handler.services[idx].Message = status.Message
       // ...
   }
   ```
5. The error is logged (`klog.Error`). The function returns void. `services[idx].Healthy` is never overwritten on the error path. The pre-upgrade value persists.
6. `dispatcher.run` checks `isHealth` to decide whether to dispatch. With the health check having errored, it tries to dispatch, and the dispatch path either fails (more logged errors) or falls through to StateKeep, which uses the cached bytes and bypasses CUE entirely.
7. The reconcile completes "successfully" from a status-write perspective. No condition flips. No event fires.

The log line you will see, every reconcile, until something rolls the revision:

```
E application_controller.go:905 "Failed to collect health status" err=<
  output.data.allLabels: Addition of lists is superseded by list.Concat
>
```

### 4.3 Drift correction after the upgrade

If a user deletes the rendered workload (`kubectl delete cm foo`):

**On a CD whose CUE still compiles on the current engine:** the controller's informer notices the delete event and triggers a reconcile immediately. The reconcile runs through the full path (health check succeeds, dispatch runs, StateKeep replays the cached manifest from `ResourceTracker.spec.compression.data`). The workload is recreated within ~1 second.

**On a pre-upgrade CD:** the watch-triggered reconcile still fires, but the health check errors as above. The dispatch path errors. StateKeep does eventually run on a subsequent periodic reconcile and replays the cached bytes (no CUE involved in that path), but the recovery delay matches the configured resync interval (5 min default).

In both cases, `StateKeep` reads the rendered manifest from the RT's compressed blob and re-applies it byte-for-byte. The recreated workload is identical to what was deleted.

### 4.4 Creating a new Application

The webhook chain at admission time:

```
kubectl apply -f new-app.yaml
   ↓
ApplicationValidator webhook (validating.applications)
   ↓ loads referenced ComponentDefinition
   ↓ compiles the CD's CUE template
   ↓ binds the App's properties to the CD's parameters
   ↓ evaluates the template
   ↓
admit / deny
```

Three failure cases:

| Case | Where caught | Error message format |
|---|---|---|
| CD's CUE has a compile-time error (deprecated syntax) | `validating.componentdefinitions` at CD apply, not at App apply | `admission webhook ... denied: Addition of lists is superseded by list.Concat` |
| CD compiles, but App's parameter values cause an evaluation error | `validating.applications` at App apply | `validation failed for workload: invalid operands "hello" and 42 to '+' (type string and int)` |
| CD compiles and evaluates fine; rendered manifest is semantically wrong (no controller will provision the external resource) | Neither webhook catches it | App is admitted, reports `healthy=true`, external resource is missing |

The S3 short-circuit case (the third row) is the most dangerous because there is no admission signal at all. The CR object exists in the API, satisfying KubeVela's default "does the resource exist?" health check, while the actual cloud resource is never created.

### 4.5 Editing an existing Application

Edits go through the App validating webhook on every UPDATE. The webhook re-evaluates the App's properties against the (current) CD.

- If the CD is healthy: the edit is admitted, a new ApplicationRevision is created (assuming no `publishVersion` annotation pins it), and the workload is patched on the next reconcile.
- If the CD has a CUE break: the edit is denied at admission. The App's spec is unchanged. The previous ApplicationRevision keeps being replayed by StateKeep. The underlying workload stays put.

A CI pipeline that runs `kubectl apply` and only checks the exit code will be misled in the second case. The `kubectl apply` returns non-zero, but pipelines that swallow apply errors will see "all clean" while having silently no-op'd the update.

### 4.6 Fixing the pre-upgrade CD

Updating the CD itself goes through the CD validating webhook on UPDATE. With the fixed CUE (e.g. switching `+` for `list.Concat`), the webhook accepts the update and:

- A new `DefinitionRevision` (e.g. `audit-merge-v2`) is created.
- The CD's `status.latestRevision` advances to v2.
- The OpenAPI schema ConfigMap (`component-schema-<name>`) is regenerated.

But **none of this rolls the ApplicationRevision for any App referencing the CD**. Each App keeps its frozen v1 ApplicationRevision, which still has the pre-upgrade CD text snapshotted inside it. The controller keeps logging the same CUE error every reconcile, the workload keeps being replayed from the RT byte cache, status stays falsely green.

### 4.7 Forcing the App to pick up the fixed CD

Three triggers, each documented in §5.4. The most common is:

```bash
kubectl annotate app -n <ns> <app-name> \
  app.oam.dev/publishVersion=post-cue-fix-$(date +%Y%m%d) --overwrite
```

On the next reconcile, the controller observes that the publishVersion has changed, builds a new ApplicationRevision from the current spec (which captures the fixed CD), renders cleanly, and patches the workload. The CUE error stops appearing in the controller log.

---

## 5. Deep dive: how the mechanics work

### 5.1 ResourceTracker as a byte cache

`ResourceTracker` is the cluster-scoped object KubeVela uses to track resources owned by an Application. The relevant fields:

```go
// apis/core.oam.dev/v1beta1/resourcetracker_types.go
type ResourceTrackerSpec struct {
    Type                  ResourceTrackerType
    ApplicationGeneration int64
    Compression           ResourceTrackerCompression  // zstd blob holds the rendered manifests
    ManagedResources      []ManagedResource           // alternative uncompressed form
}
```

When compressed (the default for non-trivial Apps), `Compression.Data` holds the full rendered manifest list, zstd-encoded. Decoded:

```yaml
[
  {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "namespace": "default",
    "name": "audit-deploy-pods",
    "component": "web",
    "raw": {
      "apiVersion": "apps/v1",
      "kind": "Deployment",
      "metadata": { ... },
      "spec": { "replicas": 5, ... }
    }
  }
]
```

The `raw` field carries the full Kubernetes object that the controller produced from the App + CD. `StateKeep` reads this and re-applies it to the API server via the plain client. **No CUE is involved in the replay path.**

This is the safety net. The data plane is decoupled from the rendering engine. As long as the cached bytes are valid Kubernetes objects, the workload can be maintained regardless of whether the CUE engine could re-render them today.

It is also the trap. Operators looking at the running workload see "everything works" while the rendering engine has been unable to re-evaluate the stored template since the upgrade.

#### Decoding the cache for inspection

```bash
kubectl get resourcetracker <rt-name> -o jsonpath='{.spec.compression.data}' \
  | base64 -d \
  | python3 -c "import sys,json,zstandard; print(json.dumps(json.loads(zstandard.ZstdDecompressor().decompress(sys.stdin.buffer.read())), indent=2))"
```

(`pip install zstandard` if not already installed.)

### 5.2 ApplicationRevision lifecycle

Each ApplicationRevision is a complete snapshot of:

- The Application's spec at the moment the revision was created
- All ComponentDefinitions referenced by that App, byte-for-byte (`Spec.ComponentDefinitions[name].Spec`)
- All TraitDefinitions, PolicyDefinitions, WorkflowStepDefinitions
- All Policies and Workflow

The revision is named `<app-name>-v<N>`. The latest is referenced from `Application.status.latestRevision`.

When the controller reconciles an App, it compares the *prospective* new revision (built from the live spec + live referenced definitions) against the *latest* stored revision. If they are equivalent under the configured comparison function, the existing revision is reused. Otherwise, a new revision is built.

The comparison function depends on annotations — see §5.4.

### 5.3 The two webhook layers

KubeVela ships two distinct validating admission webhooks. Each catches a different class of CUE error.

#### ComponentDefinitionValidator (`validating.core.oam-dev.v1beta1.componentdefinitions`)

Runs on CD CREATE and UPDATE. Validates that the CD's CUE template:

- Parses successfully under the controller's CUE library version
- Has no compile-time errors (deprecated syntax, missing imports, structural issues)

It cannot bind concrete parameters at this stage because the parameters come from each consuming Application. So it only catches *compile-time* errors. Evaluation-time errors (type mismatches, constraint violations on concrete values) pass through this webhook unchanged.

#### ApplicationValidator (`validating.core.oam.dev.v1beta1.applications`)

Runs on App CREATE and UPDATE. For each component:

- Looks up the referenced ComponentDefinition
- Binds the App's `properties` to the CD's parameters
- Evaluates the template end-to-end

This catches everything the CD validator did **plus** evaluation-time errors that surface only when concrete parameter values are bound.

Net effect for users:

| Error type | Caught at | Layer |
|---|---|---|
| `list1 + list2` (compile-time, CUE 0.11+) | CD admission | First |
| `parameter.a + parameter.b` where a=string, b=int (eval-time) | App admission | Second |
| Rendered output is structurally valid but semantically wrong (S3 case) | Neither | None — App is admitted |

### 5.4 The three triggers for new ApplicationRevisions

`pkg/controller/core.oam.dev/v1beta1/application/revision.go:369-376`:

```go
isLatestRev := deepEqualAppInRevision(h.latestAppRev, h.currentAppRev)
if metav1.HasAnnotation(h.app.ObjectMeta, oam.AnnotationAutoUpdate) {
    isLatestRev = h.app.Status.LatestRevision.RevisionHash == h.currentRevHash &&
                  DeepEqualRevision(h.latestAppRev, h.currentAppRev)
}
if h.latestAppRev != nil && oam.GetPublishVersion(h.app) != oam.GetPublishVersion(h.latestAppRev) {
    isLatestRev = false
}
```

Three independent triggers, each tested at this gate:

#### Trigger A: App spec edit (default behaviour, no annotations)

`deepEqualAppInRevision` compares the App's spec, policies, and workflow only. **It does not include ComponentDefinitions.** So a spec edit produces a new revision (which happens to capture the current CD as a side-effect), while a pure CD update does not.

#### Trigger B: `app.oam.dev/publishVersion` annotation change

The third `if` clause: when the publishVersion on the App differs from the publishVersion on the latest revision, `isLatestRev` is forced to `false`. A new revision is built unconditionally.

This is the most common remediation trigger. It does not depend on whether the spec actually changed — bumping the annotation alone is sufficient.

#### Trigger C: `app.oam.dev/autoUpdate: "true"` annotation present

The second `if` clause: when this annotation is present, the comparison switches from `deepEqualAppInRevision` to `DeepEqualRevision` (`revision.go:416`), which also walks `Spec.ComponentDefinitions[key].Spec`. With this switch, a pure CD update causes the equality check to fail, and a new revision is built automatically.

### 5.5 RT object name vs RT contents

When `autoUpdate` fires a new revision after a CD update:

- A new ApplicationRevision (e.g. `audit-app-deploy-v2`) is created.
- The ResourceTracker **keeps its existing name** (`audit-app-deploy-v1-default`) and outer labels (`appRevision=audit-app-deploy-v1`).
- The RT's `spec.compression.data` payload is **rewritten in-place** to reflect the new rendered manifests.
- The actual workload is patched via the standard apply path.

Visually:

| Surface | After CD update with autoUpdate |
|---|---|
| `kubectl get apprev` | Shows the new v2 revision |
| `kubectl get resourcetracker` | Shows the same v1-default name as before |
| Decoded `spec.compression.data` | Contains the new v2 manifest content |
| `kubectl get deployment` / `cm` | Reflects the new manifest |

Operators auditing what an Application is "supposed to deploy" by reading the RT name and labels alone will be misled. The decoded compression blob is the source of truth.

### 5.6 The two CUE compilation paths

The controller has two paths that invoke the CUE engine, and they are independent:

#### Render / dispatch path

`pkg/cue/definition/template.go:126` (workload) and `:312` (trait). This compiles the full workload template plus the bound parameters plus the runtime context. Fires when:

- A new ApplicationRevision is built and the manifests need to be produced
- The dispatcher decides re-dispatch is required (failed health, properties changed, autoUpdate)

#### Health / status evaluation path

`pkg/cue/definition/health/health.go:52-75`. This compiles **only** the `status.healthPolicy` and `status.customStatus` expressions plus the runtime context (live workload status read from the API). The workload template is not in this buffer.

The difference matters for understanding why an App can report `healthy=true` while the controller is logging "Failed to collect health status" — the health expression itself may compile fine, but the upstream `getTemplateContext` call (which reads the live workload) can error in ways that propagate to the same `application_controller.go:905` swallow point.

---

## 6. The silent-failure surfaces

Six status surfaces lie to operators after a CUE-breaking upgrade. One does not.

| Surface | Reliability post-upgrade | Why |
|---|---|---|
| `Application.status.services[*].healthy` | Lies — keeps pre-upgrade value | Bug 1: health-check error swallowed at `application_controller.go:905`, field never overwritten on error |
| `Application.status.status` (phase) | Lies — stays `running` | Same root cause as above |
| `Application.status.conditions[*]` | Lies — timestamps frozen at pre-upgrade values | Conditions only roll when a new revision actually applies |
| `vela status` CLI output | Lies — reads `services[*].healthy` and inherits its staleness | — |
| `apply.go` "creating object" log lines | Misleading — emitted before the API call | Bug 2: `loggingApply` ordering |
| Application spec edits while `publishVersion` is set | Misleading — kubectl returns OK, generation increments, render does not | Documented behaviour, not a bug, but a gotcha |
| **`ComponentDefinition.status.conditions[*]`** | **Reliable** | This is the one signal that surfaces honestly |

The post-upgrade health check that actually works:

```bash
kubectl get componentdefinition -A \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.status=="False")].message}{"\n"}{end}'
```

> **Caveat:** the CD's `Synced=True` condition is also stale-prone once a CD has recovered — see Bug 1 in §8. The condition reliably reports negative state, less reliably reports recovery.

---

## 7. Known upstream bugs

Three distinct bugs that compound to make CUE-upgrade failures hard to diagnose. Each is a small fix individually.

### Bug 1: health-check error swallowed

**Location:** `pkg/controller/core.oam.dev/v1beta1/application/application_controller.go:928-943`

```go
func applyComponentHealthToServices(...) {
    for idx, svc := range handler.services {
        if component, exists := componentMap[svc.Name]; exists {
            _, status, _, _, err := healthCheck(ctx, component, ...)
            if err != nil {
                ctx.Error(err, "Failed to collect health status")  // logged, not returned
            } else if status != nil {
                handler.services[idx].Healthy = status.Healthy
                // ...
            }
        }
    }
    // void return — caller has no signal that anything failed
}
```

**Impact:** `services[idx].Healthy` is never updated on the error path. The field retains its pre-error value indefinitely. This is the root cause of the false-green Application status.

**Suggested fix:** propagate the error to the caller, and on the error path explicitly write `services[idx].Healthy = false` with the error message in `Message`. Alternatively, surface the error via a new `Healthy=False` condition with `Reason=HealthCheckError`.

### Bug 2: apply log emitted before the API call

**Location:** `pkg/utils/apply/apply.go:205, 212, 237, 251, 261, 325`

Every `loggingApply(...)` call fires before the corresponding `c.Create / c.Update / c.Patch / c.Delete`. If the API call fails, no paired log line records the failure at info level.

**Impact:** controller logs show `"creating object" name="foo"` even when the subsequent `c.Create()` returned an error. Operators tailing logs to debug "did the apply happen?" are misled.

**Suggested fix:** emit a paired result log after each API call:

```go
err := c.Create(ctx, desired)
if err != nil {
    klog.InfoS("create failed", "name", ..., "err", err)
    return errors.Wrap(err, "cannot create object")
}
klog.InfoS("created", "name", ...)
```

### Bug 3: `ValidateUndeclaredParameters` feature gate not wired into Helm chart

**Definition:** `pkg/features/controller_features.go:140,171` — Alpha, default `false`.
**Consumer:** `pkg/appfile/validate.go:174`.

**Missing wiring:**

- `charts/vela-core/values.yaml` has no `validateUndeclaredParameters` key.
- `charts/vela-core/templates/kubevela-controller.yaml` has no `--feature-gates=ValidateUndeclaredParameters=...` flag line.

**Impact:** `helm install --set featureGates.validateUndeclaredParameters=true` is a silent no-op. The gate cannot be enabled via Helm. The only way to flip it is to manually edit the controller deployment after install.

**Suggested fix:** two-line chart patch — add the key to `values.yaml`, add the flag-construction line to the controller template.

---

## 8. Source of truth

Tested on commit `1ac24ed08` of github.com/kubevela/kubevela (branch `fix/defkit-changes-for-resource-builder-docs`), Go module `cuelang.org/go v0.14.1`. The 1.10.6 baseline was `cuelang.org/go v0.9.2`, confirmed by `git -C kubevela show v1.10.6:go.mod | grep cuelang`.

Test timeline, UTC, 2026-05-25:

| Phase | Timestamp | Event |
|---|---|---|
| Initial setup | 05:01 | k3d cluster created |
| | 05:05 | KubeVela 1.10.6 installed (CUE 0.9.2) |
| | 05:06:54 | CD (with CUE 0.9.2 syntax — valid at the time) + App applied; baseline healthy |
| Upgrade | 05:08 | KubeVela upgraded to 1.11.0-alpha.3 (CUE 0.14.1) |
| Row 1 verification | 05:08:43 | First post-upgrade reconcile, health-collection error fires |
| | 05:13:43 | Second reconcile (5 min later), same error |
| | 05:18:43 | Third reconcile, same error |
| Row 2 (pre-upgrade-CD case) | ~05:11 | CM deleted manually |
| | 05:13:43 | CM recreated on next periodic tick |
| Rows 6/7 verification | 05:15:44 | CD fixed |
| | 05:18:43 | App still failing health collection at this point |
| | 05:19:40 | `publishVersion` bumped → App clean |
| **Strict re-audit** | 08:08 — 08:15 | All rows 3-9 re-verified fresh; live cluster evidence captured per row |

---

## Appendix A — Test fixtures

Each manifest below maps to specific rows in the scenario matrix. Copy them into any namespace on a KubeVela 1.11+ cluster to reproduce the corresponding behaviour.

### A.1 `01-cd-old-cue-compile.yaml` — Row 4

CD using `parameter.left + parameter.right` for list concatenation. Worked under CUE 0.9.2; the `+` operator on lists was deprecated in 0.11. Rejected by the ComponentDefinition admission webhook on 1.11+ when re-applied.

```yaml
apiVersion: core.oam.dev/v1beta1
kind: ComponentDefinition
metadata:
  name: audit-old-cue-compile
  namespace: vela-system
spec:
  workload:
    definition:
      apiVersion: v1
      kind: ConfigMap
  schematic:
    cue:
      template: |
        import "strings"

        output: {
          apiVersion: "v1"
          kind:       "ConfigMap"
          metadata: name: parameter.name
          data: {
            allLabels: strings.Join(parameter.left + parameter.right, ",")
          }
        }
        parameter: {
          name:  string
          left:  [...string]
          right: [...string]
        }
```

### A.2 `02-cd-fixed.yaml` — Rows 6, 7 (baseline working CD)

```yaml
apiVersion: core.oam.dev/v1beta1
kind: ComponentDefinition
metadata:
  name: audit-merge
  namespace: vela-system
spec:
  workload:
    definition:
      apiVersion: v1
      kind: ConfigMap
  schematic:
    cue:
      template: |
        import (
          "list"
          "strings"
        )

        output: {
          apiVersion: "v1"
          kind:       "ConfigMap"
          metadata: name: parameter.name
          data: {
            allLabels:        strings.Join(list.Concat([parameter.left, parameter.right]), ",")
            cdRevisionMarker: "v1-baseline"
          }
        }
        parameter: {
          name:  string
          left:  [...string]
          right: [...string]
        }
```

### A.3 `03-cd-eval-error.yaml` — Rows 3, 4b (evaluation-time error)

Compiles fine because parameters are untyped (`_`). The `parameter.a + parameter.b` operation only errors at evaluation time, when concrete values are bound. Passes CD admission; fails at Application admission.

```yaml
apiVersion: core.oam.dev/v1beta1
kind: ComponentDefinition
metadata:
  name: audit-eval-error
  namespace: vela-system
spec:
  workload:
    definition:
      apiVersion: v1
      kind: ConfigMap
  schematic:
    cue:
      template: |
        output: {
          apiVersion: "v1"
          kind:       "ConfigMap"
          metadata: name: parameter.name
          data: joined: parameter.a + parameter.b
        }
        parameter: {
          name: string
          a:    _
          b:    _
        }
```

### A.4 `04-cd-deploy.yaml` — Row 8, Deployment example (baseline `replicas: 2`)

```yaml
apiVersion: core.oam.dev/v1beta1
kind: ComponentDefinition
metadata:
  name: audit-deploy
  namespace: vela-system
spec:
  workload:
    definition:
      apiVersion: apps/v1
      kind: Deployment
  schematic:
    cue:
      template: |
        output: {
          apiVersion: "apps/v1"
          kind:       "Deployment"
          metadata: name: parameter.name
          spec: {
            replicas: 2
            selector: matchLabels: app: parameter.name
            template: {
              metadata: labels: app: parameter.name
              spec: containers: [{
                name:  "main"
                image: "nginx:1.25-alpine"
              }]
            }
          }
        }
        parameter: {
          name: string
        }
```

### A.5 `05-cd-deploy-replicas5.yaml` — Row 8, Deployment example (CD update to `replicas: 5`)

Identical to A.4 except `replicas: 5`. Used to trigger the autoUpdate-driven rollover.

### A.6 `06-cd-fixed-v2.yaml` — Rows 7, 8 (CD update for `audit-merge`)

Identical structure to A.2 but with `cdRevisionMarker: "v2-AFTER-AUTOUPDATE"` and an additional `cdRevisionNote` field. The marker change makes rollover visible in the rendered ConfigMap.

### A.7 `10-fakebucket-crd.yaml` — Row 5 (CRD for S3 short-circuit test)

Defines a `FakeBucket` CRD with no controller backing it. Used to simulate the case where a CD renders a CR but no operator provisions the actual external resource.

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: fakebuckets.audit.example.com
spec:
  group: audit.example.com
  scope: Namespaced
  names:
    kind: FakeBucket
    plural: fakebuckets
    singular: fakebucket
    shortNames: ["fb"]
  versions:
    - name: v1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                bucketName:
                  type: string
                region:
                  type: string
            status:
              type: object
              properties:
                ready:
                  type: boolean
                arn:
                  type: string
```

### A.8 `11-cd-fakebucket.yaml` — Row 5 (CD rendering the FakeBucket)

```yaml
apiVersion: core.oam.dev/v1beta1
kind: ComponentDefinition
metadata:
  name: audit-fakebucket
  namespace: vela-system
spec:
  workload:
    definition:
      apiVersion: audit.example.com/v1
      kind: FakeBucket
  schematic:
    cue:
      template: |
        output: {
          apiVersion: "audit.example.com/v1"
          kind:       "FakeBucket"
          metadata: name: parameter.name
          spec: {
            bucketName: parameter.bucketName
            region:     parameter.region
          }
        }
        parameter: {
          name:       string
          bucketName: string
          region:     string
        }
```

### A.9 `21-app-fixed.yaml` — Rows 2, 6, 7 (App against working CD, no annotations)

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: audit-app-fixed
  namespace: default
spec:
  components:
    - name: cfg
      type: audit-merge
      properties:
        name: audit-fixed-cm
        left:  ["a=1", "b=2"]
        right: ["c=3"]
```

### A.10 `22-app-eval-error.yaml` — Row 4b (App that hits eval-time CUE error at admission)

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: audit-app-evalerror
  namespace: default
spec:
  components:
    - name: cfg
      type: audit-eval-error
      properties:
        name: audit-evalerror-cm
        a: "hello"
        b: 42
```

### A.11 `23-app-deploy.yaml` — Row 8, Deployment example (App with `autoUpdate: "true"`)

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: audit-app-deploy
  namespace: default
  annotations:
    app.oam.dev/autoUpdate: "true"
spec:
  components:
    - name: web
      type: audit-deploy
      properties:
        name: audit-deploy-pods
```

### A.12 `25-app-fakebucket.yaml` — Row 5 (App referencing FakeBucket CD)

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: audit-app-fakebucket
  namespace: default
spec:
  components:
    - name: bucket
      type: audit-fakebucket
      properties:
        name:       audit-bucket-1
        bucketName: my-prod-data
        region:     us-east-1
```

### A.13 `26-app-eval-valid.yaml` — Row 3 (App with valid params, then patched to break)

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: audit-app-evalvalid
  namespace: default
spec:
  components:
    - name: cfg
      type: audit-eval-error
      properties:
        name: audit-evalvalid-cm
        a: "hello"
        b: "world"
```

---

## Appendix B — Strict audit results

Every row in the scenario matrix verified against the live cluster, with timestamps from the 2026-05-25 run.

| Row | Verdict | Captured | Evidence |
|---|---|---|---|
| 1 | PASS | 05:08:43 / 05:13:43 / 05:18:43 | Three consecutive reconciles, same `application_controller.go:905 "Failed to collect health status"` error, `services[0].healthy` never updated |
| 2 | PASS (refined) | 05:13:43 (pre-upgrade-CD) + 08:14:09→08:14:10 (normal) | Two states tested: normal CD recovers sub-second on watch event; pre-upgrade CD recovers on next periodic tick |
| 3 | PASS | 08:13:48 | App spec patch denied by `validating.core.oam.dev.v1beta1.applications` with type-mismatch error |
| 4 | PASS | 08:08:29 | CD denied by `validating.core.oam-dev.v1beta1.componentdefinitions`: `Addition of lists is superseded by list.Concat` |
| 4b | PASS | 08:08:42 | CD admission accepts; App admission denies with `invalid operands "hello" and 42 to '+' (type string and int)` |
| 5 | PASS | 08:09:20 | FakeBucket CR exists, `status: {}` empty (no controller), App reports `phase=running, healthy=true` |
| 6 | PASS | 08:10:56 | New `audit-merge-v2` DefinitionRevision exists; App still on `audit-app-fixed-v1` with same hash; ConfigMap unchanged |
| 7 | PASS | 08:11:24 | `publishVersion=audit-pv-1` → new `audit-app-fixed-v2` AppRev; ConfigMap now shows new marker + new field |
| 8 | PASS | 08:12:15 → 08:13:07 | `autoUpdate: "true"` triggered automatic new AppRev after CD change. Tested with a Deployment `replicas: 2 → 5` CD update: Deployment scaled end-to-end, RT name stayed `v1-default`, decoded RT cache showed `replicas: 5` and `appRev_label: audit-app-deploy-v2` |
