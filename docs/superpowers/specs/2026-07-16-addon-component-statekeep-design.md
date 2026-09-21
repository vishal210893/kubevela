# Addon-as-Component Auxiliary StateKeep Design

## Problem

The addon-as-component renderer now folds addon auxiliaries into the rendered
inner `Application` as `k8s-objects` components. Those resources are therefore
part of the inner application's desired state and are expected to be healed by
the normal Application `StateKeep` cycle.

That healing does not currently happen. The behavior was reproduced on the
local `k3d-kubevela` cluster with the `terraform-aws` addon:

- `addon-terraform-aws` was `running` and tracked `aws-sqs` in
  `addon-terraform-aws-v1-vela-system`.
- Deleting `ComponentDefinition/vela-system/aws-sqs` left it absent for 75
  seconds, covering more than three configured 20-second application resync
  intervals.
- The inner Application remained `running`, and the ResourceTracker retained a
  metadata-only entry for the deleted definition.

The test resource was restored by restarting the inner workflow after the
investigation.

## Root Cause

`pkg/addon/render.go` labels every rendered addon Application with
`addons.oam.dev/name`. In
`pkg/resourcekeeper/resourcekeeper.go:parseApplicationResourcePolicy`, any
Application with that label and no explicit `apply-once` policy receives this
legacy implicit policy:

```go
&v1alpha1.ApplyOncePolicySpec{Enable: true}
```

That policy changes two relevant behaviors:

1. `ResourceKeeper.Dispatch` records only resource metadata in the
   ResourceTracker, omitting each managed resource's raw desired manifest.
2. `ResourceKeeper.StateKeep` returns immediately for an application-wide
   apply-once policy.

The Application controller still reconciles on schedule, but it has neither a
StateKeep operation to run nor stored manifests from which to recreate deleted
resources. Owner references and per-resource watches are not involved in this
reconciliation model; ResourceTracker data plus periodic StateKeep provide the
healing mechanism.

## Goals

- Make auxiliaries rendered by an addon component self-heal through the
  existing ResourceTracker and StateKeep path.
- Preserve an explicit `apply-once` policy authored by an addon package.
- Keep legacy `vela addon enable` behavior unchanged.
- Avoid new dynamic resource watches, owner-reference behavior, or a second
  addon-specific reconciler.
- Keep the existing last-applied annotation suppression that prevents large
  rendered inner Applications from exceeding Kubernetes annotation limits.

## Non-Goals

- Changing global `ApplyOnce` feature-gate behavior.
- Changing the semantics of the imperative addon installation path.
- Forcing self-healing when an addon package explicitly opts into apply-once.
- Replacing ResourceTracker-based drift prevention.

## Selected Design

The addon-as-component renderer will ensure that a rendered inner Application
has an explicit disabled `apply-once` policy when, and only when, the addon did
not declare an `apply-once` policy itself:

```yaml
spec:
  policies:
    - name: addon-component-state-keep
      type: apply-once
      properties:
        enable: false
```

An explicit disabled policy prevents the ResourceKeeper's addon-label fallback
from installing its implicit enabled policy. It also uses an existing public
Application contract instead of adding a private marker understood only by the
renderer and ResourceKeeper.

### Renderer Behavior

Add a focused helper in `pkg/addon/service/renderer.go`, called from
`resolveAndRender` after the addon Application is converted to an unstructured
map and before it is returned.

The helper will:

1. Ensure `spec` and `spec.policies` have their normal map/slice structures.
2. Scan policies by `type`, using `v1alpha1.ApplyOncePolicyType` rather than a
   duplicated string literal.
3. Return without modification if any `apply-once` policy exists. This preserves
   both enabled and disabled addon-authored policies, including their selectors
   and strategies.
4. Otherwise append one disabled apply-once policy without changing the order
   or content of existing policies.
5. Use `addon-component-state-keep` as the generated name. If that name is
   already used by another policy type, select a deterministic numeric suffix
   so policy names remain unique.
6. Be idempotent so repeated rendering cannot append duplicate policies.

An existing `apply-once` entry with malformed or missing properties is still
considered explicit and is preserved. The normal Application validation and
policy parser should report that addon package error; the renderer must not
silently replace author input.

### Reconciliation Flow

For an addon without an explicit apply-once policy:

1. The outer Application renders and dispatches the inner addon Application.
2. The inner Application contains `apply-once: {enable: false}` while retaining
   its `addons.oam.dev/name` label.
3. `parseApplicationResourcePolicy` finds the explicit policy, so the legacy
   addon-label fallback is not used.
4. `ResourceKeeper.Dispatch` records raw desired manifests in the inner
   ResourceTracker instead of applying `MetaOnlyOption`.
5. On each application resync, `StateKeep` compares and reapplies those stored
   manifests.
6. A deleted auxiliary is recreated no later than the next successful
   StateKeep cycle. Recovery is periodic, not event-driven.

No change is required in `pkg/resourcekeeper` for the production behavior.

### Existing Applications and Upgrades

The generated policy changes the inner Application spec. After the updated
renderer is running, the wrapping workflow must execute the addon component
again. Operators must restart that workflow or make a real wrapping Application
spec change that creates a new revision; a periodic resync of an already
completed workflow is not sufficient by itself. The resulting inner Application
spec change creates a new inner revision whose ResourceTracker contains raw
manifests. Old metadata-only trackers remain subject to normal revision garbage
collection.

### Interaction With Last-Applied Suppression

The existing
`app.oam.dev/last-applied-configuration: skip` annotation on the rendered inner
Application remains required. It prevents the outer dispatcher from embedding
the entire folded Application in a Kubernetes annotation. Disabling implicit
apply-once solves a different problem: it enables raw child-resource storage in
the inner ResourceTracker. Both behaviors must remain covered by tests.

### ResourceTracker Storage Impact

Self-healing requires the inner ResourceTracker to retain each managed
resource's raw desired manifest. This intentionally uses more storage than the
legacy metadata-only addon tracker. The last-applied sentinel and annotation
filtering remain important because they prevent a copy of the entire folded
Application from being propagated into each child resource. Live verification
must include FluxCD and Terraform AWS tracker sizes. If a catalog addon still
approaches the API server or etcd object-size limit with natural raw manifests,
the existing `ZstdResourceTracker` feature is the supported mitigation; the
renderer must not silently fall back to non-healing metadata-only tracking.

## Validation Evidence

An isolated live probe used an addon-labeled Application with an explicit
disabled apply-once policy and one `k8s-objects` ConfigMap. Its ResourceTracker
stored the ConfigMap with raw data. After deletion, StateKeep recreated the
ConfigMap with a new UID on the next 20-second cycle. This confirms the selected
policy override activates the existing healing path without controller changes.

## Test Plan

### Renderer Unit Tests

Add table-driven coverage for the policy helper:

- No `spec.policies`: append the disabled policy.
- Existing unrelated policies: preserve them and append the disabled policy.
- Existing enabled apply-once policy: preserve it and append nothing.
- Existing disabled apply-once policy: preserve it and append nothing.
- Generated-name collision with another policy type: use a deterministic unique
  suffix.
- Repeated helper invocation: remain idempotent.

Extend renderer result coverage to assert that a normal addon result contains
both the last-applied sentinel and the disabled policy.

### ResourceKeeper Regression Test

Add or refine a focused test proving that an addon-labeled Application with an
explicit `apply-once: {enable: false}` does not receive the implicit enabled
fallback and records raw managed-resource data. This protects the cross-package
contract on which the renderer fix relies.

### Automated Verification

Run the focused suites for:

- `./pkg/addon/service`
- `./pkg/resourcekeeper`
- `./pkg/appfile`

Run formatting and `git diff --check` before cluster verification.

### Live Cluster Verification

1. Reconcile the Terraform AWS addon through `type: addon`.
2. Confirm the inner Application contains the generated disabled policy.
3. Confirm an inner ResourceTracker entry such as `aws-mq` has `raw` data.
4. Delete `ComponentDefinition/vela-system/aws-mq`.
5. Confirm it is recreated within the configured StateKeep interval with a new
   UID and remains listed in the ResourceTracker.
6. Re-run FluxCD to ensure the folded child Application still avoids the
   annotation-size failure.
7. Test an addon fixture with an explicit enabled apply-once policy and confirm
   the renderer does not override it.

## Documentation

Update the addon-as-component HLD, LLD, and ResourceTracker walkthrough, then
regenerate the HTML's embedded document content so all four artifacts describe:

- auxiliaries being folded into inner `k8s-objects` components,
- the legacy addon-label apply-once fallback,
- the explicit disabled policy used by component installation, and
- periodic StateKeep recovery rather than deletion-event watches.

## Alternatives Rejected

### Installation-Mode Marker in ResourceKeeper

The renderer could annotate the inner Application and ResourceKeeper could skip
its addon-label fallback for that marker. This avoids a generated policy but
adds private coupling and changes generic reconciliation code when the existing
policy API already expresses the required behavior.

### Remove the Addon Apply-Once Fallback Globally

Removing the label-based fallback would also heal component-installed addons,
but it would change the established behavior of `vela addon enable` and increase
ResourceTracker storage for every legacy addon installation.

### Watch Every Managed Auxiliary

Watching arbitrary GVKs from ResourceTracker entries and enqueueing their owning
Application would make recovery event-driven, but it duplicates StateKeep,
requires dynamic informer lifecycle management, and still needs desired raw
state or a full workflow restart. It is disproportionate to this bug.
