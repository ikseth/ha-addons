from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    virtualbox_vm_switch_supported,
    virtualbox_switch_turn_off_action,
    virtualbox_vm_is_on,
)


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

    if isinstance(actuators, list) and "app_policy" in actuators:
        apps = _apps_from_data(coordinator.data)
        for app in apps:
            app_id = str(app.get("app_id", "")).strip()
            if app_id:
                entities.append(HA4LinuxAppPolicySwitch(coordinator, entry, app_id))

    known_vm_switches: set[str] = set()

    def _new_vm_switches() -> list[SwitchEntity]:
        new_entities: list[SwitchEntity] = []
        for item in virtualbox_items(coordinator.data):
            vm_uuid = str(item.get("uuid", "")).strip()
            vm_name = str(item.get("name", "")).strip()
            if not vm_uuid or vm_uuid in known_vm_switches:
                continue
            if not virtualbox_vm_switch_supported(coordinator.data, item):
                continue
            known_vm_switches.add(vm_uuid)
            new_entities.append(HA4LinuxVmSwitch(coordinator, entry, vm_uuid, vm_name or vm_uuid))
        return new_entities

    entities.extend(_new_vm_switches())

    if entities:
        async_add_entities(entities)

    @callback
    def _handle_coordinator_update() -> None:
        dynamic_entities = _new_vm_switches()
        if dynamic_entities:
            async_add_entities(dynamic_entities)

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


def _apps_from_data(data: dict | None) -> list[dict]:
    if not isinstance(data, dict):
        return []

    app_policy = data.get("app_policy", {})
    if isinstance(app_policy, dict):
        apps = app_policy.get("apps", [])
        if isinstance(apps, list) and apps:
            return apps

    sensors = data.get("sensors", {})
    if not isinstance(sensors, dict):
        return []

    app_policies = sensors.get("app_policies", {})
    if not isinstance(app_policies, dict):
        return []

    payload = app_policies.get("data", {})
    if not isinstance(payload, dict):
        return []

    apps = payload.get("apps", [])
    return apps if isinstance(apps, list) else []


class _HA4LinuxBaseSwitch(CoordinatorEntity[HA4LinuxCoordinator], SwitchEntity):
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


class HA4LinuxSessionSwitch(_HA4LinuxBaseSwitch):
    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_session_active"
        self._attr_name = "Active Graphical Session"
        self._attr_has_entity_name = True

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


class HA4LinuxAppPolicySwitch(_HA4LinuxBaseSwitch):
    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry, app_id: str) -> None:
        super().__init__(coordinator, entry)
        self._app_id = app_id
        pretty = app_id.replace("_", " ").replace("-", " ").title()
        self._attr_unique_id = f"{entry.entry_id}_app_policy_{app_id}"
        self._attr_name = f"App Allowed {pretty}"
        self._attr_has_entity_name = True

    def _policy_item(self) -> dict | None:
        for app in _apps_from_data(self.coordinator.data):
            if str(app.get("app_id", "")).strip() == self._app_id:
                return app
        return None

    @property
    def is_on(self) -> bool:
        item = self._policy_item()
        if not isinstance(item, dict):
            return False
        return bool(item.get("allowed", False))

    async def async_turn_on(self, **kwargs) -> None:
        result = await self.coordinator.api.app_policy_allow(self._app_id)
        if not result.get("ok", False):
            raise HomeAssistantError(result.get("error", "Unable to allow app"))
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        result = await self.coordinator.api.app_policy_block(self._app_id)
        if not result.get("ok", False):
            raise HomeAssistantError(result.get("error", "Unable to block app"))
        await self.coordinator.async_request_refresh()


class HA4LinuxVmSwitch(_HA4LinuxBaseSwitch):
    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry, vm_uuid: str, vm_name: str) -> None:
        super().__init__(coordinator, entry)
        self._vm_uuid = vm_uuid
        self._power_override: bool | None = None
        self._attr_unique_id = f"{entry.entry_id}_virtualbox_vm_switch_{_slug(vm_uuid)}"
        self._attr_name = f"VM {vm_name} Power"
        self._attr_has_entity_name = True

    def _item(self) -> dict | None:
        return find_virtualbox_item(self.coordinator.data, self._vm_uuid)

    @callback
    def _handle_coordinator_update(self) -> None:
        # Coordinator data is the source of truth; clear any optimistic state
        # once a refresh completes so the entity follows the VM's real status.
        self._power_override = None
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        item = self._item()
        return isinstance(item, dict) and virtualbox_vm_switch_supported(self.coordinator.data, item)

    @property
    def is_on(self) -> bool:
        if self._power_override is not None:
            return self._power_override
        return virtualbox_vm_is_on(self._item())

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
        }

    async def async_turn_on(self, **kwargs) -> None:
        if virtualbox_vm_is_on(self._item()):
            self._power_override = None
            return

        self._power_override = True
        self.async_write_ha_state()
        result = await self.coordinator.api.virtualbox_action("start", vm_uuid=self._vm_uuid)
        if not result.get("ok", False):
            self._power_override = None
            self.async_write_ha_state()
            raise HomeAssistantError(result.get("error", "Unable to start VM"))
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        if not virtualbox_vm_is_on(self._item()):
            self._power_override = None
            return

        self._power_override = False
        self.async_write_ha_state()
        action = virtualbox_switch_turn_off_action(self.coordinator.data)
        result = await self.coordinator.api.virtualbox_action(action, vm_uuid=self._vm_uuid)
        if not result.get("ok", False):
            self._power_override = None
            self.async_write_ha_state()
            raise HomeAssistantError(result.get("error", f"Unable to execute {action}"))
        await self.coordinator.async_request_refresh()


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_")
