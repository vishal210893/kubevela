# Coding Conventions

**Analysis Date:** 2026-03-27

## Naming Patterns

**Files:**
- Snake_case for Go files: `application_controller.go`, `gc_rev.go`, `cache_test.go`
- Test files co-located with source: `resourcekeeper.go` / `resourcekeeper_test.go`
- Suite test files named `suite_test.go` or `suit_test.go` (inconsistency exists — both spellings present)
- API types named `<resource>_types.go`: `application_types.go`, `resourcetracker_types.go`
- Generated files prefixed `zz_generated.`: `zz_generated.deepcopy.go`

**Packages:**
- Lowercase, single-word preferred: `resourcekeeper`, `appfile`, `multicluster`
- API packages follow Kubernetes convention: `apis/core.oam.dev/v1beta1/`
- Controller packages mirror API group path: `pkg/controller/core.oam.dev/v1beta1/application/`

**Functions:**
- Exported functions use PascalCase: `NewResourceKeeper()`, `ReconcileRetry()`
- Constructor pattern: `New<Type>()` returns `(*Type, error)` or `*Type`
- Reconciler method: `Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error)`

**Variables:**
- Package-level vars use camelCase: `k8sClient`, `testEnv`, `testScheme`
- Constants use PascalCase for exported, camelCase for unexported
- Error message constants: `errUpdateApplicationFinalizer = "cannot update application finalizer"`

**Types:**
- Struct names PascalCase: `Reconciler`, `ResourceKeeper`, `Application`
- Interface-driven design for testability (e.g., `reconcile.Reconciler`)

## Code Style

**Formatting:**
- `gofmt -s` (simplify mode enabled in `.golangci.yml`)
- `goimports` with local prefix `github.com/oam-dev/kubevela`
- Run: `make fmt` to format all Go and CUE files

**Linting:**
- `golangci-lint` with config at `.golangci.yml`
- Run: `make lint`
- Key enabled linters: `govet`, `gocyclo` (max complexity 35), `gocritic`, `goconst`, `goimports`, `gofmt`, `revive`, `unconvert`, `misspell`, `nakedret`, `unused`, `gosimple`, `staticcheck`
- Test files excluded from most lint rules (errcheck, gocyclo, dupl, gosec)
- Generated files (`zz_generated.*.go`) excluded from linting

**Static Analysis:**
- `go vet` via `make vet`
- `staticcheck` via `make staticcheck`
- Full reviewable check: `make reviewable` (build + manifests + fmt + vet + lint + staticcheck)

## Import Organization

**Order (enforced by goimports):**
1. Standard library (`context`, `fmt`, `time`)
2. Third-party packages (`github.com/pkg/errors`, `github.com/onsi/ginkgo/v2`)
3. Kubernetes packages (`k8s.io/api/...`, `k8s.io/apimachinery/...`, `sigs.k8s.io/controller-runtime/...`)
4. Local project packages (`github.com/oam-dev/kubevela/...`)

**Path Aliases:**
- Common import aliases used throughout:
  ```go
  corev1 "k8s.io/api/core/v1"
  metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
  apierrors "k8s.io/apimachinery/pkg/api/errors"
  kerrors "k8s.io/apimachinery/pkg/api/errors"   // alternative alias
  ctrl "sigs.k8s.io/controller-runtime"
  logf "sigs.k8s.io/controller-runtime/pkg/log"
  "k8s.io/klog/v2"
  ```
- Ginkgo/Gomega dot-imported in test files:
  ```go
  . "github.com/onsi/ginkgo/v2"
  . "github.com/onsi/gomega"
  ```
- Internal package aliases to avoid collision:
  ```go
  oamcomm "github.com/oam-dev/kubevela/apis/core.oam.dev/common"
  common2 "github.com/oam-dev/kubevela/pkg/controller/common"
  velatypes "github.com/oam-dev/kubevela/apis/types"
  oamutil "github.com/oam-dev/kubevela/pkg/oam/util"
  ```

## Error Handling

**Patterns:**
- Use `github.com/pkg/errors` for wrapping: `errors.Wrap(err, "message")`
- Use `fmt.Errorf("message: %w", err)` for standard wrapping (both patterns coexist)
- Kubernetes-style error checking: `apierrors.IsNotFound(err)`, `apierrors.IsAlreadyExists(err)`
- Error constants as string vars: `const errUpdateApplicationFinalizer = "cannot update application finalizer"`
- In controllers, return `ctrl.Result{}` with error for requeue, or `ctrl.Result{RequeueAfter: duration}` for delayed requeue
- Never discard errors silently in production code (enforced by errcheck linter, though `fmt.*` calls are excluded)

**Controller Error Pattern:**
```go
if err := r.Client.Get(ctx, key, obj); err != nil {
    if apierrors.IsNotFound(err) {
        return ctrl.Result{}, nil  // object deleted, nothing to do
    }
    return ctrl.Result{}, err  // requeue with error
}
```

## Logging

**Framework:** `k8s.io/klog/v2` for production code, `sigs.k8s.io/controller-runtime/pkg/log` for controller-runtime integration

**Log Levels (defined in `pkg/controller/common/logs.go`):**
- Level 0 (`LogInfo`): Default info level, use `klog.InfoS()` or `klog.Infof()`
- Level 1 (`LogDebug`): Verbose debug info
- Level 2 (`LogDebugWithContent`): Log with object content (HTTP body, JSON/YAML)
- Level 100 (`LogTrace`): Most verbose

**Patterns:**
```go
// Structured logging (preferred)
klog.InfoS("Reconciling WorkflowStepDefinition...", "Name", definitionName, "Namespace", req.Namespace)
klog.ErrorS(err, "Failed to initialize PolicyScopeIndex")
klog.V(4).InfoS("PolicyScopeIndex updated", "key", "value")

// Format-style logging (legacy, still present)
klog.Warningf("Invalid workflow restart annotation value for Application %s/%s", app.Namespace, app.Name)
klog.Infof("parsed %d properties by %s/%s", len(s.Properties), capability.Type, capability.Name)
```

**In Tests:**
```go
logf.SetLogger(zap.New(zap.UseDevMode(true), zap.WriteTo(GinkgoWriter)))
```

**Monitor Context:**
- `github.com/kubevela/pkg/monitor/context` used in some reconciler paths for structured tracing

## Comments

**License Header:**
- Required on all Go files (checked by `hack/licence/header-check.sh`, run via `make check-license-header`)
- Apache 2.0 with "Copyright [year] The KubeVela Authors."

**When to Comment:**
- Package-level doc comment on `doc.go` files
- Exported functions and types should have godoc comments
- `// +kubebuilder:` markers on API types for code generation
- Inline comments for non-obvious logic, especially controller reconciliation decisions

**Kubebuilder Markers:**
```go
// +kubebuilder:scaffold:imports
// +kubebuilder:scaffold:scheme
```

## Function Design

**Parameters:**
- `context.Context` as first parameter for I/O functions
- Use `client.Client` for Kubernetes API interactions (not raw clientset)
- Options pattern via separate options structs when needed

**Return Values:**
- Controllers return `(ctrl.Result, error)`
- Constructors return `(*Type, error)`
- Use named return values sparingly

## Module Design

**Exports:**
- One primary type per package file (e.g., `resourcekeeper.go` defines `ResourceKeeper`)
- Helper functions in `helper.go` or `utils.go`
- Constants and label keys in dedicated files: `pkg/oam/labels.go`

**Barrel Files:**
- Not used (Go convention). Each package imported directly.

**Scheme Registration:**
- Central scheme in `pkg/utils/common/common.go` via `common.Scheme`
- Individual API groups register via `SchemeBuilder.AddToScheme()`

## Common Patterns

**Custom Gomega Matchers (in `pkg/oam/util/`):**
- `AlreadyExistMatcher` — matches `apierrors.IsAlreadyExists`
- `NotFoundMatcher` — matches `apierrors.IsNotFound`
- `ErrorMatcher` — matches specific error messages
- Usage: `Expect(err).Should(SatisfyAny(BeNil(), &util.AlreadyExistMatcher{}))`

**Random Namespace Names for Tests:**
```go
func randomNamespaceName(basic string) string {
    return fmt.Sprintf("%s-%s", basic, strconv.FormatInt(rand.Int63(), 16))
}
```

**RequestReconcileNow Pattern:**
- Patch annotation `app.oam.dev/requestreconcile` to trigger immediate reconciliation instead of waiting for periodic resync
- Defined in `test/e2e-test/suite_test.go`

**ReadYamlToObject Utility:**
- `pkg/utils/common/common.go:368` — reads YAML fixture files into runtime.Object for tests

---

*Convention analysis: 2026-03-27*
