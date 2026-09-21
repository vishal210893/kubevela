# Design: `vela module deploy` CLI (GWCP-106942)

## Context

Installing a module today means hand-writing an Application with a single `type: module`
component and applying it. The component (GWCP-106941) does the real work: the render service
fetches the module from its registry and renders an owned Application whose components are the
install tiers (XRD, per-line Composition, per-line definitions).

`vela module deploy` is sugar over that path. It writes the one-component Application, validates
the registry and module before touching the cluster, applies it, and reports per-tier rollout.
It adds no render logic. An Application that references `type: module` directly installs the
module identically.

Upstream spec: `specs/oss-kubevela/gwcp-106942-module-deploy-cli/` in `gwre-pdo/specs`
(`requirements.md`, `design.md`, `tasks.md`). This document records the implementation design,
including four deliberate deviations from the upstream design's literal wording — see
[Deviations from the upstream spec](#deviations-from-the-upstream-spec).

## Existing pieces this builds on

| Piece | Location | Used for |
|---|---|---|
| `module.ResolveRegistry` | `pkg/module/registry.go:76` | early registry validation |
| `service.Service.FetchModule` | `pkg/module/service/fetch.go:68` | early module validation, tier names |
| `RenderApplication` tier naming | `pkg/module/service/render.go:87-116` | expected tier list |
| `type: module` ComponentDefinition | `vela-templates/definitions/internal/component/module.cue` | the component being built |
| `vela module` command group | `references/cli/module-registry.go:54` | where deploy is mounted |
| `apply.NewAPIApplicator` | `pkg/utils/apply` | applying the Application |

## Files

- `references/cli/module-deploy.go` — the command
- `references/cli/module-deploy_test.go` — its tests
- `references/cli/module-registry.go` — one line added to `NewModuleCommand` to mount deploy

## Command surface

```
vela module deploy <module> [--registry <name>] [-n <ns>] [--dry-run] [--timeout <dur>]
```

- `<module>` — required, the module name. Validated as a DNS label before anything else.
- `--registry` — optional. When empty, `ResolveRegistry` applies its own rules: the sole
  configured registry wins, otherwise one named `catalog` wins, otherwise it errors and names
  the alternatives. Making the flag required would duplicate that logic in the CLI and break the
  single-registry case that the resolver already handles.
- `-n` — install namespace, default `vela-system`.
- `--dry-run` — print the built Application and apply nothing. Redirecting it
  (`vela module deploy s3 --dry-run > s3.yaml`) covers the GitOps hand-off that the upstream
  spec's `--file` flag was for.
- `--timeout` — how long to wait for readiness, default `5m`.

The built Application:

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: module-s3-deploy
  namespace: vela-system
spec:
  components:
    - name: s3
      type: module
      properties:
        module: s3
        registry: catalog
        namespace: vela-system
```

The `registry` property carries the *resolved* registry name, not the raw flag value. When a user
omits `--registry`, the applied manifest still records which registry was chosen, so the manifest
means the same thing later even if a second registry is added.

## Flow

1. Validate the module name; build the client from `common.Args`.
2. `module.ResolveRegistry(ctx, module.NewStore(cli), registryFlag)`. Its error is returned
   unwrapped in substance — the resolver already names the configured registries or tells the
   operator to add one.
3. `service.NewService(store).FetchModule(ctx, reg.Name, moduleName)`. This proves the module exists in the
   registry, parses, and validates. The parsed module is reused: its XRD presence and enabled
   lines give the exact tier names to expect, which the status report prints even before the
   owned Application appears.
4. Build the Application.
5. If `--dry-run`, print the manifest and return — nothing is applied.
6. Apply with `apply.NewAPIApplicator`.
7. Wait and report (below).

Steps 2 and 3 happen before any write, so a bad registry or module name fails with nothing
created.

## Status reporting

Two Applications are involved:

- the **outer** Application deploy creates, `module-<module>-deploy`, whose single service is the
  `module` component;
- the **owned** Application the render service produces, `module-<module>`, whose services are the
  tiers.

Per-tier health lives only on the owned one, so deploy reads both. The outer Application's phase
is the failure channel: a fetch or render error server-side surfaces there as a failed or
terminated workflow, whereas the owned Application simply never appears. The owned Application's
`status.services[]` is the detail channel.

The wait loop polls at a fixed interval until the outer Application reaches `Running` and every
owned tier is healthy, or the timeout expires:

```
module s3 -> vela-system

TIER          STATUS   MESSAGE
s3-xrd        Healthy  Established
s3-v1-comp    Healthy
s3-v1-defs    Pending  waiting for s3-v1-comp
```

Terminal outer phases (`WorkflowFailed`, `WorkflowTerminated`, `Deleting`) stop the loop
immediately with the phase and the component's message rather than waiting out the timeout.

On timeout the command exits non-zero and names the first tier that is not healthy along with its
message, so the operator sees whether the XRD failed to become Established, a Composition is not
Ready, or a definitions tier did not apply.

## Error handling

- Resolver and fetch errors propagate with their own text; deploy adds no wrapper that would bury
  the registry names or the module path they report.
- Apply errors are wrapped with the Application name and namespace.
- Timeout is an error, not a warning: scripts calling deploy must see a non-zero exit.

## Testing

Table-driven Go tests with `fake.NewClientBuilder()`, matching the conventions in
`references/cli/module-registry_test.go`.

Seams: a `moduleDeployOptions` struct holds the fetch function and the poll interval. Production
wires the real fetch and a one-second interval; tests inject a stub fetch and a millisecond
interval, so no test sleeps.

Cases:

1. `buildModuleApplication` produces the expected name, namespace, single component, and
   `module`/`registry`/`namespace` properties.
2. `--dry-run` prints an Application with exactly one `type: module` component and creates
   nothing (asserted by listing Applications on the fake client).
3. An unresolvable registry fails before apply — the error is the resolver's, and no Application
   exists afterwards.
4. A module missing from the registry fails before apply, via the fetch seam.
5. The wait loop prints every tier and returns success once the owned Application's services are
   all healthy and the outer phase is `Running`.
6. A stuck tier hits the timeout and the error names that tier and its message.
7. A terminal outer phase (`WorkflowFailed`) stops the loop immediately without waiting for the
   timeout.

## Deviations from the upstream spec

1. **Outer Application name `module-<module>-deploy`.** The upstream design names it
   `module-<module>`, which is the exact name the render service gives the owned Application
   (`render.go:126`). With both in `vela-system` they collide — the outer Application would
   dispatch a child with its own name and namespace. The `-deploy` suffix removes the collision at
   any namespace.
2. **Default namespace `vela-system`, not `default`.** KubeVela resolves definitions from the
   Application's namespace plus `vela-system`. Definitions installed into `default` are usable only
   by Applications in `default`, which is not what a module install means. `-n` still installs a
   namespace-scoped copy for anyone who wants one.
3. **The component's `namespace` property is set** to the resolved install namespace. The upstream
   manifest sets only `module` and `registry`, which would leave tiers in `vela-system` even when
   the operator passed `-n foo`, splitting the deploy record from what it installed.
4. **`--registry` is optional.** The upstream command line shows it as required; `ResolveRegistry`
   already implements defaulting and ambiguity reporting, and requiring the flag would duplicate
   that.
5. **No `--file` flag.** Requirement 1.3 asks for one; it duplicates `--dry-run` with a shell
   redirect (`vela module deploy s3 --dry-run > s3.yaml`), which is how an operator captures the
   manifest for GitOps. Dropped to keep the flag surface minimal.

## Out of scope

- The render service and the `type: module` component (GWCP-106941).
- Module fetch (GWCP-106686) and registry configuration (GWCP-106679) beyond calling them.
- Per-line selection. The component installs the module's enabled lines; deploy has no line flag.
- Uninstall. Removing a module means deleting the Application deploy created.
