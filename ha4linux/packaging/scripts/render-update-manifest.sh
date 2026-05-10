#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HA4LINUX_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

if [[ -n "${1:-}" ]]; then
  VERSION="$1"
else
  if command -v jq >/dev/null 2>&1; then
    VERSION="$(jq -r '.version' "${HA4LINUX_ROOT}/config.json")"
  else
    VERSION="$(awk -F'\"' '/\"version\"[[:space:]]*:/ {print $4; exit}' "${HA4LINUX_ROOT}/config.json")"
  fi
fi

CHANNEL="${2:-stable}"
RAW_BASE_URL="${3:-https://raw.githubusercontent.com/ikseth/ha-addons/main/ha4linux/update-assets}"
CHANGELOG_URL="${4:-https://github.com/ikseth/ha-addons/tree/main/ha4linux}"
ASSET_NAME="ha4linux-client-update-${VERSION}.tar.gz"
ASSET_PATH="${HA4LINUX_ROOT}/update-assets/${ASSET_NAME}"
MANIFEST_PATH="${HA4LINUX_ROOT}/update-manifest.json"

if [[ ! -f "${ASSET_PATH}" ]]; then
  echo "Asset not found: ${ASSET_PATH}" >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  SHA256="$(sha256sum "${ASSET_PATH}" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  SHA256="$(shasum -a 256 "${ASSET_PATH}" | awk '{print $1}')"
else
  echo "No sha256 tool available" >&2
  exit 1
fi

ASSET_URL="${RAW_BASE_URL%/}/${ASSET_NAME}"

cat > "${MANIFEST_PATH}" <<EOF
{
  "channels": {
    "${CHANNEL}": {
      "version": "${VERSION}",
      "changelog_url": "${CHANGELOG_URL}",
      "asset_url": "${ASSET_URL}",
      "sha256": "${SHA256}"
    }
  }
}
EOF

echo "Rendered manifest: ${MANIFEST_PATH}"
echo "Asset URL: ${ASSET_URL}"
echo "SHA256: ${SHA256}"
