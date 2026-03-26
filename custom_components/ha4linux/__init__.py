from __future__ import annotations

import asyncio

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import entity_registry as er

from .api import HA4LinuxApiClient
from .const import (
    CONF_HOST,
    CONF_PORT,
    DEPRECATED_ENTITY_UNIQUE_IDS,
    CONF_TOKEN,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from .coordinator import HA4LinuxCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.UPDATE]
_SYSTEM_UPDATES_NOTIFICATION_PREFIX = f"{DOMAIN}_system_updates"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    effective = {**entry.data, **entry.options}

    api = HA4LinuxApiClient(
        session=async_get_clientsession(hass),
        host=effective[CONF_HOST],
        port=effective[CONF_PORT],
        token=effective[CONF_TOKEN],
        use_https=effective[CONF_USE_HTTPS],
        verify_ssl=effective[CONF_VERIFY_SSL],
    )

    coordinator = HA4LinuxCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    await _async_remove_deprecated_entities(hass, entry)

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "system_updates_notification_signature": None,
    }

    await _async_sync_system_updates_notification(hass, entry, coordinator)

    @callback
    def _handle_coordinator_update() -> None:
        hass.async_create_task(_async_sync_system_updates_notification(hass, entry, coordinator))

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hass.async_create_task(_async_remove_deprecated_entities_later(hass, entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        persistent_notification.async_dismiss(hass, _system_updates_notification_id(entry))
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_remove_deprecated_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    registry = er.async_get(hass)
    target_unique_ids = {
        f"{entry.entry_id}_{unique_id}"
        for unique_id in DEPRECATED_ENTITY_UNIQUE_IDS
    }

    for entity_entry in list(registry.entities.values()):
        if entity_entry.config_entry_id != entry.entry_id:
            continue
        if entity_entry.unique_id not in target_unique_ids:
            continue
        registry.async_remove(entity_entry.entity_id)


async def _async_remove_deprecated_entities_later(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await asyncio.sleep(5)
    await _async_remove_deprecated_entities(hass, entry)


def _system_updates_notification_id(entry: ConfigEntry) -> str:
    return f"{_SYSTEM_UPDATES_NOTIFICATION_PREFIX}_{entry.entry_id}"


def _system_info_payload(data: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(data, dict):
        return {}

    sensors = data.get("sensors", {})
    if not isinstance(sensors, dict):
        return {}

    module = sensors.get("system_info", {})
    if not isinstance(module, dict):
        return {}

    payload = module.get("data", {})
    return payload if isinstance(payload, dict) else {}


def _notification_signature(payload: dict[str, object]) -> tuple[object, ...]:
    packages = payload.get("updates_packages", [])
    package_signature: tuple[str, ...] = ()
    if isinstance(packages, list):
        package_signature = tuple(
            str(item.get("raw") or item.get("name") or "")
            for item in packages
            if isinstance(item, dict)
        )

    return (
        payload.get("updates_pending_count"),
        payload.get("updates_last_checked_at"),
        payload.get("distribution"),
        payload.get("package_manager"),
        package_signature,
    )


def _build_system_updates_message(entry: ConfigEntry, payload: dict[str, object]) -> str:
    host = str(entry.options.get(CONF_HOST, entry.data.get(CONF_HOST, "linux"))).strip() or "linux"
    distribution = str(payload.get("distribution") or "Linux").strip()
    package_manager = str(payload.get("package_manager") or "unknown").strip()
    checked_at = str(payload.get("updates_last_checked_at") or "unknown").strip()
    pending_count = int(payload.get("updates_pending_count") or 0)
    packages = payload.get("updates_packages", [])

    lines = [
        f"Host: `{host}`",
        f"Distribution: `{distribution}`",
        f"Package manager: `{package_manager}`",
        f"Pending updates: `{pending_count}`",
        f"Last checked at: `{checked_at}`",
    ]

    if isinstance(packages, list) and packages:
        lines.append("")
        lines.append("Preview:")
        for item in packages:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "package").strip()
            candidate_version = str(item.get("candidate_version") or "").strip()
            if candidate_version:
                lines.append(f"- `{name}` -> `{candidate_version}`")
            else:
                lines.append(f"- `{name}`")

    if bool(payload.get("updates_packages_truncated", False)):
        total = int(payload.get("updates_packages_total") or pending_count)
        shown = len(packages) if isinstance(packages, list) else 0
        remaining = max(total - shown, 0)
        if remaining > 0:
            lines.append(f"- ... and `{remaining}` more packages")

    return "\n".join(lines)


async def _async_sync_system_updates_notification(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: HA4LinuxCoordinator,
) -> None:
    entry_state = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not isinstance(entry_state, dict):
        return

    payload = _system_info_payload(coordinator.data)
    notification_id = _system_updates_notification_id(entry)

    state = str(payload.get("updates_state") or "").strip().lower()
    should_notify = (
        bool(payload.get("updates_enabled", False))
        and bool(payload.get("updates_supported", False))
        and state == "idle"
        and int(payload.get("updates_pending_count") or 0) > 0
    )

    if not should_notify:
        if entry_state.get("system_updates_notification_signature") is not None:
            persistent_notification.async_dismiss(hass, notification_id)
            entry_state["system_updates_notification_signature"] = None
        return

    signature = _notification_signature(payload)
    if signature == entry_state.get("system_updates_notification_signature"):
        return

    persistent_notification.async_create(
        hass,
        _build_system_updates_message(entry, payload),
        title="HA4Linux system updates available",
        notification_id=notification_id,
    )
    entry_state["system_updates_notification_signature"] = signature
