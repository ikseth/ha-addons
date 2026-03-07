from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN
from .coordinator import HA4LinuxCoordinator


@dataclass(frozen=True)
class HA4LinuxSensorDef:
    key: str
    description: SensorEntityDescription
    value_fn: Callable[[dict[str, Any]], float | int | str | None]


SENSOR_DEFS: tuple[HA4LinuxSensorDef, ...] = (
    HA4LinuxSensorDef(
        key="cpu_load_1",
        description=SensorEntityDescription(
            key="cpu_load_1",
            name="CPU Load 1m",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
        ),
        value_fn=lambda d: d.get("cpu_load", {}).get("data", {}).get("load_1"),
    ),
    HA4LinuxSensorDef(
        key="cpu_load_5",
        description=SensorEntityDescription(
            key="cpu_load_5",
            name="CPU Load 5m",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
        ),
        value_fn=lambda d: d.get("cpu_load", {}).get("data", {}).get("load_5"),
    ),
    HA4LinuxSensorDef(
        key="memory_used_percent",
        description=SensorEntityDescription(
            key="memory_used_percent",
            name="Memory Used",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
        ),
        value_fn=lambda d: d.get("memory", {}).get("data", {}).get("used_percent"),
    ),
    HA4LinuxSensorDef(
        key="memory_used_kb",
        description=SensorEntityDescription(
            key="memory_used_kb",
            name="Memory Used KB",
            native_unit_of_measurement=UnitOfInformation.KIBIBYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        value_fn=lambda d: d.get("memory", {}).get("data", {}).get("used_kb"),
    ),
    HA4LinuxSensorDef(
        key="network_rx_bytes",
        description=SensorEntityDescription(
            key="network_rx_bytes",
            name="Network RX Bytes",
            native_unit_of_measurement=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.TOTAL_INCREASING,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("network", {}).get("data", {}).get("total_rx_bytes"),
    ),
    HA4LinuxSensorDef(
        key="network_tx_bytes",
        description=SensorEntityDescription(
            key="network_tx_bytes",
            name="Network TX Bytes",
            native_unit_of_measurement=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.TOTAL_INCREASING,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("network", {}).get("data", {}).get("total_tx_bytes"),
    ),
    HA4LinuxSensorDef(
        key="network_rx_kib_window",
        description=SensorEntityDescription(
            key="network_rx_kib_window",
            name="Network RX Window",
            native_unit_of_measurement=UnitOfInformation.KIBIBYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
        ),
        value_fn=lambda d: d.get("network", {}).get("data", {}).get("rx_kib_window"),
    ),
    HA4LinuxSensorDef(
        key="network_tx_kib_window",
        description=SensorEntityDescription(
            key="network_tx_kib_window",
            name="Network TX Window",
            native_unit_of_measurement=UnitOfInformation.KIBIBYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
        ),
        value_fn=lambda d: d.get("network", {}).get("data", {}).get("tx_kib_window"),
    ),
    HA4LinuxSensorDef(
        key="app_policy_apps_total",
        description=SensorEntityDescription(key="app_policy_apps_total", name="App Policies Total"),
        value_fn=lambda d: d.get("app_policies", {}).get("data", {}).get("app_count"),
    ),
    HA4LinuxSensorDef(
        key="app_policy_violation_count",
        description=SensorEntityDescription(
            key="app_policy_violation_count",
            name="App Policy Violations",
        ),
        value_fn=lambda d: d.get("app_policies", {}).get("data", {}).get("violation_count"),
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
        host = self._entry.options.get(CONF_HOST, self._entry.data.get(CONF_HOST, "linux"))
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
