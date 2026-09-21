# What happens to existing KubeVela applications when a CUE-breaking upgrade lands

The headline is annoying: the workload keeps serving traffic, every kubectl status field stays green, and the controller silently fails to evaluate health on every reconcile until somebody intervenes. The post-upgrade story is not "things break loudly." It is things drifting quietly while every status field still says green.

Tested live on a fresh k3d cluster, KubeVela 1.10.6 (CUE 0.9.2) up to 1.11.0-alpha.3 (CUE 0.14.1), with a custom ComponentDefinition using `parameter.left + parameter.right` instead of `list.Concat([parameter.left, parameter.right])`. That's the canonical CUE 0.11 break.

## The matrix

| # | Scenario | Workload running? | Status correct? | Verified |
|---|---|---|---|---|
| 1 | Idle reconcile right after upgrade | Yes (RT replay) | No, stays at last pre-upgrade value (`true`) | Live: log error every 5 min, status never updates |
| 2 | Drift correction (workload deleted by hand) | Yes, via `StateKeep` — but periodic, not event-driven. The controller has **no watch on rendered child resources** (no `.Owns()`); recovery only happens on the next reconcile (resync / spec-change / RT-delete) for both normal and broken CDs | Same recovery path in both cases; the difference is broken CDs additionally report stale health, not slower drift correction | Live both states. Normal CD: CM observed recreated ~1 s after delete (08:14:09 → 08:14:10) — **coincidental timing against the 45 s resync, not a watch event**. CUE-broken CD: CM recreated on the next periodic tick (05:13:43). Gap = configured resync interval (5 min default, 45 s on this test cluster). See "Drift correction is periodic, not event-driven" below |
| 3 | Edit Application spec while CD is still broken | n/a, webhook rejects | n/a | Live: kubectl Forbidden with the CUE error inline |
| 4 | Create new Application against broken CD (compile-time CUE error) | n/a, CD itself rejected at create | n/a | Live: CD admission denied; App never reaches it |
| 4b | Create new Application against CD with evaluation-time error (needs concrete parameters: type mismatch, missing required field, constraint violation) | n/a, App rejected at create (CD admission passes) | n/a | Live: CD admission accepts, App admission denies with CUE error inline |
| 5 | New Application against a CD that compiles AND evaluates fine but renders a semantically wrong manifest (the S3 short-circuit case) | external resource never created | reports `healthy=true` falsely because with no custom `healthPolicy` the default returns healthy unconditionally — it never inspects the resource's own `.status` (`pkg/cue/definition/health/health.go:52-54`) | Live: Fake Bucket CRD with no controller — CR object exists, App reports healthy |
| 6 | Fix the CD, leave the App alone | Yes | Still broken until a new ApplicationRevision rolls | Live: same CUE error every reconcile after CD fix |
| 7 | Fix the CD + bump `app.oam.dev/publishVersion` | Yes | Correct | Live: clean reconcile, error gone |
| 8 | Update CD on an App with `app.oam.dev/autoUpdate: "true"` | Yes, reflects new CD | Correct | Live: new AppRev created automatically, workload patched, RT object name unchanged but cache rewritten in-place |
| 9 | Same as 8 but the CD change is `replicas: 2 → 5` on a Deployment | Yes, replicas scale to 5 | Correct | Live: `Deployment.spec.replicas` patched, `status.replicas` reaches 5, RT name still v1 |

Row 6 is the one that bites people. Row 1 is the headline weirdness. Rows 8 and 9 are the answer to "does updating a CD reapply the App?" — yes, but only with the right annotation, and the RT plays a deceptive game with naming. The rest are either safety nets (3, 4) or expected paths (7).

## Quick reference Q&A

### After a KubeVela upgrade breaks the CUE in an existing CD, can I trust the App's reported status?

No. `services[*].healthy` keeps whatever value it had before the upgrade (usually `true`) because the controller logs the CUE error and returns void, so the field never gets rewritten. To check whether you're actually broken, look at the corresponding ComponentDefinition's `Synced=False` condition.

### Does the running workload itself get disrupted during reconcile after the upgrade?

No, it stays put. ResourceTracker holds the rendered manifest and `StateKeep` replays those bytes through the plain Kubernetes client — CUE doesn't enter the picture, so drift correction keeps working even with rendering broken. Drift correction is **periodic, not event-driven, for both normal and broken CDs**: the Application controller has no watch on rendered child resources (no `.Owns()`; it watches only ResourceTracker on deletion, PolicyDefinition, and the Application itself — `application_controller.go:662-731`), so a manually deleted ConfigMap is invisible until the next reconcile. That reconcile fires on the periodic resync (`ApplicationReSyncPeriod`, default 5 min at `pkg/controller/common/vars.go:30`, flag `--application-re-sync-period`, configurable down to seconds), on a spec change, or on an RT deletion. A broken CD does not lose a faster path — there was never one; what it loses is honest health reporting (see the swallowed error below).

### After fixing the broken CD, does the App's calculated status fix itself?

Not on its own. The App keeps replaying its frozen pre-upgrade revision, which still has the broken CD baked into it. You need a new ApplicationRevision before status calculation succeeds again: bump `app.oam.dev/publishVersion`, edit the App spec (only works if no publishVersion is set), or have `autoUpdate: "true"` on the App already.

### When a CD is updated, does the RT's cached manifest get regenerated — even if only the template body changed and the parameters didn't?

With `autoUpdate: "true"` on the App, yes — `spec.compression.data` is rewritten in-place to the new CD output regardless of whether parameters changed. The RT object's name and outer labels stay frozen at the original revision though, which is misleading at a glance; you have to decode the blob to see the rollover. Apps pinned to a specific DefinitionRevision (via `app.oam.dev/revision-only` or `definitionRevision: name@v1`) skip the rollover entirely.

### If I create a new Application against a CD whose CUE is broken at compile time, does the webhook reject it?

Yes, at the ComponentDefinition admission layer. `kubectl apply` of a CD using `parameter.left + parameter.right` comes back with `admission webhook ... denied the request: Addition of lists is superseded by list.Concat`. The CD itself never reaches the cluster, so no consuming App can be built against it.

### What if the CD compiles fine but evaluates wrong only when parameters are bound (string + int, missing required field, constraint violation)?

The validator can't substitute parameters that don't exist at CD admission time, so this class of error passes the CD webhook and surfaces only at Application admission, when the consuming App's properties are bound and the template actually evaluates. User is still blocked from creating the App, but the rejection is at a different layer with the App's name on it. Useful for triage: if you see admission failures on Apps but the CD itself looks accepted, you're in this case.

### What about the "S3 short-circuit" case — a CD whose CUE compiles AND evaluates fine but renders a logically wrong manifest?

Neither webhook catches it. With no custom `status.healthPolicy`, KubeVela's default health evaluation returns healthy unconditionally — `CheckHealth` returns `true` when the health template is empty (`pkg/cue/definition/health/health.go:52-54`); it never inspects the rendered resource's own `.status`. The controller successfully rendered the CR object and posted it to the API, so the App reports `healthy=true` indefinitely. The external action that would provision the actual S3 bucket never fires. The only honest signal is checking the underlying external resource directly (or writing a custom `status.healthPolicy` that inspects the CR's own `.status` for completion markers).

### Editing an existing App's spec while its CD has a CUE break — does the underlying resource change?

No. The webhook re-validates the CD's CUE on UPDATE and rejects the spec change at admission, so no new ApplicationRevision is created and `StateKeep` keeps replaying the previous one. Underlying resource: untouched. The only signal is the kubectl error from `apply`, so any CI pipeline that ignores apply exit codes will think the update succeeded.

## Setup

Nothing fancy. Fresh k3d cluster, no prior vela state:

```bash
k3d cluster create kubevela --wait
vela install --version=v1.10.6        # CUE 0.9.2 era
# apply custom CD with parameter.left + parameter.right
# apply Application using it
# baseline: phase=running, healthy=true, ConfigMap rendered correctly
vela install --version=v1.11.0-alpha.3 # CUE 0.14.1 era
```

The ComponentDefinition wraps a ConfigMap and joins two label arrays:

```cue
import "strings"
output: {
  apiVersion: "v1"
  kind:       "ConfigMap"
  metadata: name: parameter.name
  data: allLabels: strings.Join(parameter.left + parameter.right, ",")
}
```

`parameter.left + parameter.right` is the trap. Works under 0.9.2. Fails under 0.14.1 with `Addition of lists is superseded by list.Concat`. Every other CUE 0.11 break behaves the same way for the purposes of this writeup.

## What the workload sees

Nothing. Before the upgrade I had a rendered ConfigMap with `data.allLabels: "app=foo,tier=web,env=prod,version=1"`. After the upgrade, same ConfigMap, same data, same labels. Helm uninstalled the old controller, helm installed the new one, the controller restarted, and the underlying object was never touched.

Delete that ConfigMap by hand and the next reconcile recreates it identically. CUE has nothing to do with this. Each managed resource's manifest is stored in `ManagedResource.Data` (`apis/core.oam.dev/v1beta1/resourcetracker_types.go:133`, json tag `raw`); when the zstd feature gate is on, the whole managed-resources list is persisted compressed under `ResourceTrackerSpec.Compression` (embedded `compression.CompressedText`) by the custom `MarshalJSON`/`UnmarshalJSON` (`resourcetracker_types.go:86-126`) and decompressed back into `ManagedResources` on read. `StateKeep` iterates `rt.Spec.ManagedResources` and calls `mr.ToUnstructuredWithData()` (`pkg/resourcekeeper/statekeep.go:77`) to decode each manifest, then re-applies it through the applicator (`statekeep.go:105`). The rendering engine never enters the picture.

That is the safety net. It is also why the upgrade looks fine when it isn't.

## What the controller sees

The kubectl-visible Application status, captured five minutes after the upgrade landed:

```
NAME               COMPONENT   TYPE                  PHASE     HEALTHY   AGE
legacy-merge-app   cfg         legacy-config-merge   running   true      6m
```

Controller log from the same window:

```
E0525 05:08:43 application_controller.go:934 "Failed to collect health status" err=<
  GenerateComponentManifest: evaluate base template app=legacy-merge-app in namespace=default:
  validation failed for workload cfg:
    output.data.allLabels: Addition of lists is superseded by list.Concat;
    see https://cuelang.org/e/v0.11-list-arithmetic
>
```

Then the reconcile finishes successfully. `Workflow return state=succeeded`, `Successfully garbage collect`, `End reconcile application`. The CUE failure only happens in the health-collection path (`evalStatus` → `applyComponentHealthToServices`); `GenerateAppFile` on the main dispatch path does not fail here because the App replays its frozen pre-upgrade revision, so the reconcile runs to completion (and `stateKeep` at `application_controller.go:336` still runs — which is why a deleted resource is still recreated on the periodic tick). The error is caught at `application_controller.go:934`, logged via `ctx.Error`, and the function returns void. The caller has no way to know it failed, so `services[*].Healthy` is never overwritten. It keeps the pre-upgrade value forever.

This is the fail-and-continue pattern I'd been calling Bug 7.2. `applyComponentHealthToServices` (`application_controller.go:928-943`) discards the error and writes `services[idx].Healthy = status.Healthy` only on success. On failure the field retains whatever it had before. The health-check path re-evaluates the CUE template — `checkComponentHealth` → `prepareWorkloadAndManifests` → `GenerateComponentManifest` (`pkg/controller/core.oam.dev/v1beta1/application/generator.go:277,415`) — which is why it fails for a broken CD while the replayed workload stays untouched.

The one place the failure surfaces honestly is the ComponentDefinition's own status:

```
$ kubectl get componentdefinition -n vela-system legacy-config-merge \
  -o jsonpath='{range .status.conditions[*]}type={.type} status={.status}/{.reason}{"\n"}{end}'
type=Synced status=False/ReconcileError
msg=cannot store capability legacy-config-merge in ConfigMap:
    failed to generate OpenAPI v3 JSON schema for capability legacy-config-merge:
    output.data.allLabels: Addition of lists is superseded by list.Concat
```

So the post-upgrade health check that works:

```bash
kubectl get componentdefinition -A \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.status=="False")].message}{"\n"}{end}'
```

There is a catch with this signal too, in the section below on stale surfaces.

## Why fixing the CD isn't enough

The instinct is obvious. Rewrite the CD's template to use `list.Concat`, apply it, done. The webhook accepts the fix. A new `DefinitionRevision` (`legacy-config-merge-v2`) gets created. The schema ConfigMap stores cleanly. CD `status.conditions` should flip back to green. Looks resolved.

Then the next App reconcile happens, and the same CUE error reappears:

```
05:18:43 "Successfully prepare current app revision"
  revisionName="legacy-merge-app-v1" revisionHash="d36d7f750e0ec421"
  isNewRevision=false
05:18:43 "Failed to collect health status" err=<
  output.data.allLabels: Addition of lists is superseded by list.Concat
>
```

`isNewRevision=false`. The controller reused `legacy-merge-app-v1`. That revision was created on 1.10.6 and has the broken CD CUE frozen inside it. The decision to mint a new ApplicationRevision is keyed off the Application's spec hash, not off CD updates underneath. App spec didn't change, so the same v1 revision keeps getting replayed, and the broken CUE inside it keeps failing.

To force a new revision, bump the publish-version annotation:

```bash
kubectl annotate app -n default legacy-merge-app \
  app.oam.dev/publishVersion=post-fix --overwrite
```

After that, `legacy-merge-app-v2` exists with a different hash referencing the fixed CD, the next reconcile picks it up, and the error vanishes from the log.

This is the step people miss. The CD goes quiet, the schema ConfigMap repopulates, and it looks like the fix is done. The App keeps logging the original error every reconcile until somebody cuts a new revision.

## You can't create a broken CD post-upgrade

Tried both ways live, both rejected at admission:

```
$ kubectl apply -f broken-new-cd.yaml
Error from server (Forbidden): admission webhook
  "validating.core.oam-dev.v1beta1.componentdefinitions" denied the request:
  output.data.allLabels: Addition of lists is superseded by list.Concat
```

Same outcome for UPDATE-back-to-broken on an existing CD: webhook PATCH path rejects with the same CUE error. So the broken-CD universe is closed under the new controller. It can only contain CDs that already existed on the cluster before the upgrade. Anything you try to create or modify after the upgrade hits the new CUE engine at admission and gets caught.

Implication: post-upgrade the bad-CD list shrinks monotonically. Every CD you fix stays fixed. You can't accidentally regress one.

## Three drift-correction paths, easy to confuse

They look the same from the outside and are actually independent. All three are driven by a reconcile — there is no event-driven watch on the rendered resources themselves, so every one of these recovers only when the next reconcile fires (periodic resync, spec change, or RT deletion), never instantly off the resource's own delete event.

If only the workload was deleted (RT intact), StateKeep decodes each manifest from `rt.Spec.ManagedResources` (`mr.ToUnstructuredWithData()`) and re-applies through the applicator. CUE never runs. This works through the upgrade unconditionally.

If the RT was deleted but the App revision survives, the controller tries to re-render via CUE on the next reconcile. With a broken CD this fails. There's an unrelated bug worth knowing: `pkg/utils/apply/apply.go:325` emits `loggingApply("creating object", ...)` *before* the `c.Create(...)` call (at `:327`/`:329`), so even when Create fails the operator log still shows "creating object" as if it worked. Same ordering at `:212` (Patch `:219`), `:237` (Create `:246`), `:251` (Update `:257`), and `:261` (Patch `:272`). Note `:205` is *not* affected — it logs `"skip update"` and returns immediately with no API call.

If the App revision itself is deleted, the controller rebuilds the revision from scratch using the current CD. If the CD is still broken, render fails for real and you finally see `application.status.conditions[Parsed]` flip to False with the CUE error in the message. This is the one path that surfaces the failure on the Application object itself, and nobody runs it in production because it's destructive.

## Drift correction is periodic, not event-driven

This is the correction to the original Row 2 framing. KubeVela's Application controller does **not** watch the resources it renders. `SetupWithManager` (`pkg/controller/core.oam.dev/v1beta1/application/application_controller.go:662-731`) registers exactly three watches: `ResourceTracker` (delete-only by default — `findObjectForResourceTracker` returns nil unless the RT is being deleted, `:816-819`), `PolicyDefinition`, and the `Application` itself via `For(...)`. There is no `.Owns()` anywhere in `pkg/controller/` and no informer on ConfigMaps/Deployments/etc. Managed resources are tracked by labels, not owner references, so deleting one does not touch its ResourceTracker either.

Consequence: a manually deleted ConfigMap generates **no event the controller is subscribed to**. It is restored only when the next reconcile runs `StateKeep` (`application_controller.go:336`). Reconciles fire on: an Application spec change, an RT deletion, or the periodic resync — `ApplicationReSyncPeriod`, default `5 * time.Minute` (`pkg/controller/common/vars.go:30`), set by `--application-re-sync-period` and configurable down to seconds (the manager's own informer relist `SyncPeriod` defaults to 10h and is not a recovery path).

This is identical for normal and broken CDs. The broken-CD reconcile still reaches `StateKeep` at `:336` (only the health-collection CUE eval fails, and that error is swallowed), so a deleted resource is still recreated on the next tick. The observed ~1 s recovery on the normal CD (08:14:09 → 08:14:10) was a periodic tick landing right after the delete on a 45 s-interval test cluster, not a watch firing — over repeated deletes it would average roughly half the resync interval, not sub-second. The honest one-liner: **drift correction latency ≈ the resync interval, for any CD.**

## The status fields that lie to you

Every obvious place an operator might look:

`application.status.services[*].healthy` keeps the pre-upgrade value because of the swallowed error at `application_controller.go:934`. `application.status.status` stays `running`. `application.status.conditions[*]` carries timestamps from before the upgrade and doesn't roll until a new revision actually applies. `vela status` reads these three and inherits their staleness.

`componentdefinition.status.conditions` does flip to False on the upgrade. That's the good signal. But it doesn't reliably flip back to True after a fix either, because the success path at `componentdefinition_controller.go:96-99` only resets conditions when `ConfigMapRef` changes:

```go
if componentDefinition.Status.ConfigMapRef != cmName {
    componentDefinition.Status.ConfigMapRef = cmName
    componentDefinition.Status.Conditions = []condition.Condition{condition.ReconcileSuccess()}
    ...
}
```

If `ConfigMapRef` is already populated (and it stays populated through the broken period), subsequent successful reconciles don't clear the stale error condition. So the CD-condition check is reliable for *detecting* a broken CD, less reliable for *confirming* it's been fixed.

The `apply.go` "creating object" log line lies in a different way: it's emitted before the API call, so it appears even when the API call fails.

So six status surfaces, one of which (CD conditions) only reliably reports the negative direction.

## The `autoUpdate` annotation, and what it actually changes

Beyond publishVersion bumps and spec edits, the other way to make a CD update reach the App is `app.oam.dev/autoUpdate: "true"`. With the annotation set, a CD change alone produces a new ApplicationRevision automatically — the controller flips its "is this revision still the latest" check from App-spec-only to App-spec-plus-definitions.

The gate is at `pkg/controller/core.oam.dev/v1beta1/application/revision.go:369-372`:

```go
isLatestRev := deepEqualAppInRevision(h.latestAppRev, h.currentAppRev)
if metav1.HasAnnotation(h.app.ObjectMeta, oam.AnnotationAutoUpdate) {
    isLatestRev = h.app.Status.LatestRevision.RevisionHash == h.currentRevHash &&
                  DeepEqualRevision(h.latestAppRev, h.currentAppRev)
}
```

The default branch calls `deepEqualAppInRevision` (`revision.go:476`), which compares `App.Spec`, Policies, and Workflow only. CD changes are invisible. The annotated branch calls `DeepEqualRevision` (`revision.go:416`), which also walks `Spec.ComponentDefinitions[key].Spec`, `WorkloadDefinitions`, and `TraitDefinitions`. CD changes flip its result.

`ComputeAppRevisionHash` (`revision.go:275`) hashes everything including CDs regardless of the annotation, and stores the result in `Status.RevisionHash`. The hash gets computed either way; the annotation just determines whether anyone reads it for the rollover decision.

That's why "updating the CD reapplied my App" and "updating the CD did nothing" are both correct memories — for different Apps with different annotations.

## RT name vs RT contents — they aren't the same thing

When autoUpdate fires after a CD update, what changes on the surface is misleading. I tested with a Deployment-rendering CD using `replicas: 2`, let the workload reach steady state, then changed the CD to `replicas: 5` and waited.

The live Deployment's `spec.replicas` went 2 → 5 and `status.replicas` followed. Controller log: `apply.go:126 "patching object" name=replica-test-deploy`. Real patch, not a no-op. A new `replica-test-app-v2` ApplicationRevision was created. So far so good.

But the ResourceTracker was still named `replica-test-app-v1-default`. Its outer labels still said `appRevision=replica-test-app-v1`. If you'd read just `kubectl get resourcetracker`, you'd swear nothing happened.

Decoding the RT's `spec.compression.data` blob (zstd-compressed manifest payload) reveals what actually changed:

```yaml
labels:
  app.oam.dev/app-revision-hash: "85992acf0942358c"
  app.oam.dev/appRevision: "replica-test-app-v2"
spec:
  replicas: 5
```

The cached manifest was rewritten in-place to the v2 content while the wrapping object kept its v1 name and labels. Workload object: patched and live. RT name and outer labels: frozen at v1. RT payload inside the compression blob: rolled to v2.

This is load-bearing if drift correction kicks in. `StateKeep` reads the rewritten payload, not the original. If a Deployment gets deleted out from under the cluster after the CD update, it comes back at `replicas: 5`, not 2. The RT name doesn't reflect this. The blob does.

Quick decode for any RT:

```bash
kubectl get resourcetracker <rt-name> -o jsonpath='{.spec.compression.data}' \
  | base64 -d \
  | python3 -c "import sys,json,zstandard; print(json.dumps(json.loads(zstandard.ZstdDecompressor().decompress(sys.stdin.buffer.read())), indent=2))"
```

(`pip install zstandard` first.)

A note for anyone running this on their own cluster: I've seen people report that the Deployment doesn't update after a CD change with autoUpdate on, and every time it's turned out to be one of three things — the annotation got written in the wrong YAML form (`autoUpdate=true` instead of `autoUpdate: "true"`, which is invalid in an annotations map and gets silently dropped), or there's an HPA on the Deployment quietly reverting the replicas change after the patch lands, or the test was checked before the next reconcile fired. The five-minute resync interval still applies with autoUpdate; for impatient testing, touch any annotation on the App to trigger an immediate reconcile.

## Three bugs worth filing upstream

None of these is inherently broken design. They're small bugs whose interaction is what makes the post-upgrade story so unobservable.

The health-check error swallow at `pkg/controller/core.oam.dev/v1beta1/application/application_controller.go:928-943` is the worst of the three because it's the proximate cause of the false-green status. `applyComponentHealthToServices` returns void; the caller has no signal. The fix is to propagate the error, and at minimum write `services[idx].Healthy = false` on failure with the error string in `Message`.

The apply-before-call ordering at `pkg/utils/apply/apply.go:212, 237, 251, 261, 325` is annoying but lower severity. Each of those `loggingApply(...)` lines fires before its corresponding `c.Patch`/`c.Create`/`c.Update`. The fix is a paired result log after each API call. (`:205` logs `"skip update"` and returns with no API call, so it is not affected — the original writeup listing it was wrong.)

The `ValidateUndeclaredParameters` feature gate isn't wired into the Helm chart at all. The gate is defined at `pkg/features/controller_features.go:140,171` (Alpha, default false) and consumed at `pkg/appfile/validate.go:174`, but `charts/vela-core/values.yaml` has no `validateUndeclaredParameters` key and `charts/vela-core/templates/kubevela-controller.yaml` has no `--feature-gates=ValidateUndeclaredParameters=...` line. So `--set featureGates.validateUndeclaredParameters=true` on `helm install` is a silent no-op. Two-line chart patch fixes it.

## Source of truth

Tested on commit `1ac24ed08` of github.com/kubevela/kubevela (branch `fix/defkit-changes-for-resource-builder-docs`), Go module `cuelang.org/go v0.14.1`. The 1.10.6 baseline was `cuelang.org/go v0.9.2`, confirmed by `git -C kubevela show v1.10.6:go.mod | grep cuelang`.

**Code re-verification (2026-06-05, branch `feat/kep-2.13-addon-types`).** Every code citation in this doc was re-checked against the current tree. Line numbers cited inline are from this re-verification. Results:

- **Confirmed unchanged:** `revision.go` autoUpdate gate (`:369-372`), `deepEqualAppInRevision` (`:476`), `DeepEqualRevision` (`:416`), `ComputeAppRevisionHash` (`:275`); `oam.AnnotationAutoUpdate` = `"app.oam.dev/autoUpdate"` (`pkg/oam/labels.go:162`); `componentdefinition_controller.go:96-99` ConfigMapRef-gated condition reset; `applyComponentHealthToServices` (`application_controller.go:928-943`); `ValidateUndeclaredParameters` gate (`pkg/features/controller_features.go:140,171`, Alpha/default-false) consumed at `pkg/appfile/validate.go:174`, absent from `charts/vela-core/values.yaml` and `charts/vela-core/templates/kubevela-controller.yaml` (so `--set featureGates.validateUndeclaredParameters=true` is indeed a silent no-op); CD/App admission CUE validation on both CREATE and UPDATE; `statekeep.go:77` decode.
- **Line drift corrected:** the `"Failed to collect health status"` log moved `:905 → :934` (the swallow function `applyComponentHealthToServices` is still `:928-943`).
- **Corrected for accuracy:** Row 2 drift correction is **periodic, not event-driven** (no `.Owns()`/child-resource watch; `application_controller.go:662-731`). The default health check returns healthy unconditionally when `healthPolicy` is empty (`pkg/cue/definition/health/health.go:52-54`) rather than probing existence. The manifest blob lives in `ManagedResource.Data` with whole-list zstd compression under `ResourceTrackerSpec.Compression` (`resourcetracker_types.go:86-138`), not a literal `Spec.Compression.Data` that StateKeep reads. The `apply.go` ordering-bug list drops `:205` (skip-update early return) — genuine sites are `:212,:237,:251,:261,:325`.

Test transcript timestamps, UTC, 2026-05-25:

| Row | What was verified | When (UTC) |
|---|---|---|
| Setup | Cluster created (k3d), vela 1.10.6 installed, broken CD + App applied | 05:01 — 05:06:54 |
| Setup | vela upgraded to 1.11.0-alpha.3 | 05:08 |
| Row 1 | First post-upgrade reconcile, `application_controller.go:934 "Failed to collect health status"` fired | 05:08:43 |
| Row 1 | Same error at next periodic reconcile (5 min later — default resync at the time) | 05:13:43 |
| Row 1 | Same error at the reconcile after the CD fix (5 min later) | 05:18:43 |
| Row 2 (broken-CD case) | CM deleted in scenario B, recovered on next periodic tick | ~05:11 → 05:13:43 |
| Row 2 (normal case) | CM deleted on healthy App, recovered ~1 s later — periodic resync tick coinciding with the delete (no watch; see Row 2 revision) | 08:14:09 → 08:14:10 |
| Rows 6/7 | CD fixed but App still broken until publishVersion bump | 05:15:44 → 05:19:40 |
| Audit re-run | All rows 3 through 9 re-verified fresh on the test cluster | 08:08 — 08:15 |

## Test fixtures (ComponentDefinitions and Applications)

These are the manifests used for the audit. All under `localtest/rttest/audit/` in the repo. Each file maps to specific rows in the matrix.

### `01-cd-broken-compile.yaml` — Row 4 (compile-time CUE break)

CD using `parameter.left + parameter.right` for list concatenation. Worked under CUE 0.9.2; the `+` operator on lists was deprecated in 0.11. Rejected by the ComponentDefinition admission webhook on 1.11+.

```yaml
apiVersion: core.oam.dev/v1beta1
kind: ComponentDefinition
metadata:
  name: audit-broken-compile
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

### `02-cd-fixed.yaml` — Rows 6, 7 (baseline working CD with `list.Concat`)

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

### `03-cd-eval-error.yaml` — Rows 3, 4b (evaluation-time CUE error path)

CD compiles fine because parameters are untyped (`_`). The `parameter.a + parameter.b` operation only errors at evaluation time, when concrete values are bound. Passes CD admission; fails at Application admission.

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

### `04-cd-deploy.yaml` — Row 9 (Deployment baseline, `replicas: 2`)

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

### `05-cd-deploy-replicas5.yaml` — Row 9 (CD update to `replicas: 5`)

Identical to `04-cd-deploy.yaml` except `replicas: 5`. Used to trigger the autoUpdate-driven rollover.

### `06-cd-fixed-v2.yaml` — Rows 7, 8 (CD update for `audit-merge`)

Identical structure to `02-cd-fixed.yaml` but with `cdRevisionMarker: "v2-AFTER-AUTOUPDATE"` and an additional `cdRevisionNote` field. The marker change makes rollover visible in the rendered ConfigMap.

### `10-fakebucket-crd.yaml` — Row 5 (CRD for the S3 short-circuit test)

Defines a `FakeBucket` CRD with `spec.bucketName`, `spec.region`, and `status.ready`/`status.arn`. No controller reconciles this — it's just an API object that exists when the App creates it.

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

### `11-cd-fakebucket.yaml` — Row 5 (CD that renders a FakeBucket)

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

### `21-app-fixed.yaml` — Rows 2, 6, 7 (App against working CD, no annotations)

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

### `22-app-eval-error.yaml` — Row 4b (App that hits eval-time CUE error at admission)

`a` is a string, `b` is an int. Template tries `parameter.a + parameter.b`. Rejected at App admission.

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

### `23-app-deploy.yaml` — Row 9 (Deployment App, `autoUpdate: "true"`)

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

### `25-app-fakebucket.yaml` — Row 5 (App referencing the FakeBucket CD)

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

### `26-app-eval-valid.yaml` — Row 3 (App with valid params, then patched to break)

App is created cleanly (both params are strings). Then patched to change `b` from string to int — the patch is admission-rejected.

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

## Strict audit results (2026-05-25)

| Row | Verdict | Captured at | Evidence |
|---|---|---|---|
| 1 | ✅ PASS | 05:08:43 / 05:13:43 / 05:18:43 | Three consecutive reconciles, same `application_controller.go:934 "Failed to collect health status"` error, status field never updated |
| 2 | ⚠️ REVISED | 05:13:43 (broken-CD) + 08:14:09→08:14:10 (normal) | Both recover via periodic `StateKeep`, not a watch. Original "sub-second on watch event" was a misread — there is no `.Owns()`/child-resource watch (`application_controller.go:662-731`); the ~1 s normal-CD recovery was a 45 s resync tick coinciding with the delete. Correct expectation: recovery within one resync interval for both |
| 3 | ✅ PASS | 08:13:48 | App spec patch denied by `validating.core.oam.dev.v1beta1.applications` with type-mismatch error |
| 4 | ✅ PASS | 08:08:29 | CD denied by `validating.core.oam-dev.v1beta1.componentdefinitions`: `Addition of lists is superseded by list.Concat` |
| 4b | ✅ PASS | 08:08:42 | CD admission accepts; App admission denies with `invalid operands "hello" and 42 to '+' (type string and int)` |
| 5 | ✅ PASS | 08:09:20 | FakeBucket CR exists, `status: {}` empty (no controller), App reports `phase=running, healthy=true` |
| 6 | ✅ PASS | 08:10:56 | New `audit-merge-v2` DefinitionRevision exists; App still on `audit-app-fixed-v1` with same hash; ConfigMap unchanged |
| 7 | ✅ PASS | 08:11:24 | `kubectl annotate publishVersion=audit-pv-1` → new `audit-app-fixed-v2` AppRev, ConfigMap shows new marker + new field |
| 8 | ✅ PASS | 08:12:31 (combined with Row 9) | `autoUpdate: "true"` triggered automatic new AppRev after CD change |
| 9 | ✅ PASS | 08:12:15 → 08:13:07 | `replicas: 2 → 5` propagated end-to-end: Deployment scaled, RT name stayed `v1-default`, decoded RT cache showed `replicas: 5` and `appRev_label: audit-app-deploy-v2` |
