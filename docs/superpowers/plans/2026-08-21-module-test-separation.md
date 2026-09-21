# Module Test Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leave `pkg/module` with isolated unit tests and no checked-in testdata while moving live-registry coverage and CI execution into `test/e2e-test`.

**Architecture:** Package tests use temporary directories populated by a shared test helper, in-memory filesystems, and injected fakes. Live-registry tests use the relocated realistic `s3` fixture, while the cluster workflow keeps the definitions-only `e2e-widget` fixture. The registry integration gate moves from the unit workflow to the E2E workflow.

**Tech Stack:** Go 1.23, Testify, Ginkgo/Gomega, OCI Distribution Registry v2, GitHub Actions, Kubernetes.

## Global Constraints

- Limit refactoring to `pkg/module`, `pkg/module/service`, and their module-specific E2E/CI references.
- Preserve unrelated tracked and untracked worktree changes.
- Remove `pkg/module/testdata`; unit-test inputs must be created during each test.
- Never make a `pkg/module` test reference `test/e2e-test` data.
- Use `registry:2` in CI; ECR stays optional manual verification with no credentials committed.
- Preserve the ECR report's proven annotation, publish/pull, and service-fetch assertions while changing fixture identity from `s3` to `e2e-widget`.
- Run Go commands with `env -u GOROOT GOFLAGS=-mod=mod`; use `CGO_ENABLED=0` for registry/E2E commands.
- Amend the latest implementation commit after verification with author `Vishal Kumar <vishal210893@gmail.com>` and committer `Jerrin Francis <jerrinfrancis7@gmail.com>`.

---

### Task 1: Make package tests use only the minimal fixture

**Files:**
- Modify: `pkg/module/parse_test.go`
- Modify: `pkg/module/publish_test.go`
- Delete: `pkg/module/testdata/modules/s3/**`

**Interfaces:**
- Consumes: fixture `minimal`, version `1.0.0`, XRD `xwidgets.example.com`, composition `widgets.example.com`, definition `widget`.
- Produces: package tests with no dependency on the realistic `s3` tree.

- [ ] **Step 1: Establish the baseline**

Run `env -u GOROOT GOFLAGS=-mod=mod go test ./pkg/module/... -count=1` and require both module packages to pass.

- [ ] **Step 2: Refactor the valid parser test**

Change `TestParseModule_WellFormedModule` to parse `testdata/modules/minimal`. Assert module `minimal`, version `1.0.0`, XRD name `xwidgets.example.com`, composition name `widgets.example.com`, line `v1`, and definition name `widget`; retain kind and cardinality assertions.

- [ ] **Step 3: Refactor generic package tests**

Make `TestPackageModuleRoundTrip` run once with `testdata/modules/minimal`. Make `TestPackageModuleArchiveContents` expect:

```go
[]string{
    "Chart.yaml",
    "_module.cue",
    "auxiliary/xrd.yaml",
    "v1/_version.cue",
    "v1/auxiliary/composition.yaml",
    "v1/definitions/widget.yaml",
}
```

Make both calls in `TestPackageModuleVersionOverride` use the minimal fixture. Preserve the tag assertions and the embedded version assertion `1.0.0`.

- [ ] **Step 4: Check remaining references, then delete `s3`**

Run `rg -n 'testdata/modules/s3|pkg/module/testdata/modules/s3' pkg/module test .github`. Only the integration files scheduled for Task 2 may remain. Delete all five files under `pkg/module/testdata/modules/s3` and their empty directories.

- [ ] **Step 5: Rerun module unit tests**

Run `env -u GOROOT GOFLAGS=-mod=mod go test ./pkg/module/... -count=1`. Require a zero exit code.

---

### Task 2: Finish moving live-registry tests to E2E

**Files:**
- Delete: `pkg/module/publish_integration_test.go`
- Delete: `pkg/module/service/fetch_integration_test.go`
- Modify: `test/e2e-test/module_publish_ecr_test.go`
- Modify: `test/e2e-test/module_fetch_integration_test.go`
- Reuse: `test/e2e-test/module_publish_test.go`
- Reuse: `test/e2e-test/testdata/module/e2e-widget/**`

**Interfaces:**
- Consumes: `modulePublishRepoRoot()` and `modulePublishFixtureRelPath` from the existing module E2E test.
- Produces: `TestPublishRoundTripECR` and `TestFetchModule_RoundTrip` under `test/e2e-test`.

- [ ] **Step 1: Normalize fixture path resolution**

In both relocated tests use:

```go
fixtureDir := filepath.Join(modulePublishRepoRoot(), modulePublishFixtureRelPath)
```

Remove `ecrTestRepoRoot` and its `runtime` import. The fetch test must not depend on a helper declared in another optional registry test.

- [ ] **Step 2: Preserve publish/pull behavior**

Keep `TestPublishRoundTripECR` gated by `MODULE_ECR_REGISTRY`. It accepts HTTP, HTTPS, OCI, and scheme-less prefixes; packages and pushes `e2e-widget`; reads the raw manifest through `authn.DefaultKeychain`; checks module, line, and enabled-line annotations; then pulls, parses, and compares the module. This preserves ECR verification scenario 2 while allowing CI to supply plain HTTP.

- [ ] **Step 3: Preserve the service fetch seam**

Keep `TestFetchModule_RoundTrip` gated by `MODULE_OCI_REGISTRY`. Package and push `e2e-widget`, construct `moduleservice.NewService` with the fake registry store, call `FetchModule`, and assert name, version, and line `v1`. Do not restore the unsupported git publishing leg.

- [ ] **Step 4: Delete integration tests from `pkg/module`**

Delete both build-tagged files. The in-process registry scenario is redundant with the registry-backed publish test and existing cluster publish/deploy E2E.

- [ ] **Step 5: Compile without running the cluster suite**

Run:

```bash
env -u GOROOT GOFLAGS=-mod=mod CGO_ENABLED=0 go test ./test/e2e-test \
  -run '^Test(PublishRoundTripECR|FetchModule_RoundTrip)$' -count=1
```

With registry variables unset, both tests must compile and report skips.

---

### Task 3: Move the registry gate into the E2E workflow

**Files:**
- Modify: `.github/workflows/unit-test.yml`
- Modify: `.github/workflows/e2e-test.yml`

**Interfaces:**
- Consumes: the two standard Go tests from Task 2.
- Produces: E2E job `module-registry-integration` backed by `registry:2`.

- [ ] **Step 1: Remove the integration job from the unit workflow**

Delete only `integration-test` from `.github/workflows/unit-test.yml`; leave `detect-noop` and `unit-tests` unchanged.

- [ ] **Step 2: Add the E2E registry job**

Add this job to `.github/workflows/e2e-test.yml` using the workflow's pinned checkout and environment setup conventions:

```yaml
  module-registry-integration:
    runs-on: ubuntu-22.04
    needs: [detect-noop]
    if: needs.detect-noop.outputs.noop != 'true'
    services:
      registry:
        image: registry:2
        ports:
          - 5000:5000
    steps:
      - name: Check out code into the Go module directory
        uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8
      - name: Setup Env
        uses: ./.github/actions/env-setup
      - name: Run module registry integration tests
        env:
          CGO_ENABLED: "0"
          MODULE_ECR_REGISTRY: http://127.0.0.1:5000/modules
          MODULE_OCI_REGISTRY: http://127.0.0.1:5000/modules
        run: >-
          go test ./test/e2e-test
          -run '^Test(PublishRoundTripECR|FetchModule_RoundTrip)$'
          -count=1 -v
```

Both variables are mandatory so neither test silently skips. The `MODULE_ECR_REGISTRY` name is historical; in CI it points to the local HTTP registry, not ECR.

- [ ] **Step 3: Validate the workflow edits**

Parse both workflow YAML files with an available YAML parser. Then run:

```bash
rg -n 'go test -tags integration ./pkg/module|module-registry-integration|MODULE_(ECR|OCI)_REGISTRY' .github/workflows
```

Require no stale tagged command under `pkg/module` and both variables in the new E2E job.

---

### Task 4: Eliminate the remaining checked-in unit fixture

**Files:**
- Create: `pkg/module/test_helpers_test.go`
- Modify: `pkg/module/parse_test.go`
- Modify: `pkg/module/publish_test.go`
- Delete: `pkg/module/testdata/modules/minimal/**`

**Interfaces:**
- Produces: `minimalModuleDir(t *testing.T) string`, which returns a fresh temporary directory containing module `minimal`, version `1.0.0`, line `v1`, XRD `xwidgets.example.com`, composition `widgets.example.com`, and definition `widget`.
- Consumes: the existing generic `writeModuleTree(t, files)` behavior, moved from `publish_test.go` into the shared helper file.

- [ ] **Step 1: Record the passing characterization baseline**

Run `env -u GOROOT GOFLAGS=-mod=mod go test ./pkg/module/... -count=1` and require zero failures.

- [ ] **Step 2: Add the shared temporary-module helper**

Create `pkg/module/test_helpers_test.go`. Move `writeModuleTree` there unchanged and add `minimalModuleDir`, which calls it with five literal entries matching the existing fixture paths and semantic values. Keep the YAML minimal: each resource needs only `apiVersion`, `kind`, and `metadata.name`; the definition also keeps its simple ConfigMap workload specification so the helper mirrors the previously validated fixture.

- [ ] **Step 3: Switch package tests to generated directories**

Make `copyMinimalModule` return `minimalModuleDir(t)` instead of copying `testdata`. Make `TestParseModule_WellFormedModule`, `TestPackageModuleRoundTrip`, `TestPackageModuleArchiveContents`, and `TestPackageModuleVersionOverride` each use a fresh `minimalModuleDir(t)`. Remove the now-unused `os.CopyFS` logic and remove `writeModuleTree` from `publish_test.go` after moving it.

- [ ] **Step 4: Delete the checked-in fixture**

Delete all five files under `pkg/module/testdata/modules/minimal` and remove the empty directory hierarchy.

- [ ] **Step 5: Verify the unit-test boundary**

Run:

```bash
gofmt -w pkg/module/test_helpers_test.go pkg/module/parse_test.go pkg/module/publish_test.go
env -u GOROOT GOFLAGS=-mod=mod go test ./pkg/module/... -count=1
test ! -e pkg/module/testdata
rg -n 'testdata/modules|minimalModuleDir' pkg/module
```

Require all unit tests to pass, no `pkg/module/testdata` path to exist, no testdata reference to remain, and all valid-directory consumers to use `minimalModuleDir`.

---

### Task 5: Verify separation and behavior

**Files:**
- Verify only; do not alter unrelated files discovered during checks.

**Interfaces:**
- Consumes: Tasks 1-4 and Kubernetes context `k3d-kubevela`.
- Produces: fresh unit, registry, and cluster E2E evidence.

- [ ] **Step 1: Audit the final layout**

Run `find pkg/module -type f | sort`, `test ! -e pkg/module/testdata`, and `rg -n 'integration|testdata/modules|test/e2e-test' pkg/module`. Require no package testdata directory and no integration or E2E references.

- [ ] **Step 2: Run all module unit tests**

Run `env -u GOROOT GOFLAGS=-mod=mod go test ./pkg/module/... -count=1` and require zero failures.

- [ ] **Step 3: Run both tests against a live registry**

With a local registry reachable at port 5000, run:

```bash
env -u GOROOT GOFLAGS=-mod=mod CGO_ENABLED=0 \
  MODULE_ECR_REGISTRY=http://127.0.0.1:5000/modules \
  MODULE_OCI_REGISTRY=http://127.0.0.1:5000/modules \
  go test ./test/e2e-test \
  -run '^Test(PublishRoundTripECR|FetchModule_RoundTrip)$' -count=1 -v
```

Both tests must run rather than skip and pass.

- [ ] **Step 4: Confirm cluster connectivity**

Run `kubectl config current-context` and `kubectl cluster-info`. The ECR report records that the k3d kubeconfig may expose an unreachable `0.0.0.0:<port>` endpoint. If this recurs, use the user-provided reachable endpoint; do not commit kubeconfig changes.

- [ ] **Step 5: Run the focused cluster workflow**

Ensure `bin/vela` and the controller are built from current source, then run:

```bash
ginkgo -v --focus 'Module publish and deploy' ./test/e2e-test
```

Require the test to publish `e2e-widget`, prove immutability and force overwrite, register and deploy the module, and observe its definition and healthy owned Application.

- [ ] **Step 6: Review the final diff**

Run `git diff --check`, inspect `git diff --stat`, and re-read the approved design. Report unit, registry-integration, and Kubernetes E2E results separately, plus the exact remaining package fixture inventory and any external connectivity blocker.

---

### Task 6: Relocate the realistic s3 fixture and its registry tests

**Files:**
- Create by relocation: `test/e2e-test/testdata/module/s3/_module.cue`
- Create by relocation: `test/e2e-test/testdata/module/s3/auxiliary/xrd.yaml`
- Create by relocation: `test/e2e-test/testdata/module/s3/v1/_version.cue`
- Create by relocation: `test/e2e-test/testdata/module/s3/v1/auxiliary/composition.yaml`
- Create by relocation: `test/e2e-test/testdata/module/s3/v1/definitions/bucket.cue`
- Modify: `test/e2e-test/module_publish_ecr_test.go`
- Modify: `test/e2e-test/module_fetch_integration_test.go`

**Interfaces:**
- Produces: `moduleRegistryFixtureRelPath = "test/e2e-test/testdata/module/s3"`, shared by the two live-registry tests.
- Preserves: `modulePublishFixtureRelPath = "test/e2e-test/testdata/module/e2e-widget"` for the cluster workflow.

- [ ] **Step 1: Restore and relocate the exact historical fixture**

Restore `pkg/module/testdata/modules/s3` from `HEAD^`, move that directory unchanged to `test/e2e-test/testdata/module/s3`, and remove the empty `pkg/module/testdata` parents. Verify the five moved files are byte-identical to `HEAD^` with `git diff --no-index` per file or SHA-256 checks.

- [ ] **Step 2: Repoint the live-registry tests**

Define this constant in `module_publish_ecr_test.go`:

```go
const moduleRegistryFixtureRelPath = "test/e2e-test/testdata/module/s3"
```

Use `filepath.Join(modulePublishRepoRoot(), moduleRegistryFixtureRelPath)` in both `TestPublishRoundTripECR` and `TestFetchModule_RoundTrip`. Update comments and repository expectations from `e2e-widget` to `s3`. Keep annotation expectations `v1` and enabled line `v1` unchanged.

- [ ] **Step 3: Verify unit separation and fixture placement**

Run:

```bash
env -u GOROOT GOFLAGS=-mod=mod go test ./pkg/module/... -count=1
test ! -e pkg/module/testdata
find test/e2e-test/testdata/module/s3 -type f | sort
rg -n 'moduleRegistryFixtureRelPath|testdata/module/s3' test/e2e-test
```

Require module unit tests to pass, no package testdata directory, exactly five `s3` files under E2E, and both live-registry tests to use the relocated path.

- [ ] **Step 4: Run both live-registry tests**

Start a temporary local OCI registry and run:

```bash
MODULE_ECR_REGISTRY=http://127.0.0.1:15000/modules \
MODULE_OCI_REGISTRY=http://127.0.0.1:15000/modules \
env -u GOROOT GOFLAGS=-mod=mod CGO_ENABLED=0 \
go test ./test/e2e-test \
  -run '^Test(PublishRoundTripECR|FetchModule_RoundTrip)$' -count=1 -v
```

Require both tests to run rather than skip and pass while publishing repository `modules/s3`.

- [ ] **Step 5: Run the unaffected cluster workflow**

Run the focused `Module publish and deploy` Ginkgo spec against the supplied cluster and require one passing spec. Its output must continue to publish and deploy `e2e-widget`, proving fixture responsibilities remain separate.

- [ ] **Step 6: Amend the implementation commit**

Stage only the five relocated fixture files and the two updated test files, inspect `git diff --cached --name-status`, then amend with:

```bash
env GIT_AUTHOR_NAME='Vishal Kumar' \
  GIT_AUTHOR_EMAIL='vishal210893@gmail.com' \
  GIT_COMMITTER_NAME='Jerrin Francis' \
  GIT_COMMITTER_EMAIL='jerrinfrancis7@gmail.com' \
  git commit --amend --no-edit
```
