# Addon Validation in the Application Webhook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move addon compatibility admission checks into the shared Application validating webhook and remove the certgen-sensitive addon webhook entry.

**Architecture:** Keep addon property parsing and compatibility checks in a reusable `addon.Validator`. The Application handler owns feature-gate orchestration, the `type: addon` fast path, shared error aggregation, and request-correlated logging. The chart and webhook registry expose only the existing Application validating route.

**Tech Stack:** Go 1.23.8, controller-runtime admission webhooks, Kubernetes feature gates, `field.ErrorList`, structured `logr` logging, Helm, Testify, Ginkgo/Gomega.

## Global constraints

- Keep `featureGates.enableAddonComponent` false by default; tests and development installs enable it explicitly.
- Do not change addon rendering, reconciliation, registry resolution, or system-requirement semantics.
- Registry, resolution, and discovery failures remain fail-open; only confirmed `pkgaddon.ErrVersionMismatch` results deny admission.
- Do not log credentials, addon property payloads, or complete Application objects.
- Use `slices.ContainsFunc` from the Go 1.23.8 standard library for the Application fast path.
- Preserve unrelated working-tree changes.
- Follow TDD: observe each new test fail before implementing its production code.

## File structure

- Create `pkg/webhook/core.oam.dev/v1beta1/addon/validator.go` for reusable addon component validation.
- Create `pkg/webhook/core.oam.dev/v1beta1/addon/validator_test.go` for validator-focused tests.
- Modify `pkg/webhook/core.oam.dev/v1beta1/addon/validating_handler.go` and its test into a thin adapter around the reusable validator until Task 3 removes the route atomically.
- Modify `pkg/webhook/core.oam.dev/v1beta1/addon/compat.go` and `compat_test.go` to make the checker handler-independent.
- Create `pkg/webhook/core.oam.dev/v1beta1/application/addon_validation.go` and `addon_validation_test.go` for shared-webhook orchestration.
- Modify `application/validating_handler.go` to inject the validator and store the request logger in context.
- Modify `application/validation.go` to aggregate addon errors.
- Modify `pkg/webhook/core.oam.dev/register.go` to remove the standalone route.
- Modify `charts/vela-core/templates/admission-webhooks/validatingWebhookConfiguration.yaml` to remove the addon entry and CA lookup.
- Modify `charts/vela-core/values.yaml` to restore the feature default to false.

---

### Task 1: Refactor addon logic into a reusable validator

**Files:**
- Create: `pkg/webhook/core.oam.dev/v1beta1/addon/validator.go`
- Create: `pkg/webhook/core.oam.dev/v1beta1/addon/validator_test.go`
- Modify: `pkg/webhook/core.oam.dev/v1beta1/addon/compat.go`
- Modify: `pkg/webhook/core.oam.dev/v1beta1/addon/compat_test.go`
- Modify: `pkg/webhook/core.oam.dev/v1beta1/addon/validating_handler.go`
- Modify: `pkg/webhook/core.oam.dev/v1beta1/addon/validating_handler_test.go`

**Interfaces:**
- Produces: `addon.NewValidator() *addon.Validator`
- Produces: `(*addon.Validator).ValidateComponents(context.Context, *v1beta1.Application) field.ErrorList`
- Produces: `addon.ComponentType == "addon"`

- [ ] **Step 1: Write failing tests for the new validator type**

Move the existing validation table into `validator_test.go` and instantiate the new type. Retain cases for compatible and incompatible addons, non-addon components, default addon name, `skipVersionValidate`, malformed properties, and multiple addon components. Add explicit property forwarding:

```go
func TestValidateComponentsForwardsProperties(t *testing.T) {
	calls := 0
	validator := &Validator{compatChecker: func(_ context.Context, addonName, version, registry string) *field.Error {
		calls++
		assert.Equal(t, "fluxcd", addonName)
		assert.Equal(t, "2.0.0", version)
		assert.Equal(t, "KubeVela", registry)
		return field.Invalid(field.NewPath("requirements"), addonName, "incompatible")
	}}
	app := &v1beta1.Application{Spec: v1beta1.ApplicationSpec{Components: []common.ApplicationComponent{
		{Name: "api", Type: "webservice"},
		{Name: "installer", Type: ComponentType, Properties: rawProps(t, map[string]any{
			"addon": "fluxcd", "version": "2.0.0", "registry": "KubeVela",
		})},
	}}}

	errs := validator.ValidateComponents(context.Background(), app)
	require.Len(t, errs, 1)
	assert.Equal(t, 1, calls)
	assert.Equal(t, "spec.components[1].properties", errs[0].Field)
}
```

- [ ] **Step 2: Run the new test and confirm RED**

Run `go test ./pkg/webhook/core.oam.dev/v1beta1/addon -run TestValidateComponents -count=1`.

Expected: compilation fails because `Validator` does not exist.

- [ ] **Step 3: Implement `Validator` without admission-server concerns**

Create `validator.go` with:

```go
type compatibilityChecker func(context.Context, string, string, string) *field.Error

type Validator struct {
	compatChecker compatibilityChecker
}

func NewValidator() *Validator {
	return &Validator{}
}

func (v *Validator) ValidateComponents(ctx context.Context, app *v1beta1.Application) field.ErrorList {
	check := v.compatChecker
	if check == nil {
		check = defaultCompatChecker
	}

	startTime := time.Now()
	logger := logging.WithContext(ctx).WithStep("validate-addon-components")
	addonComponentCount := 0
	var errs field.ErrorList
	for i, component := range app.Spec.Components {
		if component.Type != ComponentType {
			continue
		}
		addonComponentCount++

		properties := componentProperties{}
		if component.Properties != nil && len(component.Properties.Raw) > 0 {
			if err := json.Unmarshal(component.Properties.Raw, &properties); err != nil {
				logger.Debug("Skipping malformed addon component properties",
					"component", component.Name, "error", err)
				continue
			}
		}
		if properties.SkipVersionValidate {
			logger.Debug("Skipping addon compatibility validation",
				"component", component.Name, "reason", "version-validation-disabled")
			continue
		}

		addonName := properties.Addon
		if addonName == "" {
			addonName = component.Name
		}
		if compatibilityErr := check(ctx, addonName, properties.Version, properties.Registry); compatibilityErr != nil {
			errs = append(errs, field.Invalid(
				field.NewPath("spec", "components").Index(i).Child("properties"),
				component.Name,
				compatibilityErr.Detail,
			))
		}
	}

	logger.WithSuccess(len(errs) == 0, startTime).Info(
		"Addon component compatibility validation completed",
		"addonComponentCount", addonComponentCount,
		"errorCount", len(errs),
	)
	return errs
}
```

Move `ComponentType` and `componentProperties` into this file. Preserve the exact error path construction:

```go
field.Invalid(
	field.NewPath("spec", "components").Index(i).Child("properties"),
	component.Name,
	compatibilityErr.Detail,
)
```

Use `logging.WithContext(ctx)` for addon-only start/completion logs. Emit malformed-property and explicit-skip messages at debug level. Include `addonComponentCount`, `errorCount`, and duration on completion.

Keep `ValidatingHandler` as a temporary thin adapter so this task remains buildable before Task 3 removes the route. Replace its checker field with `validator *Validator`; use `NewValidator()` when nil, and delegate component validation to `validator.ValidateComponents`. Keep decoding, operation filtering, deletion handling, route registration, and handler response tests until Task 3.

- [ ] **Step 4: Make the production checker handler-independent**

Change `compat.go` to:

```go
func defaultCompatChecker(ctx context.Context, addonName, version, registry string) *field.Error
```

Replace `klog.Infof` with:

```go
logger := logging.WithContext(ctx).
	WithStep("validate-addon-compatibility").
	WithValues("addon", addonName, "version", version, "registry", registry)
```

Log stable fail-open reasons: `registry-resolution-failed`, `addon-not-found`, `version-resolution-failed`, `discovery-client-failed`, and `requirement-lookup-failed`. Keep all existing returns unchanged.

- [ ] **Step 5: Update compatibility tests**

Call the free function directly:

```go
assert.Nil(t, defaultCompatChecker(context.Background(), "some-addon", "", ""))
```

Keep mismatch classification coverage unchanged.

- [ ] **Step 6: Run addon tests and confirm GREEN**

Run `go test ./pkg/webhook/core.oam.dev/v1beta1/addon -count=1`.

Expected: PASS. Addon validation logic belongs to `Validator`; the standalone handler remains only as a temporary adapter for the still-registered route.

- [ ] **Step 7: Commit the refactor**

Stage only `pkg/webhook/core.oam.dev/v1beta1/addon` and commit with `refactor(webhook): extract addon validator`.

---

### Task 2: Orchestrate addon validation from the Application webhook

**Files:**
- Create: `pkg/webhook/core.oam.dev/v1beta1/application/addon_validation.go`
- Create: `pkg/webhook/core.oam.dev/v1beta1/application/addon_validation_test.go`
- Modify: `pkg/webhook/core.oam.dev/v1beta1/application/validating_handler.go`
- Modify: `pkg/webhook/core.oam.dev/v1beta1/application/validation.go`

**Interfaces:**
- Consumes: `addon.NewValidator`, `addon.ComponentType`, and `ValidateComponents`
- Produces: `(*ValidatingHandler).ValidateAddonComponents(context.Context, *v1beta1.Application) field.ErrorList`
- Produces: unexported `addonComponentValidator` for test injection

- [ ] **Step 1: Write failing gate and dispatch tests**

Create a recording fake:

```go
type fakeAddonComponentValidator struct {
	calls int
	errs  field.ErrorList
}

func (f *fakeAddonComponentValidator) ValidateComponents(
	_ context.Context,
	_ *v1beta1.Application,
) field.ErrorList {
	f.calls++
	return f.errs
}
```

Add three non-parallel tests using `featuregatetesting.SetFeatureGateDuringTest`:

1. Gate disabled plus addon component returns no errors and records zero calls.
2. Gate enabled plus only `webservice` components records zero calls.
3. Gate enabled plus an addon component returns the fake errors and records one call.

- [ ] **Step 2: Run dispatch tests and confirm RED**

Run `go test ./pkg/webhook/core.oam.dev/v1beta1/application -run TestValidateAddonComponents -count=1`.

Expected: compilation fails because the interface, handler field, and method do not exist.

- [ ] **Step 3: Implement the consumer boundary and fast path**

Create `addon_validation.go`:

```go
type addonComponentValidator interface {
	ValidateComponents(context.Context, *v1beta1.Application) field.ErrorList
}

func (h *ValidatingHandler) ValidateAddonComponents(
	ctx context.Context,
	app *v1beta1.Application,
) field.ErrorList {
	logger := logging.WithContext(ctx).WithStep("validate-addon-components")
	if !utilfeature.DefaultMutableFeatureGate.Enabled(features.EnableAddonComponent) {
		logger.Debug("Skipping addon component validation", "reason", "feature-gate-disabled")
		return nil
	}
	if !slices.ContainsFunc(app.Spec.Components, func(component common.ApplicationComponent) bool {
		return component.Type == addonvalidation.ComponentType
	}) {
		logger.Debug("Skipping addon component validation", "reason", "no-addon-component")
		return nil
	}
	validator := h.addonValidator
	if validator == nil {
		validator = addonvalidation.NewValidator()
	}
	return validator.ValidateComponents(ctx, app)
}
```

Use `addonvalidation` as the import alias.

- [ ] **Step 4: Inject the validator and request logger**

Add `addonValidator addonComponentValidator` to `ValidatingHandler`. After adding generation to the logger, put it in context before validation:

```go
ctx = logger.IntoContext(ctx)
ctx = util.SetNamespaceInCtx(ctx, app.Namespace)
```

Construct production handlers with:

```go
&ValidatingHandler{
	Client:          mgr.GetClient(),
	Decoder:         admission.NewDecoder(mgr.GetScheme()),
	addonValidator: addonvalidation.NewValidator(),
}
```

- [ ] **Step 5: Aggregate addon errors once**

Add this line immediately after normal component validation in `ValidateCreate`:

```go
errs = append(errs, h.ValidateAddonComponents(ctx, app)...)
```

Do not add a second call in `ValidateUpdate`; its existing call to `ValidateCreate` covers the new state.

- [ ] **Step 6: Test create/update error aggregation**

Enable `EnableAddonComponent`, inject a fake that returns an indexed error, and call `ValidateCreate` and `ValidateUpdate`. Follow the existing sharding test pattern to bypass ComponentDefinition lookup:

```go
oldSharding := sharding.EnableSharding
sharding.EnableSharding = true
t.Cleanup(func() { sharding.EnableSharding = oldSharding })
featuregatetesting.SetFeatureGateDuringTest(
	t, utilfeature.DefaultMutableFeatureGate, features.ValidateComponentWhenSharding, false,
)
```

Assert the addon field error is present and the fake is called once per top-level validation call. Keep the existing deleting-update test as the handler-level proof that no validation branch runs during deletion.

- [ ] **Step 7: Run Application and addon tests**

Run `go test ./pkg/webhook/core.oam.dev/v1beta1/application ./pkg/webhook/core.oam.dev/v1beta1/addon -count=1`.

Expected: PASS.

- [ ] **Step 8: Commit Application integration**

Stage only the Application and addon files from Tasks 1-2 and commit with `refactor(webhook): validate addons with applications`.

---

### Task 3: Remove the standalone route and chart entry

**Files:**
- Modify: `pkg/webhook/core.oam.dev/register.go`
- Modify: `charts/vela-core/templates/admission-webhooks/validatingWebhookConfiguration.yaml`
- Modify: `charts/vela-core/values.yaml`
- Delete: `pkg/webhook/core.oam.dev/v1beta1/addon/validating_handler.go`
- Delete: `pkg/webhook/core.oam.dev/v1beta1/addon/validating_handler_test.go`
- Test: `pkg/webhook/core.oam.dev/v1beta1/application/addon_validation_test.go`

**Interfaces:**
- Keeps: `/validating-core-oam-dev-v1beta1-applications`
- Removes: `/validating-core-oam-dev-v1beta1-addon-components`
- Removes: `validating.core.oam.dev.v1beta1.addoncomponents`

- [ ] **Step 1: Write a failing architecture test**

```go
func TestAddonValidationUsesSharedApplicationWebhook(t *testing.T) {
	chart, err := os.ReadFile("../../../../../charts/vela-core/templates/admission-webhooks/validatingWebhookConfiguration.yaml")
	require.NoError(t, err)
	registry, err := os.ReadFile("../../register.go")
	require.NoError(t, err)

	assert.Contains(t, string(chart), "name: validating.core.oam.dev.v1beta1.applications")
	assert.NotContains(t, string(chart), "validating.core.oam.dev.v1beta1.addoncomponents")
	assert.NotContains(t, string(chart), "/validating-core-oam-dev-v1beta1-addon-components")
	assert.NotContains(t, string(registry), "addon.RegisterValidatingHandler")
}
```

- [ ] **Step 2: Run the architecture test and confirm RED**

Run `go test ./pkg/webhook/core.oam.dev/v1beta1/application -run TestAddonValidationUsesSharedApplicationWebhook -count=1`.

Expected: FAIL because the separate chart entry and registration still exist.

- [ ] **Step 3: Remove route registration**

Delete the `utilfeature`, `features`, and addon webhook imports and the conditional `addon.RegisterValidatingHandler(mgr)` block from `pkg/webhook/core.oam.dev/register.go`. In the same step, delete the temporary `addon/validating_handler.go` adapter and its handler-only tests so no dead route code remains.

- [ ] **Step 4: Remove the chart entry and CA lookup**

From `validatingWebhookConfiguration.yaml`, remove:

- `addoncomponents` from `$vals`.
- The lookup branch for `validating.core.oam.dev.v1beta1.addoncomponents`.
- The full feature-gated addon webhook block, including its limitation comment, `matchConditions`, rules, and timeout.

Leave the shared Application webhook unchanged.

- [ ] **Step 5: Restore the opt-in default**

Set `featureGates.enableAddonComponent: false` in `charts/vela-core/values.yaml`. Keep the explicit true override in `makefiles/e2e.mk`.

- [ ] **Step 6: Run unit and architecture tests**

Run `go test ./pkg/webhook/core.oam.dev/... -count=1`.

Expected: PASS.

- [ ] **Step 7: Render both feature states**

Run:

```bash
helm template kubevela ./charts/vela-core --kube-version 1.33.0 > /tmp/kubevela-addon-off.yaml
helm template kubevela ./charts/vela-core --kube-version 1.33.0 --set featureGates.enableAddonComponent=true > /tmp/kubevela-addon-on.yaml
```

Then run:

```bash
rg -c 'name: validating.core.oam.dev.v1beta1.applications' /tmp/kubevela-addon-off.yaml
rg -c 'name: validating.core.oam.dev.v1beta1.applications' /tmp/kubevela-addon-on.yaml
rg 'addoncomponents|addon-components|matchConditions' /tmp/kubevela-addon-off.yaml /tmp/kubevela-addon-on.yaml
```

Expected: both counts are `1`; the final `rg` exits `1` with no matches.

- [ ] **Step 8: Commit route and chart removal**

Stage only `pkg/webhook/core.oam.dev/register.go`, the validating webhook template, `values.yaml`, and the architecture test. Commit with `fix(webhook): remove addon admission route`.

---

### Task 4: Verify regression and live behavior

**Files:**
- Verify only; corrections remain limited to files listed above.

**Interfaces:**
- Verifies: shared handler, gate behavior, addon compatibility, chart rendering, and default certgen installation

- [ ] **Step 1: Format changed Go files**

Run `gofmt -w` on every changed Go file listed in Tasks 1-3.

- [ ] **Step 2: Run focused tests**

Run:

```bash
go test ./pkg/webhook/core.oam.dev/v1beta1/addon ./pkg/webhook/core.oam.dev/v1beta1/application ./pkg/webhook/core.oam.dev -count=1
```

Expected: PASS.

- [ ] **Step 3: Run proportional repository checks**

```bash
go test ./pkg/webhook/... ./pkg/features/... -count=1
helm lint ./charts/vela-core
git diff --check
```

Expected: all exit `0`.

- [ ] **Step 4: Prove removed symbols are absent**

Run:

```bash
rg --glob '!**/*_test.go' 'addon\.ValidationWebhookPath|addon\.RegisterValidatingHandler|validating\.core\.oam\.dev\.v1beta1\.addoncomponents|has-addon-component' pkg/webhook/core.oam.dev charts/vela-core/templates/admission-webhooks
```

Expected: exit `1` with no matches.

- [ ] **Step 5: Verify a live default-certgen installation**

Build and install the branch with `featureGates.enableAddonComponent=true`, then run:

```bash
kubectl get validatingwebhookconfiguration kubevela-vela-core-admission -o json | jq '{applicationWebhooks: [.webhooks[] | select(.name == "validating.core.oam.dev.v1beta1.applications") | .name], addonWebhooks: [.webhooks[] | select(.name | contains("addoncomponents")) | .name]}'
```

Expected:

```json
{"applicationWebhooks":["validating.core.oam.dev.v1beta1.applications"],"addonWebhooks":[]}
```

Confirm the deployment has `--feature-gates=EnableAddonComponent=true`.

- [ ] **Step 6: Run addon-component E2E**

After standard E2E setup starts the addon mock registry, run `ginkgo -v ./e2e/addon-component`.

Expected: PASS through the shared Application webhook.

- [ ] **Step 7: Inspect final state**

Run `git diff --stat`, `git diff --check`, and `git status --short`. Confirm only planned files and pre-existing user changes remain.
