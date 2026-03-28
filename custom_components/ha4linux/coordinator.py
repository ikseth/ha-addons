from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HA4LinuxApiClient, HA4LinuxApiError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, INTEGRATION_VERSION


class HA4LinuxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: HA4LinuxApiClient) -> None:
        self.api = api
        self.entry = entry
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            capabilities = await self.api.capabilities()
            version = await self.api.version()
            sensors = await self.api.sensors()
            update_status = await self.api.update_status()

            data: dict[str, Any] = {
                "capabilities": capabilities,
                "version": version,
                "compatibility": _evaluate_compatibility(version),
                "sensors": sensors,
                "update": update_status,
                "session": None,
                "app_policy": None,
                "virtualbox": None,
            }

            actuators = capabilities.get("actuators", [])
            if isinstance(actuators, list) and "session_manager" in actuators:
                data["session"] = await self.api.session_status()

            if isinstance(actuators, list) and "app_policy" in actuators:
                data["app_policy"] = await self.api.app_policy_status()

            if isinstance(actuators, list) and "virtualbox_manager" in actuators:
                data["virtualbox"] = await self.api.virtualbox_status()

            return data
        except HA4LinuxApiError as exc:
            raise UpdateFailed(str(exc)) from exc


def _evaluate_compatibility(version: dict[str, Any]) -> dict[str, str]:
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
        return compatibility

    if min_semver is None or max_semver is None:
        compatibility["reason"] = "invalid API compatibility range"
        return compatibility

    if current_semver < min_semver or current_semver > max_semver:
        compatibility["status"] = "incompatible"
        compatibility["reason"] = "integration version outside API range"
        return compatibility

    compatibility["status"] = "compatible"
    compatibility["reason"] = "integration version within API range"
    return compatibility


def _parse_semver(raw: str) -> tuple[int, int, int] | None:
    token = raw.strip().lower()
    if not token:
        return None
    if token.startswith("v"):
        token = token[1:]
    token = token.split("-", 1)[0]
    return _parse_bound(token, wildcard_value=0, fill_value=0)


def _parse_bound(
    raw: str,
    wildcard_value: int,
    fill_value: int,
) -> tuple[int, int, int] | None:
    parts = raw.strip().lower().split(".")
    if not parts or len(parts) > 3:
        return None

    parsed: list[int] = []
    for part in parts:
        if part in {"x", "*"}:
            parsed.append(wildcard_value)
            continue
        if not part.isdigit():
            return None
        parsed.append(int(part))

    while len(parsed) < 3:
        parsed.append(fill_value)

    return tuple(parsed[:3])
