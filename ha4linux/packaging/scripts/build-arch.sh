#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HA4LINUX_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BUILD_DIR="$(mktemp -d)"

cp -a "${HA4LINUX_ROOT}/app" "${BUILD_DIR}/"
cp -a "${HA4LINUX_ROOT}/requirements.txt" "${BUILD_DIR}/"
mkdir -p "${BUILD_DIR}/packaging"
cp -a "${HA4LINUX_ROOT}/packaging/assets" "${BUILD_DIR}/packaging/"
mkdir -p "${BUILD_DIR}/packaging/common"
cp -a "${HA4LINUX_ROOT}/packaging/common/install-client.sh" "${BUILD_DIR}/packaging/common/"
cp -a "${HA4LINUX_ROOT}/packaging/common/uninstall-client.sh" "${BUILD_DIR}/packaging/common/"
cp -a "${HA4LINUX_ROOT}/packaging/arch/PKGBUILD" "${BUILD_DIR}/"
cp -a "${HA4LINUX_ROOT}/packaging/arch/ha4linux-client.install" "${BUILD_DIR}/"

(
  cd "${BUILD_DIR}"
  makepkg -f
)

find "${BUILD_DIR}" -maxdepth 1 -type f -name '*.pkg.tar.*' -exec cp -v {} "${HA4LINUX_ROOT}/packaging/" \;

echo "Arch package copied to ${HA4LINUX_ROOT}/packaging"
rm -rf "${BUILD_DIR}"
