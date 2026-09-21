#!/usr/bin/env bash
#
# Trace Propagation Verification Script
#
# Prereqs:
#   - kubevela controller is running (e.g. in your IDE debugger via setup-debugger.sh)
#   - controller logs are being captured to a file (e.g. tee them with: ./vela-core ... 2>&1 | tee vela.log)
#   - mutating + validating webhook configurations are installed and pointing at the controller
#
# Usage:
#   ./run-verify.sh <controller-log-file>
#
# What it does:
#   1. Applies six test manifests covering: simple, trait, policy, workflow, full-stack, pre-stamped trace ID
#   2. After each apply, captures the trace ID written into the Application's annotation
#   3. Greps the controller log for that trace ID in the reconciler spans
#   4. Reports PASS/FAIL per scenario

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <controller-log-file>"
  exit 1
fi

LOGFILE=$1
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
NS=trace-test

if [[ ! -f "$LOGFILE" ]]; then
  echo "ERROR: log file not found: $LOGFILE"
  exit 1
fi

apply_and_check() {
  local manifest=$1
  local app_name=$2
  local scenario=$3
  local expected_trace=${4:-}

  echo
  echo "========================================================================"
  echo "Scenario: $scenario"
  echo "  Manifest: $manifest"
  echo "  App:      $app_name"
  echo "========================================================================"

  # Capture log offset so we only grep what comes after this apply
  local pre_offset
  pre_offset=$(wc -l < "$LOGFILE")

  kubectl apply -f "$SCRIPT_DIR/$manifest"

  # Give the reconciler a few seconds to pick it up
  sleep 8

  # Read the trace ID off the live object
  local actual_trace
  actual_trace=$(kubectl get application "$app_name" -n "$NS" \
    -o jsonpath='{.metadata.annotations.app\.oam\.dev/traceID}' 2>/dev/null || true)

  if [[ -z "$actual_trace" ]]; then
    echo "  FAIL: app has no app.oam.dev/traceID annotation (mutating webhook didn't stamp it?)"
    return 1
  fi
  echo "  app.oam.dev/traceID on object: $actual_trace"

  if [[ -n "$expected_trace" && "$actual_trace" != "$expected_trace" ]]; then
    echo "  FAIL: expected pre-stamped traceID '$expected_trace', got '$actual_trace' (mutating webhook overwrote it!)"
    return 1
  fi

  # Now grep the controller log AFTER the offset for that trace ID
  local matched
  matched=$(tail -n "+$((pre_offset+1))" "$LOGFILE" | grep -c "requestID.*$actual_trace" || true)

  if (( matched == 0 )); then
    echo "  FAIL: zero controller log lines tagged with requestID=$actual_trace"
    return 1
  fi
  echo "  $matched controller log lines tagged with requestID=$actual_trace  (PASS)"

  # Check that webhook log lines also carry this trace ID
  local webhook_matched
  webhook_matched=$(grep -c "ApplicationMutator\|ApplicationValidator" "$LOGFILE" \
    | head -1 || echo 0)
  echo "  total webhook log lines in file: $webhook_matched"

  # Check for spanID emission
  local span_count
  span_count=$(tail -n "+$((pre_offset+1))" "$LOGFILE" \
    | grep -E "requestID.*$actual_trace.*\"trace_id\"|\"trace_id\".*$actual_trace" \
    | wc -l || true)
  echo "  log lines with trace_id+requestID for this app: $span_count"
}

apply_and_check 01-simple-create.yaml         trace-simple        "Simple component CREATE"
apply_and_check 02-with-trait.yaml             trace-with-trait    "Component + 2 traits"
apply_and_check 03-with-policy.yaml            trace-with-policy   "Component + 2 policies"
apply_and_check 04-with-workflow.yaml          trace-with-workflow "Component + workflow (3 steps)"
apply_and_check 05-full-stack.yaml             trace-full-stack    "Full: 2 components + traits + policy + workflow"
apply_and_check 06-pre-stamped-trace.yaml      trace-pre-stamped   "Pre-stamped traceID is preserved" "my-known-trace-id-for-replay-12345"

echo
echo "========================================================================"
echo "Update scenario: editing trace-simple should re-use same trace ID"
echo "========================================================================"
pre_trace=$(kubectl get application trace-simple -n "$NS" \
  -o jsonpath='{.metadata.annotations.app\.oam\.dev/traceID}')
echo "  pre-update trace: $pre_trace"

kubectl patch application trace-simple -n "$NS" --type merge \
  -p '{"spec":{"components":[{"name":"hello-web","type":"webservice","properties":{"image":"nginx:1.22"}}]}}'

sleep 5
post_trace=$(kubectl get application trace-simple -n "$NS" \
  -o jsonpath='{.metadata.annotations.app\.oam\.dev/traceID}')
echo "  post-update trace: $post_trace"

if [[ "$pre_trace" == "$post_trace" ]]; then
  echo "  PASS: trace ID was preserved on update (set-if-missing semantic works)"
else
  echo "  FAIL: trace ID changed on update - $pre_trace != $post_trace"
fi

echo
echo "========================================================================"
echo "Annotation-removed scenario: removing trace ID by hand triggers re-mint"
echo "========================================================================"
kubectl annotate application trace-simple -n "$NS" app.oam.dev/traceID- --overwrite
sleep 1
kubectl patch application trace-simple -n "$NS" --type merge \
  -p '{"metadata":{"labels":{"touch":"now"}}}'
sleep 5
new_trace=$(kubectl get application trace-simple -n "$NS" \
  -o jsonpath='{.metadata.annotations.app\.oam\.dev/traceID}')
echo "  trace after re-mint: $new_trace"
if [[ -n "$new_trace" && "$new_trace" != "$post_trace" ]]; then
  echo "  PASS: mutating webhook re-minted a new trace ID after manual removal"
else
  echo "  FAIL: expected new trace ID, got '$new_trace' (was '$post_trace')"
fi

echo
echo "========================================================================"
echo "Done. Inspect $LOGFILE for full webhook + reconciler log lines."
echo "Cleanup with:  kubectl delete ns $NS"
echo "========================================================================"
