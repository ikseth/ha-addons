"""Integracion Amcrest SMD: deteccion de persona y vehiculo por push.

Consume el stream de eventos de la camara (`eventManager.cgi?action=attach`),
una unica conexion persistente por la que la camara empuja los eventos SMD
segun ocurren. No hay sondeo periodico.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
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
    PLATFORMS,
)
from .coordinator import AmcrestSmdCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura una camara a partir de su entrada de configuracion."""
    client = AmcrestSmdClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    try:
        device_info = await client.async_device_info()
    except AmcrestSmdAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except AmcrestSmdApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = AmcrestSmdCoordinator(
        hass=hass,
        entry=entry,
        client=client,
        heartbeat=int(entry.options.get(CONF_HEARTBEAT, DEFAULT_HEARTBEAT)),
        device_info=device_info,
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga la entrada cerrando la conexion de forma ordenada."""
    coordinator: AmcrestSmdCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is not None:
        await coordinator.async_stop()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recarga la entrada al cambiar las opciones."""
    await hass.config_entries.async_reload(entry.entry_id)
