"""Config flow for HA4Win."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    HA4WinApiClient,
    HA4WinApiError,
    HA4WinAuthError,
    HA4WinFingerprintError,
    HA4WinForbiddenError,
)
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_TLS_FINGERPRINT,
    CONF_TOKEN,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TLS_FINGERPRINT,
    DEFAULT_USE_HTTPS,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)


class HA4WinWrongPlatformError(HA4WinApiError):
    """Raised when the endpoint belongs to a non-Windows agent."""


def _schema(data: dict[str, Any] | None = None) -> vol.Schema:
    defaults = data or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_TOKEN, default=defaults.get(CONF_TOKEN, "")): str,
            vol.Required(
                CONF_USE_HTTPS, default=defaults.get(CONF_USE_HTTPS, DEFAULT_USE_HTTPS)
            ): bool,
            vol.Required(
                CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            ): bool,
            vol.Optional(
                CONF_TLS_FINGERPRINT,
                default=defaults.get(CONF_TLS_FINGERPRINT, DEFAULT_TLS_FINGERPRINT),
            ): str,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=300)),
        }
    )


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    api = HA4WinApiClient(
        session=async_get_clientsession(hass),
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        token=data[CONF_TOKEN],
        use_https=data[CONF_USE_HTTPS],
        verify_ssl=data[CONF_VERIFY_SSL],
        tls_fingerprint=data.get(CONF_TLS_FINGERPRINT, ""),
    )
    version = await api.version()
    if str(version.get("platform", "")).strip().lower() != "windows":
        raise HA4WinWrongPlatformError(
            "This endpoint is not a Windows agent; use the HA4Linux integration for Linux hosts"
        )
    return version


def _flow_error(exc: Exception) -> str:
    if isinstance(exc, HA4WinAuthError):
        return "invalid_auth"
    if isinstance(exc, HA4WinForbiddenError):
        return "access_denied"
    if isinstance(exc, HA4WinFingerprintError):
        return "invalid_fingerprint"
    if isinstance(exc, HA4WinWrongPlatformError):
        return "wrong_platform"
    if isinstance(exc, HA4WinApiError):
        return "cannot_connect"
    return "unknown"


class HA4WinConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a HA4Win config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            try:
                await _validate_input(self.hass, user_input)
            except Exception as exc:  # Flow errors are translated for the user.
                errors["base"] = _flow_error(exc)
            else:
                title = f"HA4Win {user_input[CONF_HOST]}"
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(step_id="user", data_schema=_schema(user_input), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return HA4WinOptionsFlow()


class HA4WinOptionsFlow(config_entries.OptionsFlow):
    """Handle editable HA4Win connection options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            try:
                await _validate_input(self.hass, user_input)
            except Exception as exc:  # Flow errors are translated for the user.
                errors["base"] = _flow_error(exc)
            else:
                config_entry = self.config_entry
                if config_entry is not None:
                    unique_id = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                    duplicate = any(
                        item.entry_id != config_entry.entry_id and item.unique_id == unique_id
                        for item in self.hass.config_entries.async_entries(DOMAIN)
                    )
                    if duplicate:
                        errors["base"] = "already_configured"
                    else:
                        self.hass.config_entries.async_update_entry(
                            config_entry, unique_id=unique_id
                        )
                        return self.async_create_entry(title="", data=user_input)
                else:
                    return self.async_create_entry(title="", data=user_input)

        defaults: dict[str, Any] = {
            CONF_HOST: "",
            CONF_PORT: DEFAULT_PORT,
            CONF_TOKEN: "",
            CONF_USE_HTTPS: DEFAULT_USE_HTTPS,
            CONF_VERIFY_SSL: DEFAULT_VERIFY_SSL,
            CONF_TLS_FINGERPRINT: DEFAULT_TLS_FINGERPRINT,
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        }
        if self.config_entry is not None:
            defaults.update(self.config_entry.data)
            defaults.update(self.config_entry.options)
        if user_input is not None:
            defaults.update(user_input)
        return self.async_show_form(
            step_id="init", data_schema=_schema(defaults), errors=errors
        )
