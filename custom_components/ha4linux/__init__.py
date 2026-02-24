from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HA4LinuxApiClient
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from .coordinator import HA4LinuxCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    api = HA4LinuxApiClient(
        session=async_get_clientsession(hass),
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        token=entry.data[CONF_TOKEN],
        use_https=entry.data[CONF_USE_HTTPS],
        verify_ssl=entry.data[CONF_VERIFY_SSL],
    )

    coordinator = HA4LinuxCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
