from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN
from .coordinator import HA4LinuxCoordinator
from .system_updates import availability_attributes, pending_count, system_info_payload, updates_ready


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HA4LinuxCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    created = False

    def _try_add_entity() -> None:
        nonlocal created
        if created or not _has_system_info(coordinator.data):
            return
        created = True
        async_add_entities([HA4LinuxSystemUpdatesBinarySensor(coordinator, entry)])

    _try_add_entity()

    @callback
    def _handle_coordinator_update() -> None:
        _try_add_entity()

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


def _has_system_info(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False
    capabilities = data.get("capabilities", {})
    sensors = capabilities.get("sensors", []) if isinstance(capabilities, dict) else []
    return isinstance(sensors, list) and "system_info" in sensors


class HA4LinuxSystemUpdatesBinarySensor(CoordinatorEntity[HA4LinuxCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "system_updates_available"
    _attr_device_class = BinarySensorDeviceClass.UPDATE

    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_system_updates_available"

    @property
    def device_info(self) -> DeviceInfo:
        host = self._entry.options.get(CONF_HOST, self._entry.data.get(CONF_HOST, "linux"))
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"HA4Linux {host}",
            manufacturer="HA4Linux",
            model="Linux Host API",
        )

    def _payload(self) -> dict[str, Any]:
        return system_info_payload(self.coordinator.data)

    @property
    def available(self) -> bool:
        # Unavailable while the host has no valid sample (disabled, unsupported or still checking).
        return super().available and updates_ready(self._payload())

    @property
    def is_on(self) -> bool | None:
        count = pending_count(self._payload())
        return None if count is None else count > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        payload = self._payload()
        if not updates_ready(payload):
            return None
        return availability_attributes(payload)
