# PR #7226 manual test — propagate CUE health-eval errors from `GetStatus`

Verifies that the fix in
[kubevela/kubevela#7226](https://github.com/kubevela/kubevela/pull/7226)
converts a swallowed CUE health-policy evaluation error into a visible controller
warning, while still keeping the reconcile loop alive (best-effort behaviour).

Related investigation:
[Upgrade Behaviour on existing application (Confluence)](https://guidewireconfluence.atlassian.net/wiki/spaces/CCS/pages/3259924659/Upgrade+Behaviour+on+existing+application).

## What the fix does

| Path                                 | Before PR                                     | After PR                                              |
| ------------------------------------ | --------------------------------------------- | ----------------------------------------------------- |
| `health.GetStatus`                   | always returned `(result, nil)`               | returns `errors.Join(mapErr, healthErr, msgErr)`      |
| `collectWorkloadHealthStatus`        | returned the error → aborted reconcile        | `klog.Warningf(...)` + continues (best-effort)        |
| `collectTraitHealthStatus`           | returned the error → aborted reconcile        | `klog.Warningf(...)` + continues (best-effort)        |

Regression test in the PR:
`isHealth: context.output.spec.replicas + "not-a-number" > 0` — a CUE
`int + string` type error. This fixture uses the same trigger inside a real
`ComponentDefinition.spec.schematic.cue.healthPolicy`.

## Fixtures

- `10-cd-broken.yaml` — `ComponentDefinition` `broken-health-nginx` renders a
  plain nginx `Deployment`. Its `healthPolicy` intentionally contains
  `context.output.spec.replicas + "not-a-number"` — a CUE type error at eval
  time.
- `20-app.yaml` — `Application` `broken-health-app` in namespace `default` that
  uses the broken CD.

## Procedure

Prerequisite: a running KubeVela control plane that includes commit
[`8bb75684c`](https://github.com/kubevela/kubevela/commit/8bb75684c) (PR #7226)
— e.g. a fresh `vela install` from a chart built off `master` after the PR
merged, or a controller image built from that ref.

```bash
# 1. Apply the CD, then the App.
kubectl apply -f 10-cd-broken.yaml
kubectl apply -f 20-app.yaml

# 2. Wait a few seconds for one reconcile cycle to complete.
kubectl -n default wait --for=condition=Ready application/broken-health-app --timeout=60s || true

# 3. Confirm the Deployment DOES get created (broken health must NOT block dispatch).
kubectl -n default get deploy broken-health-nginx

# 4. Grep the controller logs for the new warning line.
kubectl -n vela-system logs deploy/kubevela-vela-core -c kubevela | \
  grep -E "evaluate workload status error \(best-effort\)|evaluate trait status error \(best-effort\)"
```

## Expected output (post-fix)

Step 3 — `Deployment` exists, `AVAILABLE 1/1`:

```
NAME                  READY   UP-TO-DATE   AVAILABLE   AGE
broken-health-nginx   1/1     1            1           25s
```

Step 4 — one or more warning lines identical in shape to:

```
W0715 10:23:47.123456       1 apply.go:310] app=broken-health-app, comp=broken-health-nginx, \
  evaluate workload status error (best-effort): failed to eval status: invalid operands 1 and \
  "not-a-number" to '+' (type int and string)
```

Application status — `services[0].healthy` is `false` (best-effort), but the
reconcile is NOT aborted; the workflow finishes:

```bash
kubectl -n default get application broken-health-app -o jsonpath='{.status.status}'
# workflowFinished

kubectl -n default get application broken-health-app -o jsonpath='{.status.services[0].healthy}'
# false
```

## What "before the fix" looked like (for reference)

Same fixtures against a controller built **before** commit `8bb75684c`:

- The `klog.Warningf("evaluate workload status error (best-effort): ...")` line
  is absent from `deploy/kubevela-vela-core` logs.
- `collectWorkloadHealthStatus` returns the error and reconcile is aborted, or
  the error is silently discarded inside `GetStatus` — either way, an operator
  looking at the Application sees `healthy: false` with no explanation of why.

## Cleanup

```bash
kubectl -n default delete -f 20-app.yaml
kubectl -n vela-system delete -f 10-cd-broken.yaml
```
