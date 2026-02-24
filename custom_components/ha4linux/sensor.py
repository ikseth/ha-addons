from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HA4LinuxCoordinator


@dataclass(frozen=True)
class HA4LinuxSensorDef:
    key: str
    description: SensorEntityDescription
    value_fn: Callable[[dict], float | int | None]


SENSOR_DEFS: tuple[HA4LinuxSensorDef, ...] = (
    HA4LinuxSensorDef(
        key="cpu_load_1",
        description=SensorEntityDescription(key="cpu_load_1", name="CPU Load 1m"),
        value_fn=lambda d: d.get("cpu_load", {}).get("data", {}).get("load_1"),
    ),
    HA4LinuxSensorDef(
        key="cpu_load_5",
        description=SensorEntityDescription(key="cpu_load_5", name="CPU Load 5m"),
        value_fn=lambda d: d.get("cpu_load", {}).get("data", {}).get("load_5"),
    ),
    HA4LinuxSensorDef(
        key="memory_used_percent",
        description=SensorEntityDescription(
            key="memory_used_percent",
            name="Memory Used",
            native_unit_of_measurement=PERCENTAGE,
        ),
        value_fn=lambda d: d.get("memory", {}).get("data", {}).get("used_percent"),
    ),
    HA4LinuxSensorDef(
        key="memory_used_kb",
        description=SensorEntityDescription(
            key="memory_used_kb",
            name="Memory Used KB",
            native_unit_of_measurement=UnitOfInformation.KIBIBYTES,
        ),
        value_fn=lambda d: d.get("memory", {}).get("data", {}).get("used_kb"),
    ),
    HA4LinuxSensorDef(
        key="network_rx_bytes",
        description=SensorEntityDescription(key="network_rx_bytes", name="Network RX Bytes"),
        value_fn=lambda d: d.get("network", {}).get("data", {}).get("total_rx_bytes"),
    ),
    HA4LinuxSensorDef(
        key="network_tx_bytes",
        description=SensorEntityDescription(key="network_tx_bytes", name="Network TX Bytes"),
        value_fn=lambda d: d.get("network", {}).get("data", {}).get("total_tx_bytes"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HA4LinuxCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(HA4LinuxSensor(coordinator, entry, definition) for definition in SENSOR_DEFS)


class HA4LinuxSensor(CoordinatorEntity[HA4LinuxCoordinator], SensorEntity):
    entity_description: SensorEntityDescription

    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry, definition: HA4LinuxSensorDef) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._def = definition
        self.entity_description = definition.description
        self._attr_unique_id = f"{entry.entry_id}_{definition.key}"
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
    def native_value(self):
        data = self.coordinator.data.get("sensors", {}) if self.coordinator.data else {}
        return self._def.value_fn(data)
