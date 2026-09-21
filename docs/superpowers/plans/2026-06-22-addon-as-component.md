# Addon as a Component Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install a KubeVela addon by declaring it as a `type: addon` component inside a normal `Application`, with no new CRD. The addon's Application and auxiliaries render as the component's `output`/`outputs`, so the wrapping Application's existing ResourceTracker, StateKeep, GC, and status handle the rest.

**Architecture:** A CueX provider `addon.#Render` (registered on the in-repo `WorkloadCompiler`) resolves an addon from the registry and renders it, reusing the existing `pkg/addon` functions (`FindAddonPackagesDetailFromRegistry`, `RenderApp`, and the auxiliary render functions). A render-only service holds the Kubernetes client and an in-process cache, injected at controller startup. The `addon` ComponentDefinition places the rendered Application in `output` and each auxiliary in `outputs`. The component's workload type is `autodetects.core.oam.dev`, so its `output` may be any GVK, including `Application`.

**Tech Stack:** Go, CUE, `github.com/kubevela/pkg/cue/cuex` (providers, runtime), `pkg/addon`, controller-runtime.

**Spec:** `docs/superpowers/specs/2026-06-22-addon-as-component-design.md`

**Branch:** `feat/addon-component` (off `master`, no Addon CR).

---

## Reference facts (verified against the codebase, do not re-derive)

CueX provider pattern (in-repo example: `pkg/cue/cuex/providers/config/config.go`):
- Wrappers: `providers.Params[T]` = `{ Params T `json:"$params"` }`, `providers.Returns[T]` = `{ Returns T `json:"$returns"` }` (module `github.com/kubevela/pkg/cue/cuex/providers`).
- Provider fn signature: `func(context.Context, *ParamsT) (*ReturnsT, error)`.
- Registration: `var Package = runtime.Must(cuexruntime.NewInternalPackage(ProviderName, embeddedCUE, map[string]cuexruntime.ProviderFn{ "render": cuexruntime.GenericProviderFn[P, R](Render) }))` where `runtime` is `github.com/kubevela/pkg/util/runtime` and `cuexruntime` is `github.com/kubevela/pkg/cue/cuex/runtime`.
- Companion CUE uses `#do` (the map key) and `#provider` (= `ProviderName`): `#Render: { #do: "render", #provider: "addon", $params: {...}, $returns: {...} }`.
- The component template is compiled by `velacuex.WorkloadCompiler.Get().CompileString(...)` at `pkg/cue/definition/template.go:139`. Registering a package on `WorkloadCompiler` (`pkg/cue/cuex/compiler.go:44`, the `cuex.NewCompilerWithInternalPackages(...)` list) makes `addon.#Render` resolvable inside `output`/`outputs`.

Component definition (precedent `vela-templates/definitions/internal/component/k8s-objects.cue`):
- A component whose `output` is an arbitrary-GVK object sets `attributes: workload: type: "autodetects.core.oam.dev"` (const `types.AutoDetectWorkloadDefinition`, `apis/types/types.go:40`) and NO `attributes.workload.definition`. `output` is decoded to `*unstructured.Unstructured` and dispatched as-is (`pkg/appfile/appfile.go:586,629`); `outputs` entries become auxiliaries (`template.go:190-211`).

`pkg/addon` reuse (all pre-existing on `master`, byte-identical, no CRD dependency):
- `func RenderApp(ctx context.Context, addon *InstallPackage, k8sClient client.Client, args map[string]interface{}) (*v1beta1.Application, []*unstructured.Unstructured, error)` — `pkg/addon/render.go:303`. Returns the addon Application (name forced to `addon-<name>`, namespace `vela-system`) plus the CUE `outputs` auxiliaries only.
- `func FindAddonPackagesDetailFromRegistry(ctx context.Context, k8sClient client.Client, addonNames []string, registryNames []string) ([]*WholeAddonPackage, error)` — `pkg/addon/helper.go:246`. Empty `registryNames` scans all registries. `*WholeAddonPackage` embeds `InstallPackage` and carries `AvailableVersions []string` and `RegistryName`.
- Auxiliary render functions the dispatcher normally calls after `RenderApp` (confirm exact signatures/return types at these lines before wiring): `RenderDefinitions` (`addon.go:683`), `RenderConfigTemplates` (`addon.go:711`), `RenderDefinitionSchema` (`addon.go:734`), `RenderViews` (`addon.go:749`), `RenderArgsSecret` (`addon.go:837`).
- Version-specific fetch when a single exact version is requested: versioned (Helm) registries expose `GetAddonInstallPackage(ctx, addonName, version string) (*InstallPackage, error)` (`versioned_registry.go:108`); non-versioned use the `Source` interface `GetInstallPackage`. `InstallPackage` struct: `pkg/addon/type.go:47`.
- System/version requirement check: `checkAddonVersionMeetRequired(ctx, require *SystemRequirements, k8sClient, dc *discovery.DiscoveryClient) error` (`addon.go:1749`) validates the addon's `SystemRequirements` (vela CLI/UX, vela-core controller, and Kubernetes versions) via semver. It runs ONLY in `Installer.enableAddon` (`addon.go:949-955`, gated by `skipVersionValidate`), NOT in `RenderApp`. The addon's requirements live on `InstallPackage.Meta.SystemRequirements` (`type.go:101`). Because it is unexported and the render service is in a different package, expose a thin wrapper in `pkg/addon` (for example `func ValidateSystemRequirements(ctx, require *SystemRequirements, cli client.Client, dc *discovery.DiscoveryClient) error`) that calls it. Build the `*discovery.DiscoveryClient` from the service's `*rest.Config`.

Dev container: build/test with `CGO_ENABLED=0 go test ./path/...`; compile-check with `CGO_ENABLED=0 go vet ./path/`.

---

## File Structure

- **Create** `pkg/addon/service/renderer.go` — render-only service: `Renderer` interface, `AddonRequest`/`AddonResult`, `rendererImpl` (holds `client.Client` + `*rest.Config` + cache), `RenderAddon`.
- **Create** `pkg/addon/service/renderer_test.go` — unit tests for `RenderAddon`.
- **Create** `pkg/addon/service/registry.go` — package-level `SetDefaultRenderer` / `DefaultRenderer` used to inject the renderer into the CueX provider without an import cycle.
- **Create** `pkg/cue/cuex/providers/addon/addon.go` — CueX provider (`Package`, `ProviderName="addon"`, `Render`).
- **Create** `pkg/cue/cuex/providers/addon/addon.cue` — `#Render` provider CUE.
- **Modify** `pkg/cue/cuex/compiler.go` — add `addon.Package` to the `WorkloadCompiler` package list.
- **Create** `vela-templates/definitions/internal/component/addon.cue` — the `addon` ComponentDefinition.
- **Modify** `cmd/core/app/server.go` — construct and inject the renderer at startup.
- **Create** `test/e2e-test/addon_component_test.go` — e2e for the component path.

Import-cycle note: the CueX provider (`pkg/cue/cuex/providers/addon`) must NOT import `pkg/addon` directly if that creates a cycle. It depends only on `pkg/addon/service` through the injected `Renderer` interface. `pkg/addon/service` imports `pkg/addon`. Verify no cycle in Task 2 Step 2.

---

## Task 1: Render-only addon service (fetch + resolve + render, no dispatch)

**Files:**
- Create: `pkg/addon/service/renderer.go`
- Create: `pkg/addon/service/renderer_test.go`

- [ ] **Step 1: Write the failing test**

`pkg/addon/service/renderer_test.go`:
```go
/*
Copyright 2026 The KubeVela Authors. Licensed under the Apache License, Version 2.0.
*/

package service

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRenderAddonNotFound(t *testing.T) {
	r := &rendererImpl{cli: fakeClientWithRegistry(t)}
	_, err := r.RenderAddon(context.Background(), AddonRequest{Name: "does-not-exist"})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "not found")
}

func TestRenderAddonReturnsApplicationAndResources(t *testing.T) {
	r := &rendererImpl{cli: fakeClientWithMockRegistry(t)} // points at the e2e mock or a stub Source
	res, err := r.RenderAddon(context.Background(), AddonRequest{Name: "example", Version: "1.0.0"})
	require.NoError(t, err)
	assert.Equal(t, "1.0.0", res.ResolvedVersion)
	assert.Equal(t, "Application", res.Application["kind"])
	assert.NotEmpty(t, res.Resources) // at least the helm-example ComponentDefinition
}
```
The `fakeClientWith*` helpers wrap a controller-runtime fake client whose `vela-addon-registry` ConfigMap points at a `Source` you can stub. If stubbing the registry `Source` is heavy, gate `TestRenderAddonReturnsApplicationAndResources` behind an env var and rely on the e2e in Task 6 for the happy path; keep `TestRenderAddonNotFound` as the always-on unit test.

- [ ] **Step 2: Run test to verify it fails**

Run: `CGO_ENABLED=0 go test ./pkg/addon/service/ -run TestRenderAddon -v`
Expected: FAIL (package/types undefined).

- [ ] **Step 3: Write minimal implementation**

`pkg/addon/service/renderer.go`:
```go
/*
Copyright 2026 The KubeVela Authors. Licensed under the Apache License, Version 2.0.
*/

package service

import (
	"context"
	"fmt"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/rest"
	"sigs.k8s.io/controller-runtime/pkg/client"

	pkgaddon "github.com/oam-dev/kubevela/pkg/addon"
)

// AddonRequest is the resolved-input for rendering one addon.
type AddonRequest struct {
	Name       string
	Version    string
	Registry   string
	Properties map[string]interface{}
}

// AddonResult is the rendered output: the addon Application and its auxiliaries
// as generic maps, ready to hand back to CUE.
type AddonResult struct {
	ResolvedVersion string
	Registry        string
	Application     map[string]interface{}
	Resources       []map[string]interface{}
}

// Renderer resolves and renders an addon without dispatching it to the cluster.
type Renderer interface {
	RenderAddon(ctx context.Context, req AddonRequest) (*AddonResult, error)
}

type rendererImpl struct {
	cli    client.Client
	config *rest.Config
}

// NewRenderer builds a render-only addon service.
func NewRenderer(cli client.Client, config *rest.Config) Renderer {
	return &rendererImpl{cli: cli, config: config}
}

func (r *rendererImpl) RenderAddon(ctx context.Context, req AddonRequest) (*AddonResult, error) {
	regs := []string{}
	if req.Registry != "" {
		regs = []string{req.Registry}
	}
	pkgs, err := pkgaddon.FindAddonPackagesDetailFromRegistry(ctx, r.cli, []string{req.Name}, regs)
	if err != nil {
		return nil, fmt.Errorf("resolve addon %q: %w", req.Name, err)
	}
	if len(pkgs) == 0 {
		return nil, fmt.Errorf("addon %q not found in registries %v", req.Name, regs)
	}
	whole := pkgs[0]
	installPkg := &whole.InstallPackage

	// Version: FindAddonPackagesDetailFromRegistry loads a concrete package.
	// If the caller pinned an exact version that differs, fetch that version.
	resolved := installPkg.Version
	if req.Version != "" && req.Version != resolved {
		// STEP: use the version-specific fetch confirmed in Reference facts
		// (versioned GetAddonInstallPackage, or the Source.GetInstallPackage path).
		// Assign installPkg + resolved from that call.
	}

	app, aux, err := pkgaddon.RenderApp(ctx, installPkg, r.cli, req.Properties)
	if err != nil {
		return nil, fmt.Errorf("render addon %q: %w", req.Name, err)
	}

	resources := make([]map[string]interface{}, 0, len(aux))
	for _, o := range aux {
		resources = append(resources, o.Object)
	}
	// STEP: append the definition/schema/view/config-template/args-secret
	// auxiliaries by calling RenderDefinitions/RenderConfigTemplates/
	// RenderDefinitionSchema/RenderViews/RenderArgsSecret (see Reference facts
	// for locations), converting each to map[string]interface{} via
	// runtime.DefaultUnstructuredConverter.ToUnstructured. Confirm each function's
	// exact signature/return type at its line before wiring.

	appMap, err := runtime.DefaultUnstructuredConverter.ToUnstructured(app)
	if err != nil {
		return nil, err
	}
	appMap["apiVersion"] = "core.oam.dev/v1beta1"
	appMap["kind"] = "Application"

	return &AddonResult{
		ResolvedVersion: resolved,
		Registry:        whole.RegistryName,
		Application:     appMap,
		Resources:       resources,
	}, nil
}

var _ = unstructured.Unstructured{}
```

Three fill-ins in this task, all naming real functions/locations (read the signature first, no guessing): the exact-version fetch, the extra auxiliary render calls, and the system-requirement check. For the check: add `SkipVersionValidate bool` to `AddonRequest`; after the InstallPackage is fetched and before `RenderApp`, call the new exported wrapper `pkgaddon.ValidateSystemRequirements(ctx, installPkg.SystemRequirements, r.cli, dc)` (unless `req.SkipVersionValidate`), where `dc` is a `*discovery.DiscoveryClient` built from `r.config` (`discovery.NewDiscoveryClientForConfig`). On failure, return a wrapped error so the component render fails and the reason surfaces on the wrapping Application. Adding the exported `ValidateSystemRequirements` wrapper in `pkg/addon` (delegating to the unexported `checkAddonVersionMeetRequired`) is part of this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `CGO_ENABLED=0 go test ./pkg/addon/service/ -run TestRenderAddonNotFound -v && CGO_ENABLED=0 go vet ./pkg/addon/service/`
Expected: PASS (not-found test), vet clean. The happy-path test runs in e2e (Task 6) if the registry stub is deferred.

- [ ] **Step 5: Commit**

```bash
git add pkg/addon/service/renderer.go pkg/addon/service/renderer_test.go
git commit -m "feat(addon): render-only addon service (fetch + render, no dispatch)"
```

---

## Task 2: CueX provider `addon.#Render` and injection seam

**Files:**
- Create: `pkg/addon/service/registry.go`
- Create: `pkg/cue/cuex/providers/addon/addon.go`
- Create: `pkg/cue/cuex/providers/addon/addon.cue`
- Modify: `pkg/cue/cuex/compiler.go`
- Create: `pkg/cue/cuex/providers/addon/addon_test.go`

- [ ] **Step 1: Injection seam (avoids the import cycle)**

`pkg/addon/service/registry.go`:
```go
/*
Copyright 2026 The KubeVela Authors. Licensed under the Apache License, Version 2.0.
*/

package service

import "sync"

var (
	mu       sync.RWMutex
	defaultR Renderer
)

// SetDefaultRenderer installs the process-wide renderer (called once at startup).
func SetDefaultRenderer(r Renderer) { mu.Lock(); defaultR = r; mu.Unlock() }

// DefaultRenderer returns the installed renderer, or nil if startup has not wired one.
func DefaultRenderer() Renderer { mu.RLock(); defer mu.RUnlock(); return defaultR }
```

- [ ] **Step 2: Verify no import cycle**

Run: `CGO_ENABLED=0 go build ./pkg/cue/cuex/providers/addon/ 2>&1 || true` after Step 3.
The provider imports only `pkg/addon/service` (for `Renderer`/`AddonRequest`/`AddonResult` + `DefaultRenderer`), never `pkg/addon` directly. `pkg/addon/service` imports `pkg/addon`. If a cycle appears, move `AddonRequest`/`AddonResult`/`Renderer` into a leaf package (e.g. `pkg/addon/service/api`) that neither `pkg/addon` nor the provider's other deps import.

- [ ] **Step 3: Provider Go + CUE**

`pkg/cue/cuex/providers/addon/addon.go`:
```go
/*
Copyright 2026 The KubeVela Authors. Licensed under the Apache License, Version 2.0.
*/

package addon

import (
	"context"
	_ "embed"
	"fmt"

	"github.com/kubevela/pkg/cue/cuex/providers"
	cuexruntime "github.com/kubevela/pkg/cue/cuex/runtime"
	"github.com/kubevela/pkg/util/runtime"

	"github.com/oam-dev/kubevela/pkg/addon/service"
)

// ProviderName is the CUE #provider value.
const ProviderName = "addon"

//go:embed addon.cue
var template string

// RenderVars is the $params shape.
type RenderVars struct {
	Addon      string                 `json:"addon"`
	Version    string                 `json:"version"`
	Registry   string                 `json:"registry"`
	Properties map[string]interface{} `json:"properties"`
}

// ResultVars is the $returns shape.
type ResultVars struct {
	ResolvedVersion string                   `json:"resolvedVersion"`
	Registry        string                   `json:"registry"`
	Application     map[string]interface{}   `json:"application"`
	Resources       []map[string]interface{} `json:"resources"`
}

type RenderParams providers.Params[RenderVars]
type RenderReturns providers.Returns[ResultVars]

// Render resolves and renders an addon via the injected render-only service.
func Render(ctx context.Context, params *RenderParams) (*RenderReturns, error) {
	r := service.DefaultRenderer()
	if r == nil {
		return nil, fmt.Errorf("addon renderer not initialized")
	}
	p := params.Params
	res, err := r.RenderAddon(ctx, service.AddonRequest{
		Name: p.Addon, Version: p.Version, Registry: p.Registry, Properties: p.Properties,
	})
	if err != nil {
		return nil, err
	}
	return &RenderReturns{Returns: ResultVars{
		ResolvedVersion: res.ResolvedVersion,
		Registry:        res.Registry,
		Application:     res.Application,
		Resources:       res.Resources,
	}}, nil
}

// Package is the internal CueX package registered on the WorkloadCompiler.
var Package = runtime.Must(cuexruntime.NewInternalPackage(ProviderName, template, map[string]cuexruntime.ProviderFn{
	"render": cuexruntime.GenericProviderFn[RenderParams, RenderReturns](Render),
}))
```

`pkg/cue/cuex/providers/addon/addon.cue`:
```cue
package addon

#Render: {
	#do:       "render"
	#provider: "addon"

	$params: {
		addon:      string
		version:    *"" | string
		registry:   *"" | string
		properties: *{} | {...}
	}
	$returns: {
		resolvedVersion: string
		registry:        string
		application: {...}
		resources: [...{...}]
	}
}
```

- [ ] **Step 4: Register on the WorkloadCompiler**

In `pkg/cue/cuex/compiler.go`, add the import and add `addon.Package` to the `cuex.NewCompilerWithInternalPackages(...)` list (around line 44), after `cueext.Package`:
```go
import (
	// ...existing imports...
	"github.com/oam-dev/kubevela/pkg/cue/cuex/providers/addon"
)
// ...
compiler := cuex.NewCompilerWithInternalPackages(
	config.Package,
	helm.Package,
	base64.Package,
	http.Package,
	kube.Package,
	cueext.Package,
	addon.Package,
)
```

- [ ] **Step 5: Provider unit test (with a fake renderer)**

`pkg/cue/cuex/providers/addon/addon_test.go`: install a fake `service.Renderer` via `service.SetDefaultRenderer`, call `Render` with a `RenderParams`, assert the returned `application`/`resources` pass through. Also assert `Render` errors when `DefaultRenderer()` is nil.

- [ ] **Step 6: Run + vet + commit**

Run: `CGO_ENABLED=0 go test ./pkg/cue/cuex/providers/addon/ -v && CGO_ENABLED=0 go vet ./pkg/cue/cuex/...`
Expected: PASS, vet clean.
```bash
git add pkg/addon/service/registry.go pkg/cue/cuex/providers/addon/ pkg/cue/cuex/compiler.go
git commit -m "feat(cuex): addon provider registered on the workload compiler"
```

---

## Task 3: The `addon` ComponentDefinition

**Files:**
- Create: `vela-templates/definitions/internal/component/addon.cue`

- [ ] **Step 1: Write the definition**

`vela-templates/definitions/internal/component/addon.cue`:
```cue
"addon": {
	annotations: {}
	attributes: workload: type: "autodetects.core.oam.dev"
	description: "Install an addon as a component; the addon's Application and auxiliaries are tracked by this Application."
	labels: {}
	type: "component"
}

template: {
	_render: addon.#Render & {
		$params: {
			addon:      parameter.addon
			version:    parameter.version
			registry:   parameter.registry
			properties: parameter.properties
		}
	}

	output: _render.$returns.application

	outputs: {
		for i, r in _render.$returns.resources {
			"aux-\(i)": r
		}
	}

	parameter: {
		// Addon name; defaults to the component name.
		addon: *context.name | string
		// Exact version or semver constraint; empty means latest.
		version?: string
		// Registry name; empty means the configured default.
		registry?: string
		// The addon's own parameters, passed through to its templates.
		properties: *{} | {...}
		// Skip the addon's vela/kubernetes SystemRequirements check (mirrors the
		// imperative skipVersionValidate escape hatch). Defaults to enforcing it.
		skipVersionValidate: *false | bool
	}
}
```

`skipVersionValidate` threads to `AddonRequest.SkipVersionValidate` in the provider and service. When false (default), the render enforces the addon's `SystemRequirements`, matching `vela addon enable`.
Note: `import "addon"` is implicit for CueX internal packages resolved by `#provider`. If the build instance requires an explicit import, mirror how `k8s-objects.cue`/other defs reference cuex packages (confirm by grepping an existing definition that calls a `#provider` package).

- [ ] **Step 2: Compile-check the definition renders**

Add a Go test (or extend an existing definitions test) that loads `addon.cue`, applies it as a ComponentDefinition, and renders a component with `parameter.addon: "example"` through the `WorkloadCompiler`, asserting `output.kind == "Application"`. Install a fake `service.SetDefaultRenderer` for the test.

Run: `CGO_ENABLED=0 go test ./pkg/cue/definition/... -run Addon -v` (or the definitions test you extended).
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add vela-templates/definitions/internal/component/addon.cue
git commit -m "feat(addon): addon ComponentDefinition (output=Application, outputs=auxiliaries)"
```

---

## Task 4: Wire the renderer at controller startup

**Files:**
- Modify: `cmd/core/app/server.go`

- [ ] **Step 1: Inject the renderer once the manager client + config exist**

In `cmd/core/app/server.go`, after the controller-runtime manager is created and its client/config are available (search for where `mgr` is built and `mgr.GetClient()` / the `*rest.Config` are in scope), add:
```go
import addonservice "github.com/oam-dev/kubevela/pkg/addon/service"
// ...
addonservice.SetDefaultRenderer(addonservice.NewRenderer(mgr.GetClient(), restConfig))
```
Place it before the manager starts (before `mgr.Start(ctx)`), so the provider is usable on the first reconcile. Confirm the exact variable names for the client and `*rest.Config` in that file.

- [ ] **Step 2: Build the binary**

Run: `CGO_ENABLED=0 go build -o /tmp/vela-core-addon-comp ./cmd/core`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add cmd/core/app/server.go
git commit -m "feat(addon): inject the addon renderer at controller startup"
```

---

## Task 5: Resolve-once cache (skip repeat registry I/O)

**Files:**
- Modify: `pkg/addon/service/renderer.go`
- Modify: `pkg/addon/service/renderer_test.go`

- [ ] **Step 1: Failing test — repeat calls do not re-fetch**

Add a test where the `Source`/fetch is counted (inject a counting stub) and assert two `RenderAddon` calls with identical `AddonRequest` trigger exactly one fetch.

- [ ] **Step 2: Implement a keyed cache**

Add to `rendererImpl` a `sync.Map` (or an LRU) keyed by `fmt.Sprintf("%s|%s|%s|%s", req.Name, req.Version, req.Registry, hashProperties(req.Properties))`. On hit, return the cached `*AddonResult`. On miss, resolve+render, store, return. `hashProperties` marshals the map to canonical JSON and SHA-256s it. Document that this cache is the in-process half of "resolve once"; the durable pin is the rendered manifests captured in the `ApplicationRevision` by the existing Application controller. Invalidate on nothing (keys already include every input); a version/property change is a new key.

- [ ] **Step 3: Run + commit**

Run: `CGO_ENABLED=0 go test ./pkg/addon/service/ -v && CGO_ENABLED=0 go vet ./pkg/addon/service/`
```bash
git add pkg/addon/service/renderer.go pkg/addon/service/renderer_test.go
git commit -m "feat(addon): cache addon resolution keyed by name/version/registry/properties"
```

---

## Task 6: End-to-end test (real cluster, real registry)

**Files:**
- Create: `test/e2e-test/addon_component_test.go`

- [ ] **Step 1: Write the e2e spec (Ginkgo, matches existing suite style)**

Add a `Describe("Addon component e2e", ...)` that, against the running controller + configured registry:
- Applies an `Application` with a single `type: addon` component (`properties.addon: "fluxcd"`, an exact `version`).
- Waits for the Application to reach `running`/healthy.
- Asserts the child `addon-fluxcd` Application exists and is owned/tracked by the wrapping Application's ResourceTracker.
- Asserts an auxiliary (e.g. the `helm` ComponentDefinition) exists.
- Deletes the auxiliary and asserts StateKeep heals it back (no manual addon step).
- Deletes the wrapping Application and asserts the child Application and auxiliaries are garbage-collected.

Follow the harness in `test/e2e-test/suite_test.go` (uses `config.GetConfigOrDie()`; assumes a running controller + registry).

- [ ] **Step 2: Run against a cluster**

Bring up the controller built in Task 4 with the real registry configured, then:
Run: `CGO_ENABLED=0 go test ./test/e2e-test/ -run TestAPIs -timeout 1800s -args --ginkgo.focus="Addon component e2e"`
Expected: the spec passes.

- [ ] **Step 3: Commit**

```bash
git add test/e2e-test/addon_component_test.go
git commit -m "test(addon): e2e for addon-as-component install, heal, and GC"
```

---

## Task 7: Reject incompatible addons at admission (Application webhook)

**Files:**
- Modify: `pkg/webhook/core.oam.dev/v1beta1/application/validation.go` (add an addon-compatibility check invoked from `ValidateComponents`, `validation.go:92`)
- Modify: `pkg/webhook/core.oam.dev/v1beta1/application/validating_handler.go` (give the handler what it needs to resolve addon meta; it already has `Client`)
- Create/extend: `pkg/webhook/core.oam.dev/v1beta1/application/validation_handlers_test.go`
- Add (if not already from Task 1): a lightweight meta resolver, e.g. `func (r *rendererImpl) ResolveSystemRequirements(ctx, req AddonRequest) (*pkgaddon.SystemRequirements, string, error)` in `pkg/addon/service`, or a `pkg/addon` helper that fetches only the addon meta (not a full render).

Behavior: for each component with `Type == "addon"`, decode its properties (`addon`, `version`, `registry`, `skipVersionValidate`), resolve the addon meta's `SystemRequirements`, and call `pkgaddon.ValidateSystemRequirements`. On mismatch, append a `field.Invalid` error (message includes the failing constraint and, if available via `getAddonVersionMeetSystemRequirement`, a suggested compatible version) so admission is denied. Honor `skipVersionValidate: true` by skipping the check.

Availability policy (make the webhook safe): fetch meta only, never a full render; on a registry/resolve error (registry down, addon not found yet, timeout) FAIL OPEN — do not deny the Application; log and let the render-time check (Task 1) and normal reconcile surface the problem. Denials happen only on a definite compatibility mismatch. This keeps a registry outage from blocking every Application apply.

- [ ] **Step 1: Failing unit test** — table-driven test on the new validation function using a fake/stubbed resolver: (a) compatible → no error; (b) incompatible vela/k8s version → one `field.Invalid`; (c) `skipVersionValidate: true` → no error; (d) resolver returns an error → no denial (fail-open). Do not require a live registry; inject the resolver.
- [ ] **Step 2: Run to verify it fails** — `CGO_ENABLED=0 go test ./pkg/webhook/core.oam.dev/v1beta1/application/ -run Addon -v` → FAIL (undefined).
- [ ] **Step 3: Implement** — add the check to `ValidateComponents` (or a dedicated `validateAddonComponents`), wire the resolver into the handler (inject via `SetupWithManager`, using `mgr.GetClient()` and, for a discovery client, `mgr.GetConfig()`), and the fail-open policy.
- [ ] **Step 4: Run + vet** — `CGO_ENABLED=0 go test ./pkg/webhook/core.oam.dev/v1beta1/application/ -v && CGO_ENABLED=0 go vet ./pkg/webhook/...` → PASS, clean.
- [ ] **Step 5: git add (no commit)** — `git add pkg/webhook/core.oam.dev/v1beta1/application/ pkg/addon/service/` (do not commit; do not add docs).

Note: the render-time check from Task 1 stays as the backstop for the fail-open case and for any path that bypasses the webhook (for example webhooks disabled). Task 6's e2e should add a rejection case; testing the webhook end-to-end requires webhooks enabled (cert setup), so the unit test above is the primary coverage.

## Ordering and readiness

The existing addon install does not sequence CRDs/definitions before the addon Application through a dependency graph. `dispatchAddonResource` (`pkg/addon/addon.go:1502`) creates the Application object first (line 1561), then applies the definitions and other auxiliaries immediately after (lines 1575-1596) in the same call. `passDefInAppAnnotation` (`utils.go:58`) only records definition names for the disable-time usage check; it is not an ordering mechanism. Correctness relies on two things: addon Applications almost always use built-in component types (not the addon's own definitions), and the Application controller requeues, so definitions applied moments later are present on a later reconcile.

The component model inherits the same behavior. The definitions are the wrapping component's `outputs` and the child addon Application is the `output`; the wrapping Application dispatches both, and the child Application requeues until the definitions exist. No new ordering code is needed for v1.

One edge case to cover in testing: an addon whose own Application consumes the addon's own component/trait definitions. Task 6 should include (or note) an addon of this shape and assert it converges. If strict ordering is ever required, restructure the definitions into their own components and use component `dependsOn` from the child-Application component; this is deliberately deferred.

## Out of scope (v1) / future work

- **Dependencies.** Addons with declared dependencies are not designed for in v1; noted in the spec. Follow-up: expand dependencies into the same wrapping Application.
- **Constraint pinning across revisions.** v1 pins the rendered manifests in the ApplicationRevision and caches in-process. A semver constraint like `>=2.0.0` re-resolves to the latest satisfying version when a new revision is cut; pinning a resolved constraint into the spec/revision is future work. Recommend exact versions for strict GitOps determinism.
- **Addon CR decision.** Whether this replaces the KEP-2.13 Addon CR is decided after v1.

## Self-Review

- **Spec coverage:** component API (Task 3), reuse of `pkg/addon` render/registry (Task 1), CueX provider + WorkloadCompiler registration (Task 2), startup injection (Task 4), resolve-once cache + revision pin (Task 5), e2e for install/heal/GC (Task 6). Nested-Application shape from the spec is realized by `output = _render.$returns.application`.
- **Type consistency:** `AddonRequest`/`AddonResult` (service) ↔ `RenderVars`/`ResultVars` (provider) ↔ `$params`/`$returns` (CUE) ↔ `parameter`/`output`/`outputs` (definition) use the same field names (addon, version, registry, properties, application, resources, resolvedVersion).
- **Known fill-in points (named, not vague):** Task 1 Step 3 has two `// STEP:` markers (exact-version fetch; extra auxiliary render calls) that name the real functions and lines to read first. Task 3 Step 1 flags confirming how a definition imports a `#provider` package. Task 4 Step 1 flags confirming the client/`*rest.Config` variable names. These are signature-confirmation steps, not placeholders.
- **Scope:** one subsystem; dependencies and CR-replacement explicitly deferred.
