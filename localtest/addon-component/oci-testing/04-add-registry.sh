#!/usr/bin/env bash
# Register the OCI registry and read it back. `registry add` validates by
# listing the catalog, tolerating only a genuinely absent one.
set -euo pipefail
SCRATCH="${SCRATCH:-/tmp/vela-oci-test}"
VELA="${VELA:-$SCRATCH/vela}"
REGISTRY_NAME="${REGISTRY_NAME:-zot-oci}"
export SSL_CERT_FILE="$SCRATCH/ca-bundle.crt"
IP="$(cat "$SCRATCH/zot-ip.txt")"

"$VELA" addon registry delete "$REGISTRY_NAME" >/dev/null 2>&1 || true
"$VELA" addon registry add "$REGISTRY_NAME" --type oci --endpoint "oci://$IP:5000/addons"

echo "--- registry list ---"; "$VELA" addon registry list
echo "--- registry get ---";  "$VELA" addon registry get "$REGISTRY_NAME"
echo "--- addon ls ---";      "$VELA" addon ls 2>/dev/null | grep -Ev '^ERR'
echo "--- dry-run render ---"
"$VELA" addon enable example example=hello-oci --dry-run 2>/dev/null \
  | grep -E 'name: addon-example|addons.oam.dev/(registry|version)'
