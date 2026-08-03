"""Binary sensor entities for HA4Win."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HA4WinCoordinator
from .sensor import (
    _available_modules,
    _device_info,
    _dict,
    _module_available,
    _module_payload,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HA4WinCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([HA4WinCompatibilityBinarySensor(coordinator, entry)])
    known: set[str] = set()

    def _new_entities() -> list[BinarySensorEntity]:
        entities: list[BinarySensorEntity] = []
        modules = _available_modules(coordinator.data)
        if "maintenance" in modules and "pending_reboot" not in known:
            known.add("pending_reboot")
            entities.extend(
                [
                    HA4WinPendingRebootBinarySensor(coordinator, entry),
                    HA4WinOnAcPowerBinarySensor(coordinator, entry),
                ]
            )
        security = _module_payload(coordinator.data, "security")
        if "security" in modules:
            for block in ("defender", "firewall", "bitlocker"):
                if (
                    block not in known
                    and _dict(security.get(block)).get("available") is True
                ):
                    known.add(block)
                    entities.append(
                        HA4WinSecurityBinarySensor(coordinator, entry, block)
                    )
        return entities

    if entities := _new_entities():
        async_add_entities(entities)

    @callback
    def _handle_update() -> None:
        if entities := _new_entities():
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(_handle_update))


class _HA4WinBaseBinarySensor(
    CoordinatorEntity[HA4WinCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HA4WinCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self.coordinator, self._entry)


class HA4WinPendingRebootBinarySensor(_HA4WinBaseBinarySensor):
    _attr_name = "Pending Reboot"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: HA4WinCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_pending_reboot"

    @property
    def available(self) -> bool:
        return super().available and _module_available(self.coordinator.data, "maintenance")

    @property
    def is_on(self) -> bool | None:
        value = _module_payload(self.coordinator.data, "maintenance").get("pending_reboot")
        return value if isinstance(value, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        payload = _module_payload(self.coordinator.data, "maintenance")
        return {"reasons": payload.get("pending_reboot_reasons")}


class HA4WinOnAcPowerBinarySensor(_HA4WinBaseBinarySensor):
    _attr_name = "On AC Power"
    _attr_device_class = BinarySensorDeviceClass.PLUG

    def __init__(self, coordinator: HA4WinCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_on_ac_power"

    @property
    def available(self) -> bool:
        source = _module_payload(self.coordinator.data, "maintenance").get("power_source")
        return (
            super().available
            and _module_available(self.coordinator.data, "maintenance")
            and source in {"ac", "battery"}
        )

    @property
    def is_on(self) -> bool | None:
        source = _module_payload(self.coordinator.data, "maintenance").get("power_source")
        return source == "ac" if source in {"ac", "battery"} else None


class HA4WinCompatibilityBinarySensor(_HA4WinBaseBinarySensor):
    _attr_name = "API Compatible"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HA4WinCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_api_compatible"

    @property
    def available(self) -> bool:
        errors = _dict(_dict(self.coordinator.data).get("endpoint_errors"))
        status = _dict(_dict(self.coordinator.data).get("compatibility")).get("status")
        return super().available and "version" not in errors and status in {"compatible", "incompatible"}

    @property
    def is_on(self) -> bool | None:
        status = _dict(_dict(self.coordinator.data).get("compatibility")).get("status")
        return status == "incompatible" if status in {"compatible", "incompatible"} else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return _dict(_dict(self.coordinator.data).get("compatibility"))


class HA4WinSecurityBinarySensor(_HA4WinBaseBinarySensor):
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(
        self, coordinator: HA4WinCoordinator, entry: ConfigEntry, block: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._block = block
        names = {
            "defender": "Defender Real-Time Protection",
            "firewall": "Firewall Enabled",
            "bitlocker": "BitLocker Protected",
        }
        self._attr_name = names[block]
        self._attr_unique_id = f"{entry.entry_id}_security_{block}"

    def _payload(self) -> dict[str, Any]:
        return _dict(_module_payload(self.coordinator.data, "security").get(self._block))

    @property
    def available(self) -> bool:
        return (
            super().available
            and _module_available(self.coordinator.data, "security")
            and self._payload().get("available") is True
        )

    @property
    def is_on(self) -> bool | None:
        payload = self._payload()
        if payload.get("available") is not True:
            return None
        if self._block == "defender":
            value = payload.get("realtime_protection_enabled")
            return not value if isinstance(value, bool) else None
        if self._block == "firewall":
            values = [payload.get(key) for key in ("domain_enabled", "private_enabled", "public_enabled")]
            return not all(values) if all(isinstance(value, bool) for value in values) else None
        volumes = payload.get("volumes")
        if not isinstance(volumes, list):
            return None
        protected = [item.get("protected") for item in volumes if isinstance(item, dict)]
        return not all(protected) if len(protected) == len(volumes) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._payload()
