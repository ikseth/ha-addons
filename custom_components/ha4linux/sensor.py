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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN
from .coordinator import HA4LinuxCoordinator


@dataclass(frozen=True)
class HA4LinuxSensorDef:
    key: str
    module_id: str
    description: SensorEntityDescription
    value_fn: Callable[[dict[str, Any]], float | int | str | None]


@dataclass(frozen=True)
class HA4LinuxMetaSensorDef:
    key: str
    description: SensorEntityDescription
    value_fn: Callable[[dict[str, Any] | None], float | int | str | None]
    attributes_fn: Callable[[dict[str, Any] | None], dict[str, Any] | None] | None = None


META_SENSOR_DEFS: tuple[HA4LinuxMetaSensorDef, ...] = (
    HA4LinuxMetaSensorDef(
        key="api_version",
        description=SensorEntityDescription(
            key="api_version",
            name="API Version",
        ),
        value_fn=lambda d: _version_payload(d).get("api_version"),
    ),
    HA4LinuxMetaSensorDef(
        key="api_schema_version",
        description=SensorEntityDescription(
            key="api_schema_version",
            name="API Schema Version",
        ),
        value_fn=lambda d: _version_payload(d).get("schema_version"),
    ),
    HA4LinuxMetaSensorDef(
        key="api_compatibility",
        description=SensorEntityDescription(
            key="api_compatibility",
            name="API Compatibility",
        ),
        value_fn=lambda d: _compatibility_payload(d).get("status"),
        attributes_fn=lambda d: _compatibility_payload(d),
    ),
    HA4LinuxMetaSensorDef(
        key="api_update_state",
        description=SensorEntityDescription(
            key="api_update_state",
            name="API Update State",
        ),
        value_fn=lambda d: _update_payload(d).get("state"),
        attributes_fn=lambda d: _update_payload(d),
    ),
)


SENSOR_DEFS: tuple[HA4LinuxSensorDef, ...] = (
    HA4LinuxSensorDef(
        key="cpu_load_1",
        module_id="cpu_load",
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
        module_id="cpu_load",
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
        module_id="memory",
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
        module_id="memory",
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
        module_id="network",
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
        module_id="network",
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
        module_id="network",
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
        module_id="network",
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
        key="raid_arrays_total",
        module_id="raid_mdstat",
        description=SensorEntityDescription(
            key="raid_arrays_total",
            name="RAID Arrays Total",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("raid_mdstat", {}).get("data", {}).get("arrays_total"),
    ),
    HA4LinuxSensorDef(
        key="raid_arrays_degraded",
        module_id="raid_mdstat",
        description=SensorEntityDescription(
            key="raid_arrays_degraded",
            name="RAID Arrays Degraded",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("raid_mdstat", {}).get("data", {}).get("arrays_degraded"),
    ),
    HA4LinuxSensorDef(
        key="raid_arrays_rebuilding",
        module_id="raid_mdstat",
        description=SensorEntityDescription(
            key="raid_arrays_rebuilding",
            name="RAID Arrays Rebuilding",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("raid_mdstat", {}).get("data", {}).get("arrays_rebuilding"),
    ),
    HA4LinuxSensorDef(
        key="virtualbox_vms_total",
        module_id="virtualbox",
        description=SensorEntityDescription(
            key="virtualbox_vms_total",
            name="VirtualBox VMs Total",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("virtualbox", {}).get("data", {}).get("vms_total"),
    ),
    HA4LinuxSensorDef(
        key="virtualbox_vms_running",
        module_id="virtualbox",
        description=SensorEntityDescription(
            key="virtualbox_vms_running",
            name="VirtualBox VMs Running",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("virtualbox", {}).get("data", {}).get("vms_running"),
    ),
    HA4LinuxSensorDef(
        key="services_total",
        module_id="services",
        description=SensorEntityDescription(
            key="services_total",
            name="Services Total",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("services", {}).get("data", {}).get("services_total"),
    ),
    HA4LinuxSensorDef(
        key="services_active",
        module_id="services",
        description=SensorEntityDescription(
            key="services_active",
            name="Services Active",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("services", {}).get("data", {}).get("services_active"),
    ),
    HA4LinuxSensorDef(
        key="services_failed",
        module_id="services",
        description=SensorEntityDescription(
            key="services_failed",
            name="Services Failed",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("services", {}).get("data", {}).get("services_failed"),
    ),
    HA4LinuxSensorDef(
        key="filesystems_total",
        module_id="filesystem",
        description=SensorEntityDescription(
            key="filesystems_total",
            name="Filesystems Total",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("filesystem", {}).get("data", {}).get("filesystems_total"),
    ),
    HA4LinuxSensorDef(
        key="filesystems_readonly",
        module_id="filesystem",
        description=SensorEntityDescription(
            key="filesystems_readonly",
            name="Filesystems Readonly",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("filesystem", {}).get("data", {}).get("filesystems_readonly"),
    ),
    HA4LinuxSensorDef(
        key="filesystems_over_90",
        module_id="filesystem",
        description=SensorEntityDescription(
            key="filesystems_over_90",
            name="Filesystems Over 90%",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        value_fn=lambda d: d.get("filesystem", {}).get("data", {}).get("filesystems_over_90"),
    ),
    HA4LinuxSensorDef(
        key="app_policy_apps_total",
        module_id="app_policies",
        description=SensorEntityDescription(key="app_policy_apps_total", name="App Policies Total"),
        value_fn=lambda d: d.get("app_policies", {}).get("data", {}).get("app_count"),
    ),
    HA4LinuxSensorDef(
        key="app_policy_violation_count",
        module_id="app_policies",
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
    meta_entities: list[SensorEntity] = [
        HA4LinuxMetaSensor(coordinator, entry, definition)
        for definition in META_SENSOR_DEFS
    ]

    available_modules = _available_modules(coordinator.data)
    static_entities: list[SensorEntity] = meta_entities + [
        HA4LinuxSensor(coordinator, entry, definition)
        for definition in SENSOR_DEFS
        if definition.module_id in available_modules
    ]
    if static_entities:
        async_add_entities(static_entities)

    known_raid_arrays: set[str] = set()
    known_services: set[str] = set()
    known_vms: set[str] = set()
    known_filesystem_metrics: set[str] = set()

    def _new_dynamic_entities() -> list[SensorEntity]:
        modules = _available_modules(coordinator.data)
        new_entities: list[SensorEntity] = []

        if "raid_mdstat" in modules:
            for item in _raid_items(coordinator.data):
                array_name = str(item.get("name", "")).strip()
                if not array_name or array_name in known_raid_arrays:
                    continue
                known_raid_arrays.add(array_name)
                new_entities.append(HA4LinuxRaidArraySensor(coordinator, entry, array_name))

        if "services" in modules:
            for item in _services_items(coordinator.data):
                service_name = str(item.get("name", "")).strip()
                if not service_name or service_name in known_services:
                    continue
                known_services.add(service_name)
                new_entities.append(HA4LinuxServiceSensor(coordinator, entry, service_name))

        if "virtualbox" in modules:
            for item in _virtualbox_items(coordinator.data):
                vm_uuid = str(item.get("uuid", "")).strip()
                vm_name = str(item.get("name", "")).strip()
                if not vm_uuid or vm_uuid in known_vms:
                    continue
                known_vms.add(vm_uuid)
                new_entities.append(HA4LinuxVmSensor(coordinator, entry, vm_uuid, vm_name or vm_uuid))

        if "filesystem" in modules:
            for item in _filesystem_items(coordinator.data):
                mountpoint = str(item.get("mountpoint", "")).strip()
                if not mountpoint:
                    continue
                for metric_key in ("used_percent", "used_gib", "free_gib"):
                    unique_metric_key = f"{mountpoint}|{metric_key}"
                    if unique_metric_key in known_filesystem_metrics:
                        continue
                    known_filesystem_metrics.add(unique_metric_key)
                    new_entities.append(
                        HA4LinuxFilesystemSensor(
                            coordinator,
                            entry,
                            mountpoint=mountpoint,
                            metric_key=metric_key,
                        )
                    )

        return new_entities

    new_entities = _new_dynamic_entities()
    if new_entities:
        async_add_entities(new_entities)

    @callback
    def _handle_coordinator_update() -> None:
        dynamic_entities = _new_dynamic_entities()
        if dynamic_entities:
            async_add_entities(dynamic_entities)

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


def _available_modules(data: dict[str, Any] | None) -> set[str]:
    if not isinstance(data, dict):
        return set()

    capabilities = data.get("capabilities", {})
    if not isinstance(capabilities, dict):
        return set()

    sensors = capabilities.get("sensors", [])
    if not isinstance(sensors, list):
        return set()

    return {str(sensor_id) for sensor_id in sensors if str(sensor_id).strip()}


def _sensor_payload(data: dict[str, Any] | None, sensor_id: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}

    sensors = data.get("sensors", {})
    if not isinstance(sensors, dict):
        return {}

    section = sensors.get(sensor_id, {})
    if not isinstance(section, dict):
        return {}

    payload = section.get("data", {})
    return payload if isinstance(payload, dict) else {}


def _version_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    payload = data.get("version", {})
    return payload if isinstance(payload, dict) else {}


def _compatibility_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    payload = data.get("compatibility", {})
    return payload if isinstance(payload, dict) else {}


def _update_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    payload = data.get("update", {})
    return payload if isinstance(payload, dict) else {}


def _raid_items(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = _sensor_payload(data, "raid_mdstat")
    arrays = payload.get("arrays", [])
    return arrays if isinstance(arrays, list) else []


def _services_items(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = _sensor_payload(data, "services")
    services = payload.get("services", [])
    return services if isinstance(services, list) else []


def _virtualbox_items(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = _sensor_payload(data, "virtualbox")
    vms = payload.get("vms", [])
    return vms if isinstance(vms, list) else []


def _filesystem_items(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = _sensor_payload(data, "filesystem")
    filesystems = payload.get("filesystems", [])
    return filesystems if isinstance(filesystems, list) else []


def _slug(value: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    return normalized.strip("_") or "unknown"


class _HA4LinuxBaseSensor(CoordinatorEntity[HA4LinuxCoordinator], SensorEntity):
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


class HA4LinuxMetaSensor(_HA4LinuxBaseSensor):
    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: HA4LinuxCoordinator,
        entry: ConfigEntry,
        definition: HA4LinuxMetaSensorDef,
    ) -> None:
        super().__init__(coordinator, entry)
        self._def = definition
        self.entity_description = definition.description
        self._attr_unique_id = f"{entry.entry_id}_{definition.key}"
        self._attr_has_entity_name = True

    @property
    def native_value(self):
        return self._def.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        if self._def.attributes_fn is None:
            return None
        return self._def.attributes_fn(self.coordinator.data)


class HA4LinuxSensor(_HA4LinuxBaseSensor):
    entity_description: SensorEntityDescription

    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry, definition: HA4LinuxSensorDef) -> None:
        super().__init__(coordinator, entry)
        self._def = definition
        self.entity_description = definition.description
        self._attr_unique_id = f"{entry.entry_id}_{definition.key}"
        self._attr_has_entity_name = True

    @property
    def native_value(self):
        data = self.coordinator.data.get("sensors", {}) if self.coordinator.data else {}
        return self._def.value_fn(data)


class HA4LinuxRaidArraySensor(_HA4LinuxBaseSensor):
    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry, array_name: str) -> None:
        super().__init__(coordinator, entry)
        self._array_name = array_name
        self._attr_unique_id = f"{entry.entry_id}_raid_array_{_slug(array_name)}"
        self._attr_name = f"RAID {array_name}"
        self._attr_has_entity_name = True

    def _item(self) -> dict[str, Any] | None:
        for item in _raid_items(self.coordinator.data):
            if str(item.get("name", "")).strip() == self._array_name:
                return item
        return None

    @property
    def native_value(self):
        item = self._item()
        if not isinstance(item, dict):
            return None
        return item.get("state")

    @property
    def extra_state_attributes(self):
        item = self._item()
        if not isinstance(item, dict):
            return None
        return {
            "level": item.get("level"),
            "active_disks": item.get("active_disks"),
            "expected_disks": item.get("expected_disks"),
            "member_state": item.get("member_state"),
            "degraded": item.get("degraded"),
            "rebuilding": item.get("rebuilding"),
        }


class HA4LinuxServiceSensor(_HA4LinuxBaseSensor):
    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry, service_name: str) -> None:
        super().__init__(coordinator, entry)
        self._service_name = service_name
        self._attr_unique_id = f"{entry.entry_id}_service_{_slug(service_name)}"
        self._attr_name = f"Service {service_name}"
        self._attr_has_entity_name = True

    def _item(self) -> dict[str, Any] | None:
        for item in _services_items(self.coordinator.data):
            if str(item.get("name", "")).strip() == self._service_name:
                return item
        return None

    @property
    def native_value(self):
        item = self._item()
        if not isinstance(item, dict):
            return None
        return item.get("status")

    @property
    def extra_state_attributes(self):
        item = self._item()
        if not isinstance(item, dict):
            return None
        return {
            "load_state": item.get("load_state"),
            "active_state": item.get("active_state"),
            "sub_state": item.get("sub_state"),
            "is_active": item.get("is_active"),
            "is_failed": item.get("is_failed"),
        }


class HA4LinuxFilesystemSensor(_HA4LinuxBaseSensor):
    _PERCENT_METRIC = "used_percent"
    _USED_GIB_METRIC = "used_gib"
    _FREE_GIB_METRIC = "free_gib"

    def __init__(
        self,
        coordinator: HA4LinuxCoordinator,
        entry: ConfigEntry,
        *,
        mountpoint: str,
        metric_key: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._mountpoint = mountpoint
        self._metric_key = metric_key
        metric_names = {
            self._PERCENT_METRIC: "Used %",
            self._USED_GIB_METRIC: "Used GiB",
            self._FREE_GIB_METRIC: "Free GiB",
        }
        metric_suffix = metric_names.get(metric_key, metric_key.replace("_", " "))
        self._attr_unique_id = f"{entry.entry_id}_filesystem_{_slug(mountpoint)}_{metric_key}"
        self._attr_name = f"FS {mountpoint} {metric_suffix}"
        self._attr_has_entity_name = True
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 2

        if self._metric_key == self._PERCENT_METRIC:
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_device_class = None
        else:
            self._attr_native_unit_of_measurement = UnitOfInformation.GIBIBYTES
            self._attr_device_class = SensorDeviceClass.DATA_SIZE

    def _item(self) -> dict[str, Any] | None:
        for item in _filesystem_items(self.coordinator.data):
            if str(item.get("mountpoint", "")).strip() == self._mountpoint:
                return item
        return None

    @property
    def native_value(self):
        item = self._item()
        if not isinstance(item, dict):
            return None
        return item.get(self._metric_key)

    @property
    def extra_state_attributes(self):
        item = self._item()
        if not isinstance(item, dict):
            return None
        return {
            "mountpoint": item.get("mountpoint"),
            "device": item.get("device"),
            "fs_type": item.get("fs_type"),
            "readonly": item.get("readonly"),
            "total_gib": item.get("total_gib"),
            "used_percent": item.get("used_percent"),
        }


class HA4LinuxVmSensor(_HA4LinuxBaseSensor):
    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry, vm_uuid: str, vm_name: str) -> None:
        super().__init__(coordinator, entry)
        self._vm_uuid = vm_uuid
        self._attr_unique_id = f"{entry.entry_id}_virtualbox_vm_{_slug(vm_uuid)}"
        self._attr_name = f"VM {vm_name}"
        self._attr_has_entity_name = True

    def _item(self) -> dict[str, Any] | None:
        for item in _virtualbox_items(self.coordinator.data):
            if str(item.get("uuid", "")).strip() == self._vm_uuid:
                return item
        return None

    @property
    def native_value(self):
        item = self._item()
        if not isinstance(item, dict):
            return None
        return item.get("status")

    @property
    def extra_state_attributes(self):
        item = self._item()
        if not isinstance(item, dict):
            return None
        return {
            "uuid": item.get("uuid"),
            "running": item.get("running"),
            "inaccessible": item.get("inaccessible"),
            "user": item.get("user"),
        }
