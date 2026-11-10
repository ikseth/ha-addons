DOMAIN = "ha4linux"
INTEGRATION_VERSION = "0.5.16"
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
CONF_NOTIFY_SYSTEM_UPDATES = "notify_system_updates"

DEFAULT_PORT = 8099
DEFAULT_USE_HTTPS = True
DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL = 20
DEFAULT_NOTIFY_SYSTEM_UPDATES = True

PLATFORMS = ["sensor", "binary_sensor", "switch", "button", "update"]

# Integration-wide entities (summary sensors, integration update) live on one "owner" entry.
HUB_OWNER_KEY = "_hub_owner_entry_id"
SIGNAL_SYSTEM_UPDATES = f"{DOMAIN}_system_updates_changed"

DEPRECATED_ENTITY_UNIQUE_IDS = {
    "network_rx_bytes",
    "network_tx_bytes",
    "network_rx_kib_window",
    "network_tx_kib_window",
}
