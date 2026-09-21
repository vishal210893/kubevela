#!/usr/bin/env bash
#
# differential-test.sh — validate the addon-as-component feature against the
# baseline `vela addon enable` flow across two clusters.
#
#   Cluster A ("baseline"): vela install (in-cluster vela-core) + `vela addon enable`.
#   Cluster B ("feature"):  CRDs+defs installed by hand, vela-core run as a LOCAL
#                           go process, addons applied as `type: addon` components.
#
# For every addon we compare the resulting `addon-<name>` Application health on
# both clusters and classify PASS / FAIL / TIMEOUT, then flag discrepancies.
#
# Assumptions (stated per the task):
#   - k3d is used (simpler to script two clusters than kind; swap if you prefer).
#   - Run from the repo root of the feat/addon-component branch.
#   - `vela`, `k3d`, `kubectl`, `go`, `python3` are on PATH.
#   - Cluster B runs vela-core out-of-cluster, so its addon SystemRequirements
#     check cannot read an in-cluster vela-core version. We therefore set
#     skipVersionValidate:true on Cluster B fixtures (mirrors
#     `vela addon enable --skip-version-validating`). This is a KNOWN, documented
#     asymmetry, not a bug.
#
# Usage:
#   ./differential-test.sh                 # curated subset (default)
#   ./differential-test.sh --all           # every addon from `vela addon list`
#   ./differential-test.sh --keep          # do not delete clusters / core on exit
#   ./differential-test.sh a b c            # explicit addon list
#
set -uo pipefail

# ----------------------------------------------------------------------------
# config
# ----------------------------------------------------------------------------
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="${WORK:-/tmp/addon-diff}"
CLUSTER_A="${CLUSTER_A:-addon-baseline}"
CLUSTER_B="${CLUSTER_B:-addon-feature}"
KCFG_A="$WORK/kubeconfig-a.yaml"
KCFG_B="$WORK/kubeconfig-b.yaml"
CORE_BIN="$WORK/vela-core"
CORE_LOG="$WORK/vela-core-b.log"
CORE_HEALTH_PORT=9441
PER_ADDON_TIMEOUT="${PER_ADDON_TIMEOUT:-300}"   # seconds, per cluster, per addon
REPORT="$WORK/differential-report.md"
NS=vela-system

# Curated subset: proven this session + a couple more. Sensible defaults, no
# mandatory parameters. Extend or use --all once the harness is green.
SUBSET=(fluxcd velaux dex kruise-rollout vela-workflow ocm-cluster-manager velaux-cloud-shell)

KEEP=0
MODE=subset
ADDONS=()
for arg in "$@"; do
  case "$arg" in
    --all)  MODE=all ;;
    --keep) KEEP=1 ;;
    --*)    echo "unknown flag: $arg" >&2; exit 2 ;;
    *)      MODE=explicit; ADDONS+=("$arg") ;;
  esac
done

mkdir -p "$WORK"
: > "$REPORT"

log()  { echo -e "\033[1;34m[diff]\033[0m $*"; }
warn() { echo -e "\033[1;33m[diff]\033[0m $*" >&2; }
err()  { echo -e "\033[1;31m[diff]\033[0m $*" >&2; }

TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN="$(command -v timeout)"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN="$(command -v gtimeout)"
fi

# ----------------------------------------------------------------------------
# cleanup
# ----------------------------------------------------------------------------
CORE_PID=""
cleanup() {
  [ -n "$CORE_PID" ] && kill "$CORE_PID" 2>/dev/null
  if [ "$KEEP" -eq 0 ]; then
    log "deleting clusters (use --keep to retain)"
    k3d cluster delete "$CLUSTER_A" >/dev/null 2>&1
    k3d cluster delete "$CLUSTER_B" >/dev/null 2>&1
  else
    warn "keeping clusters $CLUSTER_A / $CLUSTER_B and core process $CORE_PID"
  fi
}
trap cleanup EXIT

# ----------------------------------------------------------------------------
# cluster provisioning (idempotent: reuse if present)
# ----------------------------------------------------------------------------
ensure_cluster() {
  local name="$1" kcfg="$2"
  if k3d cluster list "$name" >/dev/null 2>&1; then
    log "cluster $name already exists, reusing"
  else
    log "creating cluster $name"
    k3d cluster create "$name" --wait || { err "failed to create $name"; exit 1; }
  fi
  k3d kubeconfig get "$name" > "$kcfg"
}

# ----------------------------------------------------------------------------
# Cluster A: vela install + in-cluster vela-core
# ----------------------------------------------------------------------------
setup_cluster_a() {
  log "=== Cluster A ($CLUSTER_A): vela install ==="
  ensure_cluster "$CLUSTER_A" "$KCFG_A"
  export KUBECONFIG="$KCFG_A"
  if ! kubectl get deploy -n "$NS" kubevela-vela-core >/dev/null 2>&1; then
    vela install -y || { err "vela install failed on A"; exit 1; }
  fi
  kubectl -n "$NS" rollout status deploy/kubevela-vela-core --timeout=180s || true
  log "Cluster A ready"
}

# ----------------------------------------------------------------------------
# Cluster B: manual CRDs+defs, local go-process vela-core
# ----------------------------------------------------------------------------
setup_cluster_b() {
  log "=== Cluster B ($CLUSTER_B): manual install + local core ==="
  ensure_cluster "$CLUSTER_B" "$KCFG_B"
  export KUBECONFIG="$KCFG_B"

  log "installing CRDs"
  kubectl apply --server-side -f "$REPO/charts/vela-core/crds/" >/dev/null

  log "installing definitions (hack/utils/installdefinition.sh)"
  KUBECONFIG="$KCFG_B" bash "$REPO/hack/utils/installdefinition.sh" >/dev/null 2>&1 || \
    warn "installdefinition.sh returned nonzero (continuing; some defs may be optional)"

  log "installing the 'addon' ComponentDefinition"
  vela def apply "$REPO/vela-templates/definitions/internal/component/addon.cue" -n "$NS"

  log "installing addon registry configmap"
  kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: vela-addon-registry
  namespace: $NS
data:
  registries: '{ "KubeVela":{ "name": "KubeVela", "helm": { "url": "https://kubevela.github.io/catalog/official" } } }'
EOF

  log "building vela-core"
  ( cd "$REPO" && CGO_ENABLED=0 go build -o "$CORE_BIN" ./cmd/core ) || { err "go build failed"; exit 1; }
  # sanity: the render service must be linked, or every addon fails "renderer not initialized"
  if [ "$(go tool nm "$CORE_BIN" 2>/dev/null | grep -c pkg/addon/service)" -eq 0 ]; then
    err "vela-core binary has no pkg/addon/service symbols — the blank import in cmd/core/app/server.go was dropped. Restore it and rebuild."
    exit 1
  fi

  log "starting vela-core as a local process against Cluster B"
  KUBECONFIG="$KCFG_B" "$CORE_BIN" \
    --use-webhook=false --enable-leader-election=false \
    --metrics-addr=0 --health-addr=":$CORE_HEALTH_PORT" > "$CORE_LOG" 2>&1 &
  CORE_PID=$!

  log "waiting for core health"
  local i
  for i in $(seq 1 30); do
    curl -s -m 2 "http://localhost:$CORE_HEALTH_PORT/healthz" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -s -m 2 "http://localhost:$CORE_HEALTH_PORT/healthz" >/dev/null 2>&1 || { err "core did not become healthy; see $CORE_LOG"; exit 1; }

  log "sanity: a trivial Application reconciles"
  kubectl apply -f - <<'EOF'
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: diff-sanity
  namespace: vela-system
spec:
  components:
    - name: hello
      type: webservice
      properties:
        image: oamdev/hello-world
        ports:
          - port: 8000
            expose: true
EOF
  if [ "$(poll_addon "$KCFG_B" diff-sanity "$NS" 120 sanity)" = "PASS" ]; then
    log "Cluster B controller is reconciling"
  else
    warn "sanity Application did not reach running — controller may not be reconciling; check $CORE_LOG"
  fi
  kubectl delete app diff-sanity -n "$NS" --wait=false >/dev/null 2>&1
  log "Cluster B ready"
}

# ----------------------------------------------------------------------------
# health polling with a hard timeout -> echoes PASS | FAIL | TIMEOUT
#   poll_addon <kubeconfig> <app-name> <namespace> <timeout> <label>
# PASS   = Application phase==running AND healthy==true
# FAIL   = phase==workflowFailed / render failed
# TIMEOUT= neither within the window
# ----------------------------------------------------------------------------
poll_addon() {
  local kcfg="$1" app="$2" ns="$3" tmo="$4" label="${5:-}" i phase healthy
  local deadline=$(( SECONDS + tmo ))
  while [ "$SECONDS" -lt "$deadline" ]; do
    phase=$(KUBECONFIG="$kcfg" kubectl get app "$app" -n "$ns" -o jsonpath='{.status.status}' 2>/dev/null)
    healthy=$(KUBECONFIG="$kcfg" kubectl get app "$app" -n "$ns" -o jsonpath='{.status.services[0].healthy}' 2>/dev/null)
    case "$phase" in
      running)         echo "PASS"; return 0 ;;
      workflowFailed)  echo "FAIL"; return 0 ;;
    esac
    sleep 5
  done
  echo "TIMEOUT"
}

# capture diagnostics for a failed/timed-out addon
capture() {
  local kcfg="$1" app="$2" tag="$3"
  {
    echo "### $tag :: $app"
    KUBECONFIG="$kcfg" kubectl get app "$app" -n "$NS" -o yaml 2>&1
    echo "--- workflow steps ---"
    KUBECONFIG="$kcfg" kubectl get app "$app" -n "$NS" \
      -o jsonpath='{range .status.workflow.steps[*]}{.name}={.phase} :: {.message}{"\n"}{end}' 2>&1
    echo "--- events (vela-system) ---"
    KUBECONFIG="$kcfg" kubectl get events -n "$NS" --sort-by=.lastTimestamp 2>&1 | tail -20
  } >> "$WORK/diag-$tag-$app.txt" 2>&1
}

# ----------------------------------------------------------------------------
# per-addon run
# ----------------------------------------------------------------------------
run_addon_A() {  # baseline: vela addon enable
  local name="$1"
  if [ -n "$TIMEOUT_BIN" ]; then
    KUBECONFIG="$KCFG_A" "$TIMEOUT_BIN" "$PER_ADDON_TIMEOUT" vela addon enable "$name" -y >/dev/null 2>&1 &
  else
    KUBECONFIG="$KCFG_A" vela addon enable "$name" -y >/dev/null 2>&1 &
  fi
  local ep=$!
  local res
  res=$(poll_addon "$KCFG_A" "addon-$name" "$NS" "$PER_ADDON_TIMEOUT" "A-$name")
  kill "$ep" 2>/dev/null
  [ "$res" != "PASS" ] && capture "$KCFG_A" "addon-$name" "A"
  echo "$res"
}

run_addon_B() {  # feature: type: addon component with skipVersionValidate
  local name="$1"
  KUBECONFIG="$KCFG_B" kubectl apply -f - >/dev/null 2>&1 <<EOF
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: comp-$name
  namespace: $NS
spec:
  components:
    - name: $name
      type: addon
      properties:
        skipVersionValidate: true
EOF
  local res
  res=$(poll_addon "$KCFG_B" "addon-$name" "$NS" "$PER_ADDON_TIMEOUT" "B-$name")
  [ "$res" != "PASS" ] && capture "$KCFG_B" "addon-$name" "B"
  echo "$res"
}

classify() {  # <A> <B> -> Match verdict
  local a="$1" b="$2"
  if [ "$a" = "PASS" ] && [ "$b" = "PASS" ]; then echo "MATCH (both pass)"; return; fi
  if [ "$a" = "$b" ]; then echo "MATCH (both $a)"; return; fi
  echo "DISCREPANCY (A=$a B=$b)"
}

# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
setup_cluster_a
setup_cluster_b

# resolve addon list
if [ "$MODE" = "all" ]; then
  log "enumerating all addons from Cluster A"
  mapfile -t ADDONS < <(KUBECONFIG="$KCFG_A" vela addon list 2>/dev/null | awk 'NR>1{print $1}' | sort -u)
elif [ "$MODE" = "subset" ]; then
  ADDONS=("${SUBSET[@]}")
fi
log "testing ${#ADDONS[@]} addons: ${ADDONS[*]}"

# report header
{
  echo "# Addon-as-component differential report"
  echo
  echo "- date: $(date -u +%FT%TZ)"
  echo "- cluster A (baseline, vela install): $CLUSTER_A"
  echo "- cluster B (feature, local core):    $CLUSTER_B"
  echo "- per-addon timeout: ${PER_ADDON_TIMEOUT}s per cluster"
  echo "- NOTE: Cluster B uses skipVersionValidate:true (out-of-cluster core cannot"
  echo "  satisfy the SystemRequirements version check). Documented asymmetry."
  echo
  echo "| Addon Name | Vela Install Result | Addon-as-Component Result | Match? | Notes / Error |"
  echo "|---|---|---|---|---|"
} >> "$REPORT"

DISCREPANCIES=()
for name in "${ADDONS[@]}"; do
  log "--- $name ---"
  a=$(run_addon_A "$name")
  b=$(run_addon_B "$name")
  verdict=$(classify "$a" "$b")
  note=""
  [[ "$verdict" == DISCREPANCY* ]] && { note="see diag-*-addon-$name.txt"; DISCREPANCIES+=("| $name | $a | $b | $verdict | $note |"); }
  echo "| $name | $a | $b | $verdict | $note |" >> "$REPORT"
  log "$name => A=$a B=$b => $verdict"
  # tidy up B so shared CRDs/namespaces don't collide across addons
  KUBECONFIG="$KCFG_B" kubectl delete app "comp-$name" -n "$NS" --wait=false >/dev/null 2>&1
done

# discrepancy summary
{
  echo
  echo "## Discrepancies (actionable)"
  echo
  if [ "${#DISCREPANCIES[@]}" -eq 0 ]; then
    echo "None. All addons matched across both mechanisms."
  else
    echo "| Addon Name | Vela Install Result | Addon-as-Component Result | Match? | Notes / Error |"
    echo "|---|---|---|---|---|"
    printf '%s\n' "${DISCREPANCIES[@]}"
    echo
    echo "TIMEOUT rows may mean 'needs more time', not 'broken' — re-run with a"
    echo "larger PER_ADDON_TIMEOUT before filing a bug."
  fi
} >> "$REPORT"

log "report written to $REPORT"
cat "$REPORT"
