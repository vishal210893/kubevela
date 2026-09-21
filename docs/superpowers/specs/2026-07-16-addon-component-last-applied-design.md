# Addon Component Last-Applied Annotation Fix

**Date:** 2026-07-16
**Branch:** `feat/addon-component`
**Status:** Approved

## Problem

Commit `66d75c183` moved addon auxiliary resources into `k8s-objects`
components inside the rendered child addon Application. This gives the child
Application ownership of its definitions, config templates, schemas, views,
secrets, and template outputs through its own ResourceTracker.

KubeVela's applicator normally serializes a desired resource into the
`app.oam.dev/last-applied-configuration` annotation before creating it. For
FluxCD 3.0.2, the sanitized child Application is 248,766 bytes before the
auxiliaries are folded in and 280,694 bytes afterward. Kubernetes limits the
combined size of an object's annotations to 262,144 bytes, so pre-dispatch
server-side dry-run rejects `addon-fluxcd` before it can be created.

The failure is deterministic:

```text
Application.core.oam.dev "addon-fluxcd" is invalid:
metadata.annotations: Too long: may not be more than 262144 bytes
```

A server-side dry-run of the same folded Application succeeds when
`app.oam.dev/last-applied-configuration` contains KubeVela's supported `-`
opt-out sentinel instead of a serialized copy of the resource.

## Goals

- Allow large child addon Applications such as FluxCD 3.0.2 to pass
  pre-dispatch dry-run and creation.
- Preserve the latest ownership model: the outer Application tracks only the
  child addon Application, and the child tracks its folded auxiliaries.
- Scope the altered apply behavior to Applications emitted by the addon
  renderer.
- Add regression coverage at the renderer and live-cluster boundaries.

## Non-Goals

- Changing annotation behavior for arbitrary KubeVela workloads.
- Reverting auxiliary folding or restoring auxiliaries as outer component
  outputs.
- Introducing compressed last-applied annotations or changing the generic
  three-way merge implementation.
- Editing the generated addon ComponentDefinition to enforce apply behavior.

## Design

### Renderer contract

After rendering the addon Application and appending the grouped auxiliary
components, `pkg/addon/service/renderer.go` will set:

```yaml
metadata:
  annotations:
    app.oam.dev/last-applied-configuration: "-"
```

The renderer will use `oam.AnnotationLastAppliedConfig` rather than duplicating
the annotation string. It will overwrite any value supplied by the addon
template because this annotation controls how the outer Application applies
the generated child resource; it is not an addon-owned setting.

The renderer will set the sentinel for every child addon Application, not only
when its current serialized size exceeds the Kubernetes limit. This keeps the
behavior deterministic across addon versions and avoids a size threshold that
could change when controller labels or annotations are added later in the
render pipeline.

### Apply data flow

1. The addon renderer returns the child Application with the `-` sentinel.
2. The addon ComponentDefinition exposes that Application as its component
   output.
3. `Appfile.filterAndSetAnnotations` preserves an output's `-` or `skip`
   sentinel while filtering annotations inherited from the parent Application.
4. `trimLastAppliedConfigurationForSpecialResources` sees the sentinel and
   disables generation of the full last-applied annotation.
5. Pre-dispatch dry-run and the real create send the folded child Application
   with only the small sentinel value.

No change is required in
`charts/vela-core/templates/defwithtemplate/addon.yaml`. That file is generated
from the source CUE definition, and the ComponentDefinition should remain a
thin adapter over the renderer result.

### Update semantics

Opting out removes the stored original configuration used for KubeVela's
three-way merge. Reconciles still compare and patch the desired child
Application, and the ApplicationRevision and ResourceTracker remain the durable
desired-state records. The tradeoff is accepted for addon child Applications
because retaining the full original configuration in a Kubernetes annotation
is impossible for valid large addons.

The fix will not change generic applicator behavior. A future system-wide
solution could use server-side apply or another external original-state store,
but that is outside this regression fix.

## Error Handling

- The renderer will create `metadata` and `metadata.annotations` maps when the
  addon template omits them.
- Existing addon annotations will be preserved except for an existing
  `app.oam.dev/last-applied-configuration` value, which will be replaced by the
  sentinel.
- Registry, version validation, rendering, and CUE errors retain their current
  behavior and messages.

## Testing

### Unit tests

- Verify the renderer helper adds the `-` sentinel when metadata or annotations
  are absent.
- Verify existing annotations remain intact and a conflicting last-applied
  value is replaced.
- Keep the existing `filterAndSetAnnotations` coverage that proves a component
  output sentinel survives parent-annotation filtering.
- Run the addon service, Appfile, and apply package unit tests affected by the
  data flow.

### Live-cluster regression

- Build and run the feature branch controller against the local k3d cluster.
- Apply `localtest/addon-component/fluxcd.yaml`.
- Assert `comp-fluxcd` reaches a successful workflow state.
- Assert `addon-fluxcd` exists and its last-applied annotation equals `-`.
- Assert the outer ResourceTracker records the child Application but not the
  folded `helm` ComponentDefinition.
- Assert the child ResourceTracker records the `helm` ComponentDefinition.
- Delete the `helm` ComponentDefinition and verify StateKeep recreates it.

## Alternatives Rejected

### Skip large annotations in the generic applicator

Measuring every desired resource and conditionally disabling last-applied
recording would affect all workload types and make merge behavior dependent on
payload size. It is broader than the addon regression.

### Revert auxiliary folding

Returning auxiliaries to outer component outputs would keep FluxCD below the
annotation limit, but it would undo the intended child ResourceTracker
ownership introduced by `66d75c183`.

### Add the sentinel in the ComponentDefinition

Adding the annotation in CUE or the generated chart template couples apply
semantics to generated definition content and can conflict with annotations in
the rendered Application. The renderer can set it authoritatively while
preserving all unrelated annotations.
