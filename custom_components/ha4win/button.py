"""Power action buttons for HA4Win."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import HA4WinApiError
from .const import DOMAIN
from .coordinator import HA4WinCoordinator
from .sensor import _device_info, _dict

_ACTION_NAMES = {
    "lock": "Lock",
    "sleep": "Sleep",
    "hibernate": "Hibernate",
    "restart": "Restart",
    "shutdown": "Shutdown",
    "cancel": "Cancel Shutdown",
}
_ACTION_ICONS = {
    "lock": "mdi:lock",
    "sleep": "mdi:power-sleep",
    "hibernate": "mdi:power-sleep",
    "restart": "mdi:restart",
    "shutdown": "mdi:power",
    "cancel": "mdi:cancel",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HA4WinCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    known_actions: set[str] = set()

    def _new_buttons() -> list[ButtonEntity]:
        new: list[ButtonEntity] = []
        for action in _available_actions(coordinator.data):
            if action not in _ACTION_NAMES or action in known_actions:
                continue
            known_actions.add(action)
            new.append(HA4WinPowerButton(coordinator, entry, action))
        return new

    if buttons := _new_buttons():
        async_add_entities(buttons)

    @callback
    def _handle_update() -> None:
        if buttons := _new_buttons():
            async_add_entities(buttons)

    entry.async_on_unload(coordinator.async_add_listener(_handle_update))


def _available_actions(data: dict[str, Any] | None) -> set[str]:
    capabilities = _dict(_dict(data).get("capabilities"))
    details = _dict(_dict(capabilities.get("actuator_details")).get("power_manager"))
    raw = details.get("available_actions", [])
    return {str(action).strip().lower() for action in raw} if isinstance(raw, list) else set()


class HA4WinPowerButton(CoordinatorEntity[HA4WinCoordinator], ButtonEntity):
    """Execute one parameterless power manager action."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: HA4WinCoordinator, entry: ConfigEntry, action: str
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._action = action
        self._attr_unique_id = f"{entry.entry_id}_power_{action}"
        self._attr_name = _ACTION_NAMES[action]
        self._attr_icon = _ACTION_ICONS[action]
        if action in {"restart", "shutdown"}:
            self._attr_device_class = ButtonDeviceClass.RESTART

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self.coordinator, self._entry)

    @property
    def available(self) -> bool:
        errors = _dict(_dict(self.coordinator.data).get("endpoint_errors"))
        return (
            super().available
            and "capabilities" not in errors
            and self._action in _available_actions(self.coordinator.data)
        )

    async def async_press(self) -> None:
        try:
            result = await self.coordinator.api.actuator_action(self._action)
        except HA4WinApiError as exc:
            raise HomeAssistantError(str(exc)) from exc
        if not result.get("ok", False):
            raise HomeAssistantError(
                str(result.get("error") or f"Unable to execute {self._action}")
            )
        await self.coordinator.async_request_refresh()
