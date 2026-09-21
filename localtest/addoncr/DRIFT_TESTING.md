# Manual testing: addon drift detection (KEP-2.13)

Verifies that the addon controller heals its managed resources from the
addon-owned ResourceTracker, with no registry fetch, when a resource is deleted
or edited. Two scenarios: deleting an auxiliary (a ComponentDefinition) and
deleting the owned Application.

All commands assume `KUBECONFIG` points at your test cluster. Run them from the
repo root.

## 0. Prerequisites (one-time setup)

The drift test uses the `example` addon, which only exists in the local mock
registry, so start the mock and point the registry at it.

```bash
export KUBECONFIG=~/.kube/your-test-cluster.yaml   # adjust

# 1. Start the mock addon registry (serves the "example" addon on :9098).
#    It also writes the vela-addon-registry ConfigMap pointing "KubeVela" at itself.
CGO_ENABLED=0 go run ./e2e/addon/mock &            # background; logs to your shell

# 2. Start vela-core with the AddonCRD gate on (out-of-cluster run).
CGO_ENABLED=0 go run ./cmd/core \
  --use-webhook=false --enable-leader-election=false \
  --metrics-addr=0 --health-addr=:9441 --feature-gates=AddonCRD=true &

# 3. Confirm both are up.
curl -s -o /dev/null -w 'core=%{http_code}\n' localhost:9441/healthz
curl -s -o /dev/null -w 'mock=%{http_code}\n' http://127.0.0.1:9098/example/metadata.yaml
kubectl get cm vela-addon-registry -n vela-system -o jsonpath='{.data.registries}'; echo
```

Note: `CGO_ENABLED=0` is only needed in dev containers where the cgo linker is
unavailable; drop it otherwise.

## 1. Install the addon and confirm the drift tracker

```bash
kubectl apply -f localtest/addoncr/example-drift.yaml

# Wait for running.
kubectl wait --for=jsonpath='{.status.phase}'=running addon/example --timeout=180s

# The addon-owned drift ResourceTracker records the Application, the
# helm-example ComponentDefinition, and the args Secret.
kubectl get resourcetracker addon-example-drift \
  -o jsonpath='{range .spec.managedResources[*]}{.kind}/{.name}{"\n"}{end}'
```

Expected: `addon-example-drift` exists and lists
`Application/addon-example`, `ComponentDefinition/helm-example`,
`Secret/addon-secret-example`. Its owner is `Addon/example`.

## 2. Scenario A — delete an auxiliary (ComponentDefinition)

The controller only watches `Addon` objects, so deleting a definition does not
trigger a reconcile on its own; the periodic resync (5 min) would heal it. To
see it immediately, nudge the Addon CR (any metadata change forces a reconcile).

```bash
kubectl delete componentdefinition helm-example -n vela-system

# Nudge the addon to trigger an immediate reconcile.
kubectl annotate addon example drift.test/nudge="$(date +%s)" --overwrite

# It comes back within a couple of seconds.
kubectl get componentdefinition helm-example -n vela-system
```

Expected: `helm-example` is recreated. In the vela-core log you will see
`apply.go ... "creating object" name="helm-example"` and NO registry fetch for
the example addon (the manifest came from the tracker, not the network).

## 3. Scenario B — delete the owned Application

```bash
kubectl delete application addon-example -n vela-system

# Nudge a few times while the old app finishes terminating and is recreated.
for i in $(seq 1 12); do
  kubectl annotate addon example drift.test/nudge="$(date +%s%N)" --overwrite >/dev/null
  printf 't=%ss app=%s helmDef=%s\n' "$((i*4))" \
    "$(kubectl get app addon-example -n vela-system -o jsonpath='{.status.status}' 2>/dev/null || echo MISSING)" \
    "$(kubectl get componentdefinition helm-example -n vela-system -o jsonpath='{.metadata.name}' 2>/dev/null || echo MISSING)"
  sleep 4
done
```

Expected: the Application goes `deleting` then `rendering` then `running`, and
`helm-example` stays present the whole time (it is re-applied from the tracker
with its owner-reference re-stamped to the recreated Application's UID, so it is
not garbage-collected). Both the Application and its auxiliaries are healed.

## 4. (Optional) Confirm no registry fetch on heal

```bash
# In the vela-core log, the heal path re-applies from the tracker. You should
# NOT see addon package fetches (ErrFetch / "fetch addon") around the nudges,
# only "creating object" / "patching object" apply lines.
grep -E 'helm-example|addon-example' <vela-core-log> | grep -E 'creating object|patching object' | tail
```

## 5. Cleanup

```bash
kubectl delete -f localtest/addoncr/example-drift.yaml
# Deleting the Addon CR cascades to the addon-example-drift ResourceTracker
# (owner reference) and, via the Protect deletion policy, to the owned Application.
```

## How it works (one paragraph)

On a steady-state reconcile (tracker present, version unchanged), the controller
skips the network install and calls `healFromTracker`
(`pkg/controller/core.oam.dev/v1beta1/addon/tracker.go`). It re-applies each
manifest stored in `addon-example-drift` through the standard applicator, which
three-way-merges against the live object: a deleted resource is recreated, an
edited one is patched back, an unchanged one no-ops. The owning Application is
applied first so auxiliaries can re-stamp their owner-reference UID. The network
`install()` runs only on a complete miss (no tracker) or a `spec.version` change.
