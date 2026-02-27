import os


def _as_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


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
    sensors_app_policies: bool
    actuator_session: bool
    actuator_app_policy: bool
    allowed_session_users: set[str]
    app_policy_file: str
    app_policy_use_sudo_kill: bool

    def __init__(self) -> None:
        self.bind_host = os.getenv("HA4LINUX_BIND_HOST", "0.0.0.0")
        self.bind_port = int(os.getenv("HA4LINUX_BIND_PORT", "8099"))
        self.api_token = os.getenv("HA4LINUX_API_TOKEN", "")
        self.tls_enabled = _as_bool(os.getenv("HA4LINUX_TLS_ENABLED", "true"), True)
        self.tls_certfile = os.getenv("HA4LINUX_TLS_CERTFILE", "/ssl/fullchain.pem")
        self.tls_keyfile = os.getenv("HA4LINUX_TLS_KEYFILE", "/ssl/privkey.pem")
        self.sensors_cpu = _as_bool(os.getenv("HA4LINUX_SENSORS_CPU", "true"), True)
        self.sensors_memory = _as_bool(os.getenv("HA4LINUX_SENSORS_MEMORY", "true"), True)
        self.sensors_network = _as_bool(os.getenv("HA4LINUX_SENSORS_NETWORK", "true"), True)
        self.sensors_app_policies = _as_bool(
            os.getenv("HA4LINUX_SENSORS_APP_POLICIES", "true"),
            True,
        )
        self.actuator_session = _as_bool(os.getenv("HA4LINUX_ACTUATOR_SESSION", "true"), True)
        self.actuator_app_policy = _as_bool(
            os.getenv("HA4LINUX_ACTUATOR_APP_POLICY", "true"),
            True,
        )
        self.app_policy_file = os.getenv(
            "HA4LINUX_APP_POLICY_FILE",
            "/data/app_policies.json",
        )
        self.app_policy_use_sudo_kill = _as_bool(
            os.getenv("HA4LINUX_APP_POLICY_USE_SUDO_KILL", "true"),
            True,
        )

        raw_users = os.getenv("HA4LINUX_ALLOWED_SESSION_USERS", "")
        self.allowed_session_users = {
            user.strip()
            for user in raw_users.split(",")
            if user.strip()
        }
