#!/usr/bin/env bash
# Create a clean KubeVela multi-cluster lab on k3d.
#
# This script deletes all existing k3d clusters, creates a master and slave
# cluster, installs KubeVela only on master, patches both kubeconfigs for
# cross-cluster access, joins slave into master, and verifies readiness.
#
# Usage:
#   bash localtest/multicluster/setup-k3d-multicluster.sh
#
# Optional environment variables:
#   MASTER_NAME=master
#   SLAVE_NAME=slave
#   KUBECONFIG_DIR="$HOME/.kube"
#   HOST_ADDRESS=192.168.1.10
#   VELA_BIN=./bin/vela
#   VELA_INSTALL_TIMEOUT=300s
#   CLUSTER_READY_TIMEOUT=120s

set -euo pipefail

MASTER_NAME="${MASTER_NAME:-master}"
SLAVE_NAME="${SLAVE_NAME:-slave}"
KUBECONFIG_DIR="${KUBECONFIG_DIR:-$HOME/.kube}"
MASTER_KUBECONFIG="${MASTER_KUBECONFIG:-$KUBECONFIG_DIR/$MASTER_NAME.yaml}"
SLAVE_KUBECONFIG="${SLAVE_KUBECONFIG:-$KUBECONFIG_DIR/$SLAVE_NAME.yaml}"
VELA_INSTALL_TIMEOUT="${VELA_INSTALL_TIMEOUT:-300s}"
CLUSTER_READY_TIMEOUT="${CLUSTER_READY_TIMEOUT:-120s}"

if [[ -x "${VELA_BIN:-}" ]]; then
    VELA="${VELA_BIN}"
elif [[ -x "./bin/vela" ]]; then
    VELA="./bin/vela"
else
    VELA="vela"
fi

info() {
    printf '\033[1;34m==>\033[0m %s\n' "$*"
}

warn() {
    printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2
}

die() {
    printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "$1 is required but was not found in PATH"
}

detect_host_address() {
    if [[ -n "${HOST_ADDRESS:-}" ]]; then
        printf '%s\n' "$HOST_ADDRESS"
        return
    fi

    if [[ "$(uname -s)" == "Darwin" ]]; then
        ipconfig getifaddr en0 2>/dev/null && return
        ipconfig getifaddr en1 2>/dev/null && return
    fi

    if command -v ip >/dev/null 2>&1; then
        ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i == "src") {print $(i+1); exit}}' && return
    fi

    die "could not detect host address; set HOST_ADDRESS explicitly"
}

delete_existing_k3d_clusters() {
    info "Deleting all existing k3d clusters"
    local clusters
    clusters="$(k3d cluster list --no-headers 2>/dev/null | awk '{print $1}' || true)"

    if [[ -z "$clusters" ]]; then
        info "No existing k3d clusters found"
        return
    fi

    while IFS= read -r cluster; do
        [[ -z "$cluster" ]] && continue
        info "Deleting k3d cluster: $cluster"
        k3d cluster delete "$cluster"
    done <<< "$clusters"
}

wait_for_cluster() {
    local kubeconfig="$1"
    local name="$2"

    info "Waiting for $name API server and nodes"
    KUBECONFIG="$kubeconfig" kubectl wait \
        --for=condition=Ready nodes --all \
        --timeout="$CLUSTER_READY_TIMEOUT"
}

api_port_from_kubeconfig() {
    local kubeconfig="$1"
    local server

    server="$(kubectl --kubeconfig "$kubeconfig" config view --raw -o jsonpath='{.clusters[0].cluster.server}')"
    printf '%s\n' "$server" | sed -E 's#^https://[^:/]+:([0-9]+).*$#\1#'
}

cluster_entry_from_kubeconfig() {
    local kubeconfig="$1"
    kubectl --kubeconfig "$kubeconfig" config view --raw -o jsonpath='{.clusters[0].name}'
}

patch_kubeconfig_server() {
    local kubeconfig="$1"
    local cluster_name="$2"
    local host_address="$3"
    local port="$4"

    info "Patching $kubeconfig server to https://$host_address:$port"
    kubectl --kubeconfig "$kubeconfig" config set-cluster "$cluster_name" \
        --server="https://$host_address:$port" \
        --insecure-skip-tls-verify=true >/dev/null

    kubectl --kubeconfig "$kubeconfig" config unset "clusters.$cluster_name.certificate-authority-data" >/dev/null 2>&1 || true
    kubectl --kubeconfig "$kubeconfig" config unset "clusters.$cluster_name.certificate-authority" >/dev/null 2>&1 || true
}

install_vela_on_master() {
    info "Installing KubeVela on master"
    KUBECONFIG="$MASTER_KUBECONFIG" "$VELA" install

    info "Waiting for KubeVela deployments to become available"
    KUBECONFIG="$MASTER_KUBECONFIG" kubectl wait deployment -n vela-system \
        --all \
        --for=condition=Available \
        --timeout="$VELA_INSTALL_TIMEOUT"

    KUBECONFIG="$MASTER_KUBECONFIG" kubectl wait pod -n vela-system \
        --all \
        --for=condition=Ready \
        --timeout="$VELA_INSTALL_TIMEOUT"
}

join_slave_to_master() {
    info "Joining slave cluster into master"
    KUBECONFIG="$MASTER_KUBECONFIG" "$VELA" cluster join "$SLAVE_KUBECONFIG"

    info "Waiting for joined cluster to be accepted"
    local deadline=$((SECONDS + 180))
    local status=""
    local joined_cluster_name="k3d-$SLAVE_NAME"

    while (( SECONDS < deadline )); do
        status="$(KUBECONFIG="$MASTER_KUBECONFIG" "$VELA" cluster list 2>/dev/null || true)"
        printf '%s\n' "$status"

        if printf '%s\n' "$status" | awk -v name="$joined_cluster_name" '$1 == name && $0 ~ /true/ {found=1} END {exit found ? 0 : 1}'; then
            return
        fi

        sleep 5
    done

    die "slave cluster was not accepted within 180s"
}

main() {
    require_cmd k3d
    require_cmd kubectl
    require_cmd "$VELA"

    mkdir -p "$KUBECONFIG_DIR"

    info "Removing old generated kubeconfigs"
    rm -f "$MASTER_KUBECONFIG" "$SLAVE_KUBECONFIG"

    delete_existing_k3d_clusters

    info "Creating master cluster: $MASTER_NAME"
    k3d cluster create "$MASTER_NAME"
    k3d kubeconfig get "$MASTER_NAME" > "$MASTER_KUBECONFIG"

    info "Creating slave cluster: $SLAVE_NAME"
    k3d cluster create "$SLAVE_NAME"
    k3d kubeconfig get "$SLAVE_NAME" > "$SLAVE_KUBECONFIG"

    local master_port slave_port host_address master_cluster_entry slave_cluster_entry
    master_port="$(api_port_from_kubeconfig "$MASTER_KUBECONFIG")"
    slave_port="$(api_port_from_kubeconfig "$SLAVE_KUBECONFIG")"
    host_address="$(detect_host_address)"
    master_cluster_entry="$(cluster_entry_from_kubeconfig "$MASTER_KUBECONFIG")"
    slave_cluster_entry="$(cluster_entry_from_kubeconfig "$SLAVE_KUBECONFIG")"

    patch_kubeconfig_server "$MASTER_KUBECONFIG" "$master_cluster_entry" "$host_address" "$master_port"
    patch_kubeconfig_server "$SLAVE_KUBECONFIG" "$slave_cluster_entry" "$host_address" "$slave_port"

    wait_for_cluster "$MASTER_KUBECONFIG" "$MASTER_NAME"
    wait_for_cluster "$SLAVE_KUBECONFIG" "$SLAVE_NAME"

    install_vela_on_master
    join_slave_to_master

    info "Sanity checking slave kubeconfig"
    KUBECONFIG="$SLAVE_KUBECONFIG" kubectl get ns

    cat <<EOF

Done.

Master kubeconfig: $MASTER_KUBECONFIG
Slave kubeconfig:  $SLAVE_KUBECONFIG

Use:
  export KUBECONFIG=$MASTER_KUBECONFIG
  $VELA cluster list

Cleanup:
  k3d cluster delete $SLAVE_NAME
  k3d cluster delete $MASTER_NAME
  rm -f "$MASTER_KUBECONFIG" "$SLAVE_KUBECONFIG" "$KUBECONFIG_DIR/merged"
EOF
}

main "$@"
