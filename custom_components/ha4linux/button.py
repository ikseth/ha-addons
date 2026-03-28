from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN
from .coordinator import HA4LinuxCoordinator
from .virtualbox import (
    find_virtualbox_item,
    virtualbox_items,
    virtualbox_vm_button_actions,
)

_ACTION_LABELS = {
    "start": "Start",
    "acpi_shutdown": "Graceful Shutdown",
    "savestate": "Save State",
    "poweroff": "Force Power Off",
    "reset": "Reset",
}

_ACTION_ICONS = {
    "start": "mdi:play",
    "acpi_shutdown": "mdi:power-standby",
    "savestate": "mdi:content-save",
    "poweroff": "mdi:power",
    "reset": "mdi:restart",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HA4LinuxCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    known_vm_actions: set[str] = set()

    def _new_vm_buttons() -> list[ButtonEntity]:
        new_entities: list[ButtonEntity] = []
        for item in virtualbox_items(coordinator.data):
            vm_uuid = str(item.get("uuid", "")).strip()
            vm_name = str(item.get("name", "")).strip()
            if not vm_uuid:
                continue
            for action in virtualbox_vm_button_actions(coordinator.data, item):
                action_key = f"{vm_uuid}|{action}"
                if action_key in known_vm_actions:
                    continue
                known_vm_actions.add(action_key)
                new_entities.append(
                    HA4LinuxVmActionButton(
                        coordinator,
                        entry,
                        vm_uuid=vm_uuid,
                        vm_name=vm_name or vm_uuid,
                        action=action,
                    )
                )
        return new_entities

    initial_entities = _new_vm_buttons()
    if initial_entities:
        async_add_entities(initial_entities)

    @callback
    def _handle_coordinator_update() -> None:
        dynamic_entities = _new_vm_buttons()
        if dynamic_entities:
            async_add_entities(dynamic_entities)

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class _HA4LinuxBaseButton(CoordinatorEntity[HA4LinuxCoordinator], ButtonEntity):
    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        host = self._entry.options.get(CONF_HOST, self._entry.data.get(CONF_HOST, "linux"))
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"HA4Linux {host}",
            manufacturer="HA4Linux",
            model="Linux Host API",
        )


class HA4LinuxVmActionButton(_HA4LinuxBaseButton):
    def __init__(
        self,
        coordinator: HA4LinuxCoordinator,
        entry: ConfigEntry,
        vm_uuid: str,
        vm_name: str,
        action: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._vm_uuid = vm_uuid
        self._action = action
        self._attr_unique_id = f"{entry.entry_id}_virtualbox_vm_button_{_slug(vm_uuid)}_{action}"
        self._attr_name = f"VM {vm_name} {_ACTION_LABELS.get(action, action.replace('_', ' ').title())}"
        self._attr_has_entity_name = True
        self._attr_icon = _ACTION_ICONS.get(action)

    def _item(self) -> dict | None:
        return find_virtualbox_item(self.coordinator.data, self._vm_uuid)

    @property
    def available(self) -> bool:
        item = self._item()
        return isinstance(item, dict) and self._action in virtualbox_vm_button_actions(
            self.coordinator.data,
            item,
        )

    @property
    def extra_state_attributes(self):
        item = self._item()
        if not isinstance(item, dict):
            return None
        return {
            "uuid": item.get("uuid"),
            "status": item.get("status"),
            "state_raw": item.get("state_raw"),
            "running": item.get("running"),
            "powered_on": item.get("powered_on"),
            "user": item.get("user"),
            "action": self._action,
        }

    async def async_press(self) -> None:
        result = await self.coordinator.api.virtualbox_action(self._action, vm_uuid=self._vm_uuid)
        if not result.get("ok", False):
            raise HomeAssistantError(result.get("error", f"Unable to execute {self._action}"))
        await self.coordinator.async_request_refresh()


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_")
