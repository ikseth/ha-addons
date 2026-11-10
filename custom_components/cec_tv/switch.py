"""Interruptor del televisor: orden por CEC y estado real leido por CEC."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CecTvApiError
from .const import CONF_HOST, CONF_PORT, DEFAULT_PORT, DOMAIN, INTEGRATION_VERSION
from .coordinator import CecTvCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coordinator: CecTvCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CecTvSwitch(coordinator, entry)])


class CecTvSwitch(CoordinatorEntity[CecTvCoordinator], SwitchEntity):
    """Encendido: CEC `activate`. Apagado: CEC `standby`.

    El estado no es optimista salvo durante el plazo que sigue a una orden:
    fuera de ese plazo es el que el televisor contesta por CEC. `None`
    (desconocido) cuando el televisor no contesta durante un rato, que no es lo
    mismo que apagado.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:television"

    def __init__(self, coordinator: CecTvCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_power"
        host = entry.data[CONF_HOST]
        port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.title,
            manufacturer="HDMI-CEC",
            model="TV via Kodi",
            sw_version=f"cec_tv {INTEGRATION_VERSION} / addon {coordinator.addon_version}",
            configuration_url=f"http://{host}:{port}",
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.tracker.available

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.tracker.is_on(time.time())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tracker = self.coordinator.tracker
        snapshot = tracker.snapshot
        now = time.time()
        return {
            "cec_power": snapshot.power if snapshot else None,
            "cec_error": (snapshot.error or None) if snapshot else None,
            "cec_device": (snapshot.device or None) if snapshot else None,
            "reading_age_s": tracker.reading_age(now),
            "pending_command": tracker.pending,
            "unavailable_reason": tracker.unavailable_reason,
            "addon_version": self.coordinator.addon_version,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        try:
            await self.coordinator.async_set_power(on)
        except CecTvApiError as err:
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError(f"No se pudo enviar la orden CEC: {err}") from err
