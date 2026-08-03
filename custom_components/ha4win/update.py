"""Update entities for the HA4Win agent and integration."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    INTEGRATION_DOWNLOAD_URL,
    INTEGRATION_REPOSITORY_URL,
    INTEGRATION_UPDATE_MANIFEST_URL,
    INTEGRATION_VERSION,
)
from .coordinator import HA4WinCoordinator
from .sensor import _device_info, _dict

_IN_PROGRESS_STATES = {
    "checking", "downloading", "verifying", "applying", "restarting", "rollback"
}
_INTEGRATION_UPDATE_OWNER_KEY = "_integration_update_owner_entry_id"
_MANIFEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
SCAN_INTERVAL = timedelta(hours=6)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HA4WinCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    agent_created = False

    def _try_add_agent() -> None:
        nonlocal agent_created
        if agent_created or not _agent_update_enabled(coordinator.data):
            return
        agent_created = True
        async_add_entities([HA4WinApiUpdateEntity(coordinator, entry)])

    _try_add_agent()
    owner = hass.data[DOMAIN].setdefault(_INTEGRATION_UPDATE_OWNER_KEY, entry.entry_id)
    if owner == entry.entry_id:
        async_add_entities([HA4WinIntegrationUpdateEntity(hass)])

    @callback
    def _handle_update() -> None:
        _try_add_agent()

    entry.async_on_unload(coordinator.async_add_listener(_handle_update))


def _update_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    return _dict(_dict(data).get("update"))


def _agent_update_enabled(data: dict[str, Any] | None) -> bool:
    status = _update_payload(data)
    return bool(status.get("available", False) and status.get("enabled", False))


class HA4WinApiUpdateEntity(
    CoordinatorEntity[HA4WinCoordinator], UpdateEntity
):
    """Represent remote updates of the HA4Win agent."""

    _attr_has_entity_name = True
    _attr_name = "API Update"
    _attr_title = "HA4Win API"

    def __init__(
        self, coordinator: HA4WinCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_api_update"

    def _status(self) -> dict[str, Any]:
        return _update_payload(self.coordinator.data)

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self.coordinator, self._entry)

    @property
    def available(self) -> bool:
        status = self._status()
        return (
            super().available
            and bool(status.get("available", False))
            and bool(status.get("supported", True))
            and bool(status.get("enabled", False))
        )

    @property
    def supported_features(self) -> UpdateEntityFeature:
        if self._status().get("supports_apply") is True:
            return UpdateEntityFeature.INSTALL | UpdateEntityFeature.SPECIFIC_VERSION
        return UpdateEntityFeature(0)

    @property
    def installed_version(self) -> str | None:
        return str(self._status().get("installed_version") or "").strip() or None

    @property
    def latest_version(self) -> str | None:
        return str(self._status().get("target_version") or "").strip() or None

    @property
    def in_progress(self) -> bool:
        return str(self._status().get("state", "")).lower() in _IN_PROGRESS_STATES

    @property
    def release_url(self) -> str | None:
        return str(self._status().get("changelog_url") or "").strip() or None

    @property
    def release_summary(self) -> str | None:
        status = self._status()
        reason = status.get("supports_apply_reason") or status.get("last_error") or status.get("error")
        return str(reason).strip()[:255] if reason else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._status()
        keys = (
            "ok", "enabled", "readonly_mode", "allow_in_readonly", "state",
            "update_available", "channel", "manifest_url", "asset_url", "asset_sha256",
            "supports_apply", "supports_apply_reason", "supports_rollback", "rollback_version",
            "preflight", "last_checked_at", "last_applied_at", "last_error", "error",
        )
        return {key: status.get(key) for key in keys}

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        status = self._status()
        if status.get("supports_apply") is not True:
            raise HomeAssistantError(
                str(status.get("supports_apply_reason") or "Remote update apply is unavailable")
            )
        check = await self.coordinator.api.update_check()
        if not check.get("ok", False):
            raise HomeAssistantError(str(check.get("error") or "Unable to check for updates"))
        requested = str(version).strip() if version else None
        result = await self.coordinator.api.update_apply(requested)
        if not result.get("ok", False):
            raise HomeAssistantError(str(result.get("error") or "Unable to apply update"))
        updated = dict(self.coordinator.data)
        updated["update"] = {**result, "available": True}
        self.coordinator.async_set_updated_data(updated)

        async def _deferred_refresh() -> None:
            await asyncio.sleep(5)
            with suppress(Exception):
                await self.coordinator.async_request_refresh()

        self.hass.async_create_task(_deferred_refresh())


class HA4WinIntegrationUpdateEntity(UpdateEntity):
    """Inform about updates of this custom integration."""

    _attr_unique_id = "ha4win_integration_update"
    _attr_name = "HA4Win Integration"
    _attr_title = "HA4Win"
    _attr_icon = "mdi:home-assistant"
    _attr_has_entity_name = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._session = async_get_clientsession(hass)
        self._status = self._empty_status()

    @staticmethod
    def _empty_status() -> dict[str, Any]:
        return {
            "installed_version": INTEGRATION_VERSION,
            "latest_version": None,
            "release_url": INTEGRATION_REPOSITORY_URL,
            "download_url": INTEGRATION_DOWNLOAD_URL,
            "notes": None,
            "last_checked_at": None,
            "error": None,
        }

    @property
    def available(self) -> bool:
        return self._status.get("error") is None

    @property
    def supported_features(self) -> UpdateEntityFeature:
        return UpdateEntityFeature(0)

    @property
    def installed_version(self) -> str | None:
        return str(self._status.get("installed_version") or "").strip() or None

    @property
    def latest_version(self) -> str | None:
        return str(self._status.get("latest_version") or "").strip() or None

    @property
    def release_url(self) -> str | None:
        return str(self._status.get("release_url") or "").strip() or None

    @property
    def release_summary(self) -> str | None:
        notes = self._status.get("notes")
        return str(notes).strip()[:255] if notes else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "repository_url": INTEGRATION_REPOSITORY_URL,
            "download_url": self._status.get("download_url"),
            "manifest_url": INTEGRATION_UPDATE_MANIFEST_URL,
            "notes": self._status.get("notes"),
            "last_checked_at": self._status.get("last_checked_at"),
            "error": self._status.get("error"),
        }

    async def async_update(self) -> None:
        status = self._empty_status()
        try:
            async with self._session.get(
                INTEGRATION_UPDATE_MANIFEST_URL, timeout=_MANIFEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                payload = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            status["error"] = f"Unable to fetch integration update metadata: {exc}"
            self._status = status
            return
        if not isinstance(payload, dict):
            status["error"] = "Integration update metadata is not a JSON object"
        else:
            status["latest_version"] = str(payload.get("version") or "").strip() or None
            status["release_url"] = str(payload.get("release_url") or "").strip() or INTEGRATION_REPOSITORY_URL
            status["download_url"] = str(payload.get("download_url") or "").strip() or INTEGRATION_DOWNLOAD_URL
            status["notes"] = str(payload.get("notes") or "").strip() or None
            status["last_checked_at"] = datetime.now(timezone.utc).isoformat()
        self._status = status

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        return _parse_semver(latest_version) > _parse_semver(installed_version)


def _parse_semver(raw: str) -> tuple[int, int, int]:
    token = raw.strip().lower().removeprefix("v").split("-", 1)[0]
    values = [int(part) if part.isdigit() else 0 for part in token.split(".")[:3]]
    return tuple((values + [0, 0, 0])[:3])
