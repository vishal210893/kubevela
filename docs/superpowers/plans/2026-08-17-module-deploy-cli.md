# `vela module deploy` CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `vela module deploy <module>`, which validates a module against its registry, applies a one-component `type: module` Application, and reports per-tier install progress.

**Architecture:** The command is a thin client over existing pieces. `pkg/module.ResolveRegistry` picks the registry, `pkg/module/service.Service.FetchModule` proves the module exists and yields its parsed form, a pure builder turns that into a `v1beta1.Application` with one `type: module` component, and a poll loop reads two Applications — the outer one this command creates (`module-<name>-deploy`) for phase and failure, and the owned one the render service creates (`module-<name>`) for per-tier health.

**Tech Stack:** Go 1.23, cobra, controller-runtime v0.19.7 (`sigs.k8s.io/controller-runtime/pkg/client/fake` and `.../client/interceptor` for tests), `github.com/stretchr/testify`, `github.com/gosuri/uitable` for tables.

**Design doc:** `docs/superpowers/specs/2026-08-17-module-deploy-cli-design.md`
**Upstream spec:** `specs/oss-kubevela/gwcp-106942-module-deploy-cli/` in `gwre-pdo/specs`

## Global Constraints

- Go tests in this devcontainer must run with `CGO_ENABLED=0`; without it the toolchain fails with `cannot find 'ld'`.
- All new files carry the Apache 2.0 header used by every other file in `references/cli/`, with `Copyright 2026 The KubeVela Authors.`
- No code comments beyond doc comments on exported and package-level identifiers, matching the surrounding files.
- Errors are wrapped with `fmt.Errorf(... %w ...)`; resolver and fetch errors are returned as-is so their own text (registry names, module paths) survives.
- The outer Application is named `module-<module>-deploy`. The owned Application the render service creates is `module-<module>`. Never make these equal.
- Default namespace is `vela-system` (`types.DefaultKubeVelaNS`), not `default`.
- Tests are table-driven with `t.Run` subtests, following `references/cli/module-registry_test.go`.

---

## File Structure

| File | Responsibility |
|---|---|
| `references/cli/module-deploy.go` (create) | the `deploy` command: flags, validation, builder, apply, wait/report. No `--file` flag — `--dry-run` plus a shell redirect covers manifest capture (see the design doc's deviation 5). |
| `references/cli/module-deploy_test.go` (create) | all tests for the above |
| `references/cli/module-registry.go` (modify, line 64) | mount `deploy` on the `vela module` group |

One command file is right here: `module-registry.go` holds five subcommands in ~500 lines, so a single focused file per subcommand group matches the existing shape.

---

## Task 1: Application builder and expected tiers

**Files:**
- Create: `references/cli/module-deploy.go`
- Create: `references/cli/module-deploy_test.go`

**Interfaces:**
- Consumes: `pkgmodule.Module`, `pkgmodule.Line` from `pkg/module/module.go`
- Produces:
  - `func buildModuleApplication(moduleName, registryName, namespace string) (*v1beta1.Application, error)`
  - `func expectedModuleTiers(mod *pkgmodule.Module) []string`
  - `func moduleDeployAppName(moduleName string) string`
  - `func ownedModuleAppName(moduleName string) string`

- [ ] **Step 1: Write the failing tests**

Create `references/cli/module-deploy_test.go`:

```go
/*
Copyright 2026 The KubeVela Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package cli

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	pkgmodule "github.com/oam-dev/kubevela/pkg/module"
)

func TestBuildModuleApplication(t *testing.T) {
	app, err := buildModuleApplication("s3", "catalog", "vela-system")
	require.NoError(t, err)

	assert.Equal(t, "module-s3-deploy", app.Name)
	assert.Equal(t, "vela-system", app.Namespace)
	assert.Equal(t, "core.oam.dev/v1beta1", app.APIVersion)
	assert.Equal(t, "Application", app.Kind)

	require.Len(t, app.Spec.Components, 1)
	comp := app.Spec.Components[0]
	assert.Equal(t, "s3", comp.Name)
	assert.Equal(t, "module", comp.Type)

	require.NotNil(t, comp.Properties)
	var props map[string]string
	require.NoError(t, json.Unmarshal(comp.Properties.Raw, &props))
	assert.Equal(t, map[string]string{
		"module":    "s3",
		"registry":  "catalog",
		"namespace": "vela-system",
	}, props)
}

func TestExpectedModuleTiers(t *testing.T) {
	testCases := map[string]struct {
		mod  *pkgmodule.Module
		want []string
	}{
		"xrd, one line with composition and definitions": {
			mod: &pkgmodule.Module{
				Name: "s3",
				XRD:  map[string]interface{}{"kind": "CompositeResourceDefinition"},
				Lines: map[string]pkgmodule.Line{
					"v1": {
						APIVersion:  "v1",
						Enabled:     true,
						Composition: map[string]interface{}{"kind": "Composition"},
						Definitions: []map[string]interface{}{{"kind": "ComponentDefinition"}},
					},
				},
			},
			want: []string{"s3-xrd", "s3-v1-comp", "s3-v1-defs"},
		},
		"disabled lines are skipped": {
			mod: &pkgmodule.Module{
				Name: "s3",
				Lines: map[string]pkgmodule.Line{
					"v1": {APIVersion: "v1", Enabled: true, Definitions: []map[string]interface{}{{"kind": "ComponentDefinition"}}},
					"v2": {APIVersion: "v2", Enabled: false, Definitions: []map[string]interface{}{{"kind": "ComponentDefinition"}}},
				},
			},
			want: []string{"s3-v1-defs"},
		},
		"lines are sorted lexically": {
			mod: &pkgmodule.Module{
				Name: "s3",
				Lines: map[string]pkgmodule.Line{
					"v2":  {APIVersion: "v2", Enabled: true, Definitions: []map[string]interface{}{{"kind": "ComponentDefinition"}}},
					"v10": {APIVersion: "v10", Enabled: true, Definitions: []map[string]interface{}{{"kind": "ComponentDefinition"}}},
				},
			},
			want: []string{"s3-v10-defs", "s3-v2-defs"},
		},
		"no xrd and no composition": {
			mod: &pkgmodule.Module{
				Name: "kro",
				Lines: map[string]pkgmodule.Line{
					"v1": {APIVersion: "v1", Enabled: true, Definitions: []map[string]interface{}{{"kind": "ComponentDefinition"}}},
				},
			},
			want: []string{"kro-v1-defs"},
		},
	}

	for name, tc := range testCases {
		t.Run(name, func(t *testing.T) {
			assert.Equal(t, tc.want, expectedModuleTiers(tc.mod))
		})
	}
}

func TestModuleAppNames(t *testing.T) {
	assert.Equal(t, "module-s3-deploy", moduleDeployAppName("s3"))
	assert.Equal(t, "module-s3", ownedModuleAppName("s3"))
	assert.NotEqual(t, moduleDeployAppName("s3"), ownedModuleAppName("s3"))
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `CGO_ENABLED=0 go test ./references/cli/ -run 'TestBuildModuleApplication|TestExpectedModuleTiers|TestModuleAppNames' -v`
Expected: FAIL — `undefined: buildModuleApplication`, `undefined: expectedModuleTiers`, `undefined: moduleDeployAppName`, `undefined: ownedModuleAppName`.

- [ ] **Step 3: Write the minimal implementation**

Create `references/cli/module-deploy.go`:

```go
/*
Copyright 2026 The KubeVela Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package cli

import (
	"encoding/json"
	"fmt"
	"sort"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"

	oamcommon "github.com/oam-dev/kubevela/apis/core.oam.dev/common"
	"github.com/oam-dev/kubevela/apis/core.oam.dev/v1beta1"
	pkgmodule "github.com/oam-dev/kubevela/pkg/module"
)

// moduleComponentType is the ComponentDefinition the deploy command builds a
// component of. Its template calls the module render service, which fetches the
// module and renders the owned Application holding the install tiers.
const moduleComponentType = "module"

// moduleComponentProperties are the parameters of the type: module component.
// It is a struct rather than a map so the rendered manifest has a stable field
// order.
type moduleComponentProperties struct {
	Module    string `json:"module"`
	Registry  string `json:"registry"`
	Namespace string `json:"namespace"`
}

// moduleDeployAppName is the name of the Application the deploy command
// creates. The "-deploy" suffix keeps it distinct from ownedModuleAppName: the
// render service names the owned Application "module-<name>", and the two
// collide when both live in the same namespace.
func moduleDeployAppName(moduleName string) string {
	return "module-" + moduleName + "-deploy"
}

// ownedModuleAppName is the name the render service gives the Application it
// renders for a module, mirroring RenderApplication in
// pkg/module/service/render.go.
func ownedModuleAppName(moduleName string) string {
	return "module-" + moduleName
}

// buildModuleApplication builds the one-component Application that installs a
// module. The registry name is the resolved one, not the raw flag, so the
// applied manifest records which registry was chosen.
func buildModuleApplication(moduleName, registryName, namespace string) (*v1beta1.Application, error) {
	props, err := json.Marshal(moduleComponentProperties{
		Module:    moduleName,
		Registry:  registryName,
		Namespace: namespace,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to encode the module component properties: %w", err)
	}
	return &v1beta1.Application{
		TypeMeta: metav1.TypeMeta{
			APIVersion: v1beta1.SchemeGroupVersion.String(),
			Kind:       v1beta1.ApplicationKind,
		},
		ObjectMeta: metav1.ObjectMeta{
			Name:      moduleDeployAppName(moduleName),
			Namespace: namespace,
		},
		Spec: v1beta1.ApplicationSpec{
			Components: []oamcommon.ApplicationComponent{{
				Name:       moduleName,
				Type:       moduleComponentType,
				Properties: &runtime.RawExtension{Raw: props},
			}},
		},
	}, nil
}

// expectedModuleTiers returns the component names the render service will give
// the module's install tiers, in the order it emits them. It mirrors
// RenderApplication in pkg/module/service/render.go, so the status report can
// name every tier before the owned Application exists.
func expectedModuleTiers(mod *pkgmodule.Module) []string {
	if mod == nil {
		return nil
	}
	tiers := []string{}
	if mod.XRD != nil {
		tiers = append(tiers, mod.Name+"-xrd")
	}
	for _, apiVersion := range enabledModuleLines(mod) {
		line := mod.Lines[apiVersion]
		if line.Composition != nil {
			tiers = append(tiers, fmt.Sprintf("%s-%s-comp", mod.Name, apiVersion))
		}
		if len(line.Definitions) > 0 {
			tiers = append(tiers, fmt.Sprintf("%s-%s-defs", mod.Name, apiVersion))
		}
	}
	return tiers
}

// enabledModuleLines returns the module's enabled API versions, sorted
// lexically the way the render service sorts them.
func enabledModuleLines(mod *pkgmodule.Module) []string {
	out := make([]string, 0, len(mod.Lines))
	for apiVersion, line := range mod.Lines {
		if line.Enabled {
			out = append(out, apiVersion)
		}
	}
	sort.Strings(out)
	return out
}
```

`v1beta1.ApplicationKind` and `v1beta1.SchemeGroupVersion` are defined in `apis/core.oam.dev/v1beta1/register.go:100`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `CGO_ENABLED=0 go test ./references/cli/ -run 'TestBuildModuleApplication|TestExpectedModuleTiers|TestModuleAppNames' -v`
Expected: PASS, all subtests green.

- [ ] **Step 5: Commit**

```bash
git add references/cli/module-deploy.go references/cli/module-deploy_test.go
git commit -m "feat(module): add the deploy Application builder and tier expectation"
```

---

## Task 2: The deploy command — validation, dry run, apply

**Files:**
- Modify: `references/cli/module-deploy.go`
- Modify: `references/cli/module-deploy_test.go`
- Modify: `references/cli/module-registry.go:64` (mount the subcommand)

**Interfaces:**
- Consumes: `buildModuleApplication`, `expectedModuleTiers`, `moduleDeployAppName` from Task 1; `pkgmodule.ResolveRegistry`, `pkgmodule.NewStore` (`pkg/module/registry.go:54,76`); `service.NewService(store).FetchModule(ctx, registry, moduleName)` (`pkg/module/service/fetch.go:48,68`); `apply.NewAPIApplicator(client).Apply(ctx, obj)` (`pkg/utils/apply/apply.go:81,185`)
- Produces:
  - `func NewModuleDeployCommand(c common.Args, ioStreams cmdutil.IOStreams) *cobra.Command`
  - `type moduleDeployOptions struct` with fields `module, registry, namespace string`, `dryRun bool`, `timeout, pollInterval time.Duration`, `fetch func(ctx context.Context, registry, moduleName string) (*pkgmodule.Module, error)`
  - `func (o *moduleDeployOptions) run(ctx context.Context, cli client.Client, out io.Writer) error`

- [ ] **Step 1: Write the failing tests**

Append to `references/cli/module-deploy_test.go` (and extend the import block with `bytes`, `context`, `time`, `sigs.k8s.io/controller-runtime/pkg/client`, `sigs.k8s.io/controller-runtime/pkg/client/fake`, `sigs.k8s.io/yaml`, `corev1 "k8s.io/api/core/v1"`, `"github.com/oam-dev/kubevela/apis/core.oam.dev/v1beta1"`, `pkgaddon "github.com/oam-dev/kubevela/pkg/addon"`, `velatypes "github.com/oam-dev/kubevela/apis/types"`, `"github.com/oam-dev/kubevela/pkg/utils/common"`):

```go
// moduleDeployClient returns a fake client seeded with a module registry
// ConfigMap holding the named registries, so ResolveRegistry can run without a
// cluster.
func moduleDeployClient(t *testing.T, registries ...string) client.Client {
	t.Helper()
	data := "[]"
	if len(registries) > 0 {
		entries := make([]pkgaddon.Registry, 0, len(registries))
		for _, name := range registries {
			entries = append(entries, pkgaddon.Registry{
				Name: name,
				Git:  &pkgaddon.GitAddonSource{URL: "https://github.com/kubevela/catalog", Path: "module"},
			})
		}
		raw, err := json.Marshal(entries)
		require.NoError(t, err)
		data = string(raw)
	}
	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      pkgmodule.ModuleRegistryConfigMap,
			Namespace: velatypes.DefaultKubeVelaNS,
		},
		Data: map[string]string{"registries": data},
	}
	return fake.NewClientBuilder().WithScheme(common.Scheme).WithObjects(cm).Build()
}

// stubModule is the module the fetch seam returns in tests: an XRD plus one
// enabled line with a Composition and one definition.
func stubModule() *pkgmodule.Module {
	return &pkgmodule.Module{
		Name:    "s3",
		Version: "1.0.0",
		XRD:     map[string]interface{}{"kind": "CompositeResourceDefinition"},
		Lines: map[string]pkgmodule.Line{
			"v1": {
				APIVersion:  "v1",
				Enabled:     true,
				Composition: map[string]interface{}{"kind": "Composition"},
				Definitions: []map[string]interface{}{{"kind": "ComponentDefinition"}},
			},
		},
	}
}

// countApplications returns how many Applications exist on a client.
func countApplications(t *testing.T, cli client.Client) int {
	t.Helper()
	var apps v1beta1.ApplicationList
	require.NoError(t, cli.List(context.Background(), &apps))
	return len(apps.Items)
}

func TestModuleDeployDryRun(t *testing.T) {
	cli := moduleDeployClient(t, "catalog")
	var out bytes.Buffer
	o := &moduleDeployOptions{
		module:    "s3",
		registry:  "catalog",
		namespace: velatypes.DefaultKubeVelaNS,
		dryRun:    true,
		fetch: func(_ context.Context, registry, moduleName string) (*pkgmodule.Module, error) {
			assert.Equal(t, "catalog", registry)
			assert.Equal(t, "s3", moduleName)
			return stubModule(), nil
		},
	}

	require.NoError(t, o.run(context.Background(), cli, &out))

	var printed v1beta1.Application
	require.NoError(t, yaml.Unmarshal(out.Bytes(), &printed))
	assert.Equal(t, "module-s3-deploy", printed.Name)
	require.Len(t, printed.Spec.Components, 1)
	assert.Equal(t, "module", printed.Spec.Components[0].Type)
	assert.Equal(t, 0, countApplications(t, cli))
}

func TestModuleDeployFailsBeforeApply(t *testing.T) {
	testCases := map[string]struct {
		registry    string
		registries  []string
		fetch       func(ctx context.Context, registry, moduleName string) (*pkgmodule.Module, error)
		wantErrPart string
	}{
		"unknown registry": {
			registry:    "missing",
			registries:  []string{"catalog"},
			fetch:       func(_ context.Context, _, _ string) (*pkgmodule.Module, error) { return stubModule(), nil },
			wantErrPart: `module registry "missing" not found`,
		},
		"no registry configured": {
			registry:    "",
			registries:  nil,
			fetch:       func(_ context.Context, _, _ string) (*pkgmodule.Module, error) { return stubModule(), nil },
			wantErrPart: "no module registry is configured",
		},
		"module not in registry": {
			registry:   "catalog",
			registries: []string{"catalog"},
			fetch: func(_ context.Context, _, _ string) (*pkgmodule.Module, error) {
				return nil, fmt.Errorf(`module "s4" not found in registry "catalog"`)
			},
			wantErrPart: `module "s4" not found`,
		},
	}

	for name, tc := range testCases {
		t.Run(name, func(t *testing.T) {
			cli := moduleDeployClient(t, tc.registries...)
			o := &moduleDeployOptions{
				module:    "s3",
				registry:  tc.registry,
				namespace: velatypes.DefaultKubeVelaNS,
				fetch:     tc.fetch,
			}

			err := o.run(context.Background(), cli, &bytes.Buffer{})

			require.Error(t, err)
			assert.Contains(t, err.Error(), tc.wantErrPart)
			assert.Equal(t, 0, countApplications(t, cli), "nothing may be applied when validation fails")
		})
	}
}

func TestModuleDeployResolvesDefaultRegistry(t *testing.T) {
	cli := moduleDeployClient(t, "catalog")
	var out bytes.Buffer
	o := &moduleDeployOptions{
		module:    "s3",
		registry:  "",
		namespace: velatypes.DefaultKubeVelaNS,
		dryRun:    true,
		fetch: func(_ context.Context, registry, _ string) (*pkgmodule.Module, error) {
			assert.Equal(t, "catalog", registry, "the resolved registry is passed to fetch")
			return stubModule(), nil
		},
	}

	require.NoError(t, o.run(context.Background(), cli, &out))

	var printed v1beta1.Application
	require.NoError(t, yaml.Unmarshal(out.Bytes(), &printed))
	var props map[string]string
	require.NoError(t, json.Unmarshal(printed.Spec.Components[0].Properties.Raw, &props))
	assert.Equal(t, "catalog", props["registry"], "the manifest pins the resolved registry")
}

func TestNewModuleDeployCommandFlags(t *testing.T) {
	cmd := NewModuleDeployCommand(common.Args{}, cmdutil.IOStreams{})
	assert.Equal(t, "deploy", strings.Split(cmd.Use, " ")[0])
	for _, flag := range []string{"registry", "dry-run", "timeout"} {
		assert.NotNil(t, cmd.Flags().Lookup(flag), "flag %q must exist", flag)
	}
	assert.Error(t, cmd.Args(cmd, []string{}), "the module name is required")
	assert.NoError(t, cmd.Args(cmd, []string{"s3"}))
}

func TestModuleCommandMountsDeploy(t *testing.T) {
	cmd := NewModuleCommand(common.Args{}, "", cmdutil.IOStreams{})
	names := []string{}
	for _, sub := range cmd.Commands() {
		names = append(names, strings.Split(sub.Use, " ")[0])
	}
	assert.Contains(t, names, "deploy")
}
```

Add `"strings"`, `"fmt"`, and `cmdutil "github.com/oam-dev/kubevela/pkg/utils/util"` to the test imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `CGO_ENABLED=0 go test ./references/cli/ -run 'TestModuleDeploy|TestNewModuleDeployCommandFlags|TestModuleCommandMountsDeploy' -v`
Expected: FAIL — `undefined: moduleDeployOptions`, `undefined: NewModuleDeployCommand`.

- [ ] **Step 3: Write the minimal implementation**

Add to `references/cli/module-deploy.go` (extend the import block with `context`, `io`, `time`, `github.com/spf13/cobra`, `k8s.io/apimachinery/pkg/util/validation`, `sigs.k8s.io/controller-runtime/pkg/client`, `sigs.k8s.io/yaml`, `modulesvc "github.com/oam-dev/kubevela/pkg/module/service"`, `"github.com/oam-dev/kubevela/pkg/utils/apply"`, `"github.com/oam-dev/kubevela/pkg/utils/common"`, `cmdutil "github.com/oam-dev/kubevela/pkg/utils/util"`, `velatypes "github.com/oam-dev/kubevela/apis/types"`):

```go
const (
	moduleDeployRegistryFlag = "registry"
	moduleDeployDryRunFlag   = "dry-run"
	moduleDeployTimeoutFlag  = "timeout"

	// defaultModuleDeployTimeout is how long deploy waits for every tier to
	// become healthy before giving up.
	defaultModuleDeployTimeout = 5 * time.Minute
	// defaultModuleDeployPollInterval is how often deploy re-reads the two
	// Applications while waiting.
	defaultModuleDeployPollInterval = 2 * time.Second
)

// moduleDeployOptions holds one run of the deploy command. fetch and
// pollInterval are seams: production wires the registry-backed fetch and the
// default interval, tests inject a stub and a millisecond interval.
type moduleDeployOptions struct {
	module       string
	registry     string
	namespace    string
	dryRun       bool
	timeout      time.Duration
	pollInterval time.Duration
	fetch        func(ctx context.Context, registry, moduleName string) (*pkgmodule.Module, error)
}

// NewModuleDeployCommand returns the vela module deploy command. It builds and
// applies an Application with a single type: module component, then reports the
// install tiers as they become healthy.
func NewModuleDeployCommand(c common.Args, ioStreams cmdutil.IOStreams) *cobra.Command {
	o := &moduleDeployOptions{}
	cmd := &cobra.Command{
		Use:   "deploy <module>",
		Short: "Deploy a module.",
		Long:  "Build and apply an Application that installs a module's enabled API lines, then report the install tiers as they become healthy.",
		Example: `  Deploy a module from the default registry:
	vela module deploy s3

  Deploy from a named registry, into a namespace:
	vela module deploy s3 --registry catalog -n platform

  Print the Application without applying it, capturing it for GitOps:
	vela module deploy s3 --dry-run > s3-module.yaml`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			cli, err := c.GetClient()
			if err != nil {
				return err
			}
			o.module = args[0]
			o.namespace, err = cmd.Flags().GetString("namespace")
			if err != nil {
				return err
			}
			if o.namespace == "" {
				o.namespace = velatypes.DefaultKubeVelaNS
			}
			return o.run(cmd.Context(), cli, cmd.OutOrStdout())
		},
	}
	cmd.Flags().StringVar(&o.registry, moduleDeployRegistryFlag, "", "The module registry to deploy from. Empty means the configured default.")
	cmd.Flags().BoolVar(&o.dryRun, moduleDeployDryRunFlag, false, "Print the Application without applying it.")
	cmd.Flags().DurationVar(&o.timeout, moduleDeployTimeoutFlag, defaultModuleDeployTimeout, "How long to wait for the module to become healthy.")
	addNamespaceAndEnvArg(cmd)
	return cmd
}

// run validates the registry and the module, builds the Application, and either
// prints it or applies it and waits.
func (o *moduleDeployOptions) run(ctx context.Context, cli client.Client, out io.Writer) error {
	if errs := validation.IsDNS1123Label(o.module); len(errs) > 0 {
		return fmt.Errorf("invalid module name %q: %s", o.module, errs[0])
	}
	if o.namespace == "" {
		o.namespace = velatypes.DefaultKubeVelaNS
	}
	if o.pollInterval <= 0 {
		o.pollInterval = defaultModuleDeployPollInterval
	}
	if o.timeout <= 0 {
		o.timeout = defaultModuleDeployTimeout
	}

	store := pkgmodule.NewStore(cli)
	reg, err := pkgmodule.ResolveRegistry(ctx, store, o.registry)
	if err != nil {
		return err
	}

	fetch := o.fetch
	if fetch == nil {
		fetch = modulesvc.NewService(store).FetchModule
	}
	mod, err := fetch(ctx, reg.Name, o.module)
	if err != nil {
		return err
	}

	app, err := buildModuleApplication(o.module, reg.Name, o.namespace)
	if err != nil {
		return err
	}
	if o.dryRun {
		manifest, err := yaml.Marshal(app)
		if err != nil {
			return fmt.Errorf("failed to encode the Application manifest: %w", err)
		}
		_, err = out.Write(manifest)
		return err
	}

	if err := apply.NewAPIApplicator(cli).Apply(ctx, app); err != nil {
		return fmt.Errorf("failed to apply Application %s/%s: %w", app.Namespace, app.Name, err)
	}
	fmt.Fprintf(out, "Applied Application %s/%s\n", app.Namespace, app.Name)

	return o.waitForModule(ctx, cli, expectedModuleTiers(mod), out)
}
```

Add a temporary stub so the package compiles before Task 3 implements it:

```go
// waitForModule polls the deploy Application and the owned module Application
// until every tier is healthy. Task 3 implements it.
func (o *moduleDeployOptions) waitForModule(_ context.Context, _ client.Client, _ []string, _ io.Writer) error {
	return nil
}
```

`addNamespaceAndEnvArg` is defined at `references/cli/common.go:66`; it registers the `namespace`/`-n` flag the `RunE` above reads.

Then mount the command — in `references/cli/module-registry.go`, replace line 64:

```go
	cmd.AddCommand(NewModuleRegistryCommand(c, ioStreams), NewModuleDeployCommand(c, ioStreams))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `CGO_ENABLED=0 go test ./references/cli/ -run 'TestModuleDeploy|TestNewModuleDeployCommandFlags|TestModuleCommandMountsDeploy|TestBuildModuleApplication|TestExpectedModuleTiers|TestModuleAppNames' -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add references/cli/module-deploy.go references/cli/module-deploy_test.go references/cli/module-registry.go
git commit -m "feat(module): add vela module deploy with validation, dry run, and apply"
```

---

## Task 3: Wait for readiness and report per-tier status

**Files:**
- Modify: `references/cli/module-deploy.go` (replace the `waitForModule` stub)
- Modify: `references/cli/module-deploy_test.go`

**Interfaces:**
- Consumes: `moduleDeployOptions`, `ownedModuleAppName`, `expectedModuleTiers` from Tasks 1-2; `oamcommon.ApplicationComponentStatus{Name, Healthy, Message}` (`apis/core.oam.dev/common/types.go:171`); phases `oamcommon.ApplicationRunning`, `ApplicationWorkflowFailed`, `ApplicationWorkflowTerminated`, `ApplicationDeleting` (`apis/core.oam.dev/common/types.go:158-167`)
- Produces:
  - `func (o *moduleDeployOptions) waitForModule(ctx context.Context, cli client.Client, tiers []string, out io.Writer) error`
  - `func renderModuleTierTable(tiers []string, services []oamcommon.ApplicationComponentStatus) string`
  - `func firstUnhealthyTier(tiers []string, services []oamcommon.ApplicationComponentStatus) (string, string)`

- [ ] **Step 1: Write the failing tests**

Append to `references/cli/module-deploy_test.go` (add `"sigs.k8s.io/controller-runtime/pkg/client/interceptor"` and `oamcommon "github.com/oam-dev/kubevela/apis/core.oam.dev/common"` to the imports):

```go
// moduleApps returns the deploy Application in the given phase and the owned
// module Application with the given tier services.
func moduleApps(phase oamcommon.ApplicationPhase, services []oamcommon.ApplicationComponentStatus) []client.Object {
	deployApp := &v1beta1.Application{
		ObjectMeta: metav1.ObjectMeta{Name: "module-s3-deploy", Namespace: velatypes.DefaultKubeVelaNS},
		Status:     oamcommon.AppStatus{Phase: phase},
	}
	ownedApp := &v1beta1.Application{
		ObjectMeta: metav1.ObjectMeta{Name: "module-s3", Namespace: velatypes.DefaultKubeVelaNS},
		Status:     oamcommon.AppStatus{Services: services},
	}
	return []client.Object{deployApp, ownedApp}
}

func healthyTierServices() []oamcommon.ApplicationComponentStatus {
	return []oamcommon.ApplicationComponentStatus{
		{Name: "s3-xrd", Healthy: true, Message: "Established"},
		{Name: "s3-v1-comp", Healthy: true},
		{Name: "s3-v1-defs", Healthy: true},
	}
}

func TestRenderModuleTierTable(t *testing.T) {
	table := renderModuleTierTable(
		[]string{"s3-xrd", "s3-v1-comp", "s3-v1-defs"},
		[]oamcommon.ApplicationComponentStatus{
			{Name: "s3-xrd", Healthy: true, Message: "Established"},
			{Name: "s3-v1-comp", Healthy: false, Message: "waiting"},
		},
	)

	assert.Contains(t, table, "s3-xrd")
	assert.Contains(t, table, "Healthy")
	assert.Contains(t, table, "Established")
	assert.Contains(t, table, "s3-v1-comp")
	assert.Contains(t, table, "waiting")
	assert.Contains(t, table, "s3-v1-defs", "a tier with no service yet is still listed")
	assert.Contains(t, table, "Pending")
}

func TestFirstUnhealthyTier(t *testing.T) {
	testCases := map[string]struct {
		services    []oamcommon.ApplicationComponentStatus
		wantTier    string
		wantMessage string
	}{
		"first tier not reported yet": {
			services:    nil,
			wantTier:    "s3-xrd",
			wantMessage: "not reported yet",
		},
		"second tier unhealthy": {
			services: []oamcommon.ApplicationComponentStatus{
				{Name: "s3-xrd", Healthy: true},
				{Name: "s3-v1-comp", Healthy: false, Message: "composition not ready"},
			},
			wantTier:    "s3-v1-comp",
			wantMessage: "composition not ready",
		},
		"all healthy": {
			services: healthyTierServices(),
			wantTier: "",
		},
	}

	for name, tc := range testCases {
		t.Run(name, func(t *testing.T) {
			tier, message := firstUnhealthyTier([]string{"s3-xrd", "s3-v1-comp", "s3-v1-defs"}, tc.services)
			assert.Equal(t, tc.wantTier, tier)
			if tc.wantMessage != "" {
				assert.Contains(t, message, tc.wantMessage)
			}
		})
	}
}

func TestWaitForModuleSucceeds(t *testing.T) {
	cli := fake.NewClientBuilder().WithScheme(common.Scheme).
		WithObjects(moduleApps(oamcommon.ApplicationRunning, healthyTierServices())...).Build()
	var out bytes.Buffer
	o := &moduleDeployOptions{module: "s3", namespace: velatypes.DefaultKubeVelaNS, timeout: time.Second, pollInterval: time.Millisecond}

	err := o.waitForModule(context.Background(), cli, []string{"s3-xrd", "s3-v1-comp", "s3-v1-defs"}, &out)

	require.NoError(t, err)
	assert.Contains(t, out.String(), "s3-v1-defs")
	assert.Contains(t, out.String(), "Healthy")
}

func TestWaitForModuleBecomesHealthy(t *testing.T) {
	pending := []oamcommon.ApplicationComponentStatus{
		{Name: "s3-xrd", Healthy: true, Message: "Established"},
		{Name: "s3-v1-comp", Healthy: false, Message: "waiting for s3-xrd"},
	}
	cli := fake.NewClientBuilder().WithScheme(common.Scheme).
		WithObjects(moduleApps(oamcommon.ApplicationRunning, pending)...).Build()

	gets := 0
	watched := fake.NewClientBuilder().WithScheme(common.Scheme).
		WithObjects(moduleApps(oamcommon.ApplicationRunning, pending)...).
		WithInterceptorFuncs(interceptor.Funcs{
			Get: func(ctx context.Context, c client.WithWatch, key client.ObjectKey, obj client.Object, opts ...client.GetOption) error {
				if err := c.Get(ctx, key, obj, opts...); err != nil {
					return err
				}
				app, ok := obj.(*v1beta1.Application)
				if !ok || app.Name != "module-s3" {
					return nil
				}
				gets++
				if gets > 2 {
					app.Status.Services = healthyTierServices()
				}
				return nil
			},
		}).Build()
	_ = cli
	var out bytes.Buffer
	o := &moduleDeployOptions{module: "s3", namespace: velatypes.DefaultKubeVelaNS, timeout: 2 * time.Second, pollInterval: time.Millisecond}

	err := o.waitForModule(context.Background(), watched, []string{"s3-xrd", "s3-v1-comp", "s3-v1-defs"}, &out)

	require.NoError(t, err)
	assert.Contains(t, out.String(), "waiting for s3-xrd", "the intermediate state is reported")
}

func TestWaitForModuleTimesOut(t *testing.T) {
	stuck := []oamcommon.ApplicationComponentStatus{
		{Name: "s3-xrd", Healthy: true, Message: "Established"},
		{Name: "s3-v1-comp", Healthy: false, Message: "composition not ready"},
	}
	cli := fake.NewClientBuilder().WithScheme(common.Scheme).
		WithObjects(moduleApps(oamcommon.ApplicationRunning, stuck)...).Build()
	var out bytes.Buffer
	o := &moduleDeployOptions{module: "s3", namespace: velatypes.DefaultKubeVelaNS, timeout: 30 * time.Millisecond, pollInterval: time.Millisecond}

	err := o.waitForModule(context.Background(), cli, []string{"s3-xrd", "s3-v1-comp", "s3-v1-defs"}, &out)

	require.Error(t, err)
	assert.Contains(t, err.Error(), "s3-v1-comp")
	assert.Contains(t, err.Error(), "composition not ready")
}

func TestWaitForModuleStopsOnFailedWorkflow(t *testing.T) {
	cli := fake.NewClientBuilder().WithScheme(common.Scheme).
		WithObjects(moduleApps(oamcommon.ApplicationWorkflowFailed, nil)...).Build()
	var out bytes.Buffer
	o := &moduleDeployOptions{module: "s3", namespace: velatypes.DefaultKubeVelaNS, timeout: time.Minute, pollInterval: time.Millisecond}

	start := time.Now()
	err := o.waitForModule(context.Background(), cli, []string{"s3-xrd"}, &out)

	require.Error(t, err)
	assert.Contains(t, err.Error(), string(oamcommon.ApplicationWorkflowFailed))
	assert.Less(t, time.Since(start), 5*time.Second, "a terminal phase must not wait out the timeout")
}
```

Delete the unused `cli` variable in `TestWaitForModuleBecomesHealthy` (the `_ = cli` line and its declaration) if the linter objects; it exists only to keep the two builders visually parallel.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `CGO_ENABLED=0 go test ./references/cli/ -run 'TestWaitForModule|TestRenderModuleTierTable|TestFirstUnhealthyTier' -v`
Expected: FAIL — `undefined: renderModuleTierTable`, `undefined: firstUnhealthyTier`, and the wait tests fail because the stub returns nil.

- [ ] **Step 3: Write the implementation**

Replace the `waitForModule` stub in `references/cli/module-deploy.go` (add `"github.com/gosuri/uitable"`, `apierrors "k8s.io/apimachinery/pkg/api/errors"`, `"k8s.io/apimachinery/pkg/types"` to the imports):

```go
// waitForModule polls the deploy Application and the owned module Application
// until every tier is healthy, printing the tier table whenever it changes.
//
// It reads both Applications because they carry different halves of the answer:
// the deploy Application's phase is where a fetch or render failure surfaces,
// while per-tier health lives only on the owned Application the render service
// creates.
func (o *moduleDeployOptions) waitForModule(ctx context.Context, cli client.Client, tiers []string, out io.Writer) error {
	deadline := time.Now().Add(o.timeout)
	lastTable := ""
	var lastServices []oamcommon.ApplicationComponentStatus

	for {
		var deployApp v1beta1.Application
		if err := cli.Get(ctx, types.NamespacedName{Name: moduleDeployAppName(o.module), Namespace: o.namespace}, &deployApp); err != nil {
			return fmt.Errorf("failed to read Application %s/%s: %w", o.namespace, moduleDeployAppName(o.module), err)
		}
		switch deployApp.Status.Phase {
		case oamcommon.ApplicationWorkflowFailed, oamcommon.ApplicationWorkflowTerminated, oamcommon.ApplicationDeleting:
			return fmt.Errorf("Application %s/%s is in phase %s: %s",
				o.namespace, deployApp.Name, deployApp.Status.Phase, moduleComponentMessage(&deployApp))
		}

		var ownedApp v1beta1.Application
		err := cli.Get(ctx, types.NamespacedName{Name: ownedModuleAppName(o.module), Namespace: o.namespace}, &ownedApp)
		switch {
		case apierrors.IsNotFound(err):
			lastServices = nil
		case err != nil:
			return fmt.Errorf("failed to read Application %s/%s: %w", o.namespace, ownedModuleAppName(o.module), err)
		default:
			lastServices = ownedApp.Status.Services
		}

		if table := renderModuleTierTable(tiers, lastServices); table != lastTable {
			fmt.Fprintln(out, table)
			lastTable = table
		}

		tier, message := firstUnhealthyTier(tiers, lastServices)
		if tier == "" && deployApp.Status.Phase == oamcommon.ApplicationRunning {
			fmt.Fprintf(out, "Module %q is installed in namespace %q\n", o.module, o.namespace)
			return nil
		}

		if time.Now().After(deadline) {
			if tier == "" {
				return fmt.Errorf("timed out after %s waiting for module %q: every tier is healthy but Application %s/%s is in phase %s",
					o.timeout, o.module, o.namespace, deployApp.Name, deployApp.Status.Phase)
			}
			return fmt.Errorf("timed out after %s waiting for module %q: tier %q is not ready: %s",
				o.timeout, o.module, tier, message)
		}

		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(o.pollInterval):
		}
	}
}

// moduleComponentMessage returns the message of the deploy Application's module
// component, which is where a server-side fetch or render error surfaces.
func moduleComponentMessage(app *v1beta1.Application) string {
	for _, svc := range app.Status.Services {
		if svc.Message != "" {
			return svc.Message
		}
	}
	return "no component message reported"
}

// renderModuleTierTable renders every expected tier with its reported health. A
// tier the owned Application has not reported yet is Pending, so the operator
// sees the whole install shape from the first poll.
func renderModuleTierTable(tiers []string, services []oamcommon.ApplicationComponentStatus) string {
	byName := make(map[string]oamcommon.ApplicationComponentStatus, len(services))
	for _, svc := range services {
		byName[svc.Name] = svc
	}
	table := uitable.New()
	table.AddRow("TIER", "STATUS", "MESSAGE")
	for _, tier := range tiers {
		svc, reported := byName[tier]
		switch {
		case !reported:
			table.AddRow(tier, "Pending", "")
		case svc.Healthy:
			table.AddRow(tier, "Healthy", svc.Message)
		default:
			table.AddRow(tier, "Unhealthy", svc.Message)
		}
	}
	return table.String()
}

// firstUnhealthyTier returns the first tier that is not healthy and why, or an
// empty tier name when every tier is healthy. Tiers are checked in install
// order, so the tier named is the one the install is actually stuck on.
func firstUnhealthyTier(tiers []string, services []oamcommon.ApplicationComponentStatus) (string, string) {
	byName := make(map[string]oamcommon.ApplicationComponentStatus, len(services))
	for _, svc := range services {
		byName[svc.Name] = svc
	}
	for _, tier := range tiers {
		svc, reported := byName[tier]
		switch {
		case !reported:
			return tier, "not reported yet"
		case !svc.Healthy:
			message := svc.Message
			if message == "" {
				message = "not healthy"
			}
			return tier, message
		}
	}
	return "", ""
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `CGO_ENABLED=0 go test ./references/cli/ -run 'TestWaitForModule|TestRenderModuleTierTable|TestFirstUnhealthyTier|TestModuleDeploy' -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add references/cli/module-deploy.go references/cli/module-deploy_test.go
git commit -m "feat(module): report per-tier module install status and time out with the stuck tier"
```

---

## Task 4: Full verification

**Files:**
- Modify: `references/cli/module-deploy.go` or `references/cli/module-deploy_test.go` only if a check fails

- [ ] **Step 1: Run the whole CLI package test suite with the race detector**

Run: `CGO_ENABLED=0 go test ./references/cli/... -count=1`
Expected: PASS. Nothing in `module-registry_test.go` may break — the only shared change is the extra `AddCommand` argument.

Note: `-race` requires cgo and cannot run in this devcontainer. Run `go test -race ./references/cli/...` on a host with a working linker before opening the PR, or rely on CI for it.

- [ ] **Step 2: Vet and lint**

Run: `CGO_ENABLED=0 go vet ./references/cli/...`
Then, if available: `golangci-lint run references/cli/...`
Expected: clean. Fix anything reported; unused test variables and missing doc comments on exported identifiers are the likely hits.

- [ ] **Step 3: Confirm the module package still builds**

Run: `CGO_ENABLED=0 go build ./...`
Expected: success.

- [ ] **Step 4: Manual smoke test against a cluster**

This covers the Jira acceptance criteria, which unit tests cannot: an installed module's definitions carry the identity labels.

```bash
# Build and install the CLI plus the core with the module component
make core-install
make def-install

vela module registry add catalog https://github.com/kubevela/catalog --type git

# dry run: prints one type: module component, applies nothing
vela module deploy s3 --registry catalog --dry-run
kubectl get application -n vela-system

# missing module fails before apply
vela module deploy does-not-exist --registry catalog

# real deploy
vela module deploy s3 --registry catalog
kubectl get application -n vela-system
kubectl get componentdefinition s3-v1-bucket -n vela-system -o jsonpath='{.metadata.labels}'
```

Expected: the labels include `definition.oam.dev/module=s3`, `definition.oam.dev/api-version=v1`, `definition.oam.dev/name=bucket`. If the label keys differ, check the constants in `apis/types` used by `stampIdentity` (`pkg/module/service/render.go:188`) and report the mismatch rather than changing the CLI.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A references/cli
git commit -m "fix(module): address vet and lint findings in vela module deploy"
```

---

## Self-Review Notes

Spec coverage against `requirements.md`:

| Requirement | Task |
|---|---|
| R1 build and apply the `type: module` Application | Task 1 (builder), Task 2 (apply) |
| R1.3 `--file` writes the manifest | **Dropped** — `--dry-run` plus a shell redirect covers it (design doc deviation 5) |
| R2 dry run | Task 2 |
| R3 wait and report per-tier status | Task 3 |
| R3.2 timeout names the tier and why | Task 3 |
| R4 early validation via the resolver | Task 2 |
| R5.1 dry run applies nothing (fake client) | Task 2, `TestModuleDeployDryRun` |
| R5.2 missing registry fails before apply | Task 2, `TestModuleDeployFailsBeforeApply` |
| R5.3 the built Application carries the right parameters | Task 1, `TestBuildModuleApplication` |
| Jira AC: identity labels after deploy | Task 4, manual smoke test |
