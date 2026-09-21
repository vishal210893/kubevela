# Addon-as-component: test plan for the last-applied-config RT-bloat fix

This is a hand-off document for an agent (Codex) to run the tests against a live
k3d cluster. Read all of it before running anything. The commands are copy-paste
ready. Do not skip the "How this environment works" section, or you will start a
second controller and corrupt the results.

---

## 1. What you are testing

The feature: an addon can be installed as a `type: addon` component inside a
normal Application, instead of via a dedicated Addon CR or `vela addon enable`.
The wrapping Application (`comp-<addon>`) renders the addon's own Application
(`addon-<addon>`) as its component `output`, plus the addon's definitions /
configmaps / secret as `outputs`. Both Applications are then reconciled by the
same controller.

The bug that was fixed: when the fluxcd addon is installed through the component
path, the child `addon-fluxcd` Application's ResourceTracker blew past the etcd
3 MB limit and the gRPC 2 MB limit, and the workflow ended in `workflowFailed`
with errors like:

```
failed to record resources (skip-gc) in resourcetracker addon-fluxcd-vela-system: Request entity too large: limit is 3145728
failed to record resources in resourcetracker addon-fluxcd-v1-vela-system: rpc error: code = ResourceExhausted desc = trying to send message larger than max (2429367 vs. 2097152)
```

Root cause: `comp-fluxcd` applies the inner `addon-fluxcd` Application through the
OAM applicator, which stamps a 249 KB `app.oam.dev/last-applied-configuration`
annotation (a full copy of the addon Application spec) onto `addon-fluxcd`. When
`addon-fluxcd` then renders its own child resources, KubeVela copies the parent
app's annotations onto every child (`filterAndSetAnnotations`,
`pkg/appfile/appfile.go`). The annotation strip list `DefaultFilterAnnots`
(`apis/types/types.go`) filtered the *kubectl* last-applied-config but not the
*oam* one, so every child resource inherited the 249 KB blob and the RT
overflowed.

The imperative path (`vela addon enable fluxcd`) never hit this because it creates
`addon-fluxcd` with a plain `client.Create` (`pkg/addon/addon.go` `createOrUpdate`),
which never adds the annotation.

The fix: one line in `apis/types/types.go` adds `oam.AnnotationLastAppliedConfig`
to `DefaultFilterAnnots`:

```go
var DefaultFilterAnnots = []string{
	oam.AnnotationInplaceUpgrade,
	oam.AnnotationFilterLabelKeys,
	oam.AnnotationFilterAnnotationKeys,
	oam.AnnotationLastAppliedConfiguration,
	oam.AnnotationLastAppliedConfig, // <-- the fix
}
```

You are confirming: (a) the fix makes the fluxcd component path succeed with no
compression gate, (b) the other addons still install, (c) the webhook still
rejects an incompatible addon, and (d) the RT no longer carries the 249 KB
annotation.

---

## 2. How this environment works (read this)

- The KubeVela controller (vela-core) is running in the developer's IDE on the
  host, built from the branch that contains the fix. It talks to the k3d cluster
  directly. It is running WITHOUT the `ZstdResourceTracker` / `ZstdApplicationRevision`
  feature gates, which is the point: the fix must work without compression.
- You (Codex) run only `kubectl` / `vela` commands against the same cluster. You
  do NOT start, stop, build, or restart vela-core. If you find yourself running
  `go build ./cmd/core` or launching `vela-core`, stop; that is the human's job in
  the IDE.
- If a test needs a controller change (it should not), report it and let the human
  rebuild in the IDE. Everything in this plan works against the already-running
  controller.

### Prerequisites to verify first

```bash
# Set this to the kubeconfig for the k3d cluster the IDE controller is using.
export KUBECONFIG="$HOME/.kube/master.yaml"   # adjust to your k3d kubeconfig

# 2.1 cluster reachable
kubectl get nodes

# 2.2 controller is actually reconciling (there should be a recent lease OR you
#     trust the IDE process). A quick liveness proxy: apply a trivial app later
#     and see it move. For now just confirm CRDs + the addon ComponentDefinition:
kubectl get crd applications.core.oam.dev resourcetrackers.core.oam.dev >/dev/null && echo "CRDs ok"
kubectl get componentdefinition addon -n vela-system && echo "addon ComponentDefinition installed"

# 2.3 addon registry configmap points at the official catalog
kubectl get cm vela-addon-registry -n vela-system -o jsonpath='{.data.registries}'; echo
```

If `componentdefinition addon` is missing, install it (the human normally does
this once):

```bash
vela def apply /workspaces/Open_Source/kubevela/vela-templates/definitions/internal/component/addon.cue -n vela-system
```

If the registry configmap is missing:

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: vela-addon-registry
  namespace: vela-system
data:
  registries: '{ "KubeVela":{ "name": "KubeVela", "helm": { "url": "https://kubevela.github.io/catalog/official" } } }'
EOF
```

### The RT-size inspection script

Write this helper once; several tests use it.

```bash
cat > /tmp/rtsize.py <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
mr = d.get("spec", {}).get("managedResources", [])
print("count:", len(mr))
tot = 0
for r in mr:
    raw = r.get("raw", {})
    b = len(json.dumps(raw))
    tot += b
    print("  %-28s %-48s rawBytes=%d" % (r.get("kind", "?"), r.get("name", "?"), b))
print("total raw bytes:", tot)
print("whole object bytes:", len(json.dumps(d)))
PY
```

---

## 3. Test A — full manual e2e: apply every addon fixture

This is the primary test and it mirrors exactly what a human does by hand: apply
each fixture in `localtest/addon-component/`, then watch both the wrapping app
(`comp-<addon>`) and the child app (`addon-<addon>`) until they reach `running`.
Do them one at a time and record each one's result.

### Fixture inventory

Apply every one of these. `FIX=/workspaces/Open_Source/kubevela/localtest/addon-component`.

| fixture | wrapping app | child app | kind under test | apply in Test |
|---------|--------------|-----------|-----------------|---------------|
| `fluxcd.yaml` | comp-fluxcd | addon-fluxcd | large CRDs (the RT-bloat regression) | A + B |
| `velaux.yaml` | comp-velaux | addon-velaux | k8s-objects + webservice | A |
| `dex.yaml` | comp-dex | addon-dex | helm-type addon | A |
| `kruise-rollout.yaml` | comp-kruise-rollout | addon-kruise-rollout | helm-type addon | A |
| `vela-workflow.yaml` | comp-vela-workflow | addon-vela-workflow | k8s-objects (CRD) | A |
| `webhook-reject.yaml` | comp-fluxcd-webhook | (none) | admission DENY (no skipVersionValidate) | E |
| `webhook-allow.yaml` | comp-fluxcd-webhook-allow | addon-fluxcd | admission ALLOW (skipVersionValidate) | E |

Do NOT apply `fluxcdapp.yaml`. It is a captured `kubectl get -o yaml` dump kept for
reference, not a fixture to apply.

### Reusable waiter

```bash
FIX=/workspaces/Open_Source/kubevela/localtest/addon-component

# wait_running <app-name> <max-seconds> : polls one Application to running/failed.
wait_running() {
  local app="$1" max="${2:-240}" i line ph
  for ((i=5; i<=max; i+=5)); do
    sleep 5
    line=$(kubectl get app "$app" -n vela-system --no-headers 2>/dev/null)
    echo "[$app ${i}s] $line"
    ph=$(echo "$line" | awk '{print $4}')
    [ "$ph" = "running" ] && { echo "PASS: $app running"; return 0; }
    [ "$ph" = "workflowFailed" ] && { echo "FAIL: $app workflowFailed"; return 1; }
  done
  echo "TIMEOUT: $app did not reach running in ${max}s"; return 1
}
```

### A.1 — Apply each addon fixture and verify both apps reach running

Run this block per addon. Capture the full output for every one (see §8).

```bash
# addon list: name  fixture  timeout
while read -r NAME FILE TMO; do
  echo "==================== $NAME ===================="
  kubectl apply -f "$FIX/$FILE"
  # child app appears shortly after the wrapping app dispatches its output
  wait_running "comp-$NAME"  "$TMO"
  wait_running "addon-$NAME" "$TMO"
  echo "---- final state for $NAME ----"
  kubectl get app "comp-$NAME" "addon-$NAME" -n vela-system 2>&1
  # on failure, dump the workflow step messages
  if [ "$(kubectl get app "addon-$NAME" -n vela-system -o jsonpath='{.status.status}' 2>/dev/null)" = "workflowFailed" ] \
     || [ "$(kubectl get app "comp-$NAME" -n vela-system -o jsonpath='{.status.status}' 2>/dev/null)" = "workflowFailed" ]; then
    kubectl get app "addon-$NAME" "comp-$NAME" -n vela-system \
      -o jsonpath='{range .items[*]}{.metadata.name}:{"\n"}{range .status.workflow.steps[*]}  {.name}={.phase} :: {.message}{"\n"}{end}{end}' 2>&1
  fi
done <<'ADDONS'
fluxcd fluxcd.yaml 300
velaux velaux.yaml 300
dex dex.yaml 240
kruise-rollout kruise-rollout.yaml 240
vela-workflow vela-workflow.yaml 240
ADDONS
```

### A.2 — Snapshot of everything

```bash
kubectl get app -n vela-system
kubectl get rt -n vela-system
```

Expected for A:
- Every `comp-<addon>` phase = `running`.
- Every `addon-<addon>` phase = `running` (NONE in `workflowFailed`).

Failure signals to capture verbatim:
- `Request entity too large` / `ResourceExhausted` on `addon-fluxcd` → the RT-bloat
  fix is NOT in the running controller, or it regressed.
- `addon renderer not initialized` on any app → the controller was built without
  the render service linked (see §8.5). Not a cluster problem; needs an IDE rebuild.

Reference numbers from a known-good run are in §8.6.

---

## 4. Test B — RT no longer carries the 249 KB annotation

This is the direct proof of the fix.

```bash
# B.1 three RTs exist: wrapper versioned, child root, child versioned
kubectl get rt | grep -E 'fluxcd|NAME'

# B.2 size the child root RT (holds Namespace + CRDs)
kubectl get rt addon-fluxcd-vela-system -o json > /tmp/rootrt.json
python3 /tmp/rtsize.py /tmp/rootrt.json

# B.3 size the child versioned RT (holds the workloads)
kubectl get rt addon-fluxcd-v1-vela-system -o json > /tmp/verrt.json
python3 /tmp/rtsize.py /tmp/verrt.json
```

Expected (approximate, will vary slightly by fluxcd version):
- Root RT: ~11 resources, total ~250 KB. The `Namespace flux-system` line must be
  UNDER ~1 KB (about 666 bytes). CRDs appear at their natural sizes (roughly
  11–58 KB each). Whole object well under 3 MB.
- Versioned RT: ~22 resources, total ~30 KB. Each Deployment ~2 KB, each
  ServiceAccount under 1 KB.

FAIL signal: any managed resource stored at ~269 KB, or the `Namespace flux-system`
line over ~200 KB. That means the annotation is still being inherited.

Optional explicit annotation check on the live child object (should be small):

```bash
kubectl get ns flux-system -o json \
  | python3 -c 'import json,sys; a=json.load(sys.stdin)["metadata"].get("annotations",{}); print("last-applied-config bytes:", len(a.get("app.oam.dev/last-applied-configuration","")))'
# expect a few hundred bytes, NOT ~249000
```

---

## 5. Test C — imperative path still works (control)

Confirms the fix did not change the imperative behavior. The imperative path does
its own in-cluster system-requirement check; since core runs against this cluster
it should pass, but if it complains about "system requirement", add
`--skip-version-validating`.

```bash
# C.1 remove the component-path apps first to avoid shared-resource contention
kubectl delete app comp-fluxcd addon-fluxcd -n vela-system --timeout=120s
kubectl get rt | grep -i fluxcd || echo "fluxcd RTs gone"

# C.2 imperative install
vela addon enable fluxcd --version 3.0.2 || vela addon enable fluxcd --version 3.0.2 --skip-version-validating

# C.3 wait for the addon app
for i in $(seq 1 36); do
  sleep 5
  line=$(kubectl get app addon-fluxcd -n vela-system --no-headers 2>/dev/null)
  echo "[$((i*5))s] $line"
  [ "$(echo "$line" | awk '{print $4}')" = "running" ] && { echo "PASS: imperative running"; break; }
done

# C.4 clean up before the next tests
vela addon disable fluxcd || kubectl delete app addon-fluxcd -n vela-system --timeout=120s
```

Expected: `addon-fluxcd` reaches `running`. (It always did; this only guards
against a regression from the annotation-filter change.)

---

## 6. Test D — folded into Test A

The other addons (velaux, dex, kruise-rollout, vela-workflow) are already applied
and verified in Test A.1. Because the `DefaultFilterAnnots` change is global, Test A
passing across all five addons IS the "nothing else broke" regression proof — no
separate step needed.

---

## 7. Test E — webhook accept AND reject

The Application validating webhook runs the addon compatibility check at admission.

**Precondition:** this only exercises admission if the IDE core was started with
`--use-webhook=true` and its serving certs are wired up. Confirm first:

```bash
kubectl get validatingwebhookconfiguration | grep -i kubevela || echo "NO webhook config — webhooks are OFF"
```

If webhooks are OFF, both fixtures below will simply be admitted (no admission
check runs). In that case do NOT report a failure — record "webhook OFF, admission
not exercised" and move on. The accept/reject contract can only be tested with
webhooks ON.

### E.1 — REJECT: no `skipVersionValidate`, incompatible environment → DENIED

`webhook-reject.yaml` is `comp-fluxcd-webhook`, a fluxcd addon component that omits
`skipVersionValidate`. When the running environment does not satisfy the addon's
SystemRequirements, admission must DENY the apply (the Application is never
created).

```bash
kubectl apply -f "$FIX/webhook-reject.yaml"; echo "exit=$?"
# EXPECT (webhooks ON): non-zero exit; stderr mentions the addon is incompatible /
#   does not meet system requirements. The object is NOT created:
kubectl get app comp-fluxcd-webhook -n vela-system 2>&1   # expect: NotFound
```

Capture the full stderr of the apply verbatim — the denial message is the
deliverable here.

Note: whether this actually denies depends on the running vela-core version vs the
fluxcd addon's SystemRequirements. If this environment happens to satisfy them, the
apply is (correctly) admitted; record the exit code and the resolved requirement so
the human can judge. A denial proves the check fires; an admit with a satisfied
environment is also correct.

### E.2 — ACCEPT: same addon WITH `skipVersionValidate: true` → ADMITTED

`webhook-allow.yaml` is `comp-fluxcd-webhook-allow`, the same fluxcd addon but with
`skipVersionValidate: true`, which tells the webhook to skip the compatibility
check entirely. It must always be admitted.

```bash
kubectl apply -f "$FIX/webhook-allow.yaml"; echo "exit=$?"
# EXPECT: exit=0, admitted. It then renders addon-fluxcd like Test A:
kubectl get app comp-fluxcd-webhook-allow addon-fluxcd -n vela-system 2>&1
wait_running comp-fluxcd-webhook-allow 300
wait_running addon-fluxcd 300
```

### E.3 — cleanup

```bash
kubectl delete app comp-fluxcd-webhook comp-fluxcd-webhook-allow -n vela-system --timeout=120s 2>/dev/null
```

Expected for E (webhooks ON): E.1 denied (or admitted-with-satisfied-env, recorded
either way), E.2 admitted and reaches `running`. Contract: the ONLY difference
between the two fixtures is `skipVersionValidate`, so a denied E.1 plus an admitted
E.2 proves the flag is honored at admission.

Expected: E.1 rejected, E.2 admitted. If both are admitted, webhooks are probably
off in the IDE core; note that rather than reporting a failure.

---

## 8. Reporting — capture EVERYTHING, do not summarize away detail

The whole point of this run is that a second agent (Claude) will analyze your raw
output to decide whether the fix is correct. So do not paraphrase, do not trim,
do not say "looks good". Capture the literal command output. If a command errors,
paste the full error, do not swallow it.

Write one results file and hand its full contents back:

```bash
RESULTS=/tmp/addon-component-test-results.md
: > "$RESULTS"   # truncate
```

For every step you run, append to `$RESULTS`: the exact command, its stdout+stderr,
and its exit code. A simple wrapper:

```bash
run() {
  echo "### \$ $*" >> "$RESULTS"
  { out=$("$@" 2>&1); rc=$?; } || true
  printf '%s\n' "$out" >> "$RESULTS"
  echo "(exit=$rc)" >> "$RESULTS"
  echo >> "$RESULTS"
}
# use as: run kubectl get app -n vela-system
# for pipelines/heredocs, just echo the command + output into $RESULTS manually.
```

### 8.1 Environment block (top of the results file)

Capture the ground truth about what was actually tested:

```bash
{
  echo "# Addon-component test results"
  echo "## Environment"
  echo "date: $(date -u +%FT%TZ)"
  echo "kubeconfig: $KUBECONFIG"
  echo "current-context: $(kubectl config current-context)"
  echo "server: $(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
  echo "k8s server version: $(kubectl version -o json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["serverVersion"]["gitVersion"])' 2>/dev/null)"
  echo "vela cli version: $(vela version 2>/dev/null | head -3 | tr '\n' ' ')"
  echo
  echo "## Is the fix present in the running controller?"
} >> "$RESULTS"
```

You cannot read the IDE process's source, so infer the fix indirectly and record
the inference:
- The controller Deployment may not exist (core runs in the IDE, out of cluster).
  Record `kubectl get deploy -n vela-system` output regardless.
- The behavioral proof IS Test A + Test B. State clearly in the results whether
  Test A passed and whether Test B shows the Namespace under 1 KB. If Test A fails
  with `Request entity too large`, explicitly write: "FIX NOT ACTIVE in running
  controller — ask the human to rebuild the IDE core from the fixed branch."

### 8.2 Per-test raw capture (required for each of A–E)

For each test, the results file must contain:
- the phase-polling log (every `[Ns] ...` line), not just the final state;
- the final `kubectl get app ... ` line for both the wrapper and child app of
  EVERY addon fixture (all five), not just fluxcd;
- for any Test A failure: the full `.status.workflow.steps[*]` message dump;
- for Test B: the COMPLETE `python3 /tmp/rtsize.py` output for BOTH RTs (every
  per-resource `rawBytes=` line, the totals, and the whole-object bytes), plus the
  `kubectl get rt | grep` listing and the `flux-system` Namespace annotation-byte
  check from section 4;
- for Test C: the imperative command used (with or without `--skip-version-validating`)
  and its polling log;
- for Test E: both exit codes and the full admission error text (or the note that
  webhooks are off).

Also dump both child RTs verbatim so Claude can re-inspect without you:

```bash
run kubectl get rt addon-fluxcd-vela-system -o yaml
run kubectl get rt addon-fluxcd-v1-vela-system -o yaml
run kubectl get app addon-fluxcd -n vela-system -o yaml
```

(These are large; keep them. Do not truncate.)

### 8.3 Result table (fill in real values, not "?")

One row per fixture, so nothing is glossed over.

| Test | Fixture | Expected | Observed (comp / child, secs) | Pass? |
|------|---------|----------|-------------------------------|-------|
| A | fluxcd.yaml | comp-fluxcd + addon-fluxcd `running` | | |
| A | velaux.yaml | comp-velaux + addon-velaux `running` | | |
| A | dex.yaml | comp-dex + addon-dex `running` | | |
| A | kruise-rollout.yaml | comp-kruise-rollout + addon-kruise-rollout `running` | | |
| A | vela-workflow.yaml | comp-vela-workflow + addon-vela-workflow `running` | | |
| B | (fluxcd RTs) | Namespace < 1 KB; root RT < 300 KB; no ~269 KB entries | | |
| C | (imperative) | addon-fluxcd `running` | | |
| E.1 | webhook-reject.yaml | DENIED (or admitted+env-satisfied; or webhook OFF) | | |
| E.2 | webhook-allow.yaml | ADMITTED, reaches `running` (or webhook OFF) | | |

### 8.4 Hand back

Return the ENTIRE contents of `$RESULTS` in your reply (do not attach a link, do
not summarize it — paste it). If it is very long, that is fine and expected;
completeness matters more than brevity here. End with a one-paragraph plain-English
read of what you saw, but the raw log above it is the deliverable.

## 8.5 Known failure mode: "addon renderer not initialized"

If any child `addon-<name>` app fails with a workflow-step message like:

```
function call error for _render: addon renderer not initialized
```

the running controller was built WITHOUT the addon render service linked. The
service registers itself via an `init()` that only runs when
`cmd/core/app/server.go` blank-imports it:

```go
_ "github.com/oam-dev/kubevela/pkg/addon/service" // register the addon CueX renderer
```

An IDE "optimize imports" pass can silently drop this blank import, and the next
build then ships a controller whose `api.DefaultRenderer()` is nil. This is NOT a
cluster problem and NOT something you (Codex) can fix from kubectl. Report it and
ask the human to: confirm the blank import is present in `server.go`, rebuild the
IDE core, restart it, then delete and re-apply the failed apps. Verify the fix is
in the binary before retrying:

```bash
# on the host, against the built binary:
go tool nm <vela-core-binary> | grep -c pkg/addon/service   # must be > 0
```

## 8.6 Verified reference run (for comparison)

A clean run on k3d (k8s v1.33, controller with NO feature gates, `--use-webhook=false`)
produced:

- fluxcd: `addon-fluxcd` running in ~18s; root RT `flux-system` Namespace = 661 B,
  root RT total ~252 KB (11 resources incl. CRDs), versioned RT ~30 KB (22 resources);
  zero `Request entity too large` / `ResourceExhausted` in the controller log.
- velaux, dex, kruise-rollout, vela-workflow: all `running` on both wrapper and
  child within ~60s.

If your numbers are in the same ballpark, the fix is working. A Namespace RT entry
near ~269 KB is the pre-fix signature and means the annotation is still leaking.

## 9. Full cleanup at the end

```bash
kubectl delete app -n vela-system -l '' --field-selector metadata.namespace=vela-system 2>/dev/null
# or explicitly:
kubectl delete app comp-fluxcd addon-fluxcd comp-velaux comp-dex comp-kruise-rollout comp-vela-workflow comp-fluxcd-webhook -n vela-system --timeout=180s 2>/dev/null
kubectl get rt | grep -iE 'fluxcd|velaux|dex|kruise|workflow' || echo "all addon RTs cleaned"
```

Do NOT delete the `addon` ComponentDefinition, the `vela-addon-registry`
configmap, the standard definitions, or any CRDs. Those are shared setup.
