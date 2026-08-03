#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VERSION="${1:-}"
OUTPUT_DIR="${2:-${PROJECT_DIR}/update-assets}"

if [[ -z "${VERSION}" ]]; then
  echo "Usage: $0 VERSION [OUTPUT_DIR]" >&2
  exit 2
fi

mkdir -p "${OUTPUT_DIR}"
OUTPUT_DIR="$(cd -- "${OUTPUT_DIR}" && pwd)"

for architecture in amd64 arm64 386; do
  binary="${PROJECT_DIR}/dist/ha4win-${VERSION}-windows-${architecture}/ha4win.exe"
  asset="${OUTPUT_DIR}/ha4win-${VERSION}-windows-${architecture}.zip"
  if [[ ! -f "${binary}" ]]; then
    echo "Binary not found: ${binary}; run VERSION=${VERSION} ./build/build.sh first" >&2
    exit 1
  fi
  temporary="$(mktemp -d)"
  cp "${binary}" "${temporary}/ha4win.exe"
  (
    cd "${temporary}"
    zip -q -9 "${asset}" ha4win.exe
  )
  rm -rf -- "${temporary}"
  if command -v sha256sum >/dev/null 2>&1; then
    digest="$(sha256sum "${asset}" | awk '{print $1}')"
  else
    digest="$(shasum -a 256 "${asset}" | awk '{print $1}')"
  fi
  echo "Built ${asset} (${digest})"
done
