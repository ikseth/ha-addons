DOMAIN = "ha4linux"
INTEGRATION_VERSION = "0.5.12"
INTEGRATION_REPOSITORY_URL = "https://github.com/ikseth/ha-addons/tree/main/custom_components/ha4linux"
INTEGRATION_DOWNLOAD_URL = "https://github.com/ikseth/ha-addons/archive/refs/heads/main.zip"
INTEGRATION_UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/ikseth/ha-addons/main/custom_components/ha4linux/update-manifest.json"
)

CONF_HOST = "host"
CONF_PORT = "port"
CONF_TOKEN = "token"
CONF_USE_HTTPS = "use_https"
CONF_VERIFY_SSL = "verify_ssl"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_PORT = 8099
DEFAULT_USE_HTTPS = True
DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL = 20

PLATFORMS = ["sensor", "switch", "button", "update"]

DEPRECATED_ENTITY_UNIQUE_IDS = {
    "network_rx_bytes",
    "network_tx_bytes",
    "network_rx_kib_window",
    "network_tx_kib_window",
}
