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
if command -v dpkg >/dev/null 2>&1; then
  DEFAULT_ARCH="$(dpkg --print-architecture)"
else
  case "$(uname -m)" in
    x86_64) DEFAULT_ARCH="amd64" ;;
    aarch64|arm64) DEFAULT_ARCH="arm64" ;;
    armv7l) DEFAULT_ARCH="armhf" ;;
    i386|i686) DEFAULT_ARCH="i386" ;;
    *) DEFAULT_ARCH="all" ;;
  esac
fi
ARCH="${2:-${DEFAULT_ARCH}}"
PKG_NAME="ha4linux-client"
WORK_DIR="$(mktemp -d)"
PKG_DIR="${WORK_DIR}/${PKG_NAME}_${VERSION}_${ARCH}"

mkdir -p "${PKG_DIR}/DEBIAN" "${PKG_DIR}/usr/lib/ha4linux" "${PKG_DIR}/usr/sbin"

cp -a "${HA4LINUX_ROOT}/app" "${PKG_DIR}/usr/lib/ha4linux/"
cp -a "${HA4LINUX_ROOT}/requirements.txt" "${PKG_DIR}/usr/lib/ha4linux/"
cp -a "${HA4LINUX_ROOT}/packaging/assets" "${PKG_DIR}/usr/lib/ha4linux/"
cp -a "${HA4LINUX_ROOT}/packaging/common/install-client.sh" "${PKG_DIR}/usr/lib/ha4linux/"
cp -a "${HA4LINUX_ROOT}/packaging/common/uninstall-client.sh" "${PKG_DIR}/usr/lib/ha4linux/"

cat > "${PKG_DIR}/usr/sbin/ha4linux-install-client" << 'SH'
#!/usr/bin/env bash
exec /usr/lib/ha4linux/install-client.sh "$@"
SH
chmod 755 "${PKG_DIR}/usr/sbin/ha4linux-install-client"

cat > "${PKG_DIR}/usr/sbin/ha4linux-uninstall-client" << 'SH'
#!/usr/bin/env bash
exec /usr/lib/ha4linux/uninstall-client.sh "$@"
SH
chmod 755 "${PKG_DIR}/usr/sbin/ha4linux-uninstall-client"

cat > "${PKG_DIR}/DEBIAN/control" << EOF_CTRL
Package: ${PKG_NAME}
Version: ${VERSION}
Section: admin
Priority: optional
Architecture: ${ARCH}
Maintainer: HA4Linux <noreply@example.com>
Depends: python3, python3-venv, python3-pip, sudo, openssl, ca-certificates, systemd
Description: HA4Linux client API installer and service
 Installs HA4Linux API as a systemd service with dedicated user, TLS and sudoers policy.
EOF_CTRL

cat > "${PKG_DIR}/DEBIAN/postinst" << 'EOF_POST'
#!/usr/bin/env bash
set -e
/usr/lib/ha4linux/install-client.sh --skip-deps
EOF_POST
chmod 755 "${PKG_DIR}/DEBIAN/postinst"

cat > "${PKG_DIR}/DEBIAN/prerm" << 'EOF_PRERM'
#!/usr/bin/env bash
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
  /usr/lib/ha4linux/uninstall-client.sh || true
fi
EOF_PRERM
chmod 755 "${PKG_DIR}/DEBIAN/prerm"

OUT_FILE="${HA4LINUX_ROOT}/packaging/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build "${PKG_DIR}" "${OUT_FILE}" >/dev/null

echo "Built: ${OUT_FILE}"
rm -rf "${WORK_DIR}"
