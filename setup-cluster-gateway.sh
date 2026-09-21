#!/usr/bin/env bash

set -Eeuo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHART="${REPO_ROOT}/charts/vela-core"
TEMPLATES="${CHART}/templates"
BACKUP_ROOT=""
BACKUP_TEMPLATES=""
BACKUP_READY=false

restore_templates() {
  if [[ "$BACKUP_READY" == true && -d "$BACKUP_TEMPLATES" ]]; then
    echo "==> Restoring original Helm chart templates"
    rm -rf -- "$TEMPLATES"
    mv "$BACKUP_TEMPLATES" "$TEMPLATES"
  fi

  if [[ -n "$BACKUP_ROOT" && -d "$BACKUP_ROOT" ]]; then
    rm -rf -- "$BACKUP_ROOT"
  fi
}

trap restore_templates EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

require_command() {
  local command_name=$1
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "ERROR: Required command not found: ${command_name}" >&2
    exit 1
  }
}

if [[ ! -f "${REPO_ROOT}/Makefile" || ! -f "${REPO_ROOT}/go.mod" || ! -d "$TEMPLATES" ]]; then
  echo "ERROR: Could not locate the KubeVela repository files relative to this script." >&2
  exit 1
fi

require_command make
require_command helm
require_command kubectl

cd "$REPO_ROOT"

echo "==> Installing KubeVela CRDs"
make core-install

echo "==> Installing KubeVela definitions"
make def-install

echo "==> Backing up Helm chart templates"
BACKUP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/kubevela-cluster-gateway-backup.XXXXXX")
BACKUP_TEMPLATES="${BACKUP_ROOT}/templates"
cp -R "$TEMPLATES" "$BACKUP_TEMPLATES"
BACKUP_READY=true

echo "==> Removing templates not required by Cluster Gateway"
find "$TEMPLATES" -mindepth 1 -maxdepth 1 \
  ! -name 'cluster-gateway' \
  ! -name '_helpers.tpl' \
  ! -name 'kubevela-controller.yaml' \
  ! -name 'addon_registry.yaml' \
  ! -name 'NOTES.txt' \
  -exec rm -rf -- {} +

CONTROLLER_TEMPLATE="${TEMPLATES}/kubevela-controller.yaml"
deployment_line=$(awk '
  $0 == "apiVersion: apps/v1" {
    api_line = NR
    if ((getline next_line) > 0 && next_line == "kind: Deployment") {
      print api_line
      exit
    }
  }
' "$CONTROLLER_TEMPLATE")

if [[ -z "$deployment_line" ]] || (( deployment_line < 3 )); then
  echo "ERROR: Could not find the controller Deployment boundary in ${CONTROLLER_TEMPLATE}." >&2
  exit 1
fi

separator=$(sed -n "$((deployment_line - 1))p" "$CONTROLLER_TEMPLATE")
if [[ "$separator" != "---" ]]; then
  echo "ERROR: Expected a YAML separator before the controller Deployment." >&2
  exit 1
fi

RBAC_TEMPLATE="${CONTROLLER_TEMPLATE}.rbac"
awk -v deployment_line="$deployment_line" 'NR < deployment_line - 1' \
  "$CONTROLLER_TEMPLATE" >"$RBAC_TEMPLATE"
mv "$RBAC_TEMPLATE" "$CONTROLLER_TEMPLATE"

echo "==> Installing Cluster Gateway"
helm upgrade --install kubevela "$CHART" \
  --set devLogs=true \
  --set multicluster.clusterGateway.secureTLS.enabled=false \
  --create-namespace \
  --namespace vela-system \
  --wait \
  --debug

echo "==> Verifying Cluster Gateway"
kubectl rollout status deployment/kubevela-cluster-gateway \
  --namespace vela-system

echo "==> Cluster Gateway is ready"
