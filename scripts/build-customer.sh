#!/usr/bin/env bash
# Phase 1 stub. Produces a web PWA tarball for a customer env.
#
# Phase 5 extends this to also run `npx cap copy android`, patch
# build.gradle, and produce a signed APK in dist/.
#
# Usage: bash scripts/build-customer.sh <customer>

set -euo pipefail

CUSTOMER="${1:-demo}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/customers/.env.${CUSTOMER}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "✗ Missing customer env: ${ENV_FILE}"
  echo "  Copy customers/.env.example to customers/.env.${CUSTOMER} first."
  exit 1
fi

echo "▶ Building PWA for customer: ${CUSTOMER}"
set -a
source "${ENV_FILE}"
set +a

cd "${ROOT}/frontend"
CUSTOMER_BUILD_TARGET=web pnpm exec vite build

OUT_DIR="${ROOT}/vansale/public/spa"
TARBALL="${ROOT}/dist/vansale-${CUSTOMER}-pwa-$(date +%Y%m%d%H%M).tar.gz"
mkdir -p "${ROOT}/dist"
(cd "${OUT_DIR}" && tar czf "${TARBALL}" --exclude='.DS_Store' .)
echo "✓ PWA tarball: ${TARBALL}"
echo
echo "Next steps (Phase 5 wires this into one command):"
echo "  1. Upload tarball to the server."
echo "  2. Extract to /home/<bench>/frappe-bench/apps/vansale/vansale/public/spa/"
echo "  3. supervisorctl signal QUIT frappe-bench-web:frappe-bench-frappe-web"
