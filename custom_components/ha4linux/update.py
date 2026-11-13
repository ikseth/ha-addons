from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_HOST,
    DOMAIN,
    INTEGRATION_DOWNLOAD_URL,
    INTEGRATION_REPOSITORY_URL,
    INTEGRATION_UPDATE_MANIFEST_URL,
    INTEGRATION_VERSION,
)
from .coordinator import HA4LinuxCoordinator
from .hub import HUB_DEVICE_INFO, claim_hub_owner

_IN_PROGRESS_STATES = {"checking", "downloading", "applying", "restarting", "rollback"}
_PENDING_TIMEOUT_SECONDS = 300
_REFRESH_DELAYS = (5, 15, 30, 60, 120, 180, 300)
_LOGGER = logging.getLogger(__name__)
_INTEGRATION_UPDATE_TIMEOUT = aiohttp.ClientTimeout(total=10)
SCAN_INTERVAL = timedelta(hours=6)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HA4LinuxCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    created = False

    def _try_add_entity() -> None:
        nonlocal created
        if created:
            return
        if not _is_update_available(coordinator.data):
            return
        created = True
        async_add_entities([HA4LinuxApiUpdateEntity(coordinator, entry)])

    _try_add_entity()

    if claim_hub_owner(hass, entry):
        async_add_entities([HA4LinuxIntegrationUpdateEntity(hass)])

    @callback
    def _handle_coordinator_update() -> None:
        _try_add_entity()

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


def _update_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    payload = data.get("update", {})
    return payload if isinstance(payload, dict) else {}


def _is_update_available(data: dict[str, Any] | None) -> bool:
    payload = _update_payload(data)
    return bool(payload.get("supported", False) and payload.get("enabled", False))


class _HA4LinuxBaseUpdate(CoordinatorEntity[HA4LinuxCoordinator], UpdateEntity):
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


class HA4LinuxApiUpdateEntity(_HA4LinuxBaseUpdate):
    def __init__(self, coordinator: HA4LinuxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_api_update"
        self._attr_name = "API Update"
        self._attr_has_entity_name = True
        self._attr_title = "HA4Linux API"
        self._pending_target: str | None = None
        self._pending_started: datetime | None = None
        self._pending_monotonic: float | None = None
        self._apply_confirmed = False
        self._last_valid_status: dict[str, Any] = {}
        self._last_update_issue: str | None = None
        self._refresh_cancellers: list[Any] = []
        self._remember_status()

    def _status(self) -> dict[str, Any]:
        status = _update_payload(self.coordinator.data)
        if self._pending_target is not None and not status.get("enabled", False):
            return self._last_valid_status
        return status

    def _remember_status(self) -> None:
        status = _update_payload(self.coordinator.data)
        if status.get("enabled", False) and status.get("supported", False):
            self._last_valid_status = dict(status)

    def _close_pending(self) -> None:
        self._pending_target = None
        self._pending_started = None
        self._pending_monotonic = None
        self._apply_confirmed = False
        for cancel in self._refresh_cancellers:
            cancel()
        self._refresh_cancellers.clear()

    @callback
    def _handle_coordinator_update(self) -> None:
        status = _update_payload(self.coordinator.data)
        if self.coordinator.last_update_success:
            self._remember_status()
        if self._pending_target is not None:
            if self.coordinator.last_update_success and status.get("enabled") and str(status.get("installed_version", "")).strip() == self._pending_target:
                self._last_update_issue = None
                self._close_pending()
            elif self._apply_confirmed and self.coordinator.last_update_success and status.get("enabled") and status.get("state") == "error" and (
                bool(status.get("error")) or self._applied_before_pending(status.get("last_applied_at"))
            ):
                self._close_pending()
            elif self._pending_monotonic is not None and time.monotonic() - self._pending_monotonic >= _PENDING_TIMEOUT_SECONDS:
                self._expire_pending()
        super()._handle_coordinator_update()

    def _applied_before_pending(self, raw: Any) -> bool:
        if not raw or self._pending_started is None:
            return True
        try:
            return datetime.fromisoformat(str(raw)) <= self._pending_started
        except (ValueError, TypeError):
            return False

    def _expire_pending(self) -> None:
        target = self._pending_target
        if target is None:
            return
        self._last_update_issue = f"update to {target} did not complete within {_PENDING_TIMEOUT_SECONDS} s"
        host = self._entry.options.get(CONF_HOST, self._entry.data.get(CONF_HOST, "linux"))
        _LOGGER.warning("HA4Linux update for %s: %s", host, self._last_update_issue)
        self._close_pending()
        self.async_write_ha_state()

    def _schedule_refreshes(self) -> None:
        for delay in _REFRESH_DELAYS:
            @callback
            def refresh(_now: datetime, refresh_delay: int = delay) -> None:
                if self._pending_target is not None:
                    async def run_refresh() -> None:
                        try:
                            await self.coordinator.async_request_refresh()
                        except Exception:
                            _LOGGER.exception("HA4Linux update refresh failed")
                        if refresh_delay == _PENDING_TIMEOUT_SECONDS and self._pending_target is not None:
                            self._expire_pending()

                    self.hass.async_create_task(run_refresh())

            self._refresh_cancellers.append(async_call_later(self.hass, delay, refresh))
        self.async_on_remove(self._close_pending)

    @property
    def available(self) -> bool:
        if self._pending_target is not None:
            return True
        status = self._status()
        return bool(status) and bool(status.get("supported", False)) and bool(status.get("enabled", False))

    @property
    def supported_features(self) -> UpdateEntityFeature:
        status = self._status()
        if bool(status.get("supports_apply", False)):
            return UpdateEntityFeature.INSTALL | UpdateEntityFeature.SPECIFIC_VERSION | UpdateEntityFeature.PROGRESS
        return UpdateEntityFeature(0)

    @property
    def installed_version(self) -> str | None:
        installed = self._status().get("installed_version")
        if installed is None:
            return None
        token = str(installed).strip()
        return token or None

    @property
    def latest_version(self) -> str | None:
        target = self._status().get("target_version")
        if target is None:
            return None
        token = str(target).strip()
        return token or None

    @property
    def in_progress(self) -> bool:
        if self._pending_target is not None:
            return True
        state = str(self._status().get("state", "")).strip().lower()
        return bool(self.coordinator.last_update_success and state in _IN_PROGRESS_STATES)

    @property
    def update_percentage(self) -> None:
        return None

    @property
    def release_url(self) -> str | None:
        value = self._status().get("changelog_url")
        if value is None:
            return None
        token = str(value).strip()
        return token or None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        status = self._status()
        if not status:
            return None
        return {
            "last_update_issue": self._last_update_issue,
            "ok": status.get("ok"),
            "enabled": status.get("enabled"),
            "state": status.get("state"),
            "update_available": status.get("update_available"),
            "channel": status.get("channel"),
            "manifest_url": status.get("manifest_url"),
            "asset_url": status.get("asset_url"),
            "asset_sha256": status.get("asset_sha256"),
            "supports_apply": status.get("supports_apply"),
            "supports_apply_reason": status.get("supports_apply_reason"),
            "supports_rollback": status.get("supports_rollback"),
            "preflight": status.get("preflight"),
            "last_checked_at": status.get("last_checked_at"),
            "last_applied_at": status.get("last_applied_at"),
            "error": status.get("error"),
        }

    async def async_install(
        self,
        version: str | None,
        backup: bool,
        **kwargs: Any,
    ) -> None:
        status = self._status()
        if not bool(status.get("supports_apply", False)):
            raise HomeAssistantError(
                str(
                    status.get("supports_apply_reason")
                    or "Remote apply command is not configured on this host"
                )
            )

        requested_version = str(version).strip() if version else None
        target = requested_version or self.latest_version
        if not target:
            raise HomeAssistantError("No target version available")
        self._pending_target = target
        self._pending_started = datetime.now(UTC)
        self._pending_monotonic = time.monotonic()
        self.async_write_ha_state()
        self._schedule_refreshes()
        try:
            check = await self.coordinator.api.update_check()
            if not check.get("ok", False):
                raise HomeAssistantError(check.get("error", "Unable to check update state"))
            apply_result = await self.coordinator.api.update_apply(target_version=requested_version)
            if not apply_result.get("ok", False):
                raise HomeAssistantError(apply_result.get("error", "Unable to apply update"))
        except Exception as exc:
            self._close_pending()
            self.async_write_ha_state()
            raise HomeAssistantError(str(exc)) from exc

        # Stale "error" states from earlier attempts must not close the new pending update.
        self._apply_confirmed = True
        updated_data = dict(self.coordinator.data)
        updated_data["update"] = apply_result
        self.coordinator.async_set_updated_data(updated_data)


class HA4LinuxIntegrationUpdateEntity(UpdateEntity):
    _attr_unique_id = "ha4linux_integration_update"
    _attr_name = "HA4Linux Integration"
    _attr_title = "HA4Linux"
    _attr_icon = "mdi:home-assistant"
    _attr_has_entity_name = False
    _attr_device_info = HUB_DEVICE_INFO

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._session = async_get_clientsession(hass)
        self._status: dict[str, Any] = {
            "installed_version": INTEGRATION_VERSION,
            "latest_version": None,
            "release_url": INTEGRATION_REPOSITORY_URL,
            "download_url": INTEGRATION_DOWNLOAD_URL,
            "notes": None,
            "last_checked_at": None,
            "error": None,
        }

    async def async_added_to_hass(self) -> None:
        # Check right away instead of waiting for the first SCAN_INTERVAL (6 h).
        self.async_schedule_update_ha_state(force_refresh=True)

    @property
    def available(self) -> bool:
        # A failed check keeps the last good metadata; only unavailable if no check ever succeeded.
        return self._status.get("error") is None or self._status.get("latest_version") is not None

    @property
    def supported_features(self) -> UpdateEntityFeature:
        return UpdateEntityFeature(0)

    @property
    def installed_version(self) -> str | None:
        return str(self._status.get("installed_version") or INTEGRATION_VERSION).strip() or None

    @property
    def latest_version(self) -> str | None:
        latest = self._status.get("latest_version")
        if latest is None:
            return None
        token = str(latest).strip()
        return token or None

    @property
    def release_url(self) -> str | None:
        value = self._status.get("release_url")
        if value is None:
            return None
        token = str(value).strip()
        return token or None

    @property
    def release_summary(self) -> str | None:
        value = self._status.get("notes")
        if value is None:
            return None
        token = str(value).strip()
        return token[:255] or None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return {
            "repository_url": INTEGRATION_REPOSITORY_URL,
            "download_url": self._status.get("download_url"),
            "manifest_url": INTEGRATION_UPDATE_MANIFEST_URL,
            "notes": self._status.get("notes"),
            "last_checked_at": self._status.get("last_checked_at"),
            "error": self._status.get("error"),
        }

    async def async_update(self) -> None:
        status = {
            "installed_version": INTEGRATION_VERSION,
            "latest_version": None,
            "release_url": INTEGRATION_REPOSITORY_URL,
            "download_url": INTEGRATION_DOWNLOAD_URL,
            "notes": None,
            "last_checked_at": None,
            "error": None,
        }

        try:
            async with self._session.get(
                INTEGRATION_UPDATE_MANIFEST_URL,
                timeout=_INTEGRATION_UPDATE_TIMEOUT,
            ) as response:
                response.raise_for_status()
                # raw.githubusercontent.com serves the manifest as text/plain: skip the content-type check.
                payload = await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
            self._set_error(f"Unable to fetch integration update metadata: {exc}")
            return

        if not isinstance(payload, dict):
            self._set_error("Integration update metadata is not a JSON object")
            return

        status["latest_version"] = str(payload.get("version") or "").strip() or None
        status["release_url"] = (
            str(payload.get("release_url") or "").strip() or INTEGRATION_REPOSITORY_URL
        )
        status["download_url"] = (
            str(payload.get("download_url") or "").strip() or INTEGRATION_DOWNLOAD_URL
        )
        status["notes"] = str(payload.get("notes") or "").strip() or None
        status["last_checked_at"] = datetime.now(UTC).isoformat()
        self._status = status

    def _set_error(self, error: str) -> None:
        self._status = {**self._status, "error": error}

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        return _parse_semver(latest_version) > _parse_semver(installed_version)


def _parse_semver(raw: str) -> tuple[int, int, int]:
    token = raw.strip().lower()
    token = token.removeprefix("v")
    token = token.split("-", 1)[0]
    parts = token.split(".")
    parsed: list[int] = []
    for part in parts[:3]:
        if part.isdigit():
            parsed.append(int(part))
        else:
            parsed.append(0)
    while len(parsed) < 3:
        parsed.append(0)
    return tuple(parsed[:3])
