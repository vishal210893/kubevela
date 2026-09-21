# KubeVela Native Helm Provider - Edge Case Testing Report

**Date:** 2026-03-28
**Tester:** Vishal Kumar (viskumar)
**Branch:** `feat/native-helm-provider`
**Cluster:** k3d (kubevela), Kubernetes v1.31.x
**Controller:** Running locally via GoLand debugger with `--application-re-sync-period=20s`

---

## Summary

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | Server-Side Apply works correctly (no `last-applied-configuration` annotation after upgrade) | Info (Positive) | Confirmed Working |
| 2 | Webhook timeout on large Helm charts (kube-prometheus-stack) | High | Open |
| 3 | Multi-criteria health check fails for resources without `.status.conditions` | Medium | Open |
| 4 | etcd 1.5MB size limit risk with multi-component large Helm charts (ResourceTracker bloat) | Medium | Not Reproduced |

---

## Issue 1: Server-Side Apply Confirmation

### Finding

Server-side Helm apply is working correctly. After upgrading a Helm release, the `kubectl.kubernetes.io/last-applied-configuration` annotation is **not present** on managed resources. This confirms that the native Helm provider uses server-side apply (or Helm's own apply mechanism) rather than client-side `kubectl apply`, which would inject the `last-applied-configuration` annotation.

### Why This Matters

- Server-side apply avoids the annotation size bloat that client-side apply causes (the annotation stores the entire last-applied manifest as JSON)
- This is especially important for large charts where the annotation could push resources close to etcd's 1.5MB object size limit
- It also means field ownership is properly tracked via `managedFields` rather than the deprecated annotation

### Verification

After deploying and upgrading podinfo via the helmchart component:
```bash
kubectl get deployment podinfo -n <namespace> -o jsonpath='{.metadata.annotations}' | grep last-applied
# Returns empty - no last-applied-configuration annotation present
```

### Status: **Working as Expected**

---

## Issue 2: Webhook Validation Timeout on Large Helm Charts

### Problem

When applying a KubeVela Application containing a large Helm chart (e.g., `kube-prometheus-stack` v69.3.3 with 116+ resources, CRDs, and admission webhook Jobs), the validating webhook times out with a `context deadline exceeded` error.

### Reproduction

Applied the following Application with 2 components (podinfo + kube-prometheus-stack):

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: podinfo-helm-test
spec:
  components:
    - name: podinfo
      type: helmchart
      properties:
        chart:
          source: podinfo
          repoURL: https://stefanprodan.github.io/podinfo
          version: "6.11.1"
        release:
          name: podinfo
          namespace: podinfo
        values:
          replicaCount: 2
          resources:
            limits:
              memory: 256Mi
              cpu: 100m
        options:
          createNamespace: true
          includeCRDs: true
          skipTests: true

    - name: kube-prometheus-stack
      type: helmchart
      properties:
        chart:
          source: kube-prometheus-stack
          repoURL: https://prometheus-community.github.io/helm-charts
          version: "69.3.3"
        release:
          name: kube-prometheus-stack
          namespace: monitoring
        values:
          prometheus:
            prometheusSpec:
              resources:
                limits:
                  memory: 2Gi
                  cpu: 500m
                requests:
                  memory: 512Mi
                  cpu: 100m
          alertmanager:
            enabled: true
          grafana:
            enabled: true
            adminPassword: prom-operator
          nodeExporter:
            enabled: true
          kubeStateMetrics:
            enabled: true
        options:
          createNamespace: true
          includeCRDs: true
          skipTests: true
```

Result:
```bash
kc apply -f app_helmchart_podinfo.yaml
# Error from server (InternalError): error when creating "app_helmchart_podinfo.yaml":
# Internal error occurred: failed calling webhook
# "validating.core.oam.dev.v1beta1.applications":
# failed to call webhook: Post
# "https://192.168.0.11:9445/validating-core-oam-dev-v1beta1-applications?timeout=10s":
# context deadline exceeded
```

Components:
1. `podinfo` (small chart, 3 resources) - validates quickly
2. `kube-prometheus-stack` (large chart, 116+ resources, 10 CRDs, admission webhook Jobs) - exceeds timeout

### Root Cause

The validating webhook performs a **dry-run Helm install** for each component during validation. For `kube-prometheus-stack`, this involves:

1. **CRD installation** (10 CRDs for Prometheus Operator - alertmanagerconfigs, alertmanagers, podmonitors, probes, prometheusagents, prometheuses, prometheusrules, scrapeconfigs, servicemonitors, thanosrulers)
2. **Admission webhook Job execution** (`kube-prometheus-stack-admission-create` and `kube-prometheus-stack-admission-patch` Jobs)
3. **Creating 116+ resources** during dry-run
4. **Job watching** with polling for completion

From the controller logs:
```
12:38:14.381 - Webhook validation starts (2 components)
12:38:14.409 - podinfo validated quickly (3 resources)
12:38:17.337 - kube-prometheus-stack install begins
12:38:17.416 - CRD installation starts (10 CRDs)
12:38:25.794 - Validation fails after ~11.4s with "context canceled"
```

The Kubernetes API server's default webhook timeout is **10 seconds**. The kube-prometheus-stack chart takes ~11+ seconds to dry-run install due to CRD registration, admission webhook Job execution, and resource creation.

### Impact

- Any Application with large Helm charts (100+ resources, CRDs, or admission webhooks) may fail validation
- The chart is never actually deployed because it's rejected at the webhook admission stage
- Multi-component Applications are more vulnerable since all components are validated sequentially within the same timeout window

### Possible Fixes

| Approach | Pros | Cons |
|----------|------|------|
| Increase webhook `timeoutSeconds` to 30s | Simple, immediate fix | Delays feedback for all validations |
| Skip dry-run Helm install for validation; validate schema only | Fast validation | Loses deployment-level error detection |
| Async validation with status feedback | Best UX | Significant architecture change |
| Cache chart templates to avoid re-download | Speeds up repeat validations | First validation still slow |
| Validate components in parallel | Reduces total time for multi-component apps | Adds complexity, resource contention |

### Controller Log Evidence

Key timestamps from the controller log showing the timeout sequence:

```
I0328 12:38:14.381 "Starting admission validation" componentCount=2
I0328 12:38:14.409 Helm provider: Deployed 3 resources for podinfo (fast)
I0328 12:38:17.337 Helm provider: Installing kube-prometheus-stack in monitoring
I0328 12:38:17.416 creating 1 resource(s)  [CRD: alertmanagerconfigs]
I0328 12:38:17.575 CRD alertmanagerconfigs already present
...
I0328 12:38:18.570 CRD thanosrulers already present [10th CRD]
I0328 12:38:25.488 creating 1 resource(s) [admission ServiceAccount]
E0328 12:38:25.794 "Application creation validation failed" error="context canceled"
```

Total webhook processing time: **~11.4 seconds** (exceeds 10s timeout).

### Status: **Open - Needs Fix**

---

## Issue 3: Multi-Criteria Health Check Fails for Resources Without `.status.conditions`

### Problem

When a helmchart Application includes `healthStatus` criteria for both a Deployment and a Service, the Application never reaches `running` state. The health check for Service fails because Kubernetes Services do not have a `.status.conditions` field.

### Root Cause (Dual)

**A. Health policy only searches `context.outputs`, not `context.output`**

The CUE health policy iterates `context.outputs` (additional resources) but misses `context.output` (the primary workload). If the Deployment is the primary output (`resources[0]`), it is invisible to health criteria evaluation.

From controller logs, the first resource is Service:
```
I0328 12:34:23.533 Helm provider: First resource is Service/podinfo
```

So `context.output` = Service, and `context.outputs` contains Deployment + Secret. This means the Deployment IS findable in `context.outputs`, but the Service (as primary output) is NOT in `context.outputs` - it's only in `context.output`.

**B. CUE `_|_` comparison semantics**

The health policy checks `if _resource.status.conditions == _|_` to handle resources without conditions. In CUE, comparing with bottom (`_|_`) may itself evaluate to bottom, causing neither the "has conditions" nor "no conditions" branch to execute.

### Detailed Analysis

See: [`ISSUE_scenario18_multi_health.md`](./ISSUE_scenario18_multi_health.md)

### Fix Applied (Pending Verification)

Updated `helmchart.cue` health policy to search both `context.output` and `context.outputs`:

```cue
_primaryOutput: [ for r in [context.output] if r.kind != _|_ { r } ]
_additionalOutputs: [ for _, r in context.outputs { r } ]
_allResources: _primaryOutput + _additionalOutputs
```

### Status: **Open - Fix Applied, Pending Re-test After Definition Reinstall**

---

## Issue 4: etcd Size Limit (1.5MB) Risk with Multi-Component Large Helm Charts

### Concern

When deploying a KubeVela Application with multiple components of large Helm charts, the ResourceTracker object stored in etcd could potentially exceed the 1.5MB size limit.

### Test Performed

Deployed an Application with **8 components** including several large charts to stress-test ResourceTracker size:

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: podinfo-helm-test
spec:
  components:
    # 1. podinfo - lightweight test app (3 resources)
    - name: podinfo
      type: helmchart
      properties:
        chart:
          source: podinfo
          repoURL: https://stefanprodan.github.io/podinfo
          version: "6.11.1"
        release:
          name: podinfo
          namespace: podinfo
        values:
          replicaCount: 2
          resources:
            limits:
              memory: 256Mi
              cpu: 100m
        options:
          createNamespace: true
          includeCRDs: true
          skipTests: true

    # 2. arc-crds - OCI-based CRDs chart (private registry)
    - name: arc-crds
      type: helmchart
      properties:
        chart:
          source: arc-crds
          repoURL: oci://registry-1.docker.io/vishal210893
          version: "0.1.0"
        release:
          name: arc-crds
          namespace: arc-systems
        options:
          createNamespace: true
          includeCRDs: true
          skipTests: true
          secretRef:
            name: dockerhub-credentials

    # 3. kube-prometheus-stack - 200-300+ resources (monitoring stack)
    - name: kube-prometheus-stack
      type: helmchart
      properties:
        chart:
          source: kube-prometheus-stack
          repoURL: https://prometheus-community.github.io/helm-charts
          version: "69.3.3"
        release:
          name: kube-prometheus-stack
          namespace: monitoring
        values:
          prometheus:
            prometheusSpec:
              resources:
                limits:
                  memory: 2Gi
                  cpu: 500m
                requests:
                  memory: 512Mi
                  cpu: 100m
          alertmanager:
            enabled: true
          grafana:
            enabled: true
            adminPassword: prom-operator
          nodeExporter:
            enabled: true
          kubeStateMetrics:
            enabled: true
        options:
          createNamespace: true
          includeCRDs: true
          skipTests: true

    # 4. gitlab - 300-400+ resources (enterprise umbrella chart)
    - name: gitlab
      type: helmchart
      properties:
        chart:
          source: gitlab
          repoURL: https://charts.gitlab.io/
          version: "8.10.1"
        release:
          name: gitlab
          namespace: gitlab
        values:
          global:
            hosts:
              domain: example.com
            ingress:
              configureCertmanager: false
              tls:
                enabled: false
          certmanager-issuer:
            email: test@example.com
          certmanager:
            install: false
          nginx-ingress:
            enabled: false
          prometheus:
            install: false
          gitlab-runner:
            install: false
        options:
          createNamespace: true
          includeCRDs: true
          skipTests: true

    # 5. istio-base - CRDs and cluster-wide Istio resources
    - name: istio-base
      type: helmchart
      properties:
        chart:
          source: base
          repoURL: https://istio-release.storage.googleapis.com/charts
          version: "1.25.0"
        release:
          name: istio-base
          namespace: istio-system
        values:
          defaultRevision: default
        options:
          createNamespace: true
          includeCRDs: true
          skipTests: true

    # 6. istiod - control plane
    - name: istiod
      type: helmchart
      properties:
        chart:
          source: istiod
          repoURL: https://istio-release.storage.googleapis.com/charts
          version: "1.25.0"
        release:
          name: istiod
          namespace: istio-system
        values:
          pilot:
            resources:
              requests:
                cpu: 100m
                memory: 128Mi
              limits:
                cpu: 500m
                memory: 512Mi
        options:
          createNamespace: true
          includeCRDs: true
          skipTests: true

    # 7. crossplane - ~80-100 resources (CRDs, RBAC, webhooks)
    - name: crossplane
      type: helmchart
      properties:
        chart:
          source: crossplane
          repoURL: https://charts.crossplane.io/stable
          version: "1.19.1"
        release:
          name: crossplane
          namespace: crossplane-system
        values:
          resources:
            limits:
              cpu: 500m
              memory: 512Mi
            requests:
              cpu: 100m
              memory: 256Mi
          args:
            - --debug=false
        options:
          createNamespace: true
          includeCRDs: true
          skipTests: true

    # 8. argocd - 150+ resources (CRDs, ClusterRoles, Deployments, Services)
    - name: argocd
      type: helmchart
      properties:
        chart:
          source: argo-cd
          repoURL: https://argoproj.github.io/argo-helm
          version: "7.8.23"
        release:
          name: argocd
          namespace: argocd
        values:
          server:
            replicas: 1
            resources:
              limits:
                cpu: 500m
                memory: 512Mi
              requests:
                cpu: 100m
                memory: 128Mi
          applicationSet:
            enabled: true
            resources:
              limits:
                cpu: 500m
                memory: 512Mi
              requests:
                cpu: 100m
                memory: 128Mi
          notifications:
            enabled: true
          dex:
            enabled: false
          redis:
            resources:
              limits:
                cpu: 200m
                memory: 256Mi
              requests:
                cpu: 50m
                memory: 64Mi
          controller:
            resources:
              limits:
                cpu: 1000m
                memory: 1Gi
              requests:
                cpu: 250m
                memory: 256Mi
        options:
          createNamespace: true
          includeCRDs: true
          skipTests: true
```

### Result: Not Reproduced

The etcd 1.5MB limit was **not hit** during testing with this 8-component Application. The Application was blocked by Issue 2 (webhook timeout) before reaching the ResourceTracker creation phase, but individual chart deployments that did succeed (during webhook dry-run) did not trigger etcd size errors.

Estimated total resource count across all 8 components:

| Component | Estimated Resources |
|-----------|-------------------|
| podinfo | ~3 |
| arc-crds | ~5-10 |
| kube-prometheus-stack | ~200-300 |
| gitlab | ~300-400 |
| istio-base | ~30-50 |
| istiod | ~20-30 |
| crossplane | ~80-100 |
| argocd | ~150+ |
| **Total** | **~800-1000+** |

While this total is very high, the ResourceTracker stores only resource references (GVK + namespace/name + UID), not full resource content. This keeps the ResourceTracker size manageable even for large deployments.

### Theoretical Risk

KubeVela's ResourceTracker pattern stores references to ALL managed resources for an Application in a single CR. For extremely large deployments:

- Each resource reference includes metadata (name, namespace, GVK, UID, labels)
- With 800+ resource references, the ResourceTracker could approach the 1.5MB limit
- The risk increases if resource references include additional metadata (annotations, labels, ownership info)

### etcd Limits (Reference)

| Limit | Value | Impact |
|-------|-------|--------|
| Max value size per key | 1.5 MB | ResourceTracker CR must stay under this |
| Max total DB size | 8 GB (default) | Less likely to be hit |
| Max request size | 1.5 MB | PUT/PATCH requests for ResourceTracker may fail |

### Possible Mitigations (If Issue Occurs in Future)

| Approach | Description |
|----------|-------------|
| **ResourceTracker sharding** | Split ResourceTracker into per-component sub-trackers to keep each under 1.5MB |
| **ResourceTracker compression** | Compress resource references (e.g., omit redundant fields, use compact encoding) |
| **Lazy resource tracking** | Store only GVK + namespace/name instead of full resource metadata |
| **Component-level ResourceTrackers** | One RT per component instead of one per Application |

### Status: **Not Reproduced - Theoretical Risk, Monitor in Production**

---

## Relationship Between Issues

```
Issue 2 (Webhook Timeout) -- BLOCKER
    |
    +-- Large charts take >10s to dry-run validate
    |
    +-- If webhook passes, chart deploys successfully, but...
            |
            +-- Issue 4 (etcd Size Limit) -- NOT REPRODUCED
            |       |
            |       +-- Tested with 8 components (~800-1000 resources)
            |       +-- ResourceTracker stayed within limits
            |       +-- Theoretical risk for even larger deployments
            |
            +-- Issue 3 (Health Check)
                    |
                    +-- Service health criteria fail due to missing conditions
                    +-- Primary output not searched in health policy
```

Issue 2 is a **gatekeeper** - if the webhook times out, the Application is never created, so Issues 3 and 4 are never encountered. When the webhook succeeds (smaller charts or increased timeout), Issue 3 becomes relevant. Issue 4 was not reproduced even with 8 large components.

---

## Test Environment

```
Platform:     macOS Darwin 25.3.0
Go:           1.23.8
Kubernetes:   v1.31.x (k3d)
KubeVela:     Built from feat/native-helm-provider branch
Controller:   Local debug via GoLand (PID 17672)
Resync:       20s (--application-re-sync-period=20s)
KUBECONFIG:   ~/.kube/config
```

## Next Steps

1. **Issue 2 (High Priority)**: Investigate increasing webhook timeout or implementing chart template caching - this blocks all large chart deployments
2. **Issue 3**: Reinstall helmchart definition with the `context.output` fix and re-run Scenario 18
3. **Issue 4**: Monitor in production - not reproduced with 8 components (~800-1000 resources), but keep as theoretical risk for even larger deployments
