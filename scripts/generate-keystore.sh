#!/usr/bin/env bash
# Generate a fresh PKCS12 keystore for a customer. Run ONCE per
# customer and back up the resulting file TWICE — losing it means
# every user has to uninstall and lose their offline queue.
#
# Usage: bash scripts/generate-keystore.sh <customer>
#
# After running:
#   - keystore lives at android-capacitor/keystore/vansale-<customer>.keystore
#   - password written to ~/.vansale-<customer>-keystore-pw
#   - DO NOT commit the keystore or the password file.

set -euo pipefail

CUSTOMER="${1:?Usage: generate-keystore.sh <customer>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEYSTORE_DIR="${ROOT}/android-capacitor/keystore"
KEYSTORE_PATH="${KEYSTORE_DIR}/vansale-${CUSTOMER}.keystore"
PW_FILE="${HOME}/.vansale-${CUSTOMER}-keystore-pw"

if [[ -f "${KEYSTORE_PATH}" ]]; then
  echo "✗ Keystore already exists: ${KEYSTORE_PATH}"
  echo "  Delete it by hand if you REALLY want to start over."
  exit 1
fi

mkdir -p "${KEYSTORE_DIR}"
PW="$(openssl rand -base64 24 | tr -d '=+/' | head -c 24)"

keytool -genkey -v \
  -keystore "${KEYSTORE_PATH}" \
  -alias "vansale-${CUSTOMER}" \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storetype PKCS12 \
  -storepass "${PW}" -keypass "${PW}" \
  -dname "CN=Van Sale (${CUSTOMER}), OU=Van Sales, O=Enfono Technologies, L=Unknown, ST=Unknown, C=OM"

cat > "${PW_FILE}" <<EOF
# Van Sale keystore password — DO NOT COMMIT
# Generated: $(date -u +%FT%TZ)
# Keystore: ${KEYSTORE_PATH}
VANSALE_KEYSTORE_PW=${PW}
VANSALE_KEY_PW=${PW}
EOF
chmod 600 "${PW_FILE}"

echo
echo "✓ Keystore: ${KEYSTORE_PATH}"
echo "✓ Password: ${PW_FILE}"
echo
echo "Back this up TWICE before shipping. Losing it forces every user to uninstall"
echo "and lose their offline-queued work."
