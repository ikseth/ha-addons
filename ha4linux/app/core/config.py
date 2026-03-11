import os


def _as_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _as_csv(value: str) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _as_int(
    value: str | None,
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


class Settings:
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
        self.bind_host = os.getenv("HA4LINUX_BIND_HOST", "0.0.0.0")
        self.bind_port = _as_int(os.getenv("HA4LINUX_BIND_PORT", "8099"), 8099, minimum=1, maximum=65535)
        self.api_token = os.getenv("HA4LINUX_API_TOKEN", "")
        self.tls_enabled = _as_bool(os.getenv("HA4LINUX_TLS_ENABLED", "true"), True)
        self.tls_certfile = os.getenv("HA4LINUX_TLS_CERTFILE", "/ssl/fullchain.pem")
        self.tls_keyfile = os.getenv("HA4LINUX_TLS_KEYFILE", "/ssl/privkey.pem")
        self.sensors_cpu = _as_bool(os.getenv("HA4LINUX_SENSORS_CPU", "true"), True)
        self.sensors_memory = _as_bool(os.getenv("HA4LINUX_SENSORS_MEMORY", "true"), True)
        self.sensors_network = _as_bool(os.getenv("HA4LINUX_SENSORS_NETWORK", "true"), True)
        self.sensors_raid = _as_bool(os.getenv("HA4LINUX_SENSORS_RAID", "true"), True)
        self.sensors_virtualbox = _as_bool(os.getenv("HA4LINUX_SENSORS_VIRTUALBOX", "false"), False)
        self.sensors_services = _as_bool(os.getenv("HA4LINUX_SENSORS_SERVICES", "false"), False)
        self.sensors_filesystem = _as_bool(
            os.getenv("HA4LINUX_SENSORS_FILESYSTEM", "true"),
            True,
        )
        self.sensors_app_policies = _as_bool(
            os.getenv("HA4LINUX_SENSORS_APP_POLICIES", "true"),
            True,
        )
        self.readonly_mode = _as_bool(os.getenv("HA4LINUX_READONLY_MODE", "false"), False)
        self.actuator_session = _as_bool(os.getenv("HA4LINUX_ACTUATOR_SESSION", "true"), True)
        self.actuator_app_policy = _as_bool(
            os.getenv("HA4LINUX_ACTUATOR_APP_POLICY", "true"),
            True,
        )
        self.virtualbox_user = os.getenv("HA4LINUX_VIRTUALBOX_USER", "").strip()
        self.services_watchlist = _as_csv(os.getenv("HA4LINUX_SERVICES_WATCHLIST", ""))
        self.app_policy_file = os.getenv(
            "HA4LINUX_APP_POLICY_FILE",
            "/data/app_policies.json",
        )
        self.app_policy_use_sudo_kill = _as_bool(
            os.getenv("HA4LINUX_APP_POLICY_USE_SUDO_KILL", "true"),
            True,
        )
        self.filesystem_exclude_types = _as_csv(
            os.getenv(
                "HA4LINUX_FILESYSTEM_EXCLUDE_TYPES",
                (
                    "tmpfs,ramfs,devtmpfs,proc,sysfs,cgroup,cgroup2,pstore,debugfs,tracefs,"
                    "securityfs,configfs,fusectl,mqueue,hugetlbfs,autofs,bpf,binfmt_misc,"
                    "squashfs,overlay,nfs,nfs4,cifs,smbfs,sshfs,fuse.sshfs,glusterfs,ceph,9p"
                ),
            )
        )
        self.filesystem_exclude_mounts = _as_csv(
            os.getenv(
                "HA4LINUX_FILESYSTEM_EXCLUDE_MOUNTS",
                "/proc,/sys,/dev,/run,/var/lib/docker,/var/lib/containers",
            )
        )
        self.remote_update_enabled = _as_bool(
            os.getenv("HA4LINUX_REMOTE_UPDATE_ENABLED", "false"),
            False,
        )
        self.remote_update_manifest_url = os.getenv("HA4LINUX_REMOTE_UPDATE_MANIFEST_URL", "").strip()
        self.remote_update_channel = os.getenv("HA4LINUX_REMOTE_UPDATE_CHANNEL", "stable").strip() or "stable"
        self.remote_update_check_interval_sec = _as_int(
            os.getenv("HA4LINUX_REMOTE_UPDATE_CHECK_INTERVAL_SEC", "1800"),
            1800,
            minimum=30,
            maximum=86400,
        )
        self.remote_update_check_timeout_sec = _as_int(
            os.getenv("HA4LINUX_REMOTE_UPDATE_CHECK_TIMEOUT_SEC", "10"),
            10,
            minimum=3,
            maximum=120,
        )
        self.remote_update_command_timeout_sec = _as_int(
            os.getenv("HA4LINUX_REMOTE_UPDATE_COMMAND_TIMEOUT_SEC", "300"),
            300,
            minimum=30,
            maximum=3600,
        )
        self.remote_update_apply_command = os.getenv("HA4LINUX_REMOTE_UPDATE_APPLY_COMMAND", "").strip()
        self.remote_update_rollback_command = os.getenv(
            "HA4LINUX_REMOTE_UPDATE_ROLLBACK_COMMAND",
            "",
        ).strip()
        self.remote_update_allow_in_readonly = _as_bool(
            os.getenv("HA4LINUX_REMOTE_UPDATE_ALLOW_IN_READONLY", "false"),
            False,
        )

        raw_users = os.getenv("HA4LINUX_ALLOWED_SESSION_USERS", "")
        self.allowed_session_users = {
            user.strip()
            for user in raw_users.split(",")
            if user.strip()
        }
