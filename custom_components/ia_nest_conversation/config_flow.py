"""Config flow for IA_NEST conversation."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_API_KEY,
    CONF_CA_PEM,
    CONF_MENU_ENTRY,
    CONF_SESSION_HEADER,
    CONF_TIMEOUT,
    CONF_URL,
    DEFAULT_MENU_ENTRY,
    DEFAULT_SESSION_HEADER,
    DEFAULT_TIMEOUT,
    DOMAIN,
)
from .edge_client import (
    EdgeClient,
    EdgeConnectionError,
    EdgeHttpError,
    EdgeTimeoutError,
    EdgeTlsError,
)

_LOGGER = logging.getLogger(__name__)


class IaNestConversationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure the narrow, TLS-verified IA_NEST edge client."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_URL: user_input[CONF_URL].strip().rstrip("/"),
                CONF_API_KEY: user_input[CONF_API_KEY].strip(),
                CONF_CA_PEM: user_input[CONF_CA_PEM].strip(),
                CONF_MENU_ENTRY: user_input[CONF_MENU_ENTRY].strip(),
                CONF_SESSION_HEADER: user_input[CONF_SESSION_HEADER].strip(),
                CONF_TIMEOUT: int(user_input[CONF_TIMEOUT]),
            }
            parsed = urlsplit(data[CONF_URL])
            if parsed.scheme != "https" or not parsed.netloc:
                errors[CONF_URL] = "https_required"
            elif not data[CONF_API_KEY] or not data[CONF_CA_PEM]:
                errors["base"] = "invalid_input"
            elif not data[CONF_MENU_ENTRY] or not data[CONF_SESSION_HEADER] or data[CONF_TIMEOUT] < 1:
                errors["base"] = "invalid_input"
            else:
                try:
                    client = EdgeClient(
                        async_get_clientsession(self.hass),
                        data[CONF_URL],
                        data[CONF_API_KEY],
                        data[CONF_CA_PEM],
                        data[CONF_MENU_ENTRY],
                        data[CONF_SESSION_HEADER],
                        data[CONF_TIMEOUT],
                    )
                    models = await client.async_models()
                except EdgeTlsError:
                    errors["base"] = "tls_error"
                except EdgeHttpError as err:
                    errors["base"] = "invalid_auth" if err.status in (401, 403) else "cannot_connect"
                except (EdgeConnectionError, EdgeTimeoutError):
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error while validating IA_NEST edge")
                    errors["base"] = "unknown"
                else:
                    if data[CONF_MENU_ENTRY] not in models:
                        errors[CONF_MENU_ENTRY] = "menu_entry_not_found"
                    else:
                        await self.async_set_unique_id(
                            f"{data[CONF_URL]}:{data[CONF_MENU_ENTRY]}"
                        )
                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(
                            title=f"IA_NEST ({data[CONF_MENU_ENTRY]})", data=data
                        )

        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=defaults.get(CONF_URL, "")): str,
                    vol.Required(CONF_API_KEY, default=defaults.get(CONF_API_KEY, "")): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_CA_PEM, default=defaults.get(CONF_CA_PEM, "")): TextSelector(
                        TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_MENU_ENTRY, default=defaults.get(CONF_MENU_ENTRY, DEFAULT_MENU_ENTRY)): str,
                    vol.Required(CONF_SESSION_HEADER, default=defaults.get(CONF_SESSION_HEADER, DEFAULT_SESSION_HEADER)): str,
                    vol.Required(CONF_TIMEOUT, default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)): vol.All(vol.Coerce(int), vol.Range(min=1)),
                }
            ),
            errors=errors,
        )
