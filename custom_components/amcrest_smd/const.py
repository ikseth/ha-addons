DOMAIN = "amcrest_smd"
INTEGRATION_VERSION = "0.1.0"
INTEGRATION_REPOSITORY_URL = (
    "https://github.com/ikseth/ha-addons/tree/main/custom_components/amcrest_smd"
)
INTEGRATION_DOWNLOAD_URL = "https://github.com/ikseth/ha-addons/archive/refs/heads/main.zip"
INTEGRATION_UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/ikseth/ha-addons/main/"
    "custom_components/amcrest_smd/update-manifest.json"
)

CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_HEARTBEAT = "heartbeat"

DEFAULT_PORT = 80
DEFAULT_HEARTBEAT = 15

PLATFORMS = ["binary_sensor"]

# Codigos de evento SMD (Smart Motion Detection) que exponemos.
EVENT_HUMAN = "SmartMotionHuman"
EVENT_VEHICLE = "SmartMotionVehicle"
TRACKED_EVENTS = (EVENT_HUMAN, EVENT_VEHICLE)

# La camara marca inicio y fin de cada evento con estas acciones.
ACTION_START = "Start"
ACTION_STOP = "Stop"

# Reconexion: backoff exponencial con tope, para no martillear la camara
# mientras este caida (p.ej. durante un reinicio o un corte de red).
RECONNECT_BACKOFF_START = 1.0
RECONNECT_BACKOFF_MAX = 60.0
RECONNECT_BACKOFF_FACTOR = 2.0

# Si no llega nada (ni evento ni heartbeat) en este multiplo del intervalo de
# heartbeat, damos la conexion por muerta y reconectamos.
READ_TIMEOUT_HEARTBEAT_FACTOR = 3

SIGNAL_STATE_UPDATED = f"{DOMAIN}_state_updated"
