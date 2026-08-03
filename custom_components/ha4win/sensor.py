"""Sensor entities for HA4Win."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_HOST, DOMAIN
from .coordinator import HA4WinCoordinator

ValueFn = Callable[[dict[str, Any]], float | int | str | datetime | None]
AttributesFn = Callable[[dict[str, Any]], dict[str, Any] | None]


@dataclass(frozen=True)
class HA4WinSensorDef:
    """Describe a coordinator-backed sensor."""

    key: str
    module_id: str | None
    description: SensorEntityDescription
    value_fn: ValueFn
    attributes_fn: AttributesFn | None = None
    endpoint: str = "sensors"


def _description(key: str, name: str, **kwargs: Any) -> SensorEntityDescription:
    return SensorEntityDescription(key=key, name=name, has_entity_name=True, **kwargs)


META_SENSOR_DEFS: tuple[HA4WinSensorDef, ...] = (
    HA4WinSensorDef(
        "api_version",
        None,
        _description("api_version", "API Version", entity_category=EntityCategory.DIAGNOSTIC),
        lambda data: _dict(data.get("version")).get("api_version"),
        endpoint="version",
    ),
    HA4WinSensorDef(
        "api_schema_version",
        None,
        _description(
            "api_schema_version", "API Schema Version", entity_category=EntityCategory.DIAGNOSTIC
        ),
        lambda data: _dict(data.get("version")).get("schema_version"),
        endpoint="version",
    ),
    HA4WinSensorDef(
        "api_compatibility",
        None,
        _description(
            "api_compatibility", "API Compatibility", entity_category=EntityCategory.DIAGNOSTIC
        ),
        lambda data: _dict(data.get("compatibility")).get("status"),
        lambda data: _dict(data.get("compatibility")),
        endpoint="version",
    ),
    HA4WinSensorDef(
        "api_update_state",
        None,
        _description(
            "api_update_state", "API Update State", entity_category=EntityCategory.DIAGNOSTIC
        ),
        lambda data: _dict(data.get("update")).get("state"),
        lambda data: _dict(data.get("update")),
        endpoint="update",
    ),
)


STATIC_SENSOR_DEFS: tuple[HA4WinSensorDef, ...] = (
    HA4WinSensorDef(
        "operating_system",
        "system_info",
        _description(
            "operating_system", "Operating System", entity_category=EntityCategory.DIAGNOSTIC
        ),
        lambda data: _operating_system(_module_payload(data, "system_info")),
        lambda data: _system_attributes(_module_payload(data, "system_info")),
    ),
    HA4WinSensorDef(
        "windows_build",
        "system_info",
        _description("windows_build", "Windows Build", entity_category=EntityCategory.DIAGNOSTIC),
        lambda data: _module_payload(data, "system_info").get("build"),
    ),
    HA4WinSensorDef(
        "uptime",
        "system_info",
        _description(
            "uptime",
            "Uptime",
            native_unit_of_measurement=UnitOfTime.SECONDS,
            device_class=SensorDeviceClass.DURATION,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        lambda data: _module_payload(data, "system_info").get("uptime_seconds"),
    ),
    HA4WinSensorDef(
        "last_boot",
        "system_info",
        _description(
            "last_boot",
            "Last Boot",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        lambda data: _as_datetime(_module_payload(data, "system_info").get("boot_time")),
    ),
    HA4WinSensorDef(
        "cpu_usage",
        "cpu",
        _description(
            "cpu_usage", "CPU Usage", native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2
        ),
        lambda data: _rounded(_module_payload(data, "cpu").get("usage_percent")),
        lambda data: _cpu_attributes(_module_payload(data, "cpu")),
    ),
    HA4WinSensorDef(
        "cpu_usage_user",
        "cpu",
        _description(
            "cpu_usage_user", "CPU Usage User", native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2
        ),
        lambda data: _rounded(_module_payload(data, "cpu").get("usage_user_percent")),
    ),
    HA4WinSensorDef(
        "cpu_usage_kernel",
        "cpu",
        _description(
            "cpu_usage_kernel", "CPU Usage Kernel", native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2
        ),
        lambda data: _rounded(_module_payload(data, "cpu").get("usage_kernel_percent")),
    ),
    HA4WinSensorDef(
        "memory_used_percent",
        "memory",
        _description(
            "memory_used_percent", "Memory Used (%)", native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2
        ),
        lambda data: _module_payload(data, "memory").get("used_percent"),
        lambda data: _memory_attributes(_module_payload(data, "memory")),
    ),
    HA4WinSensorDef(
        "memory_used_kb",
        "memory",
        _description(
            "memory_used_kb", "Memory Used", native_unit_of_measurement=UnitOfInformation.KIBIBYTES,
            device_class=SensorDeviceClass.DATA_SIZE, state_class=SensorStateClass.MEASUREMENT
        ),
        lambda data: _module_payload(data, "memory").get("used_kb"),
    ),
    HA4WinSensorDef(
        "memory_commit_percent",
        "memory",
        _description(
            "memory_commit_percent", "Commit Charge", native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2
        ),
        lambda data: _module_payload(data, "memory").get("commit_percent"),
    ),
    HA4WinSensorDef(
        "volumes_total", "volumes",
        _description("volumes_total", "Volumes Total", state_class=SensorStateClass.MEASUREMENT),
        lambda data: _module_payload(data, "volumes").get("volumes_total"),
    ),
    HA4WinSensorDef(
        "volumes_over_90", "volumes",
        _description("volumes_over_90", "Volumes Over 90%", state_class=SensorStateClass.MEASUREMENT),
        lambda data: _module_payload(data, "volumes").get("volumes_over_90"),
    ),
    HA4WinSensorDef(
        "services_total", "services",
        _description("services_total", "Services Total", state_class=SensorStateClass.MEASUREMENT),
        lambda data: _module_payload(data, "services").get("services_total"),
    ),
    HA4WinSensorDef(
        "services_running", "services",
        _description("services_running", "Services Running", state_class=SensorStateClass.MEASUREMENT),
        lambda data: _module_payload(data, "services").get("services_active"),
    ),
    HA4WinSensorDef(
        "services_failed", "services",
        _description("services_failed", "Services Failed", state_class=SensorStateClass.MEASUREMENT),
        lambda data: _module_payload(data, "services").get("services_failed"),
    ),
    HA4WinSensorDef(
        "windows_updates_state", "system_info",
        _description("windows_updates_state", "Windows Updates State"),
        lambda data: _module_payload(data, "system_info").get("updates_state"),
        lambda data: _updates_attributes(_module_payload(data, "system_info")),
    ),
    HA4WinSensorDef(
        "pending_windows_updates", "system_info",
        _description(
            "pending_windows_updates", "Pending Windows Updates",
            state_class=SensorStateClass.MEASUREMENT
        ),
        lambda data: _module_payload(data, "system_info").get("updates_pending_count"),
        lambda data: _updates_attributes(_module_payload(data, "system_info")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HA4WinCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    modules = _available_modules(coordinator.data)
    entities: list[SensorEntity] = [
        HA4WinSensor(coordinator, entry, definition) for definition in META_SENSOR_DEFS
    ]
    known_static = {definition.key for definition in META_SENSOR_DEFS}
    for definition in STATIC_SENSOR_DEFS:
        if definition.module_id not in modules:
            continue
        known_static.add(definition.key)
        entities.append(HA4WinSensor(coordinator, entry, definition))
    async_add_entities(entities)

    known: set[str] = set()

    def _new_dynamic_entities() -> list[SensorEntity]:
        new: list[SensorEntity] = []
        current_modules = _available_modules(coordinator.data)
        for definition in STATIC_SENSOR_DEFS:
            if (
                definition.key in known_static
                or definition.module_id not in current_modules
            ):
                continue
            known_static.add(definition.key)
            new.append(HA4WinSensor(coordinator, entry, definition))
        if "cpu" in current_modules:
            for item in _list(_module_payload(coordinator.data, "cpu").get("per_core")):
                index = item.get("index")
                key = f"core|{index}"
                if not isinstance(index, int) or key in known:
                    continue
                known.add(key)
                new.append(HA4WinCpuCoreSensor(coordinator, entry, index))
        if "network" in current_modules:
            for name in _network_interfaces(coordinator.data):
                for metric in ("rx_bytes", "tx_bytes", "rx_kib_window", "tx_kib_window"):
                    key = f"network|{name}|{metric}"
                    if key in known:
                        continue
                    known.add(key)
                    new.append(HA4WinNetworkSensor(coordinator, entry, name, metric))
        if "volumes" in current_modules:
            for item in _list(_module_payload(coordinator.data, "volumes").get("volumes")):
                mountpoint = str(item.get("mountpoint", "")).strip()
                if not mountpoint:
                    continue
                for metric in ("used_percent", "used_gib", "free_gib"):
                    key = f"volume|{mountpoint}|{metric}"
                    if key in known:
                        continue
                    known.add(key)
                    new.append(HA4WinVolumeSensor(coordinator, entry, mountpoint, metric))
        if "services" in current_modules:
            for item in _list(_module_payload(coordinator.data, "services").get("services")):
                name = str(item.get("name", "")).strip()
                key = f"service|{name}"
                if not name or key in known:
                    continue
                known.add(key)
                new.append(HA4WinServiceSensor(coordinator, entry, name))
        maintenance = _module_payload(coordinator.data, "maintenance")
        if (
            "maintenance" in current_modules
            and maintenance.get("battery_present") is True
            and "battery" not in known
        ):
            known.add("battery")
            new.append(HA4WinBatterySensor(coordinator, entry))
        return new

    if dynamic := _new_dynamic_entities():
        async_add_entities(dynamic)

    @callback
    def _handle_update() -> None:
        if dynamic := _new_dynamic_entities():
            async_add_entities(dynamic)

    entry.async_on_unload(coordinator.async_add_listener(_handle_update))


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _module_payload(data: dict[str, Any] | None, module_id: str) -> dict[str, Any]:
    sensors = _dict(_dict(data).get("sensors"))
    return _dict(_dict(sensors.get(module_id)).get("data"))


def _module_available(data: dict[str, Any] | None, module_id: str) -> bool:
    if "sensors" in _dict(_dict(data).get("endpoint_errors")):
        return False
    module = _dict(_dict(_dict(data).get("sensors")).get(module_id))
    return bool(module.get("enabled", False) and module.get("available", False))


def _available_modules(data: dict[str, Any] | None) -> set[str]:
    capabilities = _dict(_dict(data).get("capabilities"))
    raw = capabilities.get("sensors", [])
    modules = (
        {str(item) for item in raw if str(item).strip()}
        if isinstance(raw, list)
        else set()
    )
    sensors = _dict(_dict(data).get("sensors"))
    modules.update(str(key) for key in sensors if str(key).strip())
    return modules


def _endpoint_available(data: dict[str, Any] | None, endpoint: str) -> bool:
    return endpoint not in _dict(_dict(data).get("endpoint_errors"))


def _network_interfaces(data: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    raw = _module_payload(data, "network").get("interfaces")
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)} if isinstance(raw, dict) else {}


def _find_item(items: list[dict[str, Any]], key: str, value: object) -> dict[str, Any] | None:
    return next((item for item in items if item.get(key) == value), None)


def _as_datetime(value: object) -> datetime | None:
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


def _rounded(value: object) -> float | int | None:
    return round(float(value), 2) if isinstance(value, (int, float)) else None


def _operating_system(payload: dict[str, Any]) -> str | None:
    edition = str(payload.get("edition", "")).strip()
    display = str(payload.get("display_version", "")).strip()
    return " ".join(part for part in (edition, display) if part) or None


def _system_attributes(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload:
        return None
    keys = (
        "hostname", "os_name", "edition", "display_version", "build", "major", "minor",
        "build_number", "ubr", "architecture", "install_date", "domain", "domain_joined"
    )
    return {key: payload.get(key) for key in keys}


def _cpu_attributes(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        key: payload.get(key)
        for key in (
            "logical_processors",
            "processes",
            "threads",
            "handles",
            "window_seconds",
        )
    }


def _memory_attributes(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload:
        return None
    return {key: payload.get(key) for key in ("total_kb", "available_kb", "commit_total_kb", "commit_limit_kb")}


def _updates_attributes(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload:
        return None
    keys = (
        "updates_enabled", "updates_supported", "updates_provider", "updates_state",
        "updates_refresh_in_progress", "updates_pending_count", "updates_pending_security_count",
        "updates_reboot_required", "updates_last_checked_at", "updates_last_error",
        "updates_check_interval_sec", "updates_packages", "updates_packages_total",
        "updates_packages_truncated",
    )
    return {key: payload.get(key) for key in keys}


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_") or "unknown"


def _device_info(coordinator: HA4WinCoordinator, entry: ConfigEntry) -> DeviceInfo:
    system = _module_payload(coordinator.data, "system_info")
    version = _dict(_dict(coordinator.data).get("version"))
    host = str(entry.options.get(CONF_HOST, entry.data.get(CONF_HOST, "windows")))
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=str(system.get("hostname") or host),
        manufacturer="HA4Win",
        model=str(system.get("edition") or "Windows Host API"),
        sw_version=str(version.get("api_version") or "unknown"),
        hw_version=str(system.get("build") or "unknown"),
        configuration_url=f"{coordinator.api.base_url}/health",
    )


class _HA4WinBaseSensor(CoordinatorEntity[HA4WinCoordinator], SensorEntity):
    def __init__(self, coordinator: HA4WinCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self.coordinator, self._entry)


class HA4WinSensor(_HA4WinBaseSensor):
    entity_description: SensorEntityDescription

    def __init__(self, coordinator: HA4WinCoordinator, entry: ConfigEntry, definition: HA4WinSensorDef) -> None:
        super().__init__(coordinator, entry)
        self._definition = definition
        self.entity_description = definition.description
        self._attr_unique_id = f"{entry.entry_id}_{definition.key}"

    @property
    def available(self) -> bool:
        definition = self._definition
        endpoint_ok = _endpoint_available(self.coordinator.data, definition.endpoint)
        module_ok = definition.module_id is None or _module_available(self.coordinator.data, definition.module_id)
        return super().available and endpoint_ok and module_ok and self.native_value is not None

    @property
    def native_value(self):
        return self._definition.value_fn(_dict(self.coordinator.data))

    @property
    def extra_state_attributes(self):
        if self._definition.attributes_fn is None:
            return None
        return self._definition.attributes_fn(_dict(self.coordinator.data))


class HA4WinCpuCoreSensor(_HA4WinBaseSensor):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False
    _attr_has_entity_name = True

    def __init__(self, coordinator: HA4WinCoordinator, entry: ConfigEntry, index: int) -> None:
        super().__init__(coordinator, entry)
        self._index = index
        self._attr_unique_id = f"{entry.entry_id}_cpu_core_{index}_usage"
        self._attr_name = f"CPU Core {index} Usage"

    def _item(self) -> dict[str, Any] | None:
        return _find_item(_list(_module_payload(self.coordinator.data, "cpu").get("per_core")), "index", self._index)

    @property
    def available(self) -> bool:
        return super().available and _module_available(self.coordinator.data, "cpu") and self._item() is not None

    @property
    def native_value(self):
        return _rounded(_dict(self._item()).get("usage_percent"))


class HA4WinNetworkSensor(_HA4WinBaseSensor):
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_has_entity_name = True

    def __init__(self, coordinator: HA4WinCoordinator, entry: ConfigEntry, interface: str, metric: str) -> None:
        super().__init__(coordinator, entry)
        self._interface = interface
        self._metric = metric
        labels = {
            "rx_bytes": "RX Bytes",
            "tx_bytes": "TX Bytes",
            "rx_kib_window": "RX Window",
            "tx_kib_window": "TX Window",
        }
        self._attr_unique_id = f"{entry.entry_id}_nic_{_slug(interface)}_{metric}"
        self._attr_name = f"NIC {interface} {labels[metric]}"
        if metric in {"rx_bytes", "tx_bytes"}:
            self._attr_native_unit_of_measurement = UnitOfInformation.BYTES
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
            self._attr_suggested_display_precision = 0
        else:
            self._attr_native_unit_of_measurement = UnitOfInformation.KIBIBYTES
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 2

    def _item(self) -> dict[str, Any] | None:
        return _network_interfaces(self.coordinator.data).get(self._interface)

    @property
    def available(self) -> bool:
        return super().available and _module_available(self.coordinator.data, "network") and self._item() is not None

    @property
    def native_value(self):
        return _dict(self._item()).get(self._metric)

    @property
    def extra_state_attributes(self):
        item = _dict(self._item())
        network = _module_payload(self.coordinator.data, "network")
        return {
            "interface": self._interface, "description": item.get("description"), "mac": item.get("mac"),
            "oper_status": item.get("oper_status"), "speed_mbps": item.get("speed_mbps"),
            "type": item.get("type"), "window_seconds": network.get("window_seconds"),
            "aggregate_mode": network.get("aggregate_mode"),
            "selected_interfaces": network.get("selected_interfaces"),
        }


class HA4WinVolumeSensor(_HA4WinBaseSensor):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_has_entity_name = True

    def __init__(self, coordinator: HA4WinCoordinator, entry: ConfigEntry, mountpoint: str, metric: str) -> None:
        super().__init__(coordinator, entry)
        self._mountpoint = mountpoint
        self._metric = metric
        labels = {"used_percent": "Used %", "used_gib": "Used GiB", "free_gib": "Free GiB"}
        self._attr_unique_id = f"{entry.entry_id}_volume_{_slug(mountpoint)}_{metric}"
        self._attr_name = f"Volume {mountpoint} {labels[metric]}"
        if metric == "used_percent":
            self._attr_native_unit_of_measurement = PERCENTAGE
        else:
            self._attr_native_unit_of_measurement = UnitOfInformation.GIBIBYTES
            self._attr_device_class = SensorDeviceClass.DATA_SIZE

    def _item(self) -> dict[str, Any] | None:
        items = _list(_module_payload(self.coordinator.data, "volumes").get("volumes"))
        return next((item for item in items if str(item.get("mountpoint", "")).strip() == self._mountpoint), None)

    @property
    def available(self) -> bool:
        return super().available and _module_available(self.coordinator.data, "volumes") and self._item() is not None

    @property
    def native_value(self):
        return _dict(self._item()).get(self._metric)

    @property
    def extra_state_attributes(self):
        item = _dict(self._item())
        return {
            key: item.get(key)
            for key in (
                "mountpoint",
                "label",
                "fs_type",
                "drive_type",
                "readonly",
                "total_bytes",
                "used_bytes",
                "free_bytes",
                "total_gib",
            )
        }


class HA4WinServiceSensor(_HA4WinBaseSensor):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HA4WinCoordinator, entry: ConfigEntry, service_name: str) -> None:
        super().__init__(coordinator, entry)
        self._service_name = service_name
        self._attr_unique_id = f"{entry.entry_id}_service_{_slug(service_name)}"
        self._attr_name = f"Service {service_name}"

    def _item(self) -> dict[str, Any] | None:
        items = _list(_module_payload(self.coordinator.data, "services").get("services"))
        return next((item for item in items if str(item.get("name", "")).strip() == self._service_name), None)

    @property
    def available(self) -> bool:
        return super().available and _module_available(self.coordinator.data, "services") and self._item() is not None

    @property
    def native_value(self):
        return _dict(self._item()).get("status")

    @property
    def extra_state_attributes(self):
        item = _dict(self._item())
        return {
            key: item.get(key)
            for key in (
                "display_name",
                "exists",
                "start_type",
                "pid",
                "is_active",
                "is_failed",
                "can_stop",
                "exit_code",
            )
        }


class HA4WinBatterySensor(_HA4WinBaseSensor):
    _attr_unique_id: str
    _attr_name = "Battery"
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HA4WinCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_battery"

    @property
    def available(self) -> bool:
        payload = _module_payload(self.coordinator.data, "maintenance")
        return (
            super().available
            and _module_available(self.coordinator.data, "maintenance")
            and payload.get("battery_present") is True
        )

    @property
    def native_value(self):
        return _module_payload(self.coordinator.data, "maintenance").get("battery_percent")

    @property
    def extra_state_attributes(self):
        payload = _module_payload(self.coordinator.data, "maintenance")
        return {"battery_charging": payload.get("battery_charging"), "power_source": payload.get("power_source")}
