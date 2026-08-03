#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
MODULE="github.com/ikseth/ha-addons/ha4win"
VERSION="${VERSION:-0.1.0-dev}"
CHANNEL="${CHANNEL:-dev}"
COMMIT="${COMMIT:-$(git -C "${PROJECT_DIR}" rev-parse --short HEAD 2>/dev/null || printf unknown)}"
BUILD_DATE="${BUILD_DATE:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
DIST_DIR="${PROJECT_DIR}/dist"

mkdir -p "${DIST_DIR}"

for architecture in amd64 arm64 386; do
  output_directory="${DIST_DIR}/ha4win-${VERSION}-windows-${architecture}"
  mkdir -p "${output_directory}"
  (
    cd "${PROJECT_DIR}"
    CGO_ENABLED=0 GOOS=windows GOARCH="${architecture}" go build -trimpath \
      -ldflags "-s -w -X ${MODULE}/internal/version.Version=${VERSION} -X ${MODULE}/internal/version.Commit=${COMMIT} -X ${MODULE}/internal/version.BuildDate=${BUILD_DATE} -X ${MODULE}/internal/version.Channel=${CHANNEL}" \
      -o "${output_directory}/ha4win.exe" ./cmd/ha4win
  )
done

(
  cd "${DIST_DIR}"
  find . -type f -name ha4win.exe -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
