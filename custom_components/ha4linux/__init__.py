from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er

from .api import HA4LinuxApiClient, HA4LinuxApiError, HA4LinuxNotSupportedError
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

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON, Platform.UPDATE]
_SYSTEM_UPDATES_NOTIFICATION_PREFIX = f"{DOMAIN}_system_updates"
_SERVICE_SEND_MESSAGE = "send_message"
_SERVICES_REGISTERED_KEY = "_services_registered"
_MESSAGE_TARGETS = ("broadcast", "x11")
_SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("message"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("delivery"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("host"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("entry_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
    },
    extra=vol.ALLOW_EXTRA,
)


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
    await _async_register_services(hass)

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
        _async_unregister_services_if_unused(hass)
    return unload_ok


async def _async_register_services(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if bool(domain_data.get(_SERVICES_REGISTERED_KEY, False)):
        return

    async def _async_handle_send_message(call: ServiceCall) -> None:
        entry_ids = _resolve_service_entry_ids(hass, call.data)
        if not entry_ids:
            raise HomeAssistantError("No HA4Linux entries match the requested target")

        delivery = _normalize_message_targets(call.data.get("delivery"))
        title = str(call.data.get("title", "")).strip()
        message = str(call.data["message"]).strip()

        if not message:
            raise HomeAssistantError("Message must not be empty")

        tasks = [
            _async_send_message_to_entry(
                hass,
                entry_id=entry_id,
                message=message,
                title=title or None,
                delivery=delivery or None,
            )
            for entry_id in entry_ids
        ]
        results = await asyncio.gather(*tasks)

        failures = [result for result in results if not bool(result.get("ok", False))]
        if failures:
            details = "; ".join(
                f"{result.get('host') or result.get('entry_id')}: {result.get('error', 'unknown error')}"
                for result in failures
            )
            raise HomeAssistantError(details)

    hass.services.async_register(
        DOMAIN,
        _SERVICE_SEND_MESSAGE,
        _async_handle_send_message,
        schema=_SEND_MESSAGE_SCHEMA,
    )
    domain_data[_SERVICES_REGISTERED_KEY] = True


def _async_unregister_services_if_unused(hass: HomeAssistant) -> None:
    domain_data = hass.data.get(DOMAIN, {})
    if not isinstance(domain_data, dict):
        return
    if _entry_states(hass):
        return
    if hass.services.has_service(DOMAIN, _SERVICE_SEND_MESSAGE):
        hass.services.async_remove(DOMAIN, _SERVICE_SEND_MESSAGE)
    domain_data.pop(_SERVICES_REGISTERED_KEY, None)


async def _async_send_message_to_entry(
    hass: HomeAssistant,
    *,
    entry_id: str,
    message: str,
    title: str | None,
    delivery: list[str] | None,
) -> dict[str, Any]:
    entry_state = _entry_states(hass).get(entry_id)
    if not isinstance(entry_state, dict):
        return {"ok": False, "entry_id": entry_id, "error": "Entry not loaded"}

    coordinator: HA4LinuxCoordinator = entry_state["coordinator"]
    api: HA4LinuxApiClient = entry_state["api"]
    host = _entry_host(coordinator.entry)

    try:
        result = await api.message_send(
            message,
            title=title,
            targets=delivery,
        )
    except HA4LinuxNotSupportedError as exc:
        return {
            "ok": False,
            "entry_id": entry_id,
            "host": host,
            "error": f"Messaging actuator not supported: {exc}",
        }
    except HA4LinuxApiError as exc:
        return {
            "ok": False,
            "entry_id": entry_id,
            "host": host,
            "error": str(exc),
        }

    if not bool(result.get("ok", False)):
        return {
            "ok": False,
            "entry_id": entry_id,
            "host": host,
            "error": str(result.get("error") or "Unable to deliver message"),
        }

    return {
        "ok": True,
        "entry_id": entry_id,
        "host": host,
        "result": result,
    }


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


def _entry_states(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    domain_data = hass.data.get(DOMAIN, {})
    if not isinstance(domain_data, dict):
        return {}

    entry_states: dict[str, dict[str, Any]] = {}
    for entry_id, state in domain_data.items():
        if not isinstance(entry_id, str) or not isinstance(state, dict):
            continue
        if "api" not in state or "coordinator" not in state:
            continue
        entry_states[entry_id] = state
    return entry_states


def _entry_host(entry: ConfigEntry) -> str:
    return str(entry.options.get(CONF_HOST, entry.data.get(CONF_HOST, ""))).strip()


def _normalize_string_list(raw_value: object) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        values = [raw_value]
    elif isinstance(raw_value, (list, tuple, set)):
        values = [str(item) for item in raw_value]
    else:
        values = [str(raw_value)]
    return [value.strip() for value in values if value and value.strip()]


def _normalize_message_targets(raw_value: object) -> list[str]:
    normalized: list[str] = []
    seen_targets: set[str] = set()
    invalid_targets: list[str] = []

    for item in _normalize_string_list(raw_value):
        for token in item.split(","):
            target = token.strip().lower()
            if not target:
                continue
            if target not in _MESSAGE_TARGETS:
                invalid_targets.append(target)
                continue
            if target in seen_targets:
                continue
            seen_targets.add(target)
            normalized.append(target)

    if invalid_targets:
        raise HomeAssistantError(
            "Unsupported message delivery target: " + ", ".join(sorted(set(invalid_targets)))
        )

    return normalized


def _resolve_service_entry_ids(hass: HomeAssistant, data: dict[str, Any]) -> list[str]:
    entry_states = _entry_states(hass)
    if not entry_states:
        return []

    requested_entry_ids = set(_normalize_string_list(data.get("entry_id")))
    requested_hosts = set(_normalize_string_list(data.get("host")))
    requested_device_ids = set(_normalize_string_list(data.get(ATTR_DEVICE_ID)))
    requested_entity_ids = set(_normalize_string_list(data.get(ATTR_ENTITY_ID)))
    has_explicit_target = any(
        (
            requested_entry_ids,
            requested_hosts,
            requested_device_ids,
            requested_entity_ids,
        )
    )

    matched_entry_ids: set[str] = set()

    for entry_id in requested_entry_ids:
        if entry_id in entry_states:
            matched_entry_ids.add(entry_id)

    if requested_hosts:
        for entry_id, entry_state in entry_states.items():
            coordinator: HA4LinuxCoordinator = entry_state["coordinator"]
            if _entry_host(coordinator.entry) in requested_hosts:
                matched_entry_ids.add(entry_id)

    if requested_device_ids:
        device_registry = dr.async_get(hass)
        for device_id in requested_device_ids:
            device_entry = device_registry.async_get(device_id)
            if device_entry is None:
                continue
            for config_entry_id in device_entry.config_entries:
                if config_entry_id in entry_states:
                    matched_entry_ids.add(config_entry_id)

    if requested_entity_ids:
        entity_registry = er.async_get(hass)
        for entity_id in requested_entity_ids:
            entity_entry = entity_registry.async_get(entity_id)
            if entity_entry is None:
                continue
            if entity_entry.config_entry_id in entry_states:
                matched_entry_ids.add(entity_entry.config_entry_id)

    if not has_explicit_target:
        return sorted(entry_states)

    return sorted(matched_entry_ids)


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
