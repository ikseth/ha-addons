"""Constants for the HA4Win integration."""

from homeassistant.const import Platform

DOMAIN = "ha4win"
INTEGRATION_VERSION = "0.1.0"
INTEGRATION_REPOSITORY_URL = (
    "https://github.com/ikseth/ha-addons/tree/main/custom_components/ha4win"
)
INTEGRATION_DOWNLOAD_URL = (
    "https://github.com/ikseth/ha-addons/archive/refs/heads/main.zip"
)
INTEGRATION_UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/ikseth/ha-addons/main/"
    "custom_components/ha4win/update-manifest.json"
)

CONF_HOST = "host"
CONF_PORT = "port"
CONF_TOKEN = "token"
CONF_USE_HTTPS = "use_https"
CONF_VERIFY_SSL = "verify_ssl"
CONF_TLS_FINGERPRINT = "tls_fingerprint_sha256"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_PORT = 8099
DEFAULT_USE_HTTPS = True
DEFAULT_VERIFY_SSL = False
DEFAULT_TLS_FINGERPRINT = ""
DEFAULT_SCAN_INTERVAL = 20

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.UPDATE,
]
