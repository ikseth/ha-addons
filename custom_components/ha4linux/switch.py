from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN
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

    if isinstance(actuators, list) and "app_policy" in actuators:
        apps = _apps_from_data(coordinator.data)
        for app in apps:
            app_id = str(app.get("app_id", "")).strip()
            if app_id:
                entities.append(HA4LinuxAppPolicySwitch(coordinator, entry, app_id))

    if entities:
        async_add_entities(entities)


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
