# External Integrations

**Analysis Date:** 2026-03-27

## Kubernetes API Interactions

**Custom Resource Definitions (CRDs):**

All CRDs live under the `core.oam.dev` API group, generated from types in `apis/core.oam.dev/`:

| CRD | API Version | Purpose |
|-----|-------------|---------|
| `applications` | v1beta1 | Primary user-facing resource for app deployment |
| `applicationrevisions` | v1beta1 | Immutable snapshots of application versions |
| `componentdefinitions` | v1beta1 | Pluggable component types (webservice, helm, etc.) |
| `traitdefinitions` | v1beta1 | Pluggable trait types (scaler, ingress, etc.) |
| `policydefinitions` | v1beta1 | Policy types (topology, override, etc.) |
| `workflowstepdefinitions` | v1beta1 | Workflow step types (deploy, approve, etc.) |
| `workloaddefinitions` | v1beta1 | Legacy workload types |
| `resourcetrackers` | v1beta1 | Track dispatched resources for GC |
| `definitionrevisions` | v1beta1 | Versioned definition snapshots |
| `workflows` | v1alpha1 | Standalone workflow resources |
| `policies` | v1alpha1 | Standalone policy resources |

CRD manifests: `charts/vela-core/crds/`
API types: `apis/core.oam.dev/v1beta1/`, `apis/core.oam.dev/v1alpha1/`
Additional CRD: `cue.oam.dev_packages.yaml` for CUE package management

**Controller-Runtime Integration:**
- Manager setup: `cmd/core/app/server.go`
- Application reconciler: `pkg/controller/core.oam.dev/v1beta1/application/`
- ResourceKeeper (resource dispatch/GC): `pkg/resourcekeeper/`
- ResourceTracker (indirect resource watching): `pkg/resourcetracker/`
- Webhook handlers: `pkg/webhook/core.oam.dev/`
- Cache optimization: `pkg/cache/`

**Kubernetes Native Resources Used:**
- Deployments, Services, ConfigMaps, Secrets - dispatched workloads
- Namespaces - multi-tenant isolation
- RBAC (ClusterRoles, RoleBindings) - generated for auth
- ValidatingWebhookConfiguration - admission validation
- Metrics API (`k8s.io/metrics`) - resource metrics queries

## Helm Integration

**Helm v3 Library (`helm.sh/helm/v3`):**
- Used for: Chart rendering, release management, repository operations
- Native Helm provider in workflow: `pkg/workflow/providers/`
- Helm chart deployment as a component type (ComponentDefinition)
- Chart rendering for KubeVela's own deployment: `charts/vela-core/`

**FluxCD Helm Integration:**
- `github.com/fluxcd/helm-controller/api` v0.32.2 - HelmRelease CRD types
- `github.com/fluxcd/source-controller/api` v0.30.0 - HelmRepository, GitRepository CRD types
- FluxCD addons enabled during E2E: `e2e/addon/mock/testdata/fluxcd`
- Used for GitOps-style Helm release management

**ChartMuseum:**
- `github.com/chartmuseum/helm-push` v0.10.4 - Push charts to ChartMuseum registries
- Used in addon push workflow: `pkg/addon/push.go`

## Multi-Cluster Integration

**Cluster Gateway (`github.com/oam-dev/cluster-gateway`):**
- API aggregation layer for multi-cluster access
- Proxies Kubernetes API requests to managed clusters
- Deployed as part of vela-core Helm chart: `charts/vela-core/templates/cluster-gateway/`
- Configuration: `--set multicluster.clusterGateway.enabled=true`
- Image: `ghcr.io/oam-dev/cluster-gateway`

**Cluster Management:**
- `pkg/multicluster/cluster_management.go` - Cluster registration and lifecycle
- `pkg/multicluster/virtual_cluster.go` - Virtual cluster support
- `pkg/multicluster/cluster_metrics_management.go` - Cross-cluster metrics

**Open Cluster Management (OCM):**
- `open-cluster-management.io/api` v0.11.0 - OCM ManagedCluster API types
- `github.com/oam-dev/cluster-register` v1.0.4 - Cluster registration utilities

**Konnectivity:**
- `sigs.k8s.io/apiserver-network-proxy` - Network proxy for cluster-gateway connectivity

## Cloud Provider / Infrastructure Integrations

**Terraform:**
- `github.com/oam-dev/terraform-controller` v0.8.1 - Terraform-based infrastructure provisioning
- `github.com/oam-dev/terraform-config-inspect` - HCL config parsing
- `github.com/hashicorp/hcl/v2` v2.18.0 - HCL language support
- Terraform addon for Alibaba Cloud in E2E: `e2e/addon/mock/testdata/terraform-alibaba`

**Alibaba Cloud:**
- `github.com/aliyun/alibaba-cloud-sdk-go` v1.61.1704 (indirect) - Alibaba Cloud SDK
- `github.com/nacos-group/nacos-sdk-go/v2` v2.2.2 - Nacos service discovery/config (Alibaba)

## CUE Language Integration

**CUE Runtime (`cuelang.org/go` v0.14.1):**
- Definition evaluation engine: `pkg/cue/`
- Component/trait/policy definition rendering
- Input validation and schema enforcement
- Template files: `vela-templates/definitions/`
- Workflow provider templates: `pkg/workflow/template/static/`
- Definition schema: `pkg/schema/`

## Git & Source Control Integrations

**GitHub:**
- `github.com/google/go-github/v32` v32.1.0 - GitHub API for addon registry, PR operations
- OAuth2: `golang.org/x/oauth2` v0.30.0 - Token-based auth

**GitLab:**
- `gitlab.com/gitlab-org/api/client-go` v0.127.0 - GitLab API for addon sources

**Git Operations:**
- `github.com/go-git/go-git/v5` v5.16.0 - Clone, pull for addon management
- Used in: `pkg/addon/` for fetching addon definitions from Git repos

## OCI / Container Registry

**Container Registry:**
- `github.com/google/go-containerregistry` v0.18.0 - OCI image/artifact operations
- `oras.land/oras-go` v1.2.5 - OCI artifact push/pull
- Used for: OCI-based addon distribution, definition packaging

## Progressive Delivery

**OpenKruise:**
- `github.com/openkruise/kruise-api` v1.4.0 - CloneSet, Advanced StatefulSet workload types
- `github.com/openkruise/rollouts` v0.3.0 - Canary/batch rollout strategies

**Gateway API:**
- `sigs.k8s.io/gateway-api` v0.7.1 - Traffic splitting for canary rollouts

## Monitoring & Observability

**Metrics:**
- `github.com/prometheus/client_golang` v1.20.5 - Prometheus metrics
- `github.com/prometheus/client_model` v0.6.1 - Metric type definitions
- Controller-runtime metrics server: enabled by default
- Monitor package: `pkg/monitor/watcher/`

**Tracing:**
- OpenTelemetry (indirect): `go.opentelemetry.io/otel` v1.28.0
- OTLP gRPC exporter available

**Logging:**
- `k8s.io/klog/v2` v2.130.1 - Primary structured logging
- `github.com/go-logr/logr` v1.4.2 - Logger interface
- `github.com/go-logr/zapr` v1.3.0 - Zap backend
- Custom logging: `pkg/logging/`

## Authentication & Authorization

**Auth Framework:**
- `pkg/auth/` - Authentication/authorization layer
- Configurable via Helm: `--set authentication.enabled=true`
- User impersonation support: `--set authentication.withUser=true`
- Group pattern matching: `--set authentication.groupPattern='*'`
- JWT support: `github.com/form3tech-oss/jwt-go` v3.2.5

**Admission Webhooks:**
- Validating webhooks for Application resources
- Webhook cert management: `--set admissionWebhooks.enabled=true`
- Cert generator image: `ghcr.io/oam-dev/kube-webhook-certgen/kube-webhook-certgen`
- Webhook handlers: `pkg/webhook/core.oam.dev/`
- CRD validation hooks: `cmd/core/app/hooks/crdvalidation/`

## Addon System

**Addon Management (`pkg/addon/`):**
- Sources: Git repos (GitHub, GitLab), Helm repos, OCI registries
- Cache layer: `pkg/addon/cache.go`
- Push to registries: `pkg/addon/push.go`
- Addon registry: `charts/vela-core/templates/addon_registry.yaml`

## Workflow Engine

**KubeVela Workflow (`github.com/kubevela/workflow` v0.6.3):**
- Step execution engine: `pkg/workflow/workflow.go`
- Built-in providers: `pkg/workflow/providers/`
- Step templates: `pkg/workflow/template/`
- Operations (suspend, resume, rollback): `pkg/workflow/operation/`

## VelaQL (Query Language)

**Query Engine:**
- `pkg/velaql/` - Custom query language for resource introspection
- Used for: Querying application status, resource topology, cross-cluster views

## Environment Configuration

**Required for development:**
- `KUBECONFIG` - Path to Kubernetes cluster config
- Go 1.23.8+ installed

**Required for E2E (from `makefiles/e2e.mk`):**
- `GIT_COMMIT` - Auto-derived from git rev-parse
- Kind/k3d cluster running
- Docker available for image builds

**Helm chart values (key settings):**
- `image.repository` / `image.tag` - Controller image
- `multicluster.clusterGateway.enabled` - Enable multi-cluster
- `admissionWebhooks.enabled` - Enable validation webhooks
- `authentication.enabled` - Enable auth layer
- `sharding.enabled` - Enable controller sharding
- `featureGates.*` - Feature gate toggles
- `applicationRevisionLimit` - Max revisions to retain
- `controllerArgs.reSyncPeriod` - Reconciliation interval

## Webhooks & Callbacks

**Incoming (Admission Webhooks):**
- ValidatingWebhookConfiguration for Application resources
- Endpoint: `/validate-core-oam-dev-v1beta1-application`
- Handlers: `pkg/webhook/core.oam.dev/`

**Outgoing:**
- None detected (no outbound webhook dispatch)

---

*Integration audit: 2026-03-27*
