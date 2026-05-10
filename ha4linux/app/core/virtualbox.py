from __future__ import annotations

import copy
import getpass
import logging
import os
import re
import signal
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

_LIST_RE = re.compile(r'^"(?P<name>.*)"\s+\{(?P<uuid>[^}]+)\}$')
_OFF_STATES = {"", "poweroff", "saved", "aborted", "inaccessible"}
LOGGER = logging.getLogger(__name__)


class VirtualBoxCommandError(RuntimeError):
    pass


class VirtualBoxClient:
    _LIST_TIMEOUT_SECONDS = 10
    _INFO_TIMEOUT_SECONDS = 10
    _ACTION_TIMEOUT_SECONDS = 30

    def __init__(
        self,
        user: str,
        *,
        status_cache_ttl_sec: int = 30,
        status_stale_ttl_sec: int = 900,
        failure_backoff_min_sec: int = 30,
        failure_backoff_max_sec: int = 300,
    ) -> None:
        self.user = user.strip()
        if not self.user:
            raise ValueError("virtualbox user must not be empty")

        binary = shutil.which("VBoxManage") or shutil.which("vboxmanage")
        if binary is None:
            raise ValueError("VBoxManage command not found")
        self._binary = binary
        self._status_cache_ttl_sec = max(1, int(status_cache_ttl_sec))
        self._status_stale_ttl_sec = max(self._status_cache_ttl_sec, int(status_stale_ttl_sec))
        self._failure_backoff_min_sec = max(1, int(failure_backoff_min_sec))
        self._failure_backoff_max_sec = max(
            self._failure_backoff_min_sec,
            int(failure_backoff_max_sec),
        )
        self._cache_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._cached_vms: list[dict[str, Any]] = []
        self._cached_vms_refreshed_mono = 0.0
        self._cached_vms_refreshed_at: Optional[str] = None
        self._cached_vms_last_attempted_at: Optional[str] = None
        self._cached_vms_last_error: Optional[str] = None
        self._cached_vms_failure_count = 0
        self._cached_vms_backoff_until_mono = 0.0
        self._cached_vms_backoff_until: Optional[str] = None

    def list_vms(self) -> list[dict[str, Any]]:
        snapshot = self.list_vms_snapshot()
        return snapshot.get("vms", [])

    def list_vms_snapshot(self, *, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        with self._cache_lock:
            if not force_refresh and self._cache_is_fresh(now):
                return self._snapshot(stale=False, source="cache")

            if not force_refresh and self._circuit_open(now):
                if self._cache_is_usable(now):
                    return self._snapshot(stale=True, source="stale_cache")
                raise VirtualBoxCommandError(self._current_backoff_reason())

        try:
            vms = self._collect_vms()
        except VirtualBoxCommandError as exc:
            failure_message = str(exc)
            with self._cache_lock:
                self._record_failure(failure_message)
                if self._cache_is_usable(time.monotonic()):
                    LOGGER.warning(
                        "VirtualBox refresh failed for user '%s'; serving stale cache: %s",
                        self.user,
                        failure_message,
                    )
                    return self._snapshot(stale=True, source="stale_cache")
            raise

        with self._cache_lock:
            self._store_cache(vms)
            return self._snapshot(stale=False, source="live")

    def _collect_vms(self) -> list[dict[str, Any]]:
        all_vms = self._run_list("vms")
        cached_by_uuid = self._cached_vm_index()

        vms: list[dict[str, Any]] = []
        for vm in all_vms:
            name = str(vm.get("name", "")).strip()
            uuid = str(vm.get("uuid", "")).strip()
            if not uuid:
                continue

            inaccessible = name == "<inaccessible>"
            info: dict[str, str] = {}
            raw_state = ""
            if not inaccessible:
                try:
                    info = self.show_vm_info(uuid)
                    raw_state = str(info.get("VMState", "")).strip().lower()
                except VirtualBoxCommandError as exc:
                    cached = cached_by_uuid.get(uuid.lower())
                    if cached is not None:
                        vms.append(cached)
                        continue
                    LOGGER.warning(
                        "VirtualBox showvminfo failed for VM '%s' (%s): %s",
                        name or uuid,
                        uuid,
                        exc,
                    )
                    info = {}

            vms.append(
                self._build_vm_payload(
                    name=name,
                    uuid=uuid,
                    raw_state=raw_state,
                    info=info,
                    inaccessible=inaccessible,
                )
            )

        vms.sort(key=lambda item: str(item.get("name", "")))
        return vms

    def resolve_vm(
        self,
        *,
        vm_uuid: Optional[str] = None,
        vm_name: Optional[str] = None,
        vm_id: Optional[str] = None,
    ) -> dict[str, Any]:
        raw_identifier = vm_id or vm_uuid or vm_name
        identifier = str(raw_identifier or "").strip()
        if not identifier:
            raise ValueError("Missing VM identifier")

        try:
            info = self.show_vm_info(identifier)
        except VirtualBoxCommandError as exc:
            raise ValueError(f"VM '{identifier}' not found") from exc

        name = str(info.get("name", "")).strip() or identifier
        uuid = str(info.get("UUID", "")).strip() or str(vm_uuid or vm_id or "").strip()
        raw_state = str(info.get("VMState", "")).strip().lower()
        inaccessible = name == "<inaccessible>"
        if not uuid:
            cached = self._cached_vm_lookup(identifier)
            if cached is not None:
                return cached
        return self._build_vm_payload(
            name=name,
            uuid=uuid,
            raw_state=raw_state,
            info=info,
            inaccessible=inaccessible,
        )

    def show_vm_info(self, vm_identifier: str) -> dict[str, str]:
        command = self._command_prefix() + [self._binary, "showvminfo", vm_identifier, "--machinereadable"]
        result = self._run(command, timeout_seconds=self._INFO_TIMEOUT_SECONDS)
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise VirtualBoxCommandError(f"VBoxManage showvminfo failed: {stderr}")
        return self._parse_machine_readable(result.stdout)

    def start_vm(self, vm_identifier: str, *, start_type: str) -> subprocess.CompletedProcess[str]:
        return self._run(
            self._command_prefix() + [self._binary, "startvm", vm_identifier, "--type", start_type],
            timeout_seconds=self._ACTION_TIMEOUT_SECONDS,
        )

    def control_vm(self, vm_identifier: str, command: str) -> subprocess.CompletedProcess[str]:
        return self._run(
            self._command_prefix() + [self._binary, "controlvm", vm_identifier, command],
            timeout_seconds=self._ACTION_TIMEOUT_SECONDS,
        )

    def _run_list(self, list_type: str) -> list[dict[str, str]]:
        command = self._command_prefix() + [self._binary, "list", list_type]
        result = self._run(command, timeout_seconds=self._LIST_TIMEOUT_SECONDS)
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise VirtualBoxCommandError(f"VBoxManage list {list_type} failed: {stderr}")

        vms: list[dict[str, str]] = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = _LIST_RE.match(line)
            if match is None:
                continue
            vms.append(
                {
                    "name": match.group("name"),
                    "uuid": match.group("uuid"),
                }
            )
        return vms

    def _run(self, command: list[str], *, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
        with self._command_lock:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                self._terminate_process_tree(process)
                stdout, stderr = process.communicate()
                raise VirtualBoxCommandError(
                    f"Command '{' '.join(command)}' timed out after {timeout_seconds} seconds"
                ) from exc

            return subprocess.CompletedProcess(
                command,
                process.returncode,
                stdout,
                stderr,
            )

    def _terminate_process_tree(self, process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

        try:
            process.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            pass

        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    def _command_prefix(self) -> list[str]:
        try:
            current_user = getpass.getuser().strip()
        except Exception:
            current_user = os.getenv("USER", "").strip()
        if current_user == self.user:
            return []
        return ["sudo", "-n", "-H", "-u", self.user]

    def update_cached_vm(self, vm: dict[str, Any]) -> None:
        uuid = str(vm.get("uuid", "")).strip().lower()
        if not uuid:
            return

        with self._cache_lock:
            if not self._cached_vms:
                return
            updated = copy.deepcopy(vm)
            replaced = False
            new_cache: list[dict[str, Any]] = []
            for item in self._cached_vms:
                item_uuid = str(item.get("uuid", "")).strip().lower()
                if item_uuid == uuid:
                    new_cache.append(updated)
                    replaced = True
                else:
                    new_cache.append(copy.deepcopy(item))
            if not replaced:
                return
            new_cache.sort(key=lambda item: str(item.get("name", "")))
            self._cached_vms = new_cache
            self._cached_vms_refreshed_mono = time.monotonic()
            self._cached_vms_refreshed_at = self._timestamp()
            self._cached_vms_last_error = None
            self._cached_vms_failure_count = 0
            self._cached_vms_backoff_until_mono = 0.0
            self._cached_vms_backoff_until = None

    def invalidate_cache(self) -> None:
        with self._cache_lock:
            self._cached_vms_refreshed_mono = 0.0
            self._cached_vms_refreshed_at = None

    def _build_vm_payload(
        self,
        *,
        name: str,
        uuid: str,
        raw_state: str,
        info: dict[str, str],
        inaccessible: bool,
    ) -> dict[str, Any]:
        running = raw_state == "running"
        powered_on = self._is_powered_on(raw_state, running)
        status = self._normalize_state(raw_state, running=running, inaccessible=inaccessible)
        return {
            "name": name,
            "uuid": uuid,
            "status": status,
            "state_raw": raw_state or None,
            "running": running,
            "powered_on": powered_on,
            "inaccessible": inaccessible,
            "user": self.user,
            "session_name": info.get("sessionName") or None,
            "os_type": info.get("ostype") or None,
        }

    def _cache_is_fresh(self, now: float) -> bool:
        return bool(self._cached_vms) and (now - self._cached_vms_refreshed_mono) < self._status_cache_ttl_sec

    def _cache_is_usable(self, now: float) -> bool:
        return bool(self._cached_vms) and (now - self._cached_vms_refreshed_mono) < self._status_stale_ttl_sec

    def _circuit_open(self, now: float) -> bool:
        return now < self._cached_vms_backoff_until_mono

    def _record_failure(self, error: str) -> None:
        self._cached_vms_last_attempted_at = self._timestamp()
        self._cached_vms_last_error = error
        self._cached_vms_failure_count += 1
        backoff_seconds = min(
            self._failure_backoff_min_sec * (2 ** (self._cached_vms_failure_count - 1)),
            self._failure_backoff_max_sec,
        )
        self._cached_vms_backoff_until_mono = time.monotonic() + backoff_seconds
        self._cached_vms_backoff_until = self._timestamp(offset_seconds=backoff_seconds)

    def _store_cache(self, vms: list[dict[str, Any]]) -> None:
        self._cached_vms = copy.deepcopy(vms)
        self._cached_vms_refreshed_mono = time.monotonic()
        self._cached_vms_refreshed_at = self._timestamp()
        self._cached_vms_last_attempted_at = self._cached_vms_refreshed_at
        self._cached_vms_last_error = None
        self._cached_vms_failure_count = 0
        self._cached_vms_backoff_until_mono = 0.0
        self._cached_vms_backoff_until = None

    def _cached_vm_index(self) -> dict[str, dict[str, Any]]:
        with self._cache_lock:
            return {
                str(item.get("uuid", "")).strip().lower(): copy.deepcopy(item)
                for item in self._cached_vms
                if str(item.get("uuid", "")).strip()
            }

    def _cached_vm_lookup(self, identifier: str) -> Optional[dict[str, Any]]:
        identifier_key = identifier.strip().lower()
        if not identifier_key:
            return None
        with self._cache_lock:
            for item in self._cached_vms:
                name = str(item.get("name", "")).strip().lower()
                uuid = str(item.get("uuid", "")).strip().lower()
                if identifier_key in {name, uuid}:
                    return copy.deepcopy(item)
        return None

    def _snapshot(self, *, stale: bool, source: str) -> dict[str, Any]:
        now = time.monotonic()
        age_seconds = round(max(0.0, now - self._cached_vms_refreshed_mono), 3) if self._cached_vms else None
        return {
            "vms": copy.deepcopy(self._cached_vms),
            "cache": {
                "source": source,
                "stale": stale,
                "ttl_sec": self._status_cache_ttl_sec,
                "stale_ttl_sec": self._status_stale_ttl_sec,
                "failure_backoff_min_sec": self._failure_backoff_min_sec,
                "failure_backoff_max_sec": self._failure_backoff_max_sec,
                "refreshed_at": self._cached_vms_refreshed_at,
                "age_sec": age_seconds,
                "last_attempted_at": self._cached_vms_last_attempted_at,
                "last_error": self._cached_vms_last_error,
                "failure_count": self._cached_vms_failure_count,
                "backoff_until": self._cached_vms_backoff_until,
                "backoff_active": self._circuit_open(now),
            },
        }

    def _current_backoff_reason(self) -> str:
        if self._cached_vms_last_error:
            return (
                f"VirtualBox refresh backoff active until {self._cached_vms_backoff_until}; "
                f"last error: {self._cached_vms_last_error}"
            )
        return "VirtualBox refresh backoff active"

    def _timestamp(self, *, offset_seconds: int = 0) -> str:
        current = datetime.now(timezone.utc)
        if offset_seconds:
            current = datetime.fromtimestamp(current.timestamp() + offset_seconds, timezone.utc)
        return current.isoformat()

    def _normalize_state(self, raw_state: str, *, running: bool, inaccessible: bool) -> str:
        if inaccessible:
            return "inaccessible"
        if raw_state == "poweroff":
            return "stopped"
        if raw_state:
            return raw_state
        if running:
            return "running"
        return "stopped"

    def _is_powered_on(self, raw_state: str, running: bool) -> bool:
        if raw_state:
            return raw_state not in _OFF_STATES
        return running

    def _parse_machine_readable(self, raw_output: str) -> dict[str, str]:
        data: dict[str, str] = {}
        for raw_line in raw_output.splitlines():
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                value = value[1:-1]
            data[key] = value
        return data
