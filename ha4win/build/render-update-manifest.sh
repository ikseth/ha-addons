#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VERSION="${1:-}"
CHANNEL="${2:-stable}"
ARCHITECTURE="${3:-${ARCH:-amd64}}"
RAW_BASE_URL="${4:-https://raw.githubusercontent.com/ikseth/ha-addons/main/ha4win/update-assets}"
CHANGELOG_URL="${5:-https://github.com/ikseth/ha-addons/releases/tag/ha4win-v${VERSION}}"
MIN_WINDOWS_BUILD="${6:-14393}"

if [[ -z "${VERSION}" ]]; then
  echo "Usage: $0 VERSION [CHANNEL] [ARCH] [ASSET_BASE_URL] [CHANGELOG_URL] [MIN_WINDOWS_BUILD]" >&2
  exit 2
fi
case "${ARCHITECTURE}" in
  amd64|arm64|386) ;;
  *) echo "Unsupported architecture: ${ARCHITECTURE}" >&2; exit 2 ;;
esac

asset_name="ha4win-${VERSION}-windows-${ARCHITECTURE}.zip"
asset_path="${PROJECT_DIR}/update-assets/${asset_name}"
if [[ ! -f "${asset_path}" ]]; then
  echo "Asset not found: ${asset_path}" >&2
  exit 1
fi
if command -v sha256sum >/dev/null 2>&1; then
  digest="$(sha256sum "${asset_path}" | awk '{print $1}')"
else
  digest="$(shasum -a 256 "${asset_path}" | awk '{print $1}')"
fi

cat <<EOF
{
  "channels": {
    "${CHANNEL}": {
      "version": "${VERSION}",
      "changelog_url": "${CHANGELOG_URL}",
      "asset_url": "${RAW_BASE_URL%/}/${asset_name}",
      "sha256": "${digest}",
      "min_windows_build": ${MIN_WINDOWS_BUILD}
    }
  }
}
EOF
