"""Sensores binarios de deteccion SMD y de estado de la conexion."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EVENT_HUMAN, EVENT_VEHICLE
from .coordinator import AmcrestSmdCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AmcrestSmdCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AmcrestSmdDetectionSensor(
                coordinator, EVENT_HUMAN, "persona", "Persona detectada"
            ),
            AmcrestSmdDetectionSensor(
                coordinator, EVENT_VEHICLE, "vehiculo", "Vehiculo detectado"
            ),
            AmcrestSmdConnectionSensor(coordinator),
        ]
    )


def _build_device_info(coordinator: AmcrestSmdCoordinator) -> DeviceInfo:
    """Describe el dispositivo al que pertenecen las entidades.

    Si conocemos la MAC declaramos la conexion de red, con lo que HA fusiona
    estas entidades con el dispositivo que ya creo la integracion ONVIF para la
    misma camara, en vez de aparecer como un dispositivo duplicado.
    """
    serial = coordinator.device_info.get("serial_number") or coordinator.entry.entry_id
    device = DeviceInfo(
        identifiers={(DOMAIN, serial)},
        manufacturer="Amcrest",
        model=coordinator.device_info.get("device_type") or None,
        name=coordinator.entry.title,
    )

    mac = coordinator.device_info.get("mac")
    if mac:
        device["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    return device


class AmcrestSmdBaseEntity(BinarySensorEntity):
    """Base con la suscripcion al coordinador y el dispositivo comun."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: AmcrestSmdCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_device_info = _build_device_info(coordinator)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.add_listener(self.async_write_ha_state)
        )


class AmcrestSmdDetectionSensor(AmcrestSmdBaseEntity):
    """Deteccion de persona o vehiculo publicada por la camara.

    Queda `unavailable` cuando la conexion esta caida. Es deliberado: no se
    inventa un `off`, porque un `off` falso con alguien presente apagaria las
    luces de forma silenciosa. Quien consuma esta entidad decide que hacer con
    el estado desconocido.
    """

    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(
        self,
        coordinator: AmcrestSmdCoordinator,
        event_code: str,
        slug: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._event_code = event_code
        self._attr_name = name
        serial = coordinator.device_info.get("serial_number") or coordinator.entry.entry_id
        self._attr_unique_id = f"{serial}_{slug}"

    @property
    def available(self) -> bool:
        return self.coordinator.connected

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.states.get(self._event_code)


class AmcrestSmdConnectionSensor(AmcrestSmdBaseEntity):
    """Estado del stream de eventos.

    Se mantiene siempre disponible: es la entidad que dice la verdad sobre si
    los sensores de deteccion son fiables en este momento.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Conexion de eventos"

    def __init__(self, coordinator: AmcrestSmdCoordinator) -> None:
        super().__init__(coordinator)
        serial = coordinator.device_info.get("serial_number") or coordinator.entry.entry_id
        self._attr_unique_id = f"{serial}_conexion"

    @property
    def is_on(self) -> bool:
        return self.coordinator.connected
