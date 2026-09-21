# Issue: Scenario 18 — Custom Health Check with Service `Ready` Condition Always Fails

## Status

**BLOCKED** — Test is skipped / known failing. Requires changes to both the CUE health policy and the health evaluation architecture.

## Problem

When a helmchart Application includes a `healthStatus` criterion for a Service with `condition.type: Ready`, the Application **never reaches `running`** — it stays in `runningWorkflow` indefinitely.

### YAML That Fails

```yaml
healthStatus:
  - resource:
      kind: Deployment
      name: podinfo
    condition:
      type: Available        # Works — Deployment has this condition
  - resource:
      kind: Service
      name: podinfo
    condition:
      type: Ready             # Never works — Service has no conditions
```

## Root Cause Analysis

### 1. Services Have No `.status.conditions`

Kubernetes Services (ClusterIP, NodePort, LoadBalancer) do **not** have a `.status.conditions` field. A typical Service status looks like:

```yaml
status:
  loadBalancer: {}
```

There is no `conditions` array. This differs from Deployments which have:

```yaml
status:
  conditions:
    - type: Available
      status: "True"
    - type: Progressing
      status: "True"
```

### 2. CUE Health Policy Evaluation Path

The health policy in `helmchart.cue` (line 18-61) evaluates each criterion through this path:

```
For each criterion:
  1. Find matching resource in context.outputs by kind + name
  2. If found (len > 0):
     a. If resource.status.conditions exists → search for matching condition type+status
     b. If resource.status.conditions == _|_ → result: false  ← THIS IS THE BUG
  3. If not found → result: false
```

For Service, path 2b is taken: the resource exists in `context.outputs` (the Service was rendered by Helm), but `_resource.status.conditions` is `_|_` (absent), so `result: false`.

### 3. The `result: true` Fix Is Insufficient

Changing line 46 from `result: false` to `result: true` (treating "resource exists, no conditions" as healthy) was attempted. This fix has two problems:

**Problem A: Definition reload.** The health policy is a raw string literal embedded in the `ComponentDefinition` CR. Changing the `.cue` file on disk does NOT update the running controller — the definition must be re-installed in the cluster via `make def-install` or equivalent. Simply restarting the controller is insufficient if it reads definitions from the cluster, not from disk.

**Problem B: The `condition.type: Ready` is still meaningless.** Even with `result: true` for absent conditions, the user specified `condition.type: Ready` expecting it to be evaluated. Returning `true` without actually checking the condition is semantically wrong — it silently ignores the user's health criterion.

### 4. `context.outputs` Contains Live Cluster State

The health evaluation fetches live resources from the cluster via `getResourceFromObj()` in `template.go:222-253`. So `context.outputs` includes real `.status` fields from the API server, not just rendered manifests. This means:

- Deployment: has `.status.conditions` with `Available`, `Progressing` → conditions can be matched
- Service: has `.status.loadBalancer` but NO `.status.conditions` → condition matching is impossible

## Why the Test Fails

1. Application is created with two health criteria: `Deployment/Available` + `Service/Ready`
2. Controller evaluates health policy CUE template
3. Deployment criterion passes (`.status.conditions` has `Available=True`)
4. Service criterion fails (`.status.conditions` is `_|_` → `result: false`)
5. `_failedCriteria` has 1 entry → `result: len(_failedCriteria) == 0` → `false`
6. `isHealth: false` → Application stays in `runningWorkflow`, never reaches `running`
7. Test timeout at `h.waitForAppRunning()` (120s)

## Proposed Fix Options

### Option 1: "Resource Exists" Health Mode (Recommended)

Add a new condition type like `Exists` that only checks if the resource is present:

```yaml
healthStatus:
  - resource:
      kind: Service
      name: podinfo
    condition:
      type: Exists    # New: just check resource is present in cluster
```

CUE change:

```cue
if _conditionType == "Exists" {
    result: len(_matchingResources) > 0
}
if _conditionType != "Exists" {
    // existing condition matching logic
}
```

### Option 2: Fallback for Resources Without Conditions

When a resource has no `.status.conditions`, treat presence as healthy:

```cue
if _resource.status.conditions == _|_ {
    // Resource exists but has no conditions (Service, ConfigMap, Secret, etc.)
    // Treat as healthy — resource presence is the best signal available
    result: true
}
```

This was attempted (line 45-47 changed to `result: true`) but requires definition reinstallation.

### Option 3: Validate Condition Types Per Resource Kind

Add validation in the CUE schema that rejects unsupported condition types for resource kinds that don't have conditions. This would fail-fast at apply time:

```
Error: Service does not support condition type "Ready".
Supported condition types for Service: Exists
```

## Current Workaround

The test YAML has been modified to only use Deployment criteria:

```yaml
healthStatus:
  - resource:
      kind: Deployment
      name: podinfo
    condition:
      type: Available
  # Service criterion removed — not supported by health policy
```

## Files Involved

| File | Role |
|------|------|
| `vela-templates/definitions/internal/component/helmchart.cue:18-61` | Health policy CUE template |
| `pkg/cue/definition/health/health.go:53-76` | Health check evaluation engine |
| `pkg/cue/definition/template.go:220-254` | Builds `context.outputs` from live cluster |
| `test/e2e-test/testdata/helm/app_helmchart_podinfo_multi_health.yaml` | Test YAML with health criteria |
| `test/e2e-test/helmchart_test.go:1031-1071` | Scenario 18 test code |

## Impact

Any `healthStatus` criterion targeting a resource **without `.status.conditions`** will cause the Application to never reach `running`. Affected resource kinds include:
- Service (ClusterIP, NodePort, LoadBalancer)
- ConfigMap
- Secret
- ServiceAccount
- PersistentVolumeClaim (before binding)
- Namespace
