#!/usr/bin/env bash
set -euo pipefail

log() { echo "[ha4linux-uninstall] $*"; }
fail() { echo "[ha4linux-uninstall] ERROR: $*" >&2; exit 1; }

[[ "${EUID}" -eq 0 ]] || fail "Run as root"

systemctl disable --now ha4linux.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/ha4linux.service
rm -rf /etc/systemd/system/ha4linux.service.d
systemctl daemon-reload

rm -f /etc/sudoers.d/ha4linux

rm -rf /opt/ha4linux
rm -rf /etc/ha4linux
rm -rf /var/log/ha4linux
rm -rf /var/lib/ha4linux

if id -u ha4linux >/dev/null 2>&1; then
  userdel ha4linux || true
fi

if getent group ha4linux >/dev/null 2>&1; then
  groupdel ha4linux || true
fi

log "Uninstall complete"
