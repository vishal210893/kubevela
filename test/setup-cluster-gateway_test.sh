#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT="${REPO_ROOT}/setup-cluster-gateway.sh"
TEMPLATES="${REPO_ROOT}/charts/vela-core/templates"
TEST_TMP=$(mktemp -d)
trap 'rm -rf "${TEST_TMP}"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

checksum_templates() {
  find "$TEMPLATES" -type f -exec shasum {} \; | sort | shasum | awk '{print $1}'
}

resource_exists() {
  local file=$1
  local expected_kind=$2
  local expected_name=$3
  awk -v expected_kind="$expected_kind" -v expected_name="$expected_name" '
    function matches() { return kind == expected_kind && name == expected_name }
    /^---$/ {
      if (matches()) found = 1
      kind = ""
      name = ""
      next
    }
    /^kind: / { kind = substr($0, 7) }
    /^  name: / && name == "" { name = substr($0, 9) }
    END { exit !(found || matches()) }
  ' "$file"
}

BIN_DIR="${TEST_TMP}/bin"
CALL_LOG="${TEST_TMP}/calls.log"
CHART_SNAPSHOT="${TEST_TMP}/chart-snapshot"
RENDERED_CHART="${TEST_TMP}/rendered-chart.yaml"
REAL_HELM=$(command -v helm)
mkdir -p "$BIN_DIR"
: >"$CALL_LOG"

cat >"${BIN_DIR}/make" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'make|%s|%s\n' "$PWD" "$*" >>"$CALL_LOG"
EOF

cat >"${BIN_DIR}/helm" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'helm|%s\n' "$*" >>"$CALL_LOG"
chart_path=$4
rm -rf "$CHART_SNAPSHOT"
cp -R "$chart_path" "$CHART_SNAPSHOT"
if [[ "${HELM_FAIL:-0}" == "1" ]]; then
  exit 42
fi
"$REAL_HELM" template kubevela "$chart_path" \
  --set devLogs=true \
  --namespace vela-system >"$RENDERED_CHART"
EOF

cat >"${BIN_DIR}/kubectl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'kubectl|%s\n' "$*" >>"$CALL_LOG"
EOF

chmod +x "${BIN_DIR}/make" "${BIN_DIR}/helm" "${BIN_DIR}/kubectl"

run_script() {
  PATH="${BIN_DIR}:$PATH" \
    CALL_LOG="$CALL_LOG" \
    CHART_SNAPSHOT="$CHART_SNAPSHOT" \
    RENDERED_CHART="$RENDERED_CHART" \
    REAL_HELM="$REAL_HELM" \
    HELM_FAIL="${HELM_FAIL:-0}" \
    "$SCRIPT"
}

before_checksum=$(checksum_templates)
run_script
after_checksum=$(checksum_templates)
[[ "$before_checksum" == "$after_checksum" ]] || fail "source templates were not restored after success"

expected_make_calls=$(cat <<EOF
make|${REPO_ROOT}|core-install
make|${REPO_ROOT}|def-install
EOF
)
actual_make_calls=$(grep '^make|' "$CALL_LOG")
[[ "$actual_make_calls" == "$expected_make_calls" ]] || fail "unexpected make calls: ${actual_make_calls}"

helm_call=$(grep '^helm|' "$CALL_LOG")
[[ "$helm_call" == *"upgrade --install kubevela ${REPO_ROOT}/charts/vela-core"* ]] || \
  fail "Helm did not install from the source chart: ${helm_call}"
[[ "$helm_call" == *"--set devLogs=true"* ]] || fail "devLogs value is missing"
[[ "$helm_call" == *"--set multicluster.clusterGateway.secureTLS.enabled=false"* ]] || \
  fail "local Cluster Gateway TLS override is missing"
[[ "$helm_call" == *"--namespace vela-system"* ]] || fail "namespace is missing"
[[ "$helm_call" == *"--wait"* ]] || fail "wait flag is missing"
[[ "$helm_call" == *"--debug"* ]] || fail "debug flag is missing"
grep -F "kubectl|rollout status deployment/kubevela-cluster-gateway --namespace vela-system" \
  "$CALL_LOG" >/dev/null || fail "Cluster Gateway rollout was not verified"

actual_templates=$(cd "${CHART_SNAPSHOT}/templates" && find . -mindepth 1 -maxdepth 1 -print | sort)
expected_templates=$(cat <<'EOF'
./NOTES.txt
./_helpers.tpl
./addon_registry.yaml
./cluster-gateway
./kubevela-controller.yaml
EOF
)
[[ "$actual_templates" == "$expected_templates" ]] || fail "unexpected pruned templates: ${actual_templates}"

controller_template="${CHART_SNAPSHOT}/templates/kubevela-controller.yaml"
grep -Fx "kind: ServiceAccount" "$controller_template" >/dev/null || fail "ServiceAccount RBAC is missing"
grep -Fx "kind: ClusterRoleBinding" "$controller_template" >/dev/null || fail "ClusterRoleBinding RBAC is missing"
if grep -Ex '^kind: (Deployment|Service|ServiceMonitor)$' "$controller_template" >/dev/null; then
  fail "controller workload or service remained in the pruned template"
fi
resource_exists "$RENDERED_CHART" "Deployment" "kubevela-cluster-gateway" || \
  fail "rendered chart does not contain the Cluster Gateway Deployment"
if resource_exists "$RENDERED_CHART" "Deployment" "kubevela-vela-core"; then
  fail "rendered chart contains the core controller Deployment"
fi

echo "PASS: prunes the source chart for installation and restores it after success"

: >"$CALL_LOG"
HELM_FAIL=1
export HELM_FAIL
set +e
run_script >"${TEST_TMP}/helm-failure.log" 2>&1
failure_status=$?
set -e

[[ "$failure_status" -eq 42 ]] || fail "expected Helm exit status 42, got ${failure_status}"
[[ "$before_checksum" == "$(checksum_templates)" ]] || fail "source templates were not restored after Helm failure"
if grep '^kubectl|' "$CALL_LOG" >/dev/null; then
  fail "kubectl verification ran after Helm failed"
fi

echo "PASS: restores the source chart and propagates a Helm failure"
