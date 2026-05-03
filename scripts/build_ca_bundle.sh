#!/usr/bin/env bash
# Build data/ca-bundle.pem = certifi's CAs + macOS keychain CAs.
# Used by run.sh so requests/urllib trust corporate roots installed in Keychain.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  echo "missing .venv; run pip install first" >&2; exit 1
fi
source .venv/bin/activate

CERTIFI=$(python3 -c "import certifi; print(certifi.where())")
OUT=data/ca-bundle.pem
mkdir -p data
cat "$CERTIFI" > "$OUT"
security find-certificate -a -p /Library/Keychains/System.keychain >> "$OUT" || true
security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain >> "$OUT" || true
security find-certificate -a -p ~/Library/Keychains/login.keychain-db >> "$OUT" 2>/dev/null || true

echo "wrote $OUT ($(grep -c 'BEGIN CERTIFICATE' "$OUT") certs)"
