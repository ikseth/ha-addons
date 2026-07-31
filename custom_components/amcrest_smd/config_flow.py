"""Alta y opciones de la integracion desde la UI."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AmcrestSmdApiError, AmcrestSmdAuthError, AmcrestSmdClient
from .const import (
    CONF_HEARTBEAT,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DEFAULT_HEARTBEAT,
    DEFAULT_PORT,
    DOMAIN,
)


class AmcrestSmdConfigFlow(ConfigFlow, domain=DOMAIN):
    """Alta de una camara Amcrest/Dahua con deteccion SMD."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            client = AmcrestSmdClient(
                async_get_clientsession(self.hass),
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                info = await client.async_device_info()
            except AmcrestSmdAuthError:
                errors["base"] = "invalid_auth"
            except AmcrestSmdApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - la UI debe mostrar algo util
                errors["base"] = "unknown"
            else:
                serial = info.get("serial_number") or user_input[CONF_HOST]
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()

                title = info.get("device_type") or "Amcrest SMD"
                return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> AmcrestSmdOptionsFlow:
        return AmcrestSmdOptionsFlow()


class AmcrestSmdOptionsFlow(OptionsFlow):
    """Ajuste del intervalo de heartbeat."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(CONF_HEARTBEAT, DEFAULT_HEARTBEAT)
        schema = vol.Schema(
            {
                vol.Required(CONF_HEARTBEAT, default=current): vol.All(
                    int, vol.Range(min=5, max=120)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
