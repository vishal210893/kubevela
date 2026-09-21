#!/usr/bin/env bash
# End-to-end run of the addon component against a private ECR registry.
#
# Unlike the zot scripts, this needs no certificate work: ECR presents a
# publicly trusted certificate, so the controller and webhook on the host trust
# it without any keychain import.
#
# ECR does not create repositories on push, so every addon needs its repository
# created first, along with the portable catalog repository.
#
# Requires: AWS credentials in the environment, kubectl pointed at a cluster
# running a controller built from this branch, and a vela binary built from it.
set -euo pipefail

SCRATCH="${SCRATCH:-/tmp/vela-oci-test}"
REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"
VELA="${VELA:-$SCRATCH/vela}"
ADDON_NAME="${ADDON_NAME:-oci-demo}"
ADDON_VERSION="${ADDON_VERSION:-2.1.0}"
ADDON_SRC="${ADDON_SRC:-$SCRATCH/addon-src/$ADDON_NAME}"
PREFIX="${PREFIX:-vela-addon-test}"
REGISTRY_NAME="${REGISTRY_NAME:-ecr}"
NS="${NS:-${ADDON_NAME}-system}"

: "${AWS_REGION:?set AWS_REGION}"
: "${AWS_ACCOUNT_ID:?set AWS_ACCOUNT_ID}"
# An empty AWS_PROFILE is read by the CLI as a profile literally named "",
# which fails every call with "The config profile () could not be found".
unset AWS_PROFILE AWS_DEFAULT_PROFILE || true

REG="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
echo "registry: $REG/$PREFIX    addon: $ADDON_NAME:$ADDON_VERSION"

step() { printf '\n=== %s\n' "$1"; }

step "1. create the ECR repositories (ECR does not create them on push)"
for r in "$PREFIX/$ADDON_NAME" "$PREFIX/kubevela-addon-catalog"; do
  aws ecr describe-repositories --repository-names "$r" --region "$AWS_REGION" >/dev/null 2>&1 \
    || aws ecr create-repository --repository-name "$r" --region "$AWS_REGION" \
         --query 'repository.repositoryUri' --output text
done

step "2. push the addon"
aws ecr get-login-password --region "$AWS_REGION" > "$SCRATCH/ecr.pw"
chmod 600 "$SCRATCH/ecr.pw"
"$VELA" addon push "$ADDON_SRC" "oci://$REG/$PREFIX" \
  --username AWS --password "$(cat "$SCRATCH/ecr.pw")"

step "3. confirm the tag and the portable catalog exist"
curl -sS -u "AWS:$(cat "$SCRATCH/ecr.pw")" \
  "https://$REG/v2/$PREFIX/$ADDON_NAME/tags/list"; echo
curl -sS -u "AWS:$(cat "$SCRATCH/ecr.pw")" \
  "https://$REG/v2/$PREFIX/kubevela-addon-catalog/tags/list"; echo

step "4. register the OCI registry"
"$VELA" addon registry delete "$REGISTRY_NAME" >/dev/null 2>&1 || true
"$VELA" addon registry add "$REGISTRY_NAME" --type oci \
  --endpoint "oci://$REG/$PREFIX" \
  --username AWS --password-stdin < "$SCRATCH/ecr.pw"

step "5. the credential must be in a Secret, never in the ConfigMap"
kubectl -n vela-system get cm vela-addon-registry -o jsonpath='{.data.registries}' \
  | REGISTRY_NAME="$REGISTRY_NAME" python3 -c '
import json, os, sys
reg = json.load(sys.stdin)[os.environ["REGISTRY_NAME"]]
assert "oci" not in reg, "the legacy oci block must not be written: %r" % reg
helm = reg["helm"]
assert helm["url"].startswith("oci://"), helm["url"]
assert "token" not in helm, "the token must not stay in the ConfigMap"
assert helm.get("tokenSecretRef"), "expected a tokenSecretRef"
print("OK: helm block, oci:// url, tokenSecretRef=%s" % helm["tokenSecretRef"])
'
kubectl -n vela-system get "secret/addon-registry-$REGISTRY_NAME" \
  -o go-template='{{range $k,$v := .data}}secret key: {{$k}}{{"\n"}}{{end}}'

step "6. resolve through the registry"
# head closes the pipe early, which under pipefail surfaces as SIGPIPE (141).
"$VELA" addon status "$ADDON_NAME" 2>/dev/null | head -6 || true

step "7. apply the addon component"
cat > "$SCRATCH/app-$ADDON_NAME.yaml" <<EOF
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: oci-addon-e2e
  namespace: vela-system
spec:
  components:
    - name: $ADDON_NAME
      type: addon
      properties:
        addon: $ADDON_NAME
        version: "$ADDON_VERSION"
        registry: $REGISTRY_NAME
        properties:
          greeting: hello-from-ecr
          replicas: 3
        skipVersionValidation: true
EOF
kubectl apply -f "$SCRATCH/app-$ADDON_NAME.yaml"

step "8. wait for the outer and child Applications"
for _ in $(seq 1 30); do
  outer=$(kubectl -n vela-system get app oci-addon-e2e -o jsonpath='{.status.status}' 2>/dev/null || true)
  child=$(kubectl -n vela-system get app "addon-$ADDON_NAME" -o jsonpath='{.status.status}' 2>/dev/null || true)
  echo "outer=$outer child=$child"
  [ "$outer" = "running" ] && [ "$child" = "running" ] && break
  sleep 10
done

step "9. verify the rendered result"
kubectl -n vela-system get app "addon-$ADDON_NAME" -o json \
  | python3 -c 'import json,sys; l=json.load(sys.stdin)["metadata"]["labels"]; [print(f"{k}: {v}") for k,v in sorted(l.items()) if k.startswith("addons.oam.dev")]' 
kubectl -n "$NS" get cm "${ADDON_NAME}-input" -o jsonpath='{.data}{"\n"}'
kubectl get traitdefinition oci-demo-label -n vela-system -o jsonpath='traitdefinition={.metadata.name}{"\n"}'

echo
echo "PASS"
