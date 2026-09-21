# `vela module publish` CI and e2e coverage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CI prove the publish path against a real OCI registry, and add one e2e test that walks the whole loop: build a module artifact, publish it, fetch it, deploy it.

**Architecture:** Three layers of coverage. Unit tests already exist and stay untagged. A CI job runs the `-tags integration` tests, with a `registry:2` service container so the publish-to-fetch round-trip runs against a real registry daemon. A Ginkgo e2e deploys `registry:2` inside the kind cluster, publishes from the runner through a port-forward, registers the in-cluster Service URL, and deploys the module through the controller.

**Tech Stack:** Go 1.23, Ginkgo/Gomega, GitHub Actions, kind, helm, `registry:2`.

Feature design: `docs/superpowers/specs/2026-08-20-module-publish-design.md`. The feature itself is complete and staged; this plan adds coverage only.

## Global Constraints

- Run every Go command with `CGO_ENABLED=0`; without it this devcontainer's toolchain fails with "cannot find 'ld'".
- No new module dependencies, and no new container images beyond `docker.io/library/registry:2`.
- DO NOT COMMIT. Stage with `git add` and stop; the user manages commits.
- Never use `git stash`: there is staged work from the feature branch, and the devcontainer's stash list belongs to other people.
- No ECR in CI. ECR stays a manual verification, gated on `MODULE_ECR_REGISTRY`.
- CI runs on kind (`.github/actions/setup-kind-cluster`), not k3d. A docker container on the host network is reachable from the node but NOT from pods, which is why the e2e registry runs inside the cluster.
- The e2e module fixture must ship no `auxiliary/xrd.yaml` and no `auxiliary/composition.yaml`. Those are Crossplane types and the e2e cluster has no Crossplane CRDs; a definitions-only module keeps the deploy leg honest.
- Every new exported identifier gets a doc comment starting with its own name. No comments inside function bodies except for non-obvious constraints.

---

### Task 1: CI job for the tagged integration tests

**Files:**
- Modify: `.github/workflows/unit-test.yml`

**Interfaces:**
- Consumes: `pkg/module/publish_integration_test.go` (in-process registry test, needs nothing external) and `pkg/module/service/fetch_integration_test.go` (its `oci` subtest reads `MODULE_OCI_REGISTRY`).
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Read the existing workflow**

Read `.github/workflows/unit-test.yml` in full and note how it checks out, sets up Go, and invokes the unit-test composite action. Match its style: same action versions with their pinned SHAs, same Go setup, same job-level `if` guards.

- [ ] **Step 2: Add the job**

Add one job, `integration-test`, alongside the existing unit-test job. It needs:

```yaml
  integration-test:
    runs-on: ubuntu-22.04
    services:
      registry:
        image: registry:2
        ports:
          - 5000:5000
    steps:
      # checkout and Go setup copied verbatim from the unit-test job, same pinned SHAs
      - name: Run integration tests
        env:
          CGO_ENABLED: "0"
          MODULE_OCI_REGISTRY: http://127.0.0.1:5000/modules
        run: go test -tags integration ./pkg/module/... -count=1 -v
```

Two things to get right. The `registry:2` service container is what makes the `oci` subtest of `TestFetchModule_RoundTrip` run instead of skip; without `MODULE_OCI_REGISTRY` it skips silently and the job would pass while proving nothing. And `MODULE_ECR_REGISTRY` must stay unset, so `TestPublishRoundTripECR` skips — ECR is deliberately not a CI dependency.

- [ ] **Step 3: Prove the workflow is valid YAML and the job would do what it claims**

There is no act/docker in this devcontainer, so validate what you can locally:

```bash
python3 -c "import yaml,sys; d=yaml.safe_load(open('.github/workflows/unit-test.yml')); print(list(d['jobs'].keys())); print(d['jobs']['integration-test']['services'])"
```

Then prove the command itself is right by running it against a local registry the same way CI will. There is a registry already running in the k3d cluster reachable at `http://127.0.0.1:5000` from this container (check with `curl -s http://127.0.0.1:5000/v2/_catalog`; if it is gone, skip this sub-step and say so in your report):

```bash
MODULE_OCI_REGISTRY=http://127.0.0.1:5000/modules CGO_ENABLED=0 go test -tags integration ./pkg/module/... -count=1 -v
```

Expected: `TestPublishRoundTripInProcessRegistry` PASS, `TestPublishRoundTripECR` SKIP, `TestFetchModule_RoundTrip/oci` PASS, `TestFetchModule_RoundTrip/git` SKIP.

- [ ] **Step 4: Stage**

```bash
git add .github/workflows/unit-test.yml
```

---

### Task 2: A definitions-only module fixture for e2e

**Files:**
- Create: `test/e2e-test/testdata/module/e2e-widget/_module.cue`
- Create: `test/e2e-test/testdata/module/e2e-widget/v1/_version.cue`
- Create: `test/e2e-test/testdata/module/e2e-widget/v1/definitions/widget.cue`

**Interfaces:**
- Consumes: the module package format enforced by `pkg/module.ParseModule` — `_module.cue` with `module` and `version` (strict semver, no leading `v`), one `v<N>/` directory per line with `_version.cue` carrying `apiVersion`, and a non-empty `v<N>/definitions/`.
- Produces: a module directory that Task 3 publishes and deploys. Its module name is `e2e-widget` and its version is `1.0.0`; Task 3 hardcodes both.

- [ ] **Step 1: Write the fixture**

`_module.cue`:

```cue
module:  "e2e-widget"
version: "1.0.0"
```

`v1/_version.cue`:

```cue
apiVersion: "v1"
```

`v1/definitions/widget.cue` must be a ComponentDefinition that KubeVela's own definition renderer accepts, since `pkg/module/parse.go` renders `.cue` definitions through `definition.Definition.FromCUEString`. Model it on an existing internal definition, for example `vela-templates/definitions/internal/component/webservice.cue`, but keep it minimal: a `ComponentDefinition` named `e2e-widget` whose template outputs a single ConfigMap. A ConfigMap keeps the deploy leg free of image pulls and readiness waits.

Do NOT add `auxiliary/xrd.yaml` or `v1/auxiliary/composition.yaml`. Those are Crossplane types; the e2e cluster has no Crossplane CRDs, and a definitions-only module is what makes the deploy leg assert something real.

- [ ] **Step 2: Prove the fixture parses and packages**

Write a throwaway check (do not commit it) or use `go test` with an existing helper. Simplest: a one-off Go program under `/tmp` that calls `module.ParseModuleDir` and `module.PackageModule` on the fixture path and prints the module name, version, lines, and the archive's file list. Confirm the parse succeeds, the line `v1` is present and enabled, and the definition rendered with a non-empty `metadata.name`.

Expected failure mode to watch for: `render definition widget.cue: ...` means the CUE does not satisfy KubeVela's definition renderer. Fix the CUE, not the parser.

- [ ] **Step 3: Stage**

```bash
git add test/e2e-test/testdata/module/e2e-widget
```

---

### Task 3: The full-flow e2e test

**Files:**
- Create: `test/e2e-test/module_publish_test.go`
- Create: `test/e2e-test/testdata/module/registry.yaml`

**Interfaces:**
- Consumes: the fixture from Task 2 (`test/e2e-test/testdata/module/e2e-widget`, module `e2e-widget`, version `1.0.0`); the built `vela` binary that the e2e job puts at `bin/vela`; and the `module` ComponentDefinition installed by the chart.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the in-cluster registry manifest**

`test/e2e-test/testdata/module/registry.yaml`: a `Deployment` named `oci-registry` running `docker.io/library/registry:2` with container port 5000, and a `Service` named `oci-registry` exposing port 5000. Put both in the `default` namespace. Keep it plain: no persistence, no auth, no TLS. The Service DNS name `oci-registry.default.svc.cluster.local:5000` is what the controller will use.

- [ ] **Step 2: Read the conventions of the suite you are joining**

Read `test/e2e-test/helmchart_test.go` (it deploys zot from `testdata/auth/manifests/zot.yaml`, so it is the closest precedent for standing up a registry) and one smaller spec such as `test/e2e-test/definition_test.go`. Note how they get a client, how they namespace their resources, how they wait, and how they invoke the `vela` binary if they do. Follow those patterns rather than inventing new ones.

- [ ] **Step 3: Write the spec**

`test/e2e-test/module_publish_test.go`, one `Describe("Module publish and deploy")` with an ordered flow. The steps, each as its own `By`:

1. Apply `testdata/module/registry.yaml`; wait for the `oci-registry` Deployment to be Available.
2. Start `kubectl port-forward svc/oci-registry 5000:5000` as a child process (`exec.Command`), and wait for `http://127.0.0.1:5000/v2/` to answer 200 before continuing. Kill the process in `DeferCleanup`. A port-forward is how the runner reaches an in-cluster Service; a Service DNS name does not resolve on the runner.
3. Publish with the positional-reference form, which needs no registry entry:
   `bin/vela module publish test/e2e-test/testdata/module/e2e-widget http://127.0.0.1:5000/modules`
   Assert the command succeeds and its output names `modules/e2e-widget:1.0.0`.
4. Assert the artifact is really in the registry over HTTP: `GET /v2/modules/e2e-widget/tags/list` contains `1.0.0`, and the manifest at `GET /v2/modules/e2e-widget/manifests/1.0.0` (with `Accept: application/vnd.oci.image.manifest.v1+json`) carries `modules.oam.dev/module: e2e-widget` and `modules.oam.dev/lines: v1`.
5. Assert immutability against the live registry: publishing the same directory again fails, and the error names the version bump. Then `--force` succeeds.
6. Register the in-cluster URL, which is the one the controller can resolve:
   `bin/vela module registry add e2e-oci http://oci-registry.default.svc.cluster.local:5000/modules --type oci`
7. Deploy through the controller: `bin/vela module deploy e2e-widget --registry e2e-oci -n <test namespace>`. This is the fetch-and-install leg: the controller pulls the artifact the CLI published and renders its tiers.
8. Assert the outcome in the cluster: the `ComponentDefinition` the module ships exists in the test namespace, and the owned Application `module-e2e-widget` reports its definitions tier healthy. Read the tier name from the owned Application's `status.services[]` rather than hardcoding a rendered name.
9. `DeferCleanup`: delete the deploy Application, the registry entry, and the registry manifest.

Give the spec a generous but bounded timeout on the deploy wait (the CLI already waits; 5 minutes matches its default) and let failures print the CLI's combined output — a bare "exit status 1" in CI is unactionable.

- [ ] **Step 4: Compile the spec**

`go vet ./test/e2e-test/` must be clean and `CGO_ENABLED=0 go test -run XXX -count=1 ./test/e2e-test/` must build without running specs.

This test cannot run in this devcontainer: it needs the controller built from this source (the module render provider is not in any published image) and that needs a docker daemon, which is absent here. Do not try to run it. Say so plainly in your report rather than claiming a pass you did not observe.

- [ ] **Step 5: Wire it into the e2e job if it is not picked up automatically**

Check whether `makefiles/e2e.mk`'s `e2e-test` target (`ginkgo -v ./test/e2e-test`) already includes new files in that directory. It does, since it names the directory rather than individual specs, so no change should be needed. Confirm by reading the target and say so in your report; only edit it if the suite is filtered by label or focus.

- [ ] **Step 6: Stage**

```bash
git add test/e2e-test/module_publish_test.go test/e2e-test/testdata/module/registry.yaml
```

---

## Self-review

**Coverage of the user's ask:** unit tests (already present and untagged, so already in CI) plus the OCI integration job (Task 1) plus the full create-publish-fetch-deploy flow (Tasks 2 and 3). No ECR anywhere in CI, per the explicit instruction.

**Placeholder scan:** the fixture CUE in Task 2 Step 1 is described rather than written out, because it must satisfy KubeVela's definition renderer and the exact shape belongs to whoever reads `webservice.cue` alongside it. Every other step carries its content.

**Type consistency:** the fixture's module name `e2e-widget` and version `1.0.0` are fixed in Task 2 and used verbatim in Task 3's assertions. The registry Service name `oci-registry` and port 5000 are fixed in Task 3 Step 1 and reused in Steps 2, 6.

**Known gap, stated rather than hidden:** Task 3 cannot be executed in this devcontainer. Its first real run will be in CI, and that run may need one round of fixes.
