"""Constantes de la integracion CEC TV."""

from homeassistant.const import Platform

DOMAIN = "cec_tv"
INTEGRATION_VERSION = "0.1.0"
INTEGRATION_REPOSITORY_URL = (
    "https://github.com/ikseth/ha-addons/tree/main/custom_components/cec_tv"
)
INTEGRATION_DOWNLOAD_URL = "https://github.com/ikseth/ha-addons/archive/refs/heads/main.zip"
INTEGRATION_UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/ikseth/ha-addons/main/"
    "custom_components/cec_tv/update-manifest.json"
)

CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NAME = "name"

DEFAULT_PORT = 8080
DEFAULT_USERNAME = "kodi"

PLATFORMS = [Platform.SWITCH, Platform.UPDATE]

# Addon de Kodi del que depende la integracion.
ADDON_ID = "script.cec.control"
ADDON_MIN_VERSION = (0, 2, 0)
ACTION_ON = "activate"
ACTION_OFF = "standby"

# Frecuencia con la que se leen las propiedades que publica el addon. El addon
# consulta al televisor cada 30 s y en rafaga tras cada orden; leer mas a menudo
# que eso solo acorta el retraso con el que se ve un cambio.
SCAN_INTERVAL_SECONDS = 15

# Ver model.PowerTracker y docs/DESIGN.md.
HOLD_UNKNOWN_SECONDS = 90
STALE_FACTOR = 3
MIN_STALE_SECONDS = 90
OPTIMISTIC_SECONDS = 60

DATA_UPDATE_OWNER = "update_entity_owner"
