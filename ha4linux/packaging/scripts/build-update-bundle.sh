#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HA4LINUX_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd -- "${HA4LINUX_ROOT}/.." && pwd)"

if [[ -n "${1:-}" ]]; then
  VERSION="$1"
else
  if command -v jq >/dev/null 2>&1; then
    VERSION="$(jq -r '.version' "${HA4LINUX_ROOT}/config.json")"
  else
    VERSION="$(awk -F'\"' '/\"version\"[[:space:]]*:/ {print $4; exit}' "${HA4LINUX_ROOT}/config.json")"
  fi
fi

OUTPUT_DIR="${2:-${HA4LINUX_ROOT}/update-assets}"
ASSET_NAME="ha4linux-client-update-${VERSION}.tar.gz"
ASSET_PATH="${OUTPUT_DIR}/${ASSET_NAME}"

mkdir -p "${OUTPUT_DIR}"

tar \
  --sort=name \
  --mtime='UTC 2026-01-01' \
  --owner=0 \
  --group=0 \
  --numeric-owner \
  -C "${REPO_ROOT}" \
  -czf "${ASSET_PATH}" \
  ha4linux/app \
  ha4linux/requirements.txt \
  ha4linux/packaging/assets \
  ha4linux/packaging/common/install-client.sh \
  ha4linux/packaging/common/uninstall-client.sh

if command -v sha256sum >/dev/null 2>&1; then
  SHA256="$(sha256sum "${ASSET_PATH}" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  SHA256="$(shasum -a 256 "${ASSET_PATH}" | awk '{print $1}')"
else
  echo "No sha256 tool available" >&2
  exit 1
fi

echo "Built asset: ${ASSET_PATH}"
echo "SHA256: ${SHA256}"
