#!/usr/bin/env bash
# Issue a CA and a zot server certificate. The container IP goes in the SANs
# because the read path cannot use a loopback host: containerd's resolver
# forces plain HTTP for loopback, and the addon read path is HTTPS-only.
set -euo pipefail
SCRATCH="${SCRATCH:-/tmp/vela-oci-test}"
mkdir -p "$SCRATCH/tls"
cd "$SCRATCH/tls"

IP="$(hostname -i | awk '{print $1}')"
echo "$IP" > "$SCRATCH/zot-ip.txt"
echo "issuing certificate for $IP"

openssl req -x509 -newkey rsa:2048 -nodes -keyout ca.key -out ca.crt -days 30 \
  -subj "/CN=zot-test-ca" >/dev/null 2>&1

cat > san.cnf <<EOF
[req]
distinguished_name=dn
[dn]
[ext]
subjectAltName=DNS:localhost,DNS:zot.vela-system.svc,IP:127.0.0.1,IP:$IP
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EOF

openssl req -newkey rsa:2048 -nodes -keyout tls.key -out zot.csr \
  -subj "/CN=localhost" >/dev/null 2>&1
openssl x509 -req -in zot.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out tls.crt -days 30 -extfile san.cnf -extensions ext >/dev/null 2>&1

# The system trust store is not writable in the dev container, so build a
# bundle instead. Go honours SSL_CERT_FILE.
cat /etc/ssl/certs/ca-certificates.crt ca.crt > "$SCRATCH/ca-bundle.crt"

openssl x509 -in tls.crt -noout -text | grep -A1 "Subject Alternative Name"
echo "export SSL_CERT_FILE=$SCRATCH/ca-bundle.crt"
