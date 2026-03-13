#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HA4LINUX_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

APP_SRC="${HA4LINUX_ROOT}/app"
REQ_SRC="${HA4LINUX_ROOT}/requirements.txt"
SERVICE_SRC="${HA4LINUX_ROOT}/packaging/assets/ha4linux.service"
CONFIG_EXAMPLE_SRC="${HA4LINUX_ROOT}/packaging/assets/ha4linux.config.example.json"
SUDOERS_SRC="${HA4LINUX_ROOT}/packaging/assets/sudoers.ha4linux"

INSTALL_DIR="/opt/ha4linux"
ETC_DIR="/etc/ha4linux"
CERT_DIR="/etc/ha4linux/certs"
POLICY_DIR="/etc/ha4linux/policies"
POLICY_FILE="/etc/ha4linux/policies/apps.json"
CONFIG_FILE_DEFAULT="/etc/ha4linux/config.json"
ENV_FILE="/etc/ha4linux/ha4linux.env"
SERVICE_FILE="/etc/systemd/system/ha4linux.service"
SUDOERS_FILE="/etc/sudoers.d/ha4linux"
LOG_DIR="/var/log/ha4linux"
DATA_DIR="/var/lib/ha4linux"
SKIP_DEPS=false
START_SERVICE=true

log() { echo "[ha4linux-installer] $*"; }
fail() { echo "[ha4linux-installer] ERROR: $*" >&2; exit 1; }

append_if_missing() {
  local file="$1"
  local key="$2"
  local value="$3"
  if ! grep -q "^${key}=" "${file}" 2>/dev/null; then
    echo "${key}=${value}" >> "${file}"
  fi
}

write_json_config() {
  local destination="$1"
  python3 - "${destination}" "${CONFIG_EXAMPLE_SRC}" << 'PY'
import json
import os
import sys
from pathlib import Path


def as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def as_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


destination = Path(sys.argv[1])
template = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
env = os.environ

api = template.setdefault("api", {})
api["bind_host"] = env.get("HA4LINUX_BIND_HOST", api.get("bind_host", "0.0.0.0"))
api["bind_port"] = as_int(env.get("HA4LINUX_BIND_PORT"), int(api.get("bind_port", 8099)))
api["token"] = env.get("HA4LINUX_API_TOKEN", api.get("token", ""))

tls = template.setdefault("tls", {})
tls["enabled"] = as_bool(env.get("HA4LINUX_TLS_ENABLED"), bool(tls.get("enabled", True)))
tls["certfile"] = env.get("HA4LINUX_TLS_CERTFILE", tls.get("certfile", "/etc/ha4linux/certs/server.crt"))
tls["keyfile"] = env.get("HA4LINUX_TLS_KEYFILE", tls.get("keyfile", "/etc/ha4linux/certs/server.key"))

template["readonly_mode"] = as_bool(env.get("HA4LINUX_READONLY_MODE"), bool(template.get("readonly_mode", False)))

modules = template.setdefault("modules", {})
modules.setdefault("cpu", {})["enabled"] = as_bool(env.get("HA4LINUX_SENSORS_CPU"), True)
modules.setdefault("memory", {})["enabled"] = as_bool(env.get("HA4LINUX_SENSORS_MEMORY"), True)
modules.setdefault("raid", {})["enabled"] = as_bool(env.get("HA4LINUX_SENSORS_RAID"), True)
modules.setdefault("app_policies", {})["enabled"] = as_bool(env.get("HA4LINUX_SENSORS_APP_POLICIES"), True)

network = modules.setdefault("network", {})
network["enabled"] = as_bool(env.get("HA4LINUX_SENSORS_NETWORK"), True)
network["include_interfaces"] = as_csv(env.get("HA4LINUX_NETWORK_INCLUDE_INTERFACES"))
network["exclude_interfaces"] = as_csv(env.get("HA4LINUX_NETWORK_EXCLUDE_INTERFACES"))
network["aggregate_mode"] = env.get("HA4LINUX_NETWORK_AGGREGATE_MODE", network.get("aggregate_mode", "selected"))

virtualbox = modules.setdefault("virtualbox", {})
virtualbox["enabled"] = as_bool(env.get("HA4LINUX_SENSORS_VIRTUALBOX"), False)
virtualbox["user"] = env.get("HA4LINUX_VIRTUALBOX_USER", virtualbox.get("user", ""))

services = modules.setdefault("services", {})
services["enabled"] = as_bool(env.get("HA4LINUX_SENSORS_SERVICES"), False)
services["watchlist"] = as_csv(
    env.get("HA4LINUX_SERVICES_WATCHLIST", ",".join(services.get("watchlist", [])))
)

filesystem = modules.setdefault("filesystem", {})
filesystem["enabled"] = as_bool(env.get("HA4LINUX_SENSORS_FILESYSTEM"), True)
filesystem["exclude_types"] = as_csv(
    env.get("HA4LINUX_FILESYSTEM_EXCLUDE_TYPES", ",".join(filesystem.get("exclude_types", [])))
)
filesystem["exclude_mounts"] = as_csv(
    env.get("HA4LINUX_FILESYSTEM_EXCLUDE_MOUNTS", ",".join(filesystem.get("exclude_mounts", [])))
)

actuators = template.setdefault("actuators", {})
session = actuators.setdefault("session", {})
session["enabled"] = as_bool(env.get("HA4LINUX_ACTUATOR_SESSION"), True)
session["allowed_users"] = as_csv(env.get("HA4LINUX_ALLOWED_SESSION_USERS"))

app_policy_actuator = actuators.setdefault("app_policy", {})
app_policy_actuator["enabled"] = as_bool(env.get("HA4LINUX_ACTUATOR_APP_POLICY"), True)

app_policies = template.setdefault("app_policies", {})
app_policies["file"] = env.get("HA4LINUX_APP_POLICY_FILE", app_policies.get("file", "/etc/ha4linux/policies/apps.json"))
app_policies["use_sudo_kill"] = as_bool(
    env.get("HA4LINUX_APP_POLICY_USE_SUDO_KILL"),
    bool(app_policies.get("use_sudo_kill", True)),
)

management = template.setdefault("management", {})
remote_update = management.setdefault("remote_update", {})
remote_update["enabled"] = as_bool(env.get("HA4LINUX_REMOTE_UPDATE_ENABLED"), False)
remote_update["manifest_url"] = env.get("HA4LINUX_REMOTE_UPDATE_MANIFEST_URL", remote_update.get("manifest_url", ""))
remote_update["channel"] = env.get("HA4LINUX_REMOTE_UPDATE_CHANNEL", remote_update.get("channel", "stable"))
remote_update["check_interval_sec"] = as_int(
    env.get("HA4LINUX_REMOTE_UPDATE_CHECK_INTERVAL_SEC"),
    int(remote_update.get("check_interval_sec", 1800)),
)
remote_update["check_timeout_sec"] = as_int(
    env.get("HA4LINUX_REMOTE_UPDATE_CHECK_TIMEOUT_SEC"),
    int(remote_update.get("check_timeout_sec", 10)),
)
remote_update["command_timeout_sec"] = as_int(
    env.get("HA4LINUX_REMOTE_UPDATE_COMMAND_TIMEOUT_SEC"),
    int(remote_update.get("command_timeout_sec", 300)),
)
remote_update["apply_command"] = env.get(
    "HA4LINUX_REMOTE_UPDATE_APPLY_COMMAND",
    remote_update.get("apply_command", ""),
)
remote_update["rollback_command"] = env.get(
    "HA4LINUX_REMOTE_UPDATE_ROLLBACK_COMMAND",
    remote_update.get("rollback_command", ""),
)
remote_update["allow_in_readonly"] = as_bool(
    env.get("HA4LINUX_REMOTE_UPDATE_ALLOW_IN_READONLY"),
    bool(remote_update.get("allow_in_readonly", False)),
)

destination.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
PY
}

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
  [[ -f "${CONFIG_EXAMPLE_SRC}" ]] || fail "config template not found"

  mkdir -p "${INSTALL_DIR}" "${ETC_DIR}" "${CERT_DIR}" "${POLICY_DIR}" "${LOG_DIR}" "${DATA_DIR}"
  chown root:ha4linux "${POLICY_DIR}"
  chmod 770 "${POLICY_DIR}"

  cp -a "${APP_SRC}" "${INSTALL_DIR}/"
  cp -a "${REQ_SRC}" "${INSTALL_DIR}/requirements.txt"

  chown -R root:root "${INSTALL_DIR}"
  chown -R ha4linux:ha4linux "${LOG_DIR}" "${DATA_DIR}"

  if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
  fi

  if [[ -z "${HA4LINUX_API_TOKEN:-}" ]]; then
    export HA4LINUX_API_TOKEN
    HA4LINUX_API_TOKEN="$(openssl rand -hex 24)"
    log "Generated initial API token for structured config"
  fi

  config_file="${HA4LINUX_CONFIG_FILE:-${CONFIG_FILE_DEFAULT}}"
  if [[ ! -f "${config_file}" ]]; then
    write_json_config "${config_file}"
    chmod 640 "${config_file}"
    chown root:ha4linux "${config_file}"
    log "Created structured config in ${config_file}"
  fi

  if [[ ! -f "${ENV_FILE}" ]]; then
    printf 'HA4LINUX_CONFIG_FILE=%s\n' "${config_file}" > "${ENV_FILE}"
    chmod 640 "${ENV_FILE}"
    chown root:ha4linux "${ENV_FILE}"
    log "Created bootstrap env file in ${ENV_FILE}"
  else
    append_if_missing "${ENV_FILE}" HA4LINUX_CONFIG_FILE "${config_file}"
    chmod 640 "${ENV_FILE}"
    chown root:ha4linux "${ENV_FILE}"
  fi

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
  systemctl enable ha4linux.service >/dev/null 2>&1 || true
  systemctl restart ha4linux.service
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
  log "Config file: ${config_file:-${CONFIG_FILE_DEFAULT}}"
  log "Bootstrap env: ${ENV_FILE}"
  log "Service: systemctl status ha4linux.service"
}

main "$@"
