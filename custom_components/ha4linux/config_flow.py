from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HA4LinuxApiClient, HA4LinuxApiError, HA4LinuxAuthError
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USE_HTTPS,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)


def _schema(data: dict[str, Any] | None = None) -> vol.Schema:
    data = data or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=data.get(CONF_HOST, "192.168.59.202")): str,
            vol.Required(CONF_PORT, default=data.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Required(CONF_TOKEN, default=data.get(CONF_TOKEN, "")): str,
            vol.Required(CONF_USE_HTTPS, default=data.get(CONF_USE_HTTPS, DEFAULT_USE_HTTPS)): bool,
            vol.Required(CONF_VERIFY_SSL, default=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)): bool,
        }
    )


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    api = HA4LinuxApiClient(
        session=async_get_clientsession(hass),
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        token=data[CONF_TOKEN],
        use_https=data[CONF_USE_HTTPS],
        verify_ssl=data[CONF_VERIFY_SSL],
    )
    health = await api.health()
    if health.get("status") != "ok":
        raise HA4LinuxApiError("Health check failed")
    await api.capabilities()


class HA4LinuxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()

            try:
                await _validate_input(self.hass, user_input)
            except HA4LinuxAuthError:
                errors["base"] = "invalid_auth"
            except HA4LinuxApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=f"HA4Linux {user_input[CONF_HOST]}", data=user_input)

        return self.async_show_form(step_id="user", data_schema=_schema(user_input), errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return HA4LinuxOptionsFlow()


class HA4LinuxOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        config_entry = self.config_entry
        default_interval = DEFAULT_SCAN_INTERVAL
        if config_entry is not None:
            default_interval = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=default_interval,
                    ): vol.All(int, vol.Range(min=5, max=300))
                }
            ),
        )
