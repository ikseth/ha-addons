from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


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
            "last_checked_at": None,
            "last_applied_at": None,
            "last_error": None,
            "error": None,
            "supports_apply": bool(self._apply_command),
            "supports_rollback": bool(self._rollback_command),
        }

    def status(self) -> dict[str, Any]:
        if self._should_auto_check():
            self.check()
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

            current_semver = _parse_semver(self._api_version)
            target_semver = _parse_semver(target_version)
            if target_semver is None:
                return self._set_error("invalid target version in manifest")
            if current_semver is None:
                return self._set_error("invalid installed API version")

            update_available = target_semver > current_semver
            with self._lock:
                self._last_check_monotonic = time.monotonic()
                self._state.update(
                    {
                        "ok": True,
                        "state": "idle",
                        "installed_version": self._api_version,
                        "target_version": target_version,
                        "update_available": update_available,
                        "changelog_url": changelog_url,
                        "last_checked_at": _now_iso(),
                        "last_error": None,
                        "error": None,
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

        selected_version = (target_version or current.get("target_version") or "").strip()
        if not selected_version:
            return self._set_error("target version unavailable")

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
                },
            )
            with self._lock:
                self._state.update(
                    {
                        "ok": True,
                        "state": "idle",
                        "last_applied_at": _now_iso(),
                        "last_error": None,
                        "error": None,
                    }
                )
            # Re-evaluate status against manifest to avoid false positives when
            # apply command succeeds but installed version is still unchanged.
            return self.check()
        except Exception as exc:
            return self._set_error(str(exc))

    def rollback(self) -> dict[str, Any]:
        if not self._enabled:
            return self._set_error("remote update disabled by configuration")
        if self._readonly_mode and not self._allow_in_readonly:
            return self._set_error("readonly mode enabled: rollback is blocked")
        if not self._rollback_command:
            return self._set_error("rollback command not configured")

        with self._lock:
            self._state["state"] = "rollback"
            self._state["error"] = None

        try:
            self._run_command(self._rollback_command, extra_env={"HA4LINUX_CHANNEL": self._channel})
            with self._lock:
                self._state.update(
                    {
                        "ok": True,
                        "state": "idle",
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
        request = urllib.request.Request(
            self._manifest_url,
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
                }
            )
            return dict(self._state)
