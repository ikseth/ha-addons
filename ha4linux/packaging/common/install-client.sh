#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HA4LINUX_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

APP_SRC="${HA4LINUX_ROOT}/app"
REQ_SRC="${HA4LINUX_ROOT}/requirements.txt"
SERVICE_SRC="${HA4LINUX_ROOT}/packaging/assets/ha4linux.service"
ENV_EXAMPLE_SRC="${HA4LINUX_ROOT}/packaging/assets/ha4linux.env.example"
SUDOERS_SRC="${HA4LINUX_ROOT}/packaging/assets/sudoers.ha4linux"

INSTALL_DIR="/opt/ha4linux"
ETC_DIR="/etc/ha4linux"
CERT_DIR="/etc/ha4linux/certs"
POLICY_DIR="/etc/ha4linux/policies"
POLICY_FILE="/etc/ha4linux/policies/apps.json"
ENV_FILE="/etc/ha4linux/ha4linux.env"
SERVICE_FILE="/etc/systemd/system/ha4linux.service"
SUDOERS_FILE="/etc/sudoers.d/ha4linux"
LOG_DIR="/var/log/ha4linux"
DATA_DIR="/var/lib/ha4linux"
SKIP_DEPS=false
START_SERVICE=true

log() { echo "[ha4linux-installer] $*"; }
fail() { echo "[ha4linux-installer] ERROR: $*" >&2; exit 1; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "Run as root"
  fi
}

load_os_release() {
  if [[ ! -f /etc/os-release ]]; then
    fail "Cannot detect distribution: /etc/os-release not found"
  fi
  # shellcheck disable=SC1091
  source /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_LIKE="${ID_LIKE:-}"
  log "Detected distro: ${OS_ID} (${OS_LIKE})"
}

install_deps() {
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y python3 python3-venv python3-pip sudo openssl ca-certificates
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip sudo openssl ca-certificates
    return
  fi

  if command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip sudo openssl ca-certificates
    return
  fi

  if command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive refresh
    zypper --non-interactive install python3 python3-pip sudo openssl ca-certificates
    return
  fi

  if command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm python python-pip sudo openssl ca-certificates
    return
  fi

  fail "Unsupported package manager"
}

ensure_system_user() {
  getent group ha4linux >/dev/null || groupadd --system ha4linux

  if ! id -u ha4linux >/dev/null 2>&1; then
    useradd \
      --system \
      --gid ha4linux \
      --home-dir "${DATA_DIR}" \
      --create-home \
      --shell /usr/sbin/nologin \
      ha4linux
  fi
}

install_files() {
  [[ -d "${APP_SRC}" ]] || fail "App source not found at ${APP_SRC}"
  [[ -f "${REQ_SRC}" ]] || fail "requirements.txt not found"

  mkdir -p "${INSTALL_DIR}" "${ETC_DIR}" "${CERT_DIR}" "${POLICY_DIR}" "${LOG_DIR}" "${DATA_DIR}"
  chown root:ha4linux "${POLICY_DIR}"
  chmod 770 "${POLICY_DIR}"

  cp -a "${APP_SRC}" "${INSTALL_DIR}/"
  cp -a "${REQ_SRC}" "${INSTALL_DIR}/requirements.txt"

  chown -R root:root "${INSTALL_DIR}"
  chown -R ha4linux:ha4linux "${LOG_DIR}" "${DATA_DIR}"

  if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${ENV_EXAMPLE_SRC}" "${ENV_FILE}"
    TOKEN="$(openssl rand -hex 24)"
    sed -i "s/^HA4LINUX_API_TOKEN=.*/HA4LINUX_API_TOKEN=${TOKEN}/" "${ENV_FILE}"
    chmod 640 "${ENV_FILE}"
    chown root:ha4linux "${ENV_FILE}"
    log "Generated initial API token in ${ENV_FILE}"
  fi

  # Keep config forwards-compatible during upgrades.
  append_if_missing() {
    key="$1"; value="$2"
    if ! grep -q "^${key}=" "${ENV_FILE}"; then
      echo "${key}=${value}" >> "${ENV_FILE}"
    fi
  }
  append_if_missing HA4LINUX_SENSORS_APP_POLICIES true
  append_if_missing HA4LINUX_SENSORS_RAID true
  append_if_missing HA4LINUX_SENSORS_VIRTUALBOX false
  append_if_missing HA4LINUX_SENSORS_SERVICES false
  append_if_missing HA4LINUX_READONLY_MODE false
  append_if_missing HA4LINUX_VIRTUALBOX_USER ""
  append_if_missing HA4LINUX_SERVICES_WATCHLIST "apache2.service,mariadb.service,smbd.service,docker.service"
  append_if_missing HA4LINUX_ACTUATOR_APP_POLICY true
  append_if_missing HA4LINUX_APP_POLICY_FILE "${POLICY_FILE}"
  append_if_missing HA4LINUX_APP_POLICY_USE_SUDO_KILL true

  if [[ ! -f "${CERT_DIR}/server.crt" || ! -f "${CERT_DIR}/server.key" ]]; then
    HOST_CN="$(hostname -f 2>/dev/null || hostname)"
    openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
      -keyout "${CERT_DIR}/server.key" \
      -out "${CERT_DIR}/server.crt" \
      -subj "/CN=${HOST_CN}" >/dev/null 2>&1
    chmod 640 "${CERT_DIR}/server.key"
    chmod 644 "${CERT_DIR}/server.crt"
    chown root:ha4linux "${CERT_DIR}/server.key" "${CERT_DIR}/server.crt"
    log "Generated self-signed TLS certificate in ${CERT_DIR}"
  fi

  if [[ ! -f "${POLICY_FILE}" ]]; then
    cat > "${POLICY_FILE}" << 'EOF_POLICY'
{
  "apps": []
}
EOF_POLICY
    chmod 640 "${POLICY_FILE}"
    chown root:ha4linux "${POLICY_FILE}"
    log "Created empty app policy file in ${POLICY_FILE}"
  else
    chown root:ha4linux "${POLICY_FILE}"
    chmod 660 "${POLICY_FILE}"
  fi
}

setup_venv() {
  local pybin
  if command -v python3 >/dev/null 2>&1; then
    pybin="python3"
  elif command -v python >/dev/null 2>&1; then
    pybin="python"
  else
    fail "Python interpreter not found"
  fi

  "${pybin}" -m venv "${INSTALL_DIR}/.venv"
  "${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip
  "${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"
}

install_service() {
  cp "${SERVICE_SRC}" "${SERVICE_FILE}"
  chmod 644 "${SERVICE_FILE}"

  cp "${SUDOERS_SRC}" "${SUDOERS_FILE}"
  chmod 440 "${SUDOERS_FILE}"

  if command -v visudo >/dev/null 2>&1; then
    visudo -cf "${SUDOERS_FILE}" >/dev/null
  fi

  systemctl daemon-reload
  systemctl enable --now ha4linux.service
  systemctl --no-pager --full status ha4linux.service | sed -n '1,20p'
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --skip-deps)
        SKIP_DEPS=true
        shift
        ;;
      --no-start)
        START_SERVICE=false
        shift
        ;;
      *)
        fail "Unknown option: $1"
        ;;
    esac
  done

  require_root
  load_os_release
  if [[ "${SKIP_DEPS}" != "true" ]]; then
    install_deps
  fi
  ensure_system_user
  install_files
  setup_venv
  if [[ "${START_SERVICE}" == "true" ]]; then
    install_service
  else
    cp "${SERVICE_SRC}" "${SERVICE_FILE}"
    chmod 644 "${SERVICE_FILE}"
    cp "${SUDOERS_SRC}" "${SUDOERS_FILE}"
    chmod 440 "${SUDOERS_FILE}"
    if command -v visudo >/dev/null 2>&1; then
      visudo -cf "${SUDOERS_FILE}" >/dev/null
    fi
    systemctl daemon-reload
    log "Service files installed (not started)"
  fi

  log "Installation complete"
  log "Config file: ${ENV_FILE}"
  log "Service: systemctl status ha4linux.service"
}

main "$@"
