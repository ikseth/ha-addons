"""HA4Win integration setup, services, and notifications."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HA4WinApiClient, HA4WinApiError
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TLS_FINGERPRINT,
    CONF_TOKEN,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DEFAULT_TLS_FINGERPRINT,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import HA4WinCoordinator

_SERVICE_POWER_ACTION = "power_action"
_SERVICES_REGISTERED_KEY = "_services_registered"
_INTEGRATION_UPDATE_OWNER_KEY = "_integration_update_owner_entry_id"
_UPDATES_NOTIFICATION_PREFIX = f"{DOMAIN}_windows_updates"
_REBOOT_NOTIFICATION_PREFIX = f"{DOMAIN}_pending_reboot"
_POWER_ACTIONS = {"lock", "sleep", "hibernate", "restart", "shutdown", "cancel"}

_POWER_ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("action"): vol.In(_POWER_ACTIONS),
        vol.Optional("delay_seconds"): vol.All(vol.Coerce(int), vol.Range(min=0, max=86400)),
        vol.Optional("force"): cv.boolean,
        vol.Optional("message"): cv.string,
        vol.Optional("host"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("entry_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA4Win from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    effective = {**entry.data, **entry.options}
    api = HA4WinApiClient(
        session=async_get_clientsession(hass),
        host=effective[CONF_HOST],
        port=effective[CONF_PORT],
        token=effective[CONF_TOKEN],
        use_https=effective[CONF_USE_HTTPS],
        verify_ssl=effective[CONF_VERIFY_SSL],
        tls_fingerprint=effective.get(CONF_TLS_FINGERPRINT, DEFAULT_TLS_FINGERPRINT),
    )
    coordinator = HA4WinCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    system = _module_payload(coordinator.data, "system_info")
    version = _dict(_dict(coordinator.data).get("version"))
    host = str(effective[CONF_HOST]).strip()
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=str(system.get("hostname") or host),
        manufacturer="HA4Win",
        model=str(system.get("edition") or "Windows Host API"),
        sw_version=str(version.get("api_version") or "unknown"),
        hw_version=str(system.get("build") or "unknown"),
        configuration_url=f"{api.base_url}/health",
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "updates_notification_signature": None,
        "reboot_notification_signature": None,
    }
    await _async_register_services(hass)
    await _async_sync_notifications(hass, entry, coordinator)

    @callback
    def _handle_coordinator_update() -> None:
        hass.async_create_task(_async_sync_notifications(hass, entry, coordinator))

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a HA4Win config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    persistent_notification.async_dismiss(hass, _updates_notification_id(entry))
    persistent_notification.async_dismiss(hass, _reboot_notification_id(entry))
    domain_data = hass.data.get(DOMAIN, {})
    if isinstance(domain_data, dict):
        domain_data.pop(entry.entry_id, None)
        if domain_data.get(_INTEGRATION_UPDATE_OWNER_KEY) == entry.entry_id:
            domain_data.pop(_INTEGRATION_UPDATE_OWNER_KEY, None)
    _async_unregister_services_if_unused(hass)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_services(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_SERVICES_REGISTERED_KEY):
        return

    async def _handle_power_action(call: ServiceCall) -> None:
        entry_ids = _resolve_service_entry_ids(hass, call.data)
        if not entry_ids:
            raise HomeAssistantError("No HA4Win entries match the requested target")

        action = str(call.data["action"]).strip().lower()
        payload = {
            key: call.data[key]
            for key in ("delay_seconds", "force", "message")
            if key in call.data
        }
        results = await asyncio.gather(
            *(
                _async_power_action_to_entry(hass, entry_id, action, payload)
                for entry_id in entry_ids
            )
        )
        failures = [result for result in results if not result.get("ok", False)]
        if failures:
            raise HomeAssistantError(
                "; ".join(
                    f"{result.get('host') or result.get('entry_id')}: "
                    f"{result.get('error', 'unknown error')}"
                    for result in failures
                )
            )

    hass.services.async_register(
        DOMAIN,
        _SERVICE_POWER_ACTION,
        _handle_power_action,
        schema=_POWER_ACTION_SCHEMA,
    )
    domain_data[_SERVICES_REGISTERED_KEY] = True


async def _async_power_action_to_entry(
    hass: HomeAssistant,
    entry_id: str,
    action: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    state = _entry_states(hass).get(entry_id)
    if state is None:
        return {"ok": False, "entry_id": entry_id, "error": "Entry not loaded"}
    coordinator: HA4WinCoordinator = state["coordinator"]
    host = _entry_host(coordinator.entry)
    try:
        result = await coordinator.api.actuator_action(action, payload)
    except HA4WinApiError as exc:
        return {"ok": False, "entry_id": entry_id, "host": host, "error": str(exc)}
    if not result.get("ok", False):
        return {
            "ok": False,
            "entry_id": entry_id,
            "host": host,
            "error": str(result.get("error") or f"Unable to execute {action}"),
        }
    await coordinator.async_request_refresh()
    return {"ok": True, "entry_id": entry_id, "host": host, "result": result}


def _async_unregister_services_if_unused(hass: HomeAssistant) -> None:
    domain_data = hass.data.get(DOMAIN, {})
    if not isinstance(domain_data, dict) or _entry_states(hass):
        return
    if hass.services.has_service(DOMAIN, _SERVICE_POWER_ACTION):
        hass.services.async_remove(DOMAIN, _SERVICE_POWER_ACTION)
    domain_data.pop(_SERVICES_REGISTERED_KEY, None)


def _entry_states(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    domain_data = hass.data.get(DOMAIN, {})
    if not isinstance(domain_data, dict):
        return {}
    return {
        key: value
        for key, value in domain_data.items()
        if isinstance(key, str)
        and isinstance(value, dict)
        and "api" in value
        and "coordinator" in value
    }


def _entry_host(entry: ConfigEntry) -> str:
    return str(entry.options.get(CONF_HOST, entry.data.get(CONF_HOST, ""))).strip()


def _normalize_string_list(value: object) -> list[str]:
    if value is None:
        return []
    raw = [value] if isinstance(value, str) else value if isinstance(value, (list, tuple, set)) else [value]
    return [str(item).strip() for item in raw if str(item).strip()]


def _resolve_service_entry_ids(hass: HomeAssistant, data: dict[str, Any]) -> list[str]:
    states = _entry_states(hass)
    requested_entries = set(_normalize_string_list(data.get("entry_id")))
    requested_hosts = set(_normalize_string_list(data.get("host")))
    requested_devices = set(_normalize_string_list(data.get(ATTR_DEVICE_ID)))
    requested_entities = set(_normalize_string_list(data.get(ATTR_ENTITY_ID)))
    explicit = bool(requested_entries or requested_hosts or requested_devices or requested_entities)
    matched = {entry_id for entry_id in requested_entries if entry_id in states}

    for entry_id, state in states.items():
        coordinator: HA4WinCoordinator = state["coordinator"]
        if _entry_host(coordinator.entry) in requested_hosts:
            matched.add(entry_id)

    device_registry = dr.async_get(hass)
    for device_id in requested_devices:
        device = device_registry.async_get(device_id)
        if device is not None:
            matched.update(entry_id for entry_id in device.config_entries if entry_id in states)

    entity_registry = er.async_get(hass)
    for entity_id in requested_entities:
        entity = entity_registry.async_get(entity_id)
        if entity is not None and entity.config_entry_id in states:
            matched.add(entity.config_entry_id)
    return sorted(matched) if explicit else sorted(states)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _module_section(data: dict[str, Any] | None, module_id: str) -> dict[str, Any]:
    return _dict(_dict(_dict(data).get("sensors")).get(module_id))


def _module_payload(data: dict[str, Any] | None, module_id: str) -> dict[str, Any]:
    return _dict(_module_section(data, module_id).get("data"))


def _module_available(data: dict[str, Any] | None, module_id: str) -> bool:
    section = _module_section(data, module_id)
    errors = _dict(_dict(data).get("endpoint_errors"))
    return "sensors" not in errors and section.get("available") is True


def _updates_notification_id(entry: ConfigEntry) -> str:
    return f"{_UPDATES_NOTIFICATION_PREFIX}_{entry.entry_id}"


def _reboot_notification_id(entry: ConfigEntry) -> str:
    return f"{_REBOOT_NOTIFICATION_PREFIX}_{entry.entry_id}"


async def _async_sync_notifications(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: HA4WinCoordinator
) -> None:
    state = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not isinstance(state, dict):
        return
    if _module_available(coordinator.data, "system_info"):
        system = _module_payload(coordinator.data, "system_info")
        count = int(system.get("updates_pending_count") or 0)
        signature = (
            count,
            system.get("updates_last_checked_at"),
            system.get("updates_packages_total"),
        )
        if count <= 0:
            persistent_notification.async_dismiss(hass, _updates_notification_id(entry))
            state["updates_notification_signature"] = None
        elif signature != state.get("updates_notification_signature"):
            persistent_notification.async_create(
                hass,
                _build_updates_message(entry, system),
                title="HA4Win Windows updates available",
                notification_id=_updates_notification_id(entry),
            )
            state["updates_notification_signature"] = signature

    if _module_available(coordinator.data, "maintenance"):
        maintenance = _module_payload(coordinator.data, "maintenance")
        pending = maintenance.get("pending_reboot") is True
        reasons = maintenance.get("pending_reboot_reasons", [])
        signature = tuple(str(reason) for reason in reasons) if isinstance(reasons, list) else ()
        if not pending:
            persistent_notification.async_dismiss(hass, _reboot_notification_id(entry))
            state["reboot_notification_signature"] = None
        elif signature != state.get("reboot_notification_signature"):
            host = _entry_host(entry) or "Windows host"
            detail = ", ".join(signature) if signature else "unspecified"
            persistent_notification.async_create(
                hass,
                f"Host: `{host}`\n\nA Windows restart is pending.\n\nReasons: `{detail}`",
                title="HA4Win restart required",
                notification_id=_reboot_notification_id(entry),
            )
            state["reboot_notification_signature"] = signature


def _build_updates_message(entry: ConfigEntry, payload: dict[str, Any]) -> str:
    host = _entry_host(entry) or "Windows host"
    count = int(payload.get("updates_pending_count") or 0)
    security_count = int(payload.get("updates_pending_security_count") or 0)
    lines = [
        f"Host: `{host}`",
        f"Pending updates: `{count}`",
        f"Pending security updates: `{security_count}`",
        f"Last checked at: `{payload.get('updates_last_checked_at') or 'unknown'}`",
    ]
    packages = payload.get("updates_packages", [])
    if isinstance(packages, list) and packages:
        lines.extend(("", "Preview:"))
        for package in packages:
            if not isinstance(package, dict):
                continue
            title = str(package.get("title") or "Windows update")
            kb = str(package.get("kb") or "").strip()
            severity = str(package.get("severity") or "").strip()
            suffix = " · ".join(item for item in (kb, severity) if item)
            lines.append(f"- {title}" + (f" (`{suffix}`)" if suffix else ""))
    if payload.get("updates_packages_truncated") is True:
        total = int(payload.get("updates_packages_total") or count)
        shown = len(packages) if isinstance(packages, list) else 0
        if total > shown:
            lines.append(f"- ... and `{total - shown}` more updates")
    return "\n".join(lines)
