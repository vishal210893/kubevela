#!/usr/bin/env bash
#
# deploy-local-ttl.sh
#
# Build the KubeVela vela-core controller image locally, push it to the
# ephemeral ttl.sh registry (no login required), and deploy the LOCAL Helm
# chart to a k3d cluster. Used to verify the `extraEnvs` / CUE_EXPERIMENT
# change from https://github.com/kubevela/kubevela/issues/7222 end-to-end.
#
# Build/deploy steps are adapted from the internal Confluence runbook
# "Remote Debugging KubeVela Applications" (space CCS, page 1633681409),
# with the image push retargeted from Docker Hub to ttl.sh.
#
# Run this from the root of the kubevela repo, on the host where Docker and
# k3d are available:
#     ./hack/deploy-local-ttl.sh
#
# Override any of the CONFIG values via environment variables, e.g.:
#     IMAGE_TTL=1h CLUSTER_NAME=mycluster ./hack/deploy-local-ttl.sh
#
set -euo pipefail

#--- CONFIG (override via env) ------------------------------------------------
CLUSTER_NAME="${CLUSTER_NAME:-kubevela}"
NAMESPACE="${NAMESPACE:-vela-system}"
RELEASE="${RELEASE:-kubevela}"
CHART_DIR="${CHART_DIR:-./charts/vela-core}"
IMAGE_TTL="${IMAGE_TTL:-5m}"             # how long ttl.sh keeps the image
# Unique, lower-case ttl.sh repository path (ttl.sh serves anonymous, ephemeral images).
IMAGE_NAME="${IMAGE_NAME:-ttl.sh/vela-core-$( (uuidgen 2>/dev/null || git rev-parse --short HEAD) | tr 'A-Z' 'a-z' | tr -d '-' | cut -c1-12)}"
IMAGE_REF="${IMAGE_NAME}:${IMAGE_TTL}"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

#--- STEP 1: check prerequisites ----------------------------------------------
log "STEP 1: Checking prerequisites"
for bin in docker k3d kubectl helm git; do
  command -v "$bin" >/dev/null 2>&1 || die "'$bin' not found in PATH"
done
docker info >/dev/null 2>&1 || die "Docker daemon not reachable — start Docker/Rancher Desktop first"
[ -d "$CHART_DIR" ] || die "Chart dir '$CHART_DIR' not found — run this from the kubevela repo root"
echo "OK: docker, k3d, kubectl, helm, git present; Docker daemon reachable; chart found."

#--- STEP 2: read existing clusters -------------------------------------------
log "STEP 2: Existing k3d clusters"
k3d cluster list || true

#--- STEP 3: delete ALL k3d clusters, then create a fresh one -----------------
log "STEP 3: Deleting all existing k3d clusters and creating '$CLUSTER_NAME'"
EXISTING="$(k3d cluster list -o json 2>/dev/null | grep -o '"name":"[^"]*"' | cut -d'"' -f4 || true)"
if [ -n "$EXISTING" ]; then
  echo "Deleting existing k3d clusters: $EXISTING"
  k3d cluster delete --all
else
  echo "No existing k3d clusters."
fi
echo "Creating fresh k3d cluster '$CLUSTER_NAME'..."
k3d cluster create "$CLUSTER_NAME" --wait
kubectl config use-context "k3d-${CLUSTER_NAME}"
kubectl cluster-info

#--- STEP 4: build the controller image ---------------------------------------
log "STEP 4: Building vela-core image ($IMAGE_REF)"
VELA_VERSION="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo dev)"
GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo undefined)"
docker build \
  --build-arg VERSION="$VELA_VERSION" \
  --build-arg GITVERSION="$GIT_COMMIT" \
  -t "$IMAGE_REF" -f Dockerfile .

#--- STEP 5: push the image to ttl.sh -----------------------------------------
log "STEP 5: Pushing image to ttl.sh (expires in $IMAGE_TTL)"
docker push "$IMAGE_REF"
echo "Pushed: $IMAGE_REF"

#--- STEP 6 + 7: point the chart at the pushed image and deploy via Helm -------
# The chart builds the controller image ref as:
#   {{ .Values.imageRegistry }}{{ .Values.image.repository }}:{{ .Values.image.tag }}
# so we override image.repository/tag instead of hand-editing the template.
# extraEnvs (CUE_EXPERIMENT=evalv3=0,keepvalidators=0) is already the chart default.
log "STEP 6/7: Deploying local chart '$CHART_DIR' with image $IMAGE_REF"
helm upgrade --install "$RELEASE" "$CHART_DIR" \
  --create-namespace --namespace "$NAMESPACE" \
  --set imageRegistry="" \
  --set image.repository="$IMAGE_NAME" \
  --set image.tag="$IMAGE_TTL" \
  --set image.pullPolicy=Always \
  --set featureGates.enableCueExpVariable=false \
  --set featureGates.enableAddonComponent=true \
  --wait --timeout 6m --debug

#--- verify -------------------------------------------------------------------
log "Verifying deployment and CUE_EXPERIMENT injection"
kubectl get all -n "$NAMESPACE"

DEPLOY="$(kubectl -n "$NAMESPACE" get deploy \
  -l "app.kubernetes.io/name=vela-core,app.kubernetes.io/instance=${RELEASE}" \
  -o jsonpath='{.items[0].metadata.name}')"
[ -n "$DEPLOY" ] || die "Could not find the vela-core controller deployment"

echo
echo "Controller deployment: $DEPLOY"
echo "Configured env:"
kubectl -n "$NAMESPACE" get deploy "$DEPLOY" \
  -o jsonpath='{.spec.template.spec.containers[0].env}'; echo
echo
echo "CUE_EXPERIMENT in the running container:"
kubectl -n "$NAMESPACE" exec "deploy/${DEPLOY}" -c "$RELEASE" -- printenv CUE_EXPERIMENT \
  && echo "SUCCESS: extraEnvs injected correctly." \
  || echo "WARNING: CUE_EXPERIMENT not set — check charts/vela-core/values.yaml extraEnvs."

log "Done. To remove: helm delete $RELEASE -n $NAMESPACE && k3d cluster delete $CLUSTER_NAME"
