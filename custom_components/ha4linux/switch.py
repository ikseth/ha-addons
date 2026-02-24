from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HA4LinuxCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HA4LinuxCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    capabilities = coordinator.data.get("capabilities", {}) if coordinator.data else {}
    actuators = capabilities.get("actuators", []) if isinstance(capabilities, dict) else []

    entities: list[SwitchEntity] = []
    if isinstance(actuators, list) and "session_manager" in actuators:
        entities.append(HA4LinuxSessionSwitch(coordinator, entry))

    if entities:
        async_add_entities(entities)


class HA4LinuxSessionSwitch(CoordinatorEntity[HA4LinuxCoordinator], SwitchEntity):
    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_session_active"
        self._attr_name = "Active Graphical Session"
        self._attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        host = self._entry.data.get("host", "linux")
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"HA4Linux {host}",
            manufacturer="HA4Linux",
            model="Linux Host API",
        )

    @property
    def is_on(self) -> bool:
        session = self.coordinator.data.get("session") if self.coordinator.data else None
        if not isinstance(session, dict):
            return False
        active = session.get("active_session")
        return isinstance(active, dict)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.api.session_activate()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.api.session_terminate()
        await self.coordinator.async_request_refresh()
