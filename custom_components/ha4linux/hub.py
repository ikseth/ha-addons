"""Integration-wide entities: one loaded config entry ("owner") hosts them."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, HUB_OWNER_KEY
from .coordinator import HA4LinuxCoordinator

HUB_DEVICE_INFO = DeviceInfo(
    identifiers={(DOMAIN, "hub")},
    name="HA4Linux",
    manufacturer="HA4Linux",
    model="Integration summary",
    entry_type=DeviceEntryType.SERVICE,
)


def claim_hub_owner(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    owner_entry_id = hass.data.setdefault(DOMAIN, {}).setdefault(HUB_OWNER_KEY, entry.entry_id)
    return owner_entry_id == entry.entry_id


def release_hub_owner(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Hand the integration-wide entities over to another loaded entry when the owner is removed."""
    domain_data = hass.data.get(DOMAIN, {})
    if domain_data.get(HUB_OWNER_KEY) != entry.entry_id:
        return
    domain_data.pop(HUB_OWNER_KEY, None)
    for candidate in hass.config_entries.async_entries(DOMAIN):
        if candidate.entry_id != entry.entry_id and candidate.state is ConfigEntryState.LOADED:
            hass.config_entries.async_schedule_reload(candidate.entry_id)
            return


def loaded_coordinators(hass: HomeAssistant) -> list[HA4LinuxCoordinator]:
    coordinators: list[HA4LinuxCoordinator] = []
    for entry_id, state in hass.data.get(DOMAIN, {}).items():
        if not isinstance(entry_id, str) or not isinstance(state, dict):
            continue
        coordinator = state.get("coordinator")
        if isinstance(coordinator, HA4LinuxCoordinator):
            coordinators.append(coordinator)
    return coordinators
