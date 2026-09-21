# Addon as a Component (no new CRD)

**Date:** 2026-06-22
**Branch:** `feat/addon-component` (off `master`, no Addon CR)
**Status:** Draft (approved core, expected to change)
**Prior art:** POC PR kubevela/kubevela#6997, driving issue #6995.

## Goal

Let a user install an addon by declaring it as a component inside an ordinary
`Application`, instead of applying a dedicated `Addon` custom resource. The
Application controller already owns ResourceTracker, StateKeep drift healing,
garbage collection, revisions, and status rollup. An addon expressed as a
component inherits all of that, so we do not build a second controller or a
second tracker for it. Users also already know `Application`, so there is
nothing new to learn.

This design is deliberately unaware of the KEP-2.13 `Addon` CR implementation.
It reuses only the generic, pre-existing building blocks in `pkg/addon`
(registry access, version resolution, package render), not the Addon
controller.

## Non-goals (v1)

- **Addon dependencies.** v1 targets a single addon with no dependencies. If an
  addon does declare a dependency, the reused install/render path keeps its
  current behavior; we do not design for it here. Dependencies are recorded as
  future work below.
- **Multi-cluster fan-out** of the addon beyond whatever topology the addon's
  own rendered Application already carries.
- **Addon CR interop.** No coexistence logic with the `Addon` CR. Whether the CR
  is kept, deprecated, or removed is decided after this design proves out.

## What the user writes

A normal Application with a component of `type: addon`.

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: platform
spec:
  components:
    - name: fluxcd          # component name is the default addon name
      type: addon
      properties:
        addon: fluxcd       # optional; defaults to the component name
        version: "3.0.2"    # exact version or a semver constraint
        registry: KubeVela  # optional; defaults to the configured registry
        properties: {}      # the addon's own parameters, passed through
        include:            # optional; each field defaults to true
          definitions: true
          views: true
          resources: true
```

## Architecture

### Rendering shape

The `addon` ComponentDefinition (adapted from the POC's `addon.cue`) resolves
the addon and produces:

- `output`: the addon's own `Application` object (workload kind `Application`),
  the same object the current install path produces (for example
  `addon-fluxcd`).
- `outputs`: one entry per auxiliary the addon ships (definitions, views, config
  templates), each a standalone object.

These are ordinary component `output` / `outputs`, so the **wrapping
Application's ResourceTracker records all of them with no special handling**.
The result is two levels of tracking, both already implemented:

1. The wrapping Application (`platform`) tracks the child `addon-fluxcd`
   Application plus the auxiliary definitions and config objects.
2. The child `addon-fluxcd` Application tracks the real workload it renders (the
   flux controllers, CRDs, RBAC).

Drift on an auxiliary is healed by the wrapping Application's StateKeep. Drift on
a flux workload resource is healed by the child Application's StateKeep. Deleting
the wrapping Application (or just the component) cascades through the
ResourceTracker and removes the child Application and the auxiliaries.

We keep the POC's nested-Application shape rather than flattening the addon's
resources into the wrapping Application. Flattening fights the "one component is
one workload plus outputs" model and would drop the addon's own
application-level policies. Nesting reuses the existing render output as-is.

### Resolution and pinning

Resolution is keyed by `(addon, resolved version, registry, properties)`:

1. On first reconcile, or when any key input changes, resolve the addon from the
   registry and render it once, reusing `pkg/addon` (registry reader, version
   resolution, package render).
2. Pin the rendered manifests into the `ApplicationRevision` so the concrete
   result is captured with the revision.
3. Steady-state reconciles render from the pin and make no registry call. The
   network is touched only on first install or on a version or parameter change.

This keeps registry I/O out of the hot render path (the render runs on every
reconcile) and makes each revision deterministic and offline-safe after the
first resolve.

## Lifecycle (all inherited from the Application controller)

- **Install:** apply the Application. The component resolves; the resources land.
- **Update:** change `version` or `properties`. A new revision is cut, the addon
  is re-resolved and re-rendered, and the diff is applied.
- **Drift heal:** a deleted or edited resource is re-applied by StateKeep from
  the tracked manifest. No addon-owned tracker, no custom heal loop.
- **Delete:** delete the Application or the component. GC cascades through the
  ResourceTracker and removes the child Application and auxiliaries.
- **Status:** the wrapping Application's health rolls up the child Application's
  health. No custom status code.

## Reuse map

Called, not rebuilt, from `pkg/addon`:

- Registry resolution and the registry reader (`registry.go`, `reader_oss.go`,
  `source.go`).
- Version resolution for exact versions and semver constraints.
- Package render (`RenderApp` and the install-package assembly) that produces the
  addon's Application plus auxiliaries.

New in this design:

- `vela-templates/definitions/internal/component/addon.cue`: the `addon`
  ComponentDefinition (from the POC), with `output` = the addon Application and
  `outputs` = the auxiliaries.
- A resolve-and-render helper (a CueX provider, following the POC, or a thin
  render function) that returns `{application, resources[]}` and is backed by the
  resolve-once / pin-to-revision behavior above.

No dependence on the Addon CR controller, its finalizer, or its drift code.

## Error handling and edge cases

- **Addon not found / bad version:** surfaces as a component render failure on
  the Application, with the reason in the Application status. No partial install.
- **Registry unreachable on first resolve:** the render fails and the reconcile
  requeues. Once pinned, later reconciles are unaffected by registry outages.
- **Dry-run / offline after pin:** renders from the pinned manifests, so it works
  without the registry.
- **Empty render:** if the addon resolves to nothing, treat it as an error rather
  than silently producing an empty component.

## Testing

- Unit: the resolve-and-render helper (exact version, semver constraint, not
  found, parameter pass-through), and that the ComponentDefinition emits the
  Application as `output` and auxiliaries as `outputs`.
- Integration / e2e: apply an Application with a `type: addon` component against a
  cluster, assert the child Application and auxiliaries appear and reach healthy,
  delete a definition and assert StateKeep heals it, change `version` and assert a
  re-resolve, delete the Application and assert the cascade.

## Future work

- **Dependencies.** Resolve an addon's declared dependencies and bring them in,
  most likely by expanding them into the same wrapping Application (one
  Application, its ResourceTracker owns the addon and every dependency). Revisit
  once v1 lands.
- **Multi-cluster** distribution of the addon via topology policy on the wrapping
  Application.
- **Addon CR decision.** Decide whether the component model fully replaces the
  `Addon` CR, and if so, deprecate and remove it.
