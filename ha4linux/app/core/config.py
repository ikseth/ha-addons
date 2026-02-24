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
    actuator_session: bool
    allowed_session_users: set[str]

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
        self.actuator_session = _as_bool(os.getenv("HA4LINUX_ACTUATOR_SESSION", "true"), True)

        raw_users = os.getenv("HA4LINUX_ALLOWED_SESSION_USERS", "")
        self.allowed_session_users = {
            user.strip()
            for user in raw_users.split(",")
            if user.strip()
        }
