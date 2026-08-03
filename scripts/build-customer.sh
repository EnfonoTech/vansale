#!/usr/bin/env bash
# One-shot build for a customer:
#   1. Refuse if git is dirty (safety).
#   2. Bump patch version (NATIVE_VERSION + versionCode atomic).
#   3. Build the web PWA tarball (CUSTOMER_BUILD_TARGET=web).
#   4. Build the native bundle + sync Capacitor.
#   5. Patch build.gradle with signing config.
#   6. Regenerate colors.xml / strings.xml.
#   7. Assemble signed release APK.
#   8. Stage both artefacts under dist/.
#
# Usage: bash scripts/build-customer.sh <customer>
# Pre-req: customers/.env.<customer> + ~/.vansale-<customer>-keystore-pw
#          (or env vars VANSALE_KEYSTORE_PW + VANSALE_KEY_PW + VANSALE_KEYSTORE_PATH
#           supplied by the caller).

set -euo pipefail

CUSTOMER="${1:?Usage: build-customer.sh <customer>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

ENV_FILE="customers/.env.${CUSTOMER}"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "✗ Missing ${ENV_FILE}" >&2
  exit 1
fi

if ! git diff-index --quiet HEAD -- && [[ "${VANSALE_ALLOW_DIRTY:-0}" != "1" ]]; then
  echo "✗ Uncommitted changes — commit or stash (set VANSALE_ALLOW_DIRTY=1 to override)." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

# Password file fallback.
PW_FILE="${HOME}/.vansale-${CUSTOMER}-keystore-pw"
if [[ -z "${VANSALE_KEYSTORE_PW:-}" && -f "${PW_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${PW_FILE}"
  set +a
fi

KEYSTORE_PATH="${VANSALE_KEYSTORE_PATH:-${ROOT}/android-capacitor/keystore/vansale-${CUSTOMER}.keystore}"
ALIAS="vansale-${CUSTOMER}"

echo "▶ Building vansale for customer: ${CUSTOMER}"
node scripts/bump-version.mjs patch

mkdir -p dist

# --- 0. Brand logo ----------------------------------------------------------
# Must run BEFORE the vite builds — Vite copies `public/` at build time, so
# staging the logo afterwards would leave it out of both bundles.
CUSTOMER_NAME="${CUSTOMER}" node scripts/generate-customer-assets.mjs brand

# --- 1. Web PWA tarball -----------------------------------------------------
echo "▶ Building web bundle"
(cd frontend && CUSTOMER_BUILD_TARGET=web pnpm exec vite build)
WEB_TARBALL="${ROOT}/dist/vansale-${CUSTOMER}-pwa.tar.gz"
(cd "${ROOT}/vansale/public/spa" && tar czf "${WEB_TARBALL}" --exclude='.DS_Store' .)
echo "✓ ${WEB_TARBALL}"

# --- 2. Native bundle -------------------------------------------------------
echo "▶ Building native bundle"
(cd android-capacitor && CUSTOMER_BUILD_TARGET=native pnpm exec vite build)

# Android project must already exist — first-time setup runs `npx cap add android`
if [[ ! -d "${ROOT}/android-capacitor/android" ]]; then
  echo "▶ First-time: adding Android project"
  (cd android-capacitor && npx cap add android && npx cap sync android)
fi

# Copy web assets in
(cd android-capacitor && npx cap copy android)

# Patch signing + applicationId
VANSALE_KEYSTORE_PATH="${KEYSTORE_PATH}" \
VANSALE_KEYSTORE_ALIAS="${ALIAS}" \
CUSTOMER_APP_ID="${CUSTOMER_APP_ID}" \
python3 scripts/_patch-build-gradle.py

# Customer colors / strings / launcher icon + splash
CUSTOMER_NAME="${CUSTOMER}" \
CUSTOMER_THEME_PRIMARY="${CUSTOMER_THEME_PRIMARY}" \
CUSTOMER_THEME_BG="${CUSTOMER_THEME_BG:-#f8fafc}" \
CUSTOMER_APP_TITLE="${CUSTOMER_APP_TITLE}" \
CUSTOMER_APP_ID="${CUSTOMER_APP_ID}" \
node scripts/generate-customer-assets.mjs android

# --- 3. Assemble APK --------------------------------------------------------
if [[ -z "${VANSALE_KEYSTORE_PW:-}" ]]; then
  echo "✗ VANSALE_KEYSTORE_PW not set and ${PW_FILE} not found — skipping APK assembly." >&2
  echo "  PWA tarball is ready at ${WEB_TARBALL}."
  exit 0
fi

if [[ ! -f "${KEYSTORE_PATH}" ]]; then
  echo "✗ Keystore not found: ${KEYSTORE_PATH}" >&2
  echo "  Run: bash scripts/generate-keystore.sh ${CUSTOMER}"
  exit 1
fi

echo "▶ Assembling signed APK"
(cd android-capacitor/android && VANSALE_KEYSTORE_PW="${VANSALE_KEYSTORE_PW}" ./gradlew assembleRelease)

APK_SRC="${ROOT}/android-capacitor/android/app/build/outputs/apk/release/app-release.apk"
VERSION="$(grep -oE 'NATIVE_VERSION = "[^"]+"' "${ROOT}/frontend/src/app/native-version.ts" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
APK_OUT="${ROOT}/dist/vansale-${CUSTOMER}-${VERSION}.apk"
cp "${APK_SRC}" "${APK_OUT}"
echo "✓ ${APK_OUT}"

echo
echo "Done. Artefacts:"
ls -la "${ROOT}/dist"
