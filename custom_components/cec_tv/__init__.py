"""Integracion CEC TV: controla y lee un televisor por HDMI-CEC a traves de Kodi.

Depende del addon de Kodi `script.cec.control` (0.2.0 o posterior), que ejecuta
las ordenes CEC con los builtins de Kodi y publica el estado real de encendido
del televisor como propiedades de Window(Home). Esta integracion lee esas
propiedades por JSON-RPC: no abre puertos ni necesita acceso al equipo.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CecTvAddonError, CecTvApiError, CecTvAuthError, KodiCecClient
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DATA_UPDATE_OWNER,
    DEFAULT_PORT,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import CecTvCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = KodiCecClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        entry.data.get(CONF_USERNAME, ""),
        entry.data.get(CONF_PASSWORD, ""),
    )
    try:
        addon = await client.async_addon()
    except CecTvAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except CecTvAddonError as err:
        raise ConfigEntryNotReady(f"addon de Kodi: {err.reason}") from err
    except CecTvApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = CecTvCoordinator(hass, entry, client, str(addon.get("version") or ""))
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        domain_data = hass.data.get(DOMAIN, {})
        domain_data.pop(entry.entry_id, None)
        if domain_data.get(DATA_UPDATE_OWNER) == entry.entry_id:
            domain_data.pop(DATA_UPDATE_OWNER, None)
    return unloaded
