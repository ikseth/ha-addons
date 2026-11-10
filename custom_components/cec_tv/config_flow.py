"""Alta de un televisor desde la UI."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CecTvAddonError, CecTvApiError, CecTvAuthError, KodiCecClient
from .const import (
    ADDON_MIN_VERSION,
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DEFAULT_PORT,
    DEFAULT_USERNAME,
    DOMAIN,
)
from .model import version_tuple

_LOGGER = logging.getLogger(__name__)


class CecTvConfigFlow(ConfigFlow, domain=DOMAIN):
    """Un televisor por entrada, identificado por el Kodi conectado a el."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            client = KodiCecClient(async_get_clientsession(self.hass), host, port,
                                   user_input.get(CONF_USERNAME, ""),
                                   user_input.get(CONF_PASSWORD, ""))
            try:
                addon = await client.async_addon()
            except CecTvAuthError:
                errors["base"] = "invalid_auth"
            except CecTvAddonError as err:
                errors["base"] = err.reason
            except CecTvApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error inesperado dando de alta %s", host)
                errors["base"] = "unknown"
            else:
                if not addon.get("enabled", False):
                    errors["base"] = "addon_disabled"
                elif version_tuple(str(addon.get("version"))) < ADDON_MIN_VERSION:
                    errors["base"] = "addon_outdated"

            if not errors:
                data = {**user_input, CONF_HOST: host, CONF_PORT: port}
                return self.async_create_entry(title=user_input[CONF_NAME].strip(), data=data)

        defaults = user_input or {}
        schema = vol.Schema({
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Optional(CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME)): str,
            vol.Optional(CONF_PASSWORD, default=""): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
