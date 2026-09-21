#!/usr/bin/env bash
# Run zot over TLS, bound to all interfaces so a non-loopback address works.
set -euo pipefail
SCRATCH="${SCRATCH:-/tmp/vela-oci-test}"
ZOT_VERSION="${ZOT_VERSION:-v2.1.20}"
ARCH="$(uname -m)"; [ "$ARCH" = "aarch64" ] && ARCH=arm64 || ARCH=amd64
IP="$(cat "$SCRATCH/zot-ip.txt")"
mkdir -p "$SCRATCH/zot-data"

if [ ! -x "$SCRATCH/zot" ]; then
  echo "downloading zot $ZOT_VERSION ($ARCH)"
  curl -sSL -o "$SCRATCH/zot" \
    "https://github.com/project-zot/zot/releases/download/$ZOT_VERSION/zot-linux-$ARCH"
  chmod +x "$SCRATCH/zot"
fi

cat > "$SCRATCH/zot-config.json" <<EOF
{
  "distSpecVersion": "1.1.0",
  "storage": {"rootDirectory": "$SCRATCH/zot-data"},
  "http": {"address": "0.0.0.0", "port": "5000",
           "tls": {"cert": "$SCRATCH/tls/tls.crt", "key": "$SCRATCH/tls/tls.key"}},
  "log": {"level": "info", "output": "$SCRATCH/zot.log"}
}
EOF

pkill -x zot 2>/dev/null || true
sleep 1
setsid "$SCRATCH/zot" serve "$SCRATCH/zot-config.json" \
  > "$SCRATCH/zot-stdout.log" 2>&1 < /dev/null &

for _ in $(seq 1 30); do
  if curl --cacert "$SCRATCH/tls/ca.crt" -sf "https://$IP:5000/v2/" >/dev/null 2>&1; then
    echo "zot ready at https://$IP:5000"
    exit 0
  fi
  sleep 1
done
echo "zot did not become ready; see $SCRATCH/zot.log" >&2
exit 1
