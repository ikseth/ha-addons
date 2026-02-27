from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HA4LinuxApiClient, HA4LinuxApiError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN


class HA4LinuxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: HA4LinuxApiClient) -> None:
        self.api = api
        self.entry = entry
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            capabilities = await self.api.capabilities()
            sensors = await self.api.sensors()

            data: dict[str, Any] = {
                "capabilities": capabilities,
                "sensors": sensors,
                "session": None,
                "app_policy": None,
            }

            actuators = capabilities.get("actuators", [])
            if isinstance(actuators, list) and "session_manager" in actuators:
                data["session"] = await self.api.session_status()

            if isinstance(actuators, list) and "app_policy" in actuators:
                data["app_policy"] = await self.api.app_policy_status()

            return data
        except HA4LinuxApiError as exc:
            raise UpdateFailed(str(exc)) from exc
