from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from app.core.update_preflight import evaluate_update_preflight


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_semver(raw: str) -> tuple[int, int, int] | None:
    token = raw.strip().lower()
    if not token:
        return None
    if token.startswith("v"):
        token = token[1:]
    token = token.split("-", 1)[0]
    parts = token.split(".")
    if len(parts) > 3:
        return None
    parsed: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        parsed.append(int(part))
    while len(parsed) < 3:
        parsed.append(0)
    return tuple(parsed[:3])


class UpdateManager:
    def __init__(
        self,
        *,
        api_version: str,
        enabled: bool,
        readonly_mode: bool,
        allow_in_readonly: bool,
        manifest_url: str,
        channel: str,
        check_interval_sec: int,
        check_timeout_sec: int,
        command_timeout_sec: int,
        apply_command: str,
        rollback_command: str,
    ) -> None:
        self._api_version = api_version
        self._enabled = enabled
        self._readonly_mode = readonly_mode
        self._allow_in_readonly = allow_in_readonly
        self._manifest_url = manifest_url.strip()
        self._channel = channel.strip() or "stable"
        self._check_interval_sec = max(check_interval_sec, 30)
        self._check_timeout_sec = max(check_timeout_sec, 3)
        self._command_timeout_sec = max(command_timeout_sec, 30)
        self._apply_command = apply_command.strip()
        self._rollback_command = rollback_command.strip()
        self._lock = threading.Lock()
        self._last_check_monotonic = 0.0
        self._state: dict[str, Any] = {
            "ok": True,
            "supported": True,
            "enabled": self._enabled,
            "readonly_mode": self._readonly_mode,
            "allow_in_readonly": self._allow_in_readonly,
            "state": "idle" if self._enabled else "disabled",
            "installed_version": self._api_version,
            "target_version": None,
            "update_available": False,
            "channel": self._channel,
            "manifest_url": self._manifest_url,
            "changelog_url": None,
            "asset_url": None,
            "asset_sha256": None,
            "last_checked_at": None,
            "last_applied_at": None,
            "last_error": None,
            "error": None,
            "supports_apply": False,
            "supports_rollback": bool(self._rollback_command),
            "supports_apply_reason": None,
            "preflight": {},
        }

    def status(self) -> dict[str, Any]:
        if self._should_auto_check():
            self.check()
        else:
            self._refresh_preflight()
        with self._lock:
            return dict(self._state)

    def check(self) -> dict[str, Any]:
        if not self._enabled:
            return self._set_error("remote update disabled by configuration")
        if not self._manifest_url:
            return self._set_error("manifest URL not configured")

        with self._lock:
            self._state["state"] = "checking"
            self._state["error"] = None

        try:
            manifest = self._fetch_manifest()
            target_version = str(manifest.get("version", "")).strip()
            changelog_url = str(manifest.get("changelog_url", "")).strip() or None
            asset_url = str(manifest.get("asset_url", "")).strip() or None
            asset_sha256 = str(manifest.get("sha256", "")).strip() or None

            current_semver = _parse_semver(self._api_version)
            target_semver = _parse_semver(target_version)
            if target_semver is None:
                return self._set_error("invalid target version in manifest")
            if current_semver is None:
                return self._set_error("invalid installed API version")

            update_available = target_semver > current_semver
            with self._lock:
                self._last_check_monotonic = time.monotonic()
                preflight = self._evaluate_preflight(asset_url=asset_url)
                self._state.update(
                    {
                        "ok": True,
                        "state": "idle",
                        "installed_version": self._api_version,
                        "target_version": target_version,
                        "update_available": update_available,
                        "changelog_url": changelog_url,
                        "asset_url": asset_url,
                        "asset_sha256": asset_sha256,
                        "last_checked_at": _now_iso(),
                        "last_error": None,
                        "error": None,
                        "supports_apply": bool(self._apply_command and asset_url and preflight["can_apply"]),
                        "supports_rollback": bool(self._rollback_command),
                        "supports_apply_reason": preflight["reason"],
                        "preflight": preflight,
                    }
                )
                return dict(self._state)
        except Exception as exc:
            return self._set_error(str(exc))

    def apply(self, target_version: str | None = None) -> dict[str, Any]:
        if not self._enabled:
            return self._set_error("remote update disabled by configuration")
        if self._readonly_mode and not self._allow_in_readonly:
            return self._set_error("readonly mode enabled: updates are blocked")
        if not self._apply_command:
            return self._set_error("apply command not configured")

        current = self.check()
        if not current.get("ok", False):
            return current
        preflight = current.get("preflight", {})
        if not bool(preflight.get("can_apply", False)):
            return self._set_error(
                str(current.get("supports_apply_reason") or "preflight failed for remote apply")
            )

        selected_version = (target_version or current.get("target_version") or "").strip()
        if not selected_version:
            return self._set_error("target version unavailable")
        asset_url = str(current.get("asset_url") or "").strip()
        asset_sha256 = str(current.get("asset_sha256") or "").strip()
        if not asset_url:
            return self._set_error("update asset URL not available")

        current_semver = _parse_semver(self._api_version)
        selected_semver = _parse_semver(selected_version)
        if current_semver is None or selected_semver is None:
            return self._set_error("invalid semantic version during apply")

        if target_version is None and not bool(current.get("update_available", False)):
            return self._set_error("no update available")

        if selected_semver <= current_semver:
            return self._set_error("target version is not newer than installed version")

        with self._lock:
            self._state["state"] = "applying"
            self._state["error"] = None

        try:
            self._run_command(
                self._apply_command,
                extra_env={
                    "HA4LINUX_TARGET_VERSION": selected_version,
                    "HA4LINUX_INSTALLED_VERSION": self._api_version,
                    "HA4LINUX_CHANNEL": self._channel,
                    "HA4LINUX_MANIFEST_URL": self._manifest_url,
                    "HA4LINUX_UPDATE_ASSET_URL": asset_url,
                    "HA4LINUX_UPDATE_ASSET_SHA256": asset_sha256,
                },
            )
            with self._lock:
                self._state.update(
                    {
                        "ok": True,
                        "state": "restarting",
                        "target_version": selected_version,
                        "last_applied_at": _now_iso(),
                        "last_error": None,
                        "error": None,
                        "asset_url": asset_url,
                        "asset_sha256": asset_sha256,
                    }
                )
                return dict(self._state)
        except Exception as exc:
            return self._set_error(str(exc))

    def rollback(self) -> dict[str, Any]:
        if not self._enabled:
            return self._set_error("remote update disabled by configuration")
        if self._readonly_mode and not self._allow_in_readonly:
            return self._set_error("readonly mode enabled: rollback is blocked")
        if not self._rollback_command:
            return self._set_error("rollback command not configured")

        preflight = self._evaluate_preflight(asset_url=str(self._state.get("asset_url") or "").strip())
        if not bool(preflight.get("can_apply", False)):
            return self._set_error(str(preflight.get("reason") or "preflight failed for rollback"))

        with self._lock:
            self._state["state"] = "rollback"
            self._state["error"] = None

        try:
            self._run_command(self._rollback_command, extra_env={"HA4LINUX_CHANNEL": self._channel})
            with self._lock:
                self._state.update(
                    {
                        "ok": True,
                        "state": "restarting",
                        "last_error": None,
                        "error": None,
                    }
                )
                return dict(self._state)
        except Exception as exc:
            return self._set_error(str(exc))

    def _should_auto_check(self) -> bool:
        if not self._enabled or not self._manifest_url:
            return False
        elapsed = time.monotonic() - self._last_check_monotonic
        return self._last_check_monotonic <= 0 or elapsed >= self._check_interval_sec

    def _fetch_manifest(self) -> dict[str, Any]:
        parsed_url = urllib.parse.urlsplit(self._manifest_url)
        query_params = urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True)
        # Bypass raw.githubusercontent CDN lag so hosts see the latest stable manifest quickly.
        query_params.append(("ha4linux_ts", str(int(time.time() // 30))))
        request_url = urllib.parse.urlunsplit(
            parsed_url._replace(query=urllib.parse.urlencode(query_params))
        )
        request = urllib.request.Request(
            request_url,
            method="GET",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._check_timeout_sec) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"manifest fetch failed: {exc}") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("manifest is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("manifest payload must be a JSON object")

        # Optional channel layout:
        # {\"channels\": {\"stable\": {\"version\": \"...\"}}}
        channels = payload.get("channels")
        if isinstance(channels, dict):
            selected = channels.get(self._channel)
            if not isinstance(selected, dict):
                raise RuntimeError(f"manifest channel '{self._channel}' not found")
            return selected

        return payload

    def _run_command(self, raw_command: str, extra_env: dict[str, str]) -> None:
        argv = shlex.split(raw_command)
        if not argv:
            raise RuntimeError("empty command")

        env = {**os.environ, **extra_env}
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=self._command_timeout_sec,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            raise RuntimeError(f"command failed ({completed.returncode}): {stderr}")

    def _set_error(self, message: str) -> dict[str, Any]:
        with self._lock:
            self._state.update(
                {
                    "ok": False,
                    "state": "error",
                    "last_error": message,
                    "error": message,
                    "supports_apply": bool(
                        self._apply_command
                        and self._state.get("asset_url")
                        and bool(self._state.get("preflight", {}).get("can_apply", False))
                    ),
                    "supports_rollback": bool(self._rollback_command),
                }
            )
            return dict(self._state)

    def _refresh_preflight(self) -> None:
        with self._lock:
            asset_url = str(self._state.get("asset_url") or "").strip()
            preflight = self._evaluate_preflight(asset_url=asset_url)
            self._state["preflight"] = preflight
            self._state["supports_apply_reason"] = preflight["reason"]
            self._state["supports_apply"] = bool(
                self._apply_command and asset_url and preflight["can_apply"]
            )

    def _evaluate_preflight(self, *, asset_url: str) -> dict[str, Any]:
        preflight = evaluate_update_preflight(
            apply_command=self._apply_command,
            rollback_command=self._rollback_command,
        )
        preflight["asset_available"] = bool(asset_url)
        if not asset_url and preflight.get("reason") is None:
            preflight["can_apply"] = False
            preflight["ok"] = False
            preflight["reason"] = "update asset URL not available"
        return preflight
