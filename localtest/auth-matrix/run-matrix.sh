#!/usr/bin/env bash
# =============================================================================
# OCI Docker Hub auth matrix — runs all four variants in sequence and prints
# a pass/fail summary. Run on the Mac where your kubeconfig points at the k3d
# cluster ($KUBECONFIG or ~/.kube/master.yaml).
#
# Usage:
#   export PAT='dckr_pat_<rotated-pat>'      # required
#   export NS=arc-system                     # optional, default arc-system
#   bash run-matrix.sh
#
# Exit code 0 if variants 1-3 succeed AND variant 4 fails with the expected
# "auth secret … not found" error. Non-zero otherwise.
# =============================================================================
set -u
set -o pipefail

NS="${NS:-arc-system}"
TIMEOUT="${TIMEOUT:-90}"     # seconds to wait per variant
HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ -z "${PAT:-}" ]]; then
    echo "ERROR: PAT environment variable is not set." >&2
    echo "  export PAT='dckr_pat_<your-current-pat>'" >&2
    exit 2
fi

PAT_B64="$(printf '%s' "$PAT" | base64 | tr -d '\n')"

pass=0
fail=0

banner() {
    printf '\n\033[1;36m============================================================\033[0m\n'
    printf '\033[1;36m %s\033[0m\n' "$1"
    printf '\033[1;36m============================================================\033[0m\n'
}

wait_for_phase() {
    local app="$1"
    local want="$2"             # "succeeded" or "failed"
    local elapsed=0
    while (( elapsed < TIMEOUT )); do
        local phase
        phase="$(kubectl get application -n "$NS" "$app" \
            -o jsonpath='{.status.status}' 2>/dev/null || true)"
        case "$want" in
            succeeded) [[ "$phase" == "running" || "$phase" == "workflowFinished" ]] && return 0 ;;
            failed)    [[ "$phase" == "workflowTerminated" || "$phase" == "workflowSuspending" || "$phase" == "rendering" ]] && return 0 ;;
        esac
        sleep 3
        elapsed=$(( elapsed + 3 ))
    done
    return 1
}

dump_failure() {
    local app="$1"
    echo "--- describe ---"
    kubectl describe application -n "$NS" "$app" 2>/dev/null | tail -40
    echo "--- workflow steps ---"
    kubectl get application -n "$NS" "$app" \
        -o jsonpath='{range .status.workflow.steps[*]}{"  step="}{.name}{" phase="}{.phase}{" msg="}{.message}{"\n"}{end}' 2>/dev/null
}

cleanup() {
    banner "Cleanup"
    kubectl delete -n "$NS" application \
        oci-auth-basic-data oci-auth-dockerconfig oci-auth-opaque oci-auth-configmap-fail \
        --ignore-not-found 2>/dev/null || true
    kubectl delete -n "$NS" secret \
        dockerhub-creds-basic-data dockerhub-creds-dockerconfig dockerhub-creds-opaque \
        --ignore-not-found 2>/dev/null || true
    kubectl delete -n "$NS" configmap dockerhub-creds-cm --ignore-not-found 2>/dev/null || true
}
trap cleanup EXIT

# -----------------------------------------------------------------------------
banner "Pre-flight: cluster reachable?"
if ! kubectl version --client=false >/dev/null 2>&1; then
    echo "kubectl cannot reach the cluster. Check KUBECONFIG."
    exit 2
fi
kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create namespace "$NS"

# Clear any leftover Applications from previous runs
kubectl delete -n "$NS" application \
    oci-auth-basic-data oci-auth-dockerconfig oci-auth-opaque oci-auth-configmap-fail \
    --ignore-not-found >/dev/null 2>&1 || true
kubectl delete -n "$NS" secret \
    dockerhub-creds-basic-data dockerhub-creds-dockerconfig dockerhub-creds-opaque \
    --ignore-not-found >/dev/null 2>&1 || true
kubectl delete -n "$NS" configmap dockerhub-creds-cm --ignore-not-found >/dev/null 2>&1 || true

# -----------------------------------------------------------------------------
banner "Variant 1 — kubernetes.io/basic-auth Secret (data: base64)"
sed -e "s|<REPLACE_WITH_BASE64_PAT>|${PAT_B64}|" "$HERE/01-basic-auth-base64.yaml" \
    | kubectl apply -f -
if wait_for_phase oci-auth-basic-data succeeded; then
    echo "PASS: oci-auth-basic-data"
    pass=$(( pass + 1 ))
else
    echo "FAIL: oci-auth-basic-data did not reach a success phase within ${TIMEOUT}s"
    dump_failure oci-auth-basic-data
    fail=$(( fail + 1 ))
fi

# -----------------------------------------------------------------------------
banner "Variant 2 — kubernetes.io/dockerconfigjson Secret"
kubectl create secret docker-registry dockerhub-creds-dockerconfig \
    -n "$NS" \
    --docker-server=registry-1.docker.io \
    --docker-username=vishal210893 \
    --docker-password="$PAT" \
    --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$HERE/02-dockerconfigjson.yaml"
if wait_for_phase oci-auth-dockerconfig succeeded; then
    echo "PASS: oci-auth-dockerconfig"
    pass=$(( pass + 1 ))
else
    echo "FAIL: oci-auth-dockerconfig did not reach a success phase within ${TIMEOUT}s"
    dump_failure oci-auth-dockerconfig
    fail=$(( fail + 1 ))
fi

# -----------------------------------------------------------------------------
banner "Variant 3 — Opaque Secret"
sed -e "s|<REPLACE_WITH_BASE64_PAT>|${PAT_B64}|" "$HERE/03-opaque.yaml" \
    | kubectl apply -f -
if wait_for_phase oci-auth-opaque succeeded; then
    echo "PASS: oci-auth-opaque"
    pass=$(( pass + 1 ))
else
    echo "FAIL: oci-auth-opaque did not reach a success phase within ${TIMEOUT}s"
    dump_failure oci-auth-opaque
    fail=$(( fail + 1 ))
fi

# -----------------------------------------------------------------------------
banner "Variant 4 — ConfigMap (must fail with 'auth secret … not found')"
kubectl apply -f "$HERE/04-configmap-unsupported.yaml"
sleep 8

msg="$(kubectl get application -n "$NS" oci-auth-configmap-fail \
    -o jsonpath='{range .status.workflow.steps[*]}{.message}{"\n"}{end}' 2>/dev/null)"
echo "workflow message(s):"
printf '%s\n' "$msg"

if printf '%s' "$msg" | grep -qE 'auth secret .*not found'; then
    echo "PASS: oci-auth-configmap-fail (correctly rejected ConfigMap)"
    pass=$(( pass + 1 ))
else
    echo "FAIL: variant 4 did not surface the expected 'auth secret … not found' error"
    dump_failure oci-auth-configmap-fail
    fail=$(( fail + 1 ))
fi

# -----------------------------------------------------------------------------
banner "Summary"
printf 'pass=%d fail=%d\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
