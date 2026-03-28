#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HA4LINUX_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

APP_SRC="${HA4LINUX_ROOT}/app"
REQ_SRC="${HA4LINUX_ROOT}/requirements.txt"
SERVICE_SRC="${HA4LINUX_ROOT}/packaging/assets/ha4linux.service"
CONFIG_EXAMPLE_SRC="${HA4LINUX_ROOT}/packaging/assets/ha4linux.config.example.json"
SUDOERS_SRC="${HA4LINUX_ROOT}/packaging/assets/sudoers.ha4linux"
UPDATE_APPLY_SRC="${HA4LINUX_ROOT}/packaging/assets/ha4linux-update-apply"
UPDATE_ROLLBACK_SRC="${HA4LINUX_ROOT}/packaging/assets/ha4linux-update-rollback"
UPDATE_APPLY_ROOT_SRC="${HA4LINUX_ROOT}/packaging/assets/ha4linux-update-apply-root.py"
UPDATE_ROLLBACK_ROOT_SRC="${HA4LINUX_ROOT}/packaging/assets/ha4linux-update-rollback-root.py"

INSTALL_DIR="/opt/ha4linux"
UPDATE_DIR="${INSTALL_DIR}/update"
ETC_DIR="/etc/ha4linux"
CERT_DIR="/etc/ha4linux/certs"
POLICY_DIR="/etc/ha4linux/policies"
POLICY_FILE="/etc/ha4linux/policies/apps.json"
CONFIG_FILE_DEFAULT="/etc/ha4linux/config.json"
ENV_FILE="/etc/ha4linux/ha4linux.env"
SERVICE_FILE="/etc/systemd/system/ha4linux.service"
SUDOERS_FILE="/etc/sudoers.d/ha4linux"
UPDATE_APPLY_TARGET="${UPDATE_DIR}/ha4linux-update-apply"
UPDATE_ROLLBACK_TARGET="${UPDATE_DIR}/ha4linux-update-rollback"
UPDATE_APPLY_ROOT_TARGET="${UPDATE_DIR}/ha4linux-update-apply-root.py"
UPDATE_ROLLBACK_ROOT_TARGET="${UPDATE_DIR}/ha4linux-update-rollback-root.py"
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

copy_if_different() {
  local src="$1"
  local dst="$2"
  local mode="$3"
  local tmp_file

  mkdir -p "$(dirname "${dst}")"
  if [[ -e "${dst}" ]] && cmp -s "${src}" "${dst}"; then
    return
  fi

  tmp_file="$(mktemp "${TMPDIR:-/tmp}/ha4linux-install.XXXXXX")"
  cp "${src}" "${tmp_file}"
  chmod "${mode}" "${tmp_file}"
  cp -f "${tmp_file}" "${dst}"
  rm -f "${tmp_file}"
}

render_sudoers_policy() {
  local destination="$1"
  local selected_config="${config_file:-${HA4LINUX_CONFIG_FILE:-${CONFIG_FILE_DEFAULT}}}"

  python3 - "${destination}" "${selected_config}" << 'PY'
import json
import os
import sys
from pathlib import Path


def as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def read_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def nested_get(data: dict, *keys: str, default=None):
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return as_bool(value, default)


def env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip()


destination = Path(sys.argv[1])
config = read_config(Path(sys.argv[2]))

readonly_mode = env_bool(
    "HA4LINUX_READONLY_MODE",
    as_bool(nested_get(config, "readonly_mode", default=False), False),
)
sensors_virtualbox = env_bool(
    "HA4LINUX_SENSORS_VIRTUALBOX",
    as_bool(nested_get(config, "modules", "virtualbox", "enabled", default=False), False),
)
actuator_virtualbox = env_bool(
    "HA4LINUX_ACTUATOR_VIRTUALBOX",
    as_bool(nested_get(config, "actuators", "virtualbox", "enabled", default=False), False),
)

if readonly_mode:
    actuator_virtualbox = False

virtualbox_enabled = sensors_virtualbox or actuator_virtualbox

lines: list[str] = []
lines.append(
    "Cmnd_Alias HA4LINUX_SESSION = /usr/bin/loginctl activate *, /usr/bin/loginctl terminate-session *"
)
lines.append(
    "Cmnd_Alias HA4LINUX_APPS = /usr/bin/systemctl stop *, /bin/kill -15 *, /bin/kill -9 *, /usr/bin/kill -15 *, /usr/bin/kill -9 *"
)

if virtualbox_enabled:
    virtualbox_commands = [
        "/usr/bin/VBoxManage list vms",
        "/usr/bin/VBoxManage list runningvms",
        "/usr/bin/vboxmanage list vms",
        "/usr/bin/vboxmanage list runningvms",
    ]
    if actuator_virtualbox:
        virtualbox_commands.extend(
            [
                "/usr/bin/VBoxManage showvminfo * --machinereadable",
                "/usr/bin/VBoxManage startvm * --type *",
                "/usr/bin/VBoxManage controlvm * acpipowerbutton",
                "/usr/bin/VBoxManage controlvm * savestate",
                "/usr/bin/VBoxManage controlvm * poweroff",
                "/usr/bin/VBoxManage controlvm * reset",
                "/usr/bin/vboxmanage showvminfo * --machinereadable",
                "/usr/bin/vboxmanage startvm * --type *",
                "/usr/bin/vboxmanage controlvm * acpipowerbutton",
                "/usr/bin/vboxmanage controlvm * savestate",
                "/usr/bin/vboxmanage controlvm * poweroff",
                "/usr/bin/vboxmanage controlvm * reset",
            ]
        )
    lines.append(f"Cmnd_Alias HA4LINUX_VBOX = {', '.join(virtualbox_commands)}")

lines.append(
    "Cmnd_Alias HA4LINUX_UPDATE = /opt/ha4linux/update/ha4linux-update-apply-root.py, /opt/ha4linux/update/ha4linux-update-rollback-root.py"
)
lines.append("ha4linux ALL=(root) NOPASSWD: HA4LINUX_SESSION, HA4LINUX_APPS")
lines.append("ha4linux ALL=(root) NOPASSWD: HA4LINUX_UPDATE")

if virtualbox_enabled:
    lines.append("ha4linux ALL=(ALL) NOPASSWD: HA4LINUX_VBOX")

lines.append("Defaults:ha4linux !requiretty")

destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

install_sudoers_policy() {
  local rendered_file
  local readonly_mode_value

  readonly_mode_value="$(_config_readonly_mode)"
  if [[ "${readonly_mode_value}" == "true" ]] && [[ -f "${SUDOERS_FILE}" ]]; then
    if command -v visudo >/dev/null 2>&1; then
      visudo -cf "${SUDOERS_FILE}" >/dev/null
    fi
    log "Readonly mode enabled; preserving existing sudoers policy in ${SUDOERS_FILE}"
    return
  fi

  rendered_file="$(mktemp "${TMPDIR:-/tmp}/ha4linux-sudoers.XXXXXX")"
  render_sudoers_policy "${rendered_file}"
  chmod 440 "${rendered_file}"

  if command -v visudo >/dev/null 2>&1; then
    visudo -cf "${rendered_file}" >/dev/null
  fi

  copy_if_different "${rendered_file}" "${SUDOERS_FILE}" 440
  rm -f "${rendered_file}"
}

_config_readonly_mode() {
  local selected_config="${config_file:-${HA4LINUX_CONFIG_FILE:-${CONFIG_FILE_DEFAULT}}}"

  python3 - "${selected_config}" << 'PY'
import json
import os
import sys
from pathlib import Path


def as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


config_path = Path(sys.argv[1])
config: dict = {}
if config_path.exists():
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            config = payload
    except Exception:
        config = {}

if "HA4LINUX_READONLY_MODE" in os.environ:
    result = as_bool(os.environ["HA4LINUX_READONLY_MODE"], False)
else:
    result = as_bool(config.get("readonly_mode"), False)

print("true" if result else "false")
PY
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


def prefer_env_string(name: str, default: str) -> str:
    value = env.get(name)
    if value is None:
        return default
    token = value.strip()
    return token if token else default


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

system_info = modules.setdefault("system_info", {})
system_info["enabled"] = as_bool(env.get("HA4LINUX_SENSORS_SYSTEM_INFO"), True)
system_info["updates_enabled"] = as_bool(env.get("HA4LINUX_SYSTEM_UPDATES_ENABLED"), True)
system_info["updates_check_interval_sec"] = as_int(
    env.get("HA4LINUX_SYSTEM_UPDATES_CHECK_INTERVAL_SEC"),
    int(system_info.get("updates_check_interval_sec", 86400)),
)
system_info["updates_command_timeout_sec"] = as_int(
    env.get("HA4LINUX_SYSTEM_UPDATES_COMMAND_TIMEOUT_SEC"),
    int(system_info.get("updates_command_timeout_sec", 60)),
)
system_info["updates_max_packages"] = as_int(
    env.get("HA4LINUX_SYSTEM_UPDATES_MAX_PACKAGES"),
    int(system_info.get("updates_max_packages", 25)),
)

actuators = template.setdefault("actuators", {})
session = actuators.setdefault("session", {})
session["enabled"] = as_bool(env.get("HA4LINUX_ACTUATOR_SESSION"), True)
session["allowed_users"] = as_csv(env.get("HA4LINUX_ALLOWED_SESSION_USERS"))

app_policy_actuator = actuators.setdefault("app_policy", {})
app_policy_actuator["enabled"] = as_bool(env.get("HA4LINUX_ACTUATOR_APP_POLICY"), True)

virtualbox_actuator = actuators.setdefault("virtualbox", {})
virtualbox_actuator["enabled"] = as_bool(env.get("HA4LINUX_ACTUATOR_VIRTUALBOX"), False)
virtualbox_actuator["allowed_actions"] = as_csv(
    env.get(
        "HA4LINUX_VIRTUALBOX_ALLOWED_ACTIONS",
        ",".join(virtualbox_actuator.get("allowed_actions", [])),
    )
)
virtualbox_actuator["allowed_vms"] = as_csv(
    env.get(
        "HA4LINUX_VIRTUALBOX_ALLOWED_VMS",
        ",".join(virtualbox_actuator.get("allowed_vms", [])),
    )
)
virtualbox_actuator["start_type"] = prefer_env_string(
    "HA4LINUX_VIRTUALBOX_START_TYPE",
    str(virtualbox_actuator.get("start_type", "headless")),
)
virtualbox_actuator["switch_turn_off_action"] = prefer_env_string(
    "HA4LINUX_VIRTUALBOX_SWITCH_TURN_OFF_ACTION",
    str(virtualbox_actuator.get("switch_turn_off_action", "acpi_shutdown")),
)

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
remote_update["apply_command"] = prefer_env_string(
    "HA4LINUX_REMOTE_UPDATE_APPLY_COMMAND",
    str(remote_update.get("apply_command", "")),
)
remote_update["rollback_command"] = prefer_env_string(
    "HA4LINUX_REMOTE_UPDATE_ROLLBACK_COMMAND",
    str(remote_update.get("rollback_command", "")),
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
  [[ -f "${UPDATE_APPLY_SRC}" ]] || fail "update apply helper not found"
  [[ -f "${UPDATE_ROLLBACK_SRC}" ]] || fail "update rollback helper not found"
  [[ -f "${UPDATE_APPLY_ROOT_SRC}" ]] || fail "root update apply helper not found"
  [[ -f "${UPDATE_ROLLBACK_ROOT_SRC}" ]] || fail "root update rollback helper not found"

  mkdir -p "${INSTALL_DIR}" "${UPDATE_DIR}" "${ETC_DIR}" "${CERT_DIR}" "${POLICY_DIR}" "${LOG_DIR}" "${DATA_DIR}"
  chown root:ha4linux "${POLICY_DIR}"
  chmod 770 "${POLICY_DIR}"

  rm -rf "${INSTALL_DIR}/app"
  rm -f "${INSTALL_DIR}/requirements.txt"
  cp -a "${APP_SRC}" "${INSTALL_DIR}/"
  cp -a "${REQ_SRC}" "${INSTALL_DIR}/requirements.txt"
  install -m 755 "${UPDATE_APPLY_SRC}" "${UPDATE_APPLY_TARGET}"
  install -m 755 "${UPDATE_ROLLBACK_SRC}" "${UPDATE_ROLLBACK_TARGET}"
  install -m 755 "${UPDATE_APPLY_ROOT_SRC}" "${UPDATE_APPLY_ROOT_TARGET}"
  install -m 755 "${UPDATE_ROLLBACK_ROOT_SRC}" "${UPDATE_ROLLBACK_ROOT_TARGET}"

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
  copy_if_different "${SERVICE_SRC}" "${SERVICE_FILE}" 644
  install_sudoers_policy

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
    copy_if_different "${SERVICE_SRC}" "${SERVICE_FILE}" 644
    install_sudoers_policy
    systemctl daemon-reload
    log "Service files installed (not started)"
  fi

  log "Installation complete"
  log "Config file: ${config_file:-${CONFIG_FILE_DEFAULT}}"
  log "Bootstrap env: ${ENV_FILE}"
  log "Service: systemctl status ha4linux.service"
}

main "$@"
