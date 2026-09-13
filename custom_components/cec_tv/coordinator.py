"""Coordinador: lee periodicamente las propiedades que publica el addon."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CecTvApiError, CecTvAuthError, KodiCecClient
from .const import (
    ACTION_OFF,
    ACTION_ON,
    DOMAIN,
    HOLD_UNKNOWN_SECONDS,
    MIN_STALE_SECONDS,
    OPTIMISTIC_SECONDS,
    SCAN_INTERVAL_SECONDS,
    STALE_FACTOR,
)
from .model import POWER_ON, POWER_STANDBY, PowerTracker, Snapshot, labels

_LOGGER = logging.getLogger(__name__)


class CecTvCoordinator(DataUpdateCoordinator[Snapshot]):
    """Un coordinador por Kodi/televisor.

    Si Kodi no responde, la lectura falla y las entidades quedan no disponibles.
    Si responde pero el addon no publica o publica algo antiguo, el tracker lo
    marca como no disponible con su motivo.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: KodiCecClient,
                 addon_version: str) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} {entry.title}",
                         update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS))
        self.entry = entry
        self.client = client
        self.addon_version = addon_version
        self.tracker = PowerTracker(hold_unknown=HOLD_UNKNOWN_SECONDS, stale_factor=STALE_FACTOR,
                                    min_stale=MIN_STALE_SECONDS, optimistic=OPTIMISTIC_SECONDS)

    async def _async_update_data(self) -> Snapshot:
        try:
            result = await self.client.async_get_labels(labels())
        except CecTvAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CecTvApiError as err:
            raise UpdateFailed(str(err)) from err
        snapshot = Snapshot.from_labels(result)
        self.tracker.update(snapshot, time.time())
        return snapshot

    async def async_set_power(self, on: bool) -> None:
        """Envia la orden al addon y la registra para no parpadear."""
        await self.client.async_run_action(ACTION_ON if on else ACTION_OFF)
        self.tracker.command(POWER_ON if on else POWER_STANDBY, time.time())
        self.async_update_listeners()
        await self.async_request_refresh()
