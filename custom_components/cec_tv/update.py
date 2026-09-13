"""Aviso de versiones nuevas de la integracion (no instala: la instalacion es manual).

Una sola entidad para toda la integracion, aunque haya varios televisores: la
crea la primera entrada que se carga.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_UPDATE_OWNER,
    DOMAIN,
    INTEGRATION_REPOSITORY_URL,
    INTEGRATION_UPDATE_MANIFEST_URL,
    INTEGRATION_VERSION,
)
from .model import version_tuple

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(hours=6)
_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_UPDATE_OWNER) not in (None, entry.entry_id):
        return
    domain_data[DATA_UPDATE_OWNER] = entry.entry_id
    async_add_entities([CecTvIntegrationUpdate(hass)], update_before_add=False)


class CecTvIntegrationUpdate(UpdateEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "integration"
    _attr_unique_id = f"{DOMAIN}_integration_update"
    _attr_supported_features = UpdateEntityFeature(0)
    _attr_should_poll = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._session = async_get_clientsession(hass)
        self._latest: str | None = None
        self._release_url: str | None = INTEGRATION_REPOSITORY_URL
        self._notes: str | None = None
        self._error: str | None = None

    @property
    def installed_version(self) -> str:
        return INTEGRATION_VERSION

    @property
    def latest_version(self) -> str | None:
        return self._latest or INTEGRATION_VERSION

    @property
    def release_url(self) -> str | None:
        return self._release_url

    @property
    def release_summary(self) -> str | None:
        return self._notes[:255] if self._notes else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"manifest_url": INTEGRATION_UPDATE_MANIFEST_URL, "error": self._error}

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        return version_tuple(latest_version) > version_tuple(installed_version)

    async def async_update(self) -> None:
        try:
            async with self._session.get(INTEGRATION_UPDATE_MANIFEST_URL, timeout=_TIMEOUT) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            # Sin internet no pasa nada: se sigue mostrando la version instalada.
            self._error = str(err)
            return
        if isinstance(payload, dict):
            self._latest = str(payload.get("version") or "").strip() or None
            self._release_url = str(payload.get("release_url") or "").strip() or INTEGRATION_REPOSITORY_URL
            self._notes = str(payload.get("notes") or "").strip() or None
            self._error = None
