import json
import os
from pathlib import Path
from typing import Any

_MISSING = object()


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _as_csv(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _as_int(
    value: Any,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default

    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return parsed


def _as_str(value: Any, default: str) -> str:
    if value is None:
        return default
    return str(value).strip()


def _as_choice(value: Any, default: str, allowed: set[str]) -> str:
    token = _as_str(value, default).lower()
    return token if token in allowed else default


def _lookup_config_value(config: dict[str, Any], *paths: str) -> Any:
    current: Any = config
    for token in paths:
        if not isinstance(current, dict) or token not in current:
            return _MISSING
        current = current[token]
    return current


def _pick_config_value(config: dict[str, Any], *candidates: tuple[str, ...]) -> Any:
    for path in candidates:
        value = _lookup_config_value(config, *path)
        if value is not _MISSING:
            return value
    return _MISSING


def _discover_config_file() -> str:
    explicit = os.getenv("HA4LINUX_CONFIG_FILE", "").strip()
    if explicit:
        return explicit

    for candidate in ("/etc/ha4linux/config.json", "/data/options.json"):
        if Path(candidate).is_file():
            return candidate
    return ""


def _load_json_config(path: str) -> dict[str, Any]:
    if not path:
        return {}

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _resolve_value(
    config: dict[str, Any],
    env_key: str,
    default: Any,
    *candidates: tuple[str, ...],
) -> Any:
    env_value = os.getenv(env_key)
    if env_value is not None:
        return env_value

    json_value = _pick_config_value(config, *candidates)
    if json_value is not _MISSING:
        return json_value

    return default


class Settings:
    config_file: str
    bind_host: str
    bind_port: int
    api_token: str
    tls_enabled: bool
    tls_certfile: str
    tls_keyfile: str
    sensors_cpu: bool
    sensors_memory: bool
    sensors_network: bool
    sensors_raid: bool
    sensors_virtualbox: bool
    sensors_services: bool
    sensors_filesystem: bool
    sensors_app_policies: bool
    actuator_session: bool
    actuator_app_policy: bool
    readonly_mode: bool
    allowed_session_users: set[str]
    virtualbox_user: str
    network_include_interfaces: list[str]
    network_exclude_interfaces: list[str]
    network_aggregate_mode: str
    services_watchlist: list[str]
    app_policy_file: str
    app_policy_use_sudo_kill: bool
    filesystem_exclude_types: list[str]
    filesystem_exclude_mounts: list[str]
    remote_update_enabled: bool
    remote_update_manifest_url: str
    remote_update_channel: str
    remote_update_check_interval_sec: int
    remote_update_check_timeout_sec: int
    remote_update_command_timeout_sec: int
    remote_update_apply_command: str
    remote_update_rollback_command: str
    remote_update_allow_in_readonly: bool

    def __init__(self) -> None:
        self.config_file = _discover_config_file()
        config = _load_json_config(self.config_file)

        self.bind_host = _as_str(
            _resolve_value(
                config,
                "HA4LINUX_BIND_HOST",
                "0.0.0.0",
                ("api", "bind_host"),
                ("bind_host",),
            ),
            "0.0.0.0",
        )
        self.bind_port = _as_int(
            _resolve_value(
                config,
                "HA4LINUX_BIND_PORT",
                8099,
                ("api", "bind_port"),
                ("bind_port",),
            ),
            8099,
            minimum=1,
            maximum=65535,
        )
        self.api_token = _as_str(
            _resolve_value(
                config,
                "HA4LINUX_API_TOKEN",
                "",
                ("api", "token"),
                ("api_token",),
            ),
            "",
        )
        self.tls_enabled = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_TLS_ENABLED",
                True,
                ("tls", "enabled"),
                ("tls_enabled",),
            ),
            True,
        )
        self.tls_certfile = _as_str(
            _resolve_value(
                config,
                "HA4LINUX_TLS_CERTFILE",
                "/ssl/fullchain.pem",
                ("tls", "certfile"),
                ("tls_certfile",),
            ),
            "/ssl/fullchain.pem",
        )
        self.tls_keyfile = _as_str(
            _resolve_value(
                config,
                "HA4LINUX_TLS_KEYFILE",
                "/ssl/privkey.pem",
                ("tls", "keyfile"),
                ("tls_keyfile",),
            ),
            "/ssl/privkey.pem",
        )
        self.sensors_cpu = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_SENSORS_CPU",
                True,
                ("modules", "cpu", "enabled"),
                ("sensors_cpu",),
            ),
            True,
        )
        self.sensors_memory = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_SENSORS_MEMORY",
                True,
                ("modules", "memory", "enabled"),
                ("sensors_memory",),
            ),
            True,
        )
        self.sensors_network = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_SENSORS_NETWORK",
                True,
                ("modules", "network", "enabled"),
                ("sensors_network",),
            ),
            True,
        )
        self.sensors_raid = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_SENSORS_RAID",
                True,
                ("modules", "raid", "enabled"),
                ("sensors_raid",),
            ),
            True,
        )
        self.sensors_virtualbox = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_SENSORS_VIRTUALBOX",
                False,
                ("modules", "virtualbox", "enabled"),
                ("sensors_virtualbox",),
            ),
            False,
        )
        self.sensors_services = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_SENSORS_SERVICES",
                False,
                ("modules", "services", "enabled"),
                ("sensors_services",),
            ),
            False,
        )
        self.sensors_filesystem = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_SENSORS_FILESYSTEM",
                True,
                ("modules", "filesystem", "enabled"),
                ("sensors_filesystem",),
            ),
            True,
        )
        self.sensors_app_policies = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_SENSORS_APP_POLICIES",
                True,
                ("modules", "app_policies", "enabled"),
                ("sensors_app_policies",),
            ),
            True,
        )
        self.readonly_mode = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_READONLY_MODE",
                False,
                ("readonly_mode",),
                ("safety", "readonly_mode"),
            ),
            False,
        )
        self.actuator_session = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_ACTUATOR_SESSION",
                True,
                ("actuators", "session", "enabled"),
                ("actuator_session",),
            ),
            True,
        )
        self.actuator_app_policy = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_ACTUATOR_APP_POLICY",
                True,
                ("actuators", "app_policy", "enabled"),
                ("actuator_app_policy",),
            ),
            True,
        )
        self.virtualbox_user = _as_str(
            _resolve_value(
                config,
                "HA4LINUX_VIRTUALBOX_USER",
                "",
                ("modules", "virtualbox", "user"),
                ("virtualbox_user",),
            ),
            "",
        )
        self.network_include_interfaces = _as_csv(
            _resolve_value(
                config,
                "HA4LINUX_NETWORK_INCLUDE_INTERFACES",
                [],
                ("modules", "network", "include_interfaces"),
                ("network_include_interfaces",),
            )
        )
        self.network_exclude_interfaces = _as_csv(
            _resolve_value(
                config,
                "HA4LINUX_NETWORK_EXCLUDE_INTERFACES",
                [],
                ("modules", "network", "exclude_interfaces"),
                ("network_exclude_interfaces",),
            )
        )
        self.network_aggregate_mode = _as_choice(
            _resolve_value(
                config,
                "HA4LINUX_NETWORK_AGGREGATE_MODE",
                "selected",
                ("modules", "network", "aggregate_mode"),
                ("network_aggregate_mode",),
            ),
            "selected",
            {"selected", "all"},
        )
        self.services_watchlist = _as_csv(
            _resolve_value(
                config,
                "HA4LINUX_SERVICES_WATCHLIST",
                [],
                ("modules", "services", "watchlist"),
                ("services_watchlist",),
            )
        )
        self.app_policy_file = _as_str(
            _resolve_value(
                config,
                "HA4LINUX_APP_POLICY_FILE",
                "/data/app_policies.json",
                ("app_policies", "file"),
                ("app_policy_file",),
            ),
            "/data/app_policies.json",
        )
        self.app_policy_use_sudo_kill = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_APP_POLICY_USE_SUDO_KILL",
                True,
                ("app_policies", "use_sudo_kill"),
                ("app_policy_use_sudo_kill",),
            ),
            True,
        )
        self.filesystem_exclude_types = _as_csv(
            _resolve_value(
                config,
                "HA4LINUX_FILESYSTEM_EXCLUDE_TYPES",
                [
                    "tmpfs",
                    "ramfs",
                    "devtmpfs",
                    "proc",
                    "sysfs",
                    "cgroup",
                    "cgroup2",
                    "pstore",
                    "debugfs",
                    "tracefs",
                    "securityfs",
                    "configfs",
                    "fusectl",
                    "mqueue",
                    "hugetlbfs",
                    "autofs",
                    "bpf",
                    "binfmt_misc",
                    "squashfs",
                    "overlay",
                    "nfs",
                    "nfs4",
                    "cifs",
                    "smbfs",
                    "sshfs",
                    "fuse.sshfs",
                    "glusterfs",
                    "ceph",
                    "9p",
                ],
                ("modules", "filesystem", "exclude_types"),
                ("filesystem_exclude_types",),
            )
        )
        self.filesystem_exclude_mounts = _as_csv(
            _resolve_value(
                config,
                "HA4LINUX_FILESYSTEM_EXCLUDE_MOUNTS",
                ["/proc", "/sys", "/dev", "/run", "/var/lib/docker", "/var/lib/containers"],
                ("modules", "filesystem", "exclude_mounts"),
                ("filesystem_exclude_mounts",),
            )
        )
        self.remote_update_enabled = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_REMOTE_UPDATE_ENABLED",
                False,
                ("management", "remote_update", "enabled"),
                ("remote_update_enabled",),
            ),
            False,
        )
        self.remote_update_manifest_url = _as_str(
            _resolve_value(
                config,
                "HA4LINUX_REMOTE_UPDATE_MANIFEST_URL",
                "",
                ("management", "remote_update", "manifest_url"),
                ("remote_update_manifest_url",),
            ),
            "",
        )
        self.remote_update_channel = _as_str(
            _resolve_value(
                config,
                "HA4LINUX_REMOTE_UPDATE_CHANNEL",
                "stable",
                ("management", "remote_update", "channel"),
                ("remote_update_channel",),
            ),
            "stable",
        ) or "stable"
        self.remote_update_check_interval_sec = _as_int(
            _resolve_value(
                config,
                "HA4LINUX_REMOTE_UPDATE_CHECK_INTERVAL_SEC",
                1800,
                ("management", "remote_update", "check_interval_sec"),
                ("remote_update_check_interval_sec",),
            ),
            1800,
            minimum=30,
            maximum=86400,
        )
        self.remote_update_check_timeout_sec = _as_int(
            _resolve_value(
                config,
                "HA4LINUX_REMOTE_UPDATE_CHECK_TIMEOUT_SEC",
                10,
                ("management", "remote_update", "check_timeout_sec"),
                ("remote_update_check_timeout_sec",),
            ),
            10,
            minimum=3,
            maximum=120,
        )
        self.remote_update_command_timeout_sec = _as_int(
            _resolve_value(
                config,
                "HA4LINUX_REMOTE_UPDATE_COMMAND_TIMEOUT_SEC",
                300,
                ("management", "remote_update", "command_timeout_sec"),
                ("remote_update_command_timeout_sec",),
            ),
            300,
            minimum=30,
            maximum=3600,
        )
        self.remote_update_apply_command = _as_str(
            _resolve_value(
                config,
                "HA4LINUX_REMOTE_UPDATE_APPLY_COMMAND",
                "",
                ("management", "remote_update", "apply_command"),
                ("remote_update_apply_command",),
            ),
            "",
        )
        self.remote_update_rollback_command = _as_str(
            _resolve_value(
                config,
                "HA4LINUX_REMOTE_UPDATE_ROLLBACK_COMMAND",
                "",
                ("management", "remote_update", "rollback_command"),
                ("remote_update_rollback_command",),
            ),
            "",
        )
        self.remote_update_allow_in_readonly = _as_bool(
            _resolve_value(
                config,
                "HA4LINUX_REMOTE_UPDATE_ALLOW_IN_READONLY",
                False,
                ("management", "remote_update", "allow_in_readonly"),
                ("remote_update_allow_in_readonly",),
            ),
            False,
        )

        raw_users = _resolve_value(
            config,
            "HA4LINUX_ALLOWED_SESSION_USERS",
            [],
            ("actuators", "session", "allowed_users"),
            ("allowed_session_users",),
        )
        self.allowed_session_users = {user for user in _as_csv(raw_users) if user}
