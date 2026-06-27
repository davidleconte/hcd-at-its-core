#!/bin/bash
# gen-certs.sh — Generate a PEM certificate authority and SAN-bearing node/client
# certificates for the HCD 2.0 secure profile (Modules 88 & 91).
#
# HCD 2.0 / Cassandra 5.0 accepts PEM key material directly (no JKS conversion) and,
# for mTLS, maps a client certificate's SAN to a database role. The nodetool --ssl
# hostname-verification fix on JDK 17 requires certs to carry a Subject Alternative
# Name (SAN) matching the host — so every cert below sets a SAN explicitly.
#
# Usage:
#   ./scripts/gen-certs.sh              # writes ./certs/
#   CERT_DIR=/tmp/c ./scripts/gen-certs.sh
#
# Output (all PEM):
#   certs/ca.crt                  root CA (use as truststore on every node)
#   certs/hcd-nodeN.{key,crt,pem} per-node key, cert, and combined keystore
#   certs/analyst.{key,crt,pem}   client identity → role 'analyst'  (spiffe SAN)
#   certs/auditor.{key,crt,pem}   client identity → role 'auditor'  (spiffe SAN)
set -euo pipefail

CERT_DIR="${CERT_DIR:-./certs}"
DAYS="${DAYS:-825}"
KEY_BITS="${KEY_BITS:-2048}"

# node name → static IP (mirrors docker-compose.yml)
NODES=("hcd-node1:172.28.0.2" "hcd-node2:172.28.0.3" "hcd-node3:172.28.0.4" \
       "hcd-node4:172.28.0.5" "hcd-node5:172.28.0.6" "hcd-node6:172.28.0.7")

if ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: openssl not found. Install it (brew install openssl / apt-get install openssl)." >&2
    exit 1
fi

mkdir -p "$CERT_DIR"
echo "Generating PEM PKI into ${CERT_DIR}/ (validity ${DAYS} days)..."
echo "WARNING: DEMO CA — private keys are unencrypted and short-lived. Do NOT reuse in production." >&2

# ─── 1. Root CA ────────────────────────────────────────────────────────────────
if [ ! -f "${CERT_DIR}/ca.crt" ]; then
    openssl genrsa -out "${CERT_DIR}/ca.key" "$KEY_BITS" 2>/dev/null
    openssl req -x509 -new -nodes -key "${CERT_DIR}/ca.key" -sha256 -days "$DAYS" \
        -subj "/O=HCD Demo/OU=Security/CN=HCD Demo Root CA" \
        -out "${CERT_DIR}/ca.crt" 2>/dev/null
    echo "  [OK] Root CA → ca.crt"
else
    echo "  [skip] ca.crt already exists (delete ${CERT_DIR} to regenerate)"
fi

# sign_cert <name> <subject-CN> <san-block>
sign_cert() {
    local name="$1" cn="$2" san="$3"
    local ext; ext="$(mktemp)"
    cat > "$ext" <<EOF
subjectAltName = ${san}
extendedKeyUsage = serverAuth, clientAuth
EOF
    openssl genrsa -out "${CERT_DIR}/${name}.key" "$KEY_BITS" 2>/dev/null
    openssl req -new -key "${CERT_DIR}/${name}.key" -subj "/O=HCD Demo/CN=${cn}" \
        -out "${CERT_DIR}/${name}.csr" 2>/dev/null
    openssl x509 -req -in "${CERT_DIR}/${name}.csr" \
        -CA "${CERT_DIR}/ca.crt" -CAkey "${CERT_DIR}/ca.key" -CAcreateserial \
        -out "${CERT_DIR}/${name}.crt" -days "$DAYS" -sha256 -extfile "$ext" 2>/dev/null
    # Combined keystore PEM (key + cert chain) — what HCD consumes as 'keystore'.
    cat "${CERT_DIR}/${name}.key" "${CERT_DIR}/${name}.crt" > "${CERT_DIR}/${name}.pem"
    rm -f "${CERT_DIR}/${name}.csr" "$ext"
}

# ─── 2. Per-node server certs (SAN = DNS hostname + container IP + localhost) ────
for entry in "${NODES[@]}"; do
    node="${entry%%:*}"; ip="${entry##*:}"
    sign_cert "$node" "$node" "DNS:${node},DNS:localhost,IP:${ip},IP:127.0.0.1"
    echo "  [OK] Node cert → ${node}.pem (SAN: ${node}, ${ip})"
done

# ─── 3. Client identity certs for mTLS (SAN = spiffe URI → role) ────────────────
# In secure mode: ADD IDENTITY 'spiffe://hcd/role/analyst' TO ROLE analyst;
sign_cert "analyst" "analyst" "URI:spiffe://hcd/role/analyst,DNS:analyst"
echo "  [OK] Client cert → analyst.pem (identity: spiffe://hcd/role/analyst)"
sign_cert "auditor" "auditor" "URI:spiffe://hcd/role/auditor,DNS:auditor"
echo "  [OK] Client cert → auditor.pem (identity: spiffe://hcd/role/auditor)"

echo ""
echo "Done. Mount ${CERT_DIR} into the cluster with the secure overlay:"
echo "    make gen-certs && make up-secure"
echo "Truststore for every node: ${CERT_DIR}/ca.crt"
