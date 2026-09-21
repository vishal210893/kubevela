# rttest: does a CD update create a new ResourceTracker for an existing App?

This folder lets you verify, on a live cluster, the answer to one specific
question:

> When the ComponentDefinition is updated, does the existing Application that
> references it create a new ResourceTracker reflecting the new CD?

Short answer: **no**, not until you also force a new ApplicationRevision.
This test proves it visually using a static marker field in the CD template
that changes between v1 and v2 of the CD — so you can tell at a glance whether
the rendered manifest came from the new CD or the cached old one.

The whole thing works on any current vela version (1.10+, 1.11+, etc.).
You do not need a CUE break for the result to hold. The break was just one
specific *failure mode*; the underlying behaviour (CD update is inert from the
App's perspective) is general.

## Prerequisites

- A test cluster with KubeVela installed (any 1.10+/1.11+ version is fine).
  Whatever version you've got — the test works.
- `kubectl` pointed at it.
- This folder.

## The flow (5 minutes)

### Step 1 — apply CD v1 and the App

```bash
kubectl apply -f 01-cd-v1.yaml
kubectl apply -f 02-app.yaml

# wait a bit for reconcile
sleep 10

kubectl get app -n default rttest-app -o wide
# expect: phase=running, healthy=true
```

### Step 2 — capture baseline state

```bash
./inspect.sh > 1-baseline.txt
cat 1-baseline.txt
```

You should see:

- ResourceTracker `rttest-app-v1-default`
- ApplicationRevision `rttest-app-v1`
- DefinitionRevision `rttest-merge-v1`
- Rendered ConfigMap data:
  - `allLabels: app=foo,tier=web,env=prod,version=1`
  - `cdRevisionMarker: v1-original-cd`
- No `cdRevisionAddedNote` field

### Step 3 — update the CD (this is THE TEST)

```bash
kubectl apply -f 03-cd-v2.yaml
sleep 30        # generous wait for any reconcile to happen
./inspect.sh > 2-after-cd-update.txt
diff 1-baseline.txt 2-after-cd-update.txt
```

What you'll see change:

- New `DefinitionRevision rttest-merge-v2` exists
- CD `latestRevision` points to v2
- Schema ConfigMap (in vela-system) was regenerated

What you'll see **NOT** change:

- App still on `rttest-app-v1`, same revision hash
- ResourceTracker still `rttest-app-v1-default`
- Rendered ConfigMap `cdRevisionMarker` still says `v1-original-cd`
- No `cdRevisionAddedNote` field in the ConfigMap

This is the finding. CD update creates a new DefinitionRevision and the
controller may even reconcile the App via the CD-watch trigger — but the App's
ApplicationRevision is keyed off the App's own spec hash, not off CD updates,
so it reuses the v1 revision and replays the cached manifest from the existing
RT.

### Step 4 — force a new ApplicationRevision

```bash
kubectl annotate app -n default rttest-app \
  app.oam.dev/publishVersion=post-cd-update --overwrite
sleep 15
./inspect.sh > 3-after-publishversion.txt
diff 2-after-cd-update.txt 3-after-publishversion.txt
```

Now you should see the actual rollover:

- New `ApplicationRevision rttest-app-v2` exists
- New `ResourceTracker rttest-app-v2-default` exists (different name, app-gen=2)
- Old RT `rttest-app-v1-default` is gone (garbage-collected by the default
  `revisionLimit`)
- Rendered ConfigMap now shows:
  - `cdRevisionMarker: v2-AFTER-CD-UPDATE`
  - `cdRevisionAddedNote: this field did not exist in v1 of the CD`

The new field in the CD template only shows up here, in step 4 — after the new
revision is created. Step 3 alone never produced it.

### Step 5 — alternative trigger: spec edit (instead of publishVersion)

For comparison, you can take a second App that has no `publishVersion`
annotation and edit its spec directly. That also produces a new revision and
new RT. But if `publishVersion` is set (like our rttest-app after step 4),
spec edits are silently no-op'd until publishVersion is bumped again.

To see this, try:

```bash
# this WILL be a no-op because publishVersion is currently set on rttest-app
kubectl patch app -n default rttest-app --type=merge \
  -p '{"spec":{"components":[{"name":"cfg","type":"rttest-merge","properties":{"name":"rttest-merged-config","left":["NEW=label"],"right":["env=prod"]}}]}}'

# kubectl returns "patched", but:
./inspect.sh | grep allLabels
# expect: allLabels still shows the v2 content from the previous publishVersion bump
# (the NEW=label change was silently dropped)
```

This is a separate gotcha worth knowing: an App with `publishVersion` set
silently pins its render. Spec edits land in the API object but don't
propagate until `publishVersion` is bumped.

### Step 6 — the third trigger: `autoUpdate` annotation

There's a third path to make CD updates flow through to the App: setting
`app.oam.dev/autoUpdate=true` on the Application. With this annotation, the
controller switches its revision-comparison logic from "App spec only"
(`deepEqualAppInRevision`) to "App spec + all definitions"
(`DeepEqualRevision`, at `pkg/controller/core.oam.dev/v1beta1/application/revision.go:416`).
Source: `revision.go:369-372`:

```go
isLatestRev := deepEqualAppInRevision(h.latestAppRev, h.currentAppRev)
if metav1.HasAnnotation(h.app.ObjectMeta, oam.AnnotationAutoUpdate) {
    isLatestRev = h.app.Status.LatestRevision.RevisionHash == h.currentRevHash &&
                  DeepEqualRevision(h.latestAppRev, h.currentAppRev)
}
```

To verify the autoUpdate path, start from the step 2 baseline (rttest-app
fresh on `cdRevisionMarker: v1-original-cd`, no publishVersion, no autoUpdate)
and run:

```bash
kubectl annotate app -n default rttest-app app.oam.dev/autoUpdate=true --overwrite
sleep 5
kubectl apply -f 03-cd-v2.yaml
sleep 30
./inspect.sh | grep -E 'cdRevisionMarker|ApplicationRevision|ResourceTracker'
# expect: new ApplicationRevision and RT created automatically, ConfigMap
# now shows cdRevisionMarker: v2-AFTER-CD-UPDATE and cdRevisionAddedNote
```

You did not bump publishVersion. You did not edit the App spec. The CD update
alone triggered a new revision because autoUpdate flipped the comparison
function to include CD content in the equality check.

When you don't set autoUpdate, the CD's `Spec` is still hashed into
`ApplicationRevision.Status.RevisionHash` (per `ComputeAppRevisionHash` at
`revision.go:275`), but the default `currentAppRevIsNew` check at line 369
uses `deepEqualAppInRevision`, which only compares App.Spec, Policies, and
Workflow. So the hash differs after a CD update, but nobody compares it
unless autoUpdate is set.

This explains a common confusion: people remember "CD updates re-render the
App" and people also observe "CD updates don't do anything to the App."
Both are accurate. They're describing different apps with different
annotations.

### Step 7 — cleanup

```bash
kubectl delete -f 02-app.yaml
kubectl delete -f 03-cd-v2.yaml   # or 01-cd-v1.yaml if you stopped early
```

## Optional: full upgrade simulation (CUE-breaking scenario)

The original question that motivated this test came from the KubeVela 1.10 →
1.11 upgrade where CUE jumped from 0.9.2 to 0.14.1, breaking some valid 0.9.2
CUE syntax. To reproduce the full silent-failure story (workload keeps running,
status stays green, health collection silently fails every reconcile), you
need a cluster you can install 1.10.6 on first:

```bash
# 1. fresh cluster
k3d cluster create kubevela --wait

# 2. install 1.10.6 (CUE 0.9.2)
vela install --version=v1.10.6

# 3. apply the BROKEN CD and App (works on 1.10.6 because it's still CUE 0.9.2)
kubectl apply -f 00-cd-broken.yaml
kubectl apply -f 02-app.yaml-with-legacy-config-merge   # adjust component type
# or just use 01-cd-v1 and 02-app.yaml (they work on any version)

# 4. upgrade to 1.11.0-alpha.3 (CUE 0.14.1)
vela install --version=v1.11.0-alpha.3

# 5. observe: App still healthy=true (lie), controller logs CUE error every 5 min,
#    CD condition flips to Synced=False, rendered ConfigMap still served by RT cache
```

The webhook on 1.11 rejects `00-cd-broken.yaml`, so you can only use that file
on 1.10.6 (before the upgrade). Once you're on 1.11, all CD applies have to
use list.Concat (i.e. the 01- and 03- files).

## What `inspect.sh` captures

- App phase, healthy field, revision name, hash, generation, publishVersion
- App conditions with lastTransitionTime (tells you which condition rolled and when)
- ApplicationRevisions list
- ResourceTrackers (cluster-wide)
- DefinitionRevisions for the test CD
- CD configMapRef, latestRevision, status.conditions
- Rendered ConfigMap data block (look for cdRevisionMarker / cdRevisionAddedNote)
- Last 60s of controller log filtered for the relevant patterns

Diff successive runs to see what changed at each step. That's the whole point.

## Files

- `00-cd-broken.yaml` — original CUE-broken CD, for reference / 1.10.6-only use
- `01-cd-v1.yaml` — working CD v1, with `cdRevisionMarker: v1-original-cd`
- `02-app.yaml` — Application referencing `rttest-merge`
- `03-cd-v2.yaml` — same CD with marker bumped to v2 + a new field
- `inspect.sh` — single-shot state dump for diffing
- `README.md` — this file
