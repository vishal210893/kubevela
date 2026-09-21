# Testing Patterns

**Analysis Date:** 2026-03-27

## Test Framework

**Runner:**
- Ginkgo v2 (`github.com/onsi/ginkgo/v2`) for BDD-style integration and E2E tests
- Standard `testing` package for pure unit tests
- Both coexist in the same codebase; Ginkgo is dominant for controller/integration tests

**Assertion Libraries:**
- Gomega (`github.com/onsi/gomega`) with Ginkgo tests (dot-imported)
- `github.com/stretchr/testify/assert` and `testify/require` for standard unit tests
- `github.com/crossplane/crossplane-runtime/pkg/test` for some crossplane-derived utilities

**Run Commands:**
```bash
make test                    # Run all unit tests (envtest + cli gen)
make unit-test-core          # Unit tests for core packages with KUBEBUILDER_ASSETS
make core-test               # Simple go test ./pkg/... with coverage
make e2e-test                # E2E tests via ginkgo -v ./test/e2e-test
make e2e-test-local          # Full local E2E: k3d cluster + helm deploy + ginkgo
make e2e-addon-test          # Addon-specific E2E tests
make e2e-multicluster-test   # Multicluster E2E tests with 30m timeout

# Run specific E2E test by focus
ginkgo -v -focus="Helmchart" ./test/e2e-test

# Unit tests for a specific package
go test ./pkg/resourcekeeper/...
KUBEBUILDER_ASSETS="..." go test ./pkg/controller/...
```

## Test File Organization

**Location:**
- Co-located with source code (Go convention)
- Test files in same package (whitebox) or `_test` package (blackbox)

**Naming:**
- `<name>_test.go` for test files
- `suite_test.go` (or `suit_test.go`) for Ginkgo suite bootstrap
- `gc_suite_test.go` when multiple suites exist in one package

**Structure:**
```
pkg/resourcekeeper/
  resourcekeeper.go
  resourcekeeper_test.go      # standard go test (testify)
  suite_test.go               # Ginkgo suite bootstrap (envtest)
  gc_suite_test.go            # separate Ginkgo suite for GC tests
  gc_test.go                  # Ginkgo specs for GC
  dispatch_and_delete_test.go # Ginkgo specs for dispatch
```

## Test Types

### Unit Tests (standard `testing`)

Located in `pkg/` alongside source. Use `testify/assert` or `testify/require` with table-driven tests.

**Pattern — Table-Driven with Map:**
```go
func TestUnstructured(t *testing.T) {
    tests := map[string]struct {
        u         *unstructured.Unstructured
        typeLabel string
        exp       string
        resource  string
    }{
        "native resource": { /* ... */ },
        "workload":        { /* ... */ },
    }
    for name, ti := range tests {
        t.Log(fmt.Sprint("Running test: ", name))
        got, err := util.GetDefinitionName(mapper, ti.u, ti.typeLabel)
        assert.NoError(t, err)
        assert.Equal(t, ti.exp, got)
    }
}
```

**Pattern — testify/require (fail-fast):**
```go
func TestNewResourceKeeper(t *testing.T) {
    r := require.New(t)
    cli := fake.NewClientBuilder().WithScheme(common.Scheme).Build()
    // ...
    _, err := NewResourceKeeper(context.Background(), cli, app)
    r.Error(err)
    r.Contains(err.Error(), "failed to parse apply-once policy")
}
```

### Integration Tests (Ginkgo + envtest)

Located in `pkg/controller/`, `pkg/resourcekeeper/`, etc. Use `controller-runtime/pkg/envtest` to spin up a real API server.

**Suite Bootstrap Pattern (`suite_test.go`):**
```go
var testEnv *envtest.Environment
var k8sClient client.Client

func TestAPIs(t *testing.T) {
    RegisterFailHandler(Fail)
    RunSpecs(t, "Controller Suite")
}

var _ = BeforeSuite(func() {
    logf.SetLogger(zap.New(zap.UseDevMode(true), zap.WriteTo(GinkgoWriter)))
    testEnv = &envtest.Environment{
        ControlPlaneStartTimeout: time.Minute,
        ControlPlaneStopTimeout:  time.Minute,
        CRDDirectoryPaths:        []string{filepath.Join("../..", "charts/vela-core/crds")},
        UseExistingCluster:       ptr.To(false),
        ErrorIfCRDPathMissing:    true,
    }
    cfg, err := testEnv.Start()
    Expect(err).ShouldNot(HaveOccurred())
    k8sClient, err = client.New(cfg, client.Options{Scheme: common.Scheme})
    Expect(err).ShouldNot(HaveOccurred())
})

var _ = AfterSuite(func() {
    Expect(testEnv.Stop()).Should(Succeed())
})
```

**CRD Paths:**
- CRDs sourced from `charts/vela-core/crds/` directory
- Additional test-specific CRDs in `testdata/crds/` directories

### E2E Tests (Ginkgo against live cluster)

Located in `test/e2e-test/`. Require a running Kubernetes cluster with KubeVela installed.

**Suite Bootstrap (`test/e2e-test/suite_test.go`):**
```go
var k8sClient client.Client

func TestAPIs(t *testing.T) {
    RegisterFailHandler(Fail)
    RunSpecs(t, "OAM Core Resource Controller Suite")
}

var _ = BeforeSuite(func() {
    // Connects to existing cluster via KUBECONFIG
    k8sClient, err = client.New(config.GetConfigOrDie(), client.Options{Scheme: scheme})
    // Creates WorkloadDefinitions, ClusterRoles, ClusterRoleBindings
})

var _ = AfterSuite(func() {
    // Cleans up ClusterRoleBindings
})
```

**E2E Test Pattern (`test/e2e-test/helmchart_test.go`):**
```go
var _ = Describe("Helmchart Component Reconciliation", Ordered, func() {
    ctx := context.Background()
    var namespace string
    var app *v1beta1.Application

    BeforeAll(func() {
        namespace = "helm-e2e-" + rand.RandomString(4)
        ns := &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: namespace}}
        Expect(k8sClient.Create(ctx, ns)).Should(SatisfyAny(Succeed(), Not(HaveOccurred())))
    })

    AfterAll(func() {
        // Cleanup app and namespace
    })

    Context("Scenario 1: ...", func() {
        It("should deploy successfully", func() {
            // Deploy, wait with Eventually
        })
        It("should recover when resource deleted", func() {
            // Delete, trigger reconcile, verify recovery
        })
    })
})
```

**E2E Async Patterns:**
```go
// Wait for condition with Eventually
Eventually(func(g Gomega) {
    g.Expect(k8sClient.Get(ctx, appKey, app)).Should(Succeed())
    g.Expect(app.Status.Phase).Should(Equal(common2.ApplicationRunning))
}, 120*time.Second, 3*time.Second).Should(Succeed())

// Wait for deletion
Eventually(func() bool {
    err := k8sClient.Get(ctx, key, &v1beta1.Application{})
    return err != nil
}, 60*time.Second, 2*time.Second).Should(BeTrue())
```

## Test Utilities and Helpers

**Custom Gomega Matchers (`pkg/oam/util/`):**
- `AlreadyExistMatcher` — matches `apierrors.IsAlreadyExists` errors
- `NotFoundMatcher` — matches `apierrors.IsNotFound` errors
- `ErrorMatcher` — matches specific error values

**Reconcile Helpers (`pkg/oam/testutil/helper.go`):**
- `ReconcileRetry(r, req)` — reconcile with retry via Eventually (15s timeout)
- `ReconcileOnce(r, req)` — single reconcile, prints error
- `ReconcileOnceAfterFinalizer(r, req)` — reconcile twice (first adds finalizer)

**YAML Loading (`pkg/utils/common/common.go`):**
- `ReadYamlToObject(path, object)` — reads YAML fixture file into runtime.Object

**Namespace Helpers (in E2E test files):**
- `createNamespace(ctx, name)` — delete-then-create pattern with Eventually
- `randomNamespaceName(basic)` — generates random namespace to avoid GC delays

**RequestReconcileNow (`test/e2e-test/suite_test.go`):**
- Patches `app.oam.dev/requestreconcile` annotation to trigger immediate reconciliation

**FakeRecorder (`pkg/controller/.../application/suite_test.go`):**
- Custom event recorder that captures events by object name for assertion

## Mocking

**Fake Kubernetes Client:**
```go
cli := fake.NewClientBuilder().WithScheme(common.Scheme).Build()
```

**Mock Package (`pkg/oam/mock/`):**
- `mocks.go` — implements OAM interfaces (Conditioned, WorkloadReferencer, etc.)
- `client.go` — mock controller-runtime client with configurable REST mapper

**Test Mock Server (`test/mock/`):**
- `test/mock/nacos/` — Nacos mock for config writer tests

**FakeDynamicClient:**
```go
fakeDynamicClient := fake.NewSimpleDynamicClient(testScheme)
singleton.DynamicClient.Set(fakeDynamicClient)
```

## Fixtures and Test Data

**E2E Test Data:**
- `test/e2e-test/testdata/app/` — Application YAML fixtures (`app1.yaml` through `app12.yaml`, plus named scenarios)
- `test/e2e-test/testdata/definition/` — Definition YAML fixtures
- `test/e2e-test/testdata/helm/` — Helm chart test fixtures

**Integration Test Data:**
- CRDs at `charts/vela-core/crds/` (shared by envtest and production)
- Controller-specific: `pkg/controller/.../application/testdata/`
- Inline YAML constants in test files (common pattern for WorkloadDefinitions, ComponentDefinitions)

**Pattern — Inline YAML in Test Files:**
```go
const workloadDefinition = `
apiVersion: core.oam.dev/v1beta1
kind: WorkloadDefinition
metadata:
  name: test-worker
spec:
  ...
`
```

**Pattern — YAML File Loading:**
```go
raw, err := os.ReadFile("testdata/helm/app_helmchart_podinfo.yaml")
Expect(err).Should(BeNil())
raw = bytes.ReplaceAll(raw, []byte("placeholder_ns"), []byte(namespace))
app = &v1beta1.Application{}
Expect(yaml.Unmarshal(raw, app)).Should(BeNil())
```

## Coverage

**Requirements:** No enforced minimum. Coverage generated but not gated.

**View Coverage:**
```bash
make unit-test-core   # generates coverage.txt
make core-test        # generates cover.out
go tool cover -html=coverage.txt
```

## E2E Test Infrastructure

**Setup Flow (Makefile targets in `makefiles/e2e.mk`):**
1. `make e2e-setup-core-pre-hook` — modify charts for testing
2. `make e2e-setup-core-wo-auth` — helm install with test image
3. `make e2e-setup-core-post-hook` — wait for readiness, install addons (kruise, fluxcd, terraform)

**Local E2E (`make e2e-test-local`):**
1. Creates k3d cluster (`kubevela-debug`)
2. Builds Docker image (`vela-core:e2e-test`)
3. Loads image into k3d
4. Helm installs with test configuration
5. Runs `ginkgo -v ./test/e2e-test`

**Key Helm Values for E2E:**
- `image.pullPolicy=IfNotPresent`
- `applicationRevisionLimit=5`
- `controllerArgs.reSyncPeriod=1m`
- `featureGates.enableCueValidation=true`
- `featureGates.validateResourcesExist=true`

## Common Test Patterns

**Async Testing with Eventually:**
```go
Eventually(func(g Gomega) {
    obj := &v1beta1.Application{}
    g.Expect(k8sClient.Get(ctx, key, obj)).Should(Succeed())
    g.Expect(obj.Status.Phase).Should(Equal(common.ApplicationRunning))
}, 120*time.Second, 3*time.Second).Should(Succeed())
```

**Error Testing:**
```go
// testify style
r := require.New(t)
_, err := NewResourceKeeper(context.Background(), cli, app)
r.Error(err)
r.Contains(err.Error(), "failed to parse apply-once policy")

// Gomega style
Expect(err).Should(HaveOccurred())
Expect(err.Error()).Should(ContainSubstring("expected message"))
```

**Create-or-Ignore Pattern:**
```go
Expect(k8sClient.Create(ctx, obj)).Should(SatisfyAny(BeNil(), &util.AlreadyExistMatcher{}))
```

**Ginkgo Ordered Containers:**
```go
var _ = Describe("Feature", Ordered, func() {
    BeforeAll(func() { /* one-time setup */ })
    AfterAll(func() { /* one-time cleanup */ })
    Context("scenario", func() {
        It("step 1", func() { /* ... */ })
        It("step 2", func() { /* depends on step 1 */ })
    })
})
```

---

*Testing analysis: 2026-03-27*
