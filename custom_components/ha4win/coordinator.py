"""Data coordinator for HA4Win."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any, Awaitable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HA4WinApiClient, HA4WinApiError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, INTEGRATION_VERSION

_LOGGER = logging.getLogger(__name__)
_CORE_ENDPOINTS = ("capabilities", "version", "sensors")


class HA4WinCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch independent HA4Win endpoints concurrently."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: HA4WinApiClient) -> None:
        self.api = api
        self.entry = entry
        interval = int(
            entry.options.get(
                CONF_SCAN_INTERVAL,
                entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        )
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        capabilities_task = asyncio.create_task(self.api.capabilities())

        async def _power_status_after_capabilities() -> dict[str, Any] | None:
            try:
                capabilities = await capabilities_task
            except HA4WinApiError:
                return None
            actuators = capabilities.get("actuators", [])
            if not isinstance(actuators, list) or "power_manager" not in actuators:
                return None
            return await self.api.actuator_action("status")

        calls: dict[str, Awaitable[dict[str, Any] | None]] = {
            "capabilities": capabilities_task,
            "version": self.api.version(),
            "sensors": self.api.sensors(),
            "update": self.api.update_status(),
            "power_status": _power_status_after_capabilities(),
        }
        results = await asyncio.gather(*calls.values(), return_exceptions=True)
        previous = self.data if isinstance(self.data, dict) else {}
        data: dict[str, Any] = {}
        endpoint_errors: dict[str, str] = {}

        for key, result in zip(calls, results, strict=True):
            if isinstance(result, BaseException):
                endpoint_errors[key] = str(result)
                _LOGGER.debug("HA4Win endpoint %s failed: %s", key, result)
                old_value = previous.get(key, {})
                data[key] = dict(old_value) if isinstance(old_value, dict) else {}
                continue
            data[key] = result if isinstance(result, dict) else {}

        failed_core = [key for key in _CORE_ENDPOINTS if key in endpoint_errors]
        if len(failed_core) == len(_CORE_ENDPOINTS) and not any(previous.get(key) for key in _CORE_ENDPOINTS):
            details = "; ".join(f"{key}: {endpoint_errors[key]}" for key in failed_core)
            raise UpdateFailed(details)

        update = data.get("update", {})
        if not isinstance(update, dict):
            update = {}
        update = dict(update)
        if "update" in endpoint_errors:
            update["available"] = False
            update["error"] = endpoint_errors["update"]
        else:
            update.setdefault("supported", True)
            update.setdefault("enabled", False)
            update.setdefault("update_available", False)
            update.setdefault("state", "idle")
            update["available"] = True
        data["update"] = update

        power_status = data.get("power_status", {})
        if isinstance(power_status, dict):
            power_status = dict(power_status)
            power_status["available"] = "power_status" not in endpoint_errors and bool(power_status)
            if "power_status" in endpoint_errors:
                power_status["error"] = endpoint_errors["power_status"]
            data["power_status"] = power_status

        version = data.get("version", {})
        data["compatibility"] = _evaluate_compatibility(version if isinstance(version, dict) else {})
        data["endpoint_errors"] = endpoint_errors
        return data


def _evaluate_compatibility(version: dict[str, Any]) -> dict[str, str]:
    """Evaluate the integration version against the agent's supported range."""
    minimum = str(version.get("min_integration_version", "0.0.0")).strip()
    maximum = str(version.get("max_integration_version", "999.999.999")).strip()
    current = INTEGRATION_VERSION

    current_semver = _parse_semver(current)
    min_semver = _parse_bound(minimum, wildcard_value=0, fill_value=0)
    max_semver = _parse_bound(maximum, wildcard_value=999_999, fill_value=999_999)
    compatibility = {
        "status": "unknown",
        "integration_version": current,
        "min_integration_version": minimum,
        "max_integration_version": maximum,
        "reason": "version information unavailable",
    }

    if current_semver is None:
        compatibility["reason"] = f"invalid integration version '{current}'"
    elif min_semver is None or max_semver is None:
        compatibility["reason"] = "invalid API compatibility range"
    elif current_semver < min_semver or current_semver > max_semver:
        compatibility["status"] = "incompatible"
        compatibility["reason"] = "integration version outside API range"
    else:
        compatibility["status"] = "compatible"
        compatibility["reason"] = "integration version within API range"
    return compatibility


def _parse_semver(raw: str) -> tuple[int, int, int] | None:
    token = raw.strip().lower()
    if not token:
        return None
    if token.startswith("v"):
        token = token[1:]
    return _parse_bound(token.split("-", 1)[0], wildcard_value=0, fill_value=0)


def _parse_bound(
    raw: str, wildcard_value: int, fill_value: int
) -> tuple[int, int, int] | None:
    parts = raw.strip().lower().split(".")
    if not parts or len(parts) > 3:
        return None
    parsed: list[int] = []
    for part in parts:
        if part in {"x", "*"}:
            parsed.append(wildcard_value)
        elif part.isdigit():
            parsed.append(int(part))
        else:
            return None
    while len(parsed) < 3:
        parsed.append(fill_value)
    return tuple(parsed[:3])
