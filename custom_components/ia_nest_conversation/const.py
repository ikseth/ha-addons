"""Constants for the IA_NEST conversation integration."""

DOMAIN = "ia_nest_conversation"

CONF_URL = "url"
CONF_API_KEY = "api_key"
CONF_CA_PEM = "ca_pem"
CONF_MENU_ENTRY = "menu_entry"
CONF_SESSION_HEADER = "session_header"
CONF_TIMEOUT = "timeout"
CONF_PERSON_MAP = "person_map"
CONF_PERSON_HEADER = "person_header"
CONF_DEVICE_HEADER = "device_header"

DEFAULT_MENU_ENTRY = "casa"
DEFAULT_SESSION_HEADER = "X-IANest-Conversation-Id"
DEFAULT_TIMEOUT = 60
DEFAULT_PERSON_MAP: dict[str, str] = {}
DEFAULT_PERSON_HEADER = "X-IANest-Person"
DEFAULT_DEVICE_HEADER = "X-IANest-Device"

