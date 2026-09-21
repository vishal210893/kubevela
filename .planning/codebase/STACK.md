# Technology Stack

**Analysis Date:** 2026-03-27

## Languages

**Primary:**
- Go 1.23.8 - All controller, CLI, and API code (`go.mod`)
- CUE v0.14.1 - Definition templates and validation (`vela-templates/definitions/`, `pkg/workflow/providers/`)

**Secondary:**
- Bash - Build scripts, CI helpers (`hack/`, `entrypoint.sh`, `vela-templates/gen_definitions.sh`)
- YAML - Kubernetes manifests, Helm charts, CI workflows (`charts/`, `.github/workflows/`)

## Runtime

**Environment:**
- Go 1.23.8 (pinned in `go.mod` and CI via `GO_VERSION: '1.23.8'`)
- Kubernetes v1.31.x (API libs at v0.31.10, envtest at 1.31.0)
- Alpine 3.18 base image for production container (`Dockerfile`)

**Package Manager:**
- Go Modules (`go.mod`, `go.sum`)
- Lockfile: `go.sum` present

## Frameworks

**Core:**
- controller-runtime v0.19.7 - Kubernetes controller framework (`sigs.k8s.io/controller-runtime`)
- controller-tools v0.16.5 - CRD generation and code generation (`sigs.k8s.io/controller-tools`)
- Cobra v1.9.1 - CLI framework for both core manager and vela CLI (`github.com/spf13/cobra`)
- Helm v3.14.4 - Helm chart rendering and release management (`helm.sh/helm/v3`)

**Testing:**
- Ginkgo v2.23.3 - BDD test framework for E2E and integration tests (`github.com/onsi/ginkgo/v2`)
- Gomega v1.36.2 - Matcher library used with Ginkgo (`github.com/onsi/gomega`)
- testify v1.10.0 - Unit test assertions (`github.com/stretchr/testify`)
- gomock v1.6.0 - Mock generation (`github.com/golang/mock`)
- envtest (via setup-envtest) - Kubernetes API server for integration tests

**Build/Dev:**
- Make - Primary build orchestration (`Makefile`, `makefiles/*.mk`)
- Docker - Multi-stage container builds (`Dockerfile`, `Dockerfile.cli`, `Dockerfile.e2e`)
- Kustomize v4.5.4 - CRD manifest composition (`makefiles/dependency.mk`)
- goimports - Import formatting (`makefiles/dependency.mk`)
- GoReleaser - Release automation (`.goreleaser.yaml`)

## Key Dependencies

**Critical:**
- `sigs.k8s.io/controller-runtime` v0.19.7 - Core controller manager, reconciler loops, webhooks, client
- `helm.sh/helm/v3` v3.14.4 - Helm chart operations (install, upgrade, template rendering)
- `cuelang.org/go` v0.14.1 - CUE language runtime for definition evaluation and validation
- `github.com/kubevela/workflow` v0.6.3 - Workflow engine for application deployment steps
- `github.com/kubevela/pkg` v1.10.0 - Shared KubeVela utilities (controller client, sharding, profiling)

**Infrastructure:**
- `github.com/oam-dev/cluster-gateway` v1.9.2 - Multi-cluster access via API aggregation
- `github.com/crossplane/crossplane-runtime` v1.16.0 - Crossplane condition/status utilities
- `github.com/oam-dev/terraform-controller` v0.8.1 - Terraform integration for infrastructure provisioning
- `github.com/fluxcd/helm-controller/api` v0.32.2 - FluxCD Helm release CRD types
- `github.com/fluxcd/source-controller/api` v0.30.0 - FluxCD source CRD types (HelmRepository, etc.)
- `github.com/openkruise/kruise-api` v1.4.0 - OpenKruise workload types (CloneSet, etc.)
- `github.com/openkruise/rollouts` v0.3.0 - Progressive delivery / canary rollout support
- `open-cluster-management.io/api` v0.11.0 - OCM multi-cluster management APIs
- `github.com/prometheus/client_golang` v1.20.5 - Prometheus metrics exposition
- `sigs.k8s.io/gateway-api` v0.7.1 - Kubernetes Gateway API types

**CLI/UX:**
- `github.com/spf13/cobra` v1.9.1 - CLI command framework
- `github.com/AlecAivazis/survey/v2` v2.1.1 - Interactive CLI prompts
- `github.com/briandowns/spinner` v1.23.0 - CLI loading spinners
- `github.com/fatih/color` v1.18.0 - Colored terminal output
- `github.com/rivo/tview` v0.0.0 - Terminal UI widgets

**Git/Registry:**
- `github.com/go-git/go-git/v5` v5.16.0 - Git operations for addon management
- `github.com/google/go-containerregistry` v0.18.0 - OCI container/artifact registry client
- `github.com/chartmuseum/helm-push` v0.10.4 - Push Helm charts to ChartMuseum
- `gitlab.com/gitlab-org/api/client-go` v0.127.0 - GitLab API client
- `github.com/google/go-github/v32` v32.1.0 - GitHub API client

## Configuration

**Environment:**
- Controller flags configured via `cmd/core/app/options/` (CoreOptions struct)
- Feature gates via `k8s.io/apiserver/pkg/util/feature` and `pkg/features/`
- Key feature gates: `enableCueValidation`, `validateResourcesExist`, `enableApplicationScopedPolicies`, `enableGlobalPolicies`, `zstdResourceTracker`, `zstdApplicationRevision`
- Helm values in `charts/vela-core/` control deployment configuration

**Build:**
- `Makefile` - Top-level orchestrator, includes `makefiles/*.mk`
- `makefiles/const.mk` - Version vars, image names, LDFLAGS
- `makefiles/build.mk` - Binary and Docker build targets
- `makefiles/dependency.mk` - Tool installation (golangci-lint, staticcheck, kustomize, cue, envtest)
- `makefiles/e2e.mk` - E2E test setup and execution targets
- `makefiles/develop.mk` - Developer workflow targets
- `makefiles/release.mk` - Release automation targets
- `.golangci.yml` - Linter configuration
- `.goreleaser.yaml` - Release binary distribution

## Build Targets (Makefile)

**Core:**
- `make build` / `make vela-cli` - Build vela CLI binary to `bin/vela`
- `make kubectl-vela` - Build kubectl plugin to `bin/kubectl-vela`
- `make manager` - Build core controller binary to `bin/manager`
- `make docker-build` - Build Docker images (core + CLI)
- `make image-load` - Build E2E test image and load into Kind cluster

**Code Quality:**
- `make fmt` - Format Go and CUE code (goimports + cue fmt)
- `make vet` - Run go vet
- `make lint` - Run golangci-lint v1.60.1
- `make staticcheck` - Run staticcheck v0.6.1
- `make reviewable` - Full pre-PR check (build + manifests + fmt + vet + lint + staticcheck)

**Generation:**
- `make manifests` - Generate CRDs, RBAC, sync from kubevela/pkg, dispatch to Helm chart crds/
- `make tidy` - Run go mod tidy

**Testing:**
- `make test` - Run unit tests with envtest + CLI gen tests
- `make core-test` - Run `go test ./pkg/...`
- `make e2e-test` - Run E2E tests via Ginkgo (`test/e2e-test/`)
- `make e2e-test-local` - Full local E2E: k3d cluster + build + deploy + test
- `make e2e-multicluster-test` - Multi-cluster E2E tests
- `make e2e-addon-test` - Addon E2E tests

## CI/CD

**GitHub Actions Workflows (`.github/workflows/`):**
- `unit-test.yml` - Unit tests on push/PR to master/release branches
- `e2e-test.yml` - E2E tests against K8s v1.31 matrix
- `e2e-multicluster-test.yml` - Multi-cluster E2E tests
- `go.yml` - Go build verification
- `core-api-test.yml` - Core API integration tests
- `definition-lint.yml` - CUE definition linting
- `codeql-analysis.yml` - CodeQL security scanning
- `trivy-scan.yml` - Container vulnerability scanning
- `release.yml` - Release automation
- `chart.yml` - Helm chart CI
- `commit-lint.yml` - Commit message validation
- `license.yml` - License header checking
- `sdk-test.yml` / `sync-sdk.yaml` - SDK testing and sync

**CI Environment:**
- Runner: ubuntu-22.04
- Go: 1.23.8
- Kind/k3d for E2E cluster provisioning
- Helm for deployment during E2E

## Platform Requirements

**Development:**
- Go 1.23.8+
- Docker (for image builds and Kind/k3d)
- Kind or k3d (local Kubernetes cluster)
- kubectl
- Helm 3
- Make
- CUE CLI v0.14.1 (auto-installed by Make)

**Production:**
- Kubernetes v1.31.x cluster
- Helm 3 for installation via `charts/vela-core/`
- Container runtime (alpine:3.18 base)
- CRDs installed from `charts/vela-core/crds/`

## Binaries

| Binary | Entry Point | Purpose |
|--------|-------------|---------|
| `manager` | `cmd/core/main.go` | Core controller manager (runs in-cluster) |
| `vela` | `references/cmd/cli/main.go` | CLI tool for developers/operators |
| `kubectl-vela` | `cmd/plugin/main.go` | kubectl plugin |

---

*Stack analysis: 2026-03-27*
