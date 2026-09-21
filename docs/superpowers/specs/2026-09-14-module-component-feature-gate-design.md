# Gate `type: module` components on `EnableModuleComponent`

## Problem

The `EnableModuleComponent` feature gate is defined and mostly wired, but the
`vela/module` CueX provider never reads it. An operator who leaves the gate off
still gets a `type: module` ComponentDefinition installed by the chart, and an
Application that uses it fails with `module renderer not initialized` — an
internal-sounding message that does not tell the operator the feature is off or
how to turn it on.

The `type: addon` component already solves this. `pkg/cue/cuex/providers/addon/addon.go:70`
checks the gate at the top of `Render` and returns a message naming the gate.
This design brings module to the same shape.

## What is already in place

- `pkg/features/controller_features.go:157` — `EnableModuleComponent`, Alpha, default `false`.
- `cmd/core/app/server.go:147` — `moduleservice.Register()` runs only when the gate is on.
- `charts/vela-core/values.yaml:188` — `featureGates.enableModuleComponent: false`.
- `charts/vela-core/templates/kubevela-controller.yaml:336` — passes the gate as a controller flag.
- `references/docgen/def-doc/component/module.eg.md` — documents the gate for users.

## What is missing

`pkg/cue/cuex/providers/module/module.go:64` — `Render` goes straight to
`api.DefaultRenderer()` with no gate check, and `module_test.go` has no
gate-disabled case.

## Design

### Why the CueX package stays registered

`module.Package` is registered unconditionally on both the workload compiler
(`pkg/cue/cuex/compiler.go:54`) and the workflow compiler
(`pkg/workflow/providers/compiler.go:85`). This does not change. The `type: module`
ComponentDefinition imports `vela/module`, so dropping the package when the gate
is off would break definition compilation and OpenAPI schema generation for a
definition the chart still installs. Registering the package and refusing inside
the provider is the same trade-off addon already made, and the reason the gate
check lives in `Render` rather than at registration.

### The guard

First statement in `Render`, before `api.DefaultRenderer()`:

```go
if !utilfeature.DefaultMutableFeatureGate.Enabled(features.EnableModuleComponent) {
    return nil, fmt.Errorf("module-as-component is disabled; enable the EnableModuleComponent feature gate to use type: module components")
}
```

Ordering matters. With the gate off no renderer is registered either, so without
this guard the operator sees the nil-renderer error instead of the actionable one.

New imports: `utilfeature "k8s.io/apiserver/pkg/util/feature"` and
`github.com/oam-dev/kubevela/pkg/features`.

### Scope boundary

No admission webhook branch for module. The addon webhook branch
(`ValidateAddonComponents`) validates addon version compatibility; the gate check
there only keeps that validation from running when the feature is off. It is not
the gating mechanism, and module has no equivalent validation to gate. Rejecting
`type: module` at admission would diverge from the pattern this change mirrors.

The `vela module` CLI commands are also out of scope. The gate is a controller
process flag; the CLI talks to registries directly.

## Testing

### Unit

`pkg/cue/cuex/providers/module/module_test.go`:

- Add an `enableModuleComponent(t)` helper using
  `featuregatetesting.SetFeatureGateDuringTest`, matching `addon_test.go:35`.
- Call it from all five existing tests. Gates default to false, so without this
  every existing test would start failing on the new guard.
- Add `TestRender_IsRefusedWhenTheGateIsDisabled`: gate off, a working fake
  renderer installed, assert the error names `EnableModuleComponent` and assert
  `fake.req` is still the zero `api.ModuleRequest` — proof the renderer was never
  reached.

### Live verification on k3d

Cluster `k3d-kubevela` exists; `vela-system` currently has no KubeVela install.

1. Publish the s3 testdata module to `ttl.sh` and seed the `vela-module-registry`
   ConfigMap in `vela-system` with an OCI entry pointing at it.
2. Build the controller image and deploy the local chart with the gate at its
   default `false`. Apply a `type: module` Application. Expect: the Application
   does not reconcile, its status carries the `EnableModuleComponent` message,
   and no owned Application appears in `vela-system`.
3. `helm upgrade --set featureGates.enableModuleComponent=true`. Apply the same
   Application. Expect: it reconciles, the owned Application appears in
   `vela-system`, and the component reports healthy.

Step 2 needs no registry — the guard fires before any fetch — but seeding it
first keeps the two runs identical apart from the gate value.

## Files

| File | Change |
|------|--------|
| `pkg/cue/cuex/providers/module/module.go` | Gate guard at the top of `Render`, two imports |
| `pkg/cue/cuex/providers/module/module_test.go` | Gate helper, applied to five tests; one new disabled-gate test |

No API types change, so `make generate` and `make manifests` are not required.
