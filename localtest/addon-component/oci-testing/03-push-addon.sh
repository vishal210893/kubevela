#!/usr/bin/env bash
# Package the example addon fixture and push it as an OCI Helm chart. This is
# the OCI push path: chart push plus a best-effort portable catalog update.
set -euo pipefail
SCRATCH="${SCRATCH:-/tmp/vela-oci-test}"
REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"
VELA="${VELA:-$SCRATCH/vela}"
export SSL_CERT_FILE="$SCRATCH/ca-bundle.crt"
IP="$(cat "$SCRATCH/zot-ip.txt")"

if [ ! -x "$VELA" ]; then
  echo "building vela from $REPO_ROOT"
  (cd "$REPO_ROOT" && CGO_ENABLED=0 go build -o "$VELA" ./references/cmd/cli)
fi

rm -rf "$SCRATCH/addon-src"
mkdir -p "$SCRATCH/addon-src"
cp -r "$REPO_ROOT/pkg/addon/testdata/example" "$SCRATCH/addon-src/example"

"$VELA" addon push "$SCRATCH/addon-src/example" "oci://$IP:5000/addons"

echo "--- repositories ---"
curl --cacert "$SCRATCH/tls/ca.crt" -sS "https://$IP:5000/v2/_catalog"; echo
echo "--- tags ---"
curl --cacert "$SCRATCH/tls/ca.crt" -sS "https://$IP:5000/v2/addons/example/tags/list"; echo
