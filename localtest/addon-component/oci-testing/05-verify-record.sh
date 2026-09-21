#!/usr/bin/env bash
# The stored record must be a Helm block with an oci:// URL and no oci block.
set -euo pipefail
REGISTRY_NAME="${REGISTRY_NAME:-zot-oci}"

RECORD="$(kubectl -n vela-system get cm vela-addon-registry -o jsonpath='{.data.registries}')"
echo "$RECORD" | python3 -m json.tool

echo "$RECORD" | python3 -c '
import json, sys, os
name = os.environ.get("REGISTRY_NAME", "zot-oci")
reg = json.load(sys.stdin)[name]
assert "oci" not in reg, "the legacy oci block must not be written: %r" % reg
assert "helm" in reg, "expected a helm block, got %r" % reg
assert reg["helm"]["url"].startswith("oci://"), reg["helm"]["url"]
assert "password" not in reg["helm"], "an oci registry must not store a password"
print("OK: helm block with an oci:// URL, no legacy oci block")
'
