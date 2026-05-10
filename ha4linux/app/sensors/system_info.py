from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from app.sensors.base import Sensor


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_os_release() -> dict[str, str]:
    path = Path("/etc/os-release")
    if not path.is_file():
        return {}

    payload: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        token = value.strip()
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
            token = token[1:-1]
        payload[key.strip()] = token

    return payload


def _preferred_distribution(os_release: dict[str, str]) -> str:
    for key in ("PRETTY_NAME", "NAME"):
        token = str(os_release.get(key, "")).strip()
        if token:
            return token

    return "Linux"


def _distribution_codename(os_release: dict[str, str]) -> Optional[str]:
    for key in ("VERSION_CODENAME", "UBUNTU_CODENAME"):
        token = str(os_release.get(key, "")).strip()
        if token:
            return token
    return None


def _parse_apt_updates(output: str) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("listing") or line.lower().startswith("warning:"):
            continue
        if "/" not in line:
            continue

        package_name, rest = line.split("/", 1)
        details = rest.split()
        candidate_version = details[1] if len(details) >= 2 else None

        installed_version = None
        marker = "[upgradable from: "
        marker_index = line.lower().find(marker)
        if marker_index >= 0 and line.endswith("]"):
            installed_version = line[marker_index + len(marker) : -1].strip()

        packages.append(
            {
                "name": package_name.strip(),
                "candidate_version": candidate_version,
                "installed_version": installed_version,
                "raw": line,
            }
        )

    return packages


def _parse_dnf_updates(output: str) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("last metadata expiration check"):
            continue
        if lowered.startswith("obsoleting packages"):
            continue
        if lowered.startswith("security:"):
            continue

        parts = line.split()
        if len(parts) < 3:
            continue

        package_arch = parts[0].strip()
        candidate_version = parts[1].strip()
        repository = parts[2].strip()
        if "." in package_arch:
            package_name, architecture = package_arch.rsplit(".", 1)
        else:
            package_name, architecture = package_arch, None

        packages.append(
            {
                "name": package_name,
                "architecture": architecture,
                "candidate_version": candidate_version,
                "repository": repository,
                "raw": line,
            }
        )

    return packages


def _parse_pacman_updates(output: str) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if " -> " in line:
            name_and_installed, candidate_version = line.split(" -> ", 1)
            left_parts = name_and_installed.split()
            if len(left_parts) < 2:
                continue
            package_name = left_parts[0].strip()
            installed_version = left_parts[1].strip()
            packages.append(
                {
                    "name": package_name,
                    "installed_version": installed_version,
                    "candidate_version": candidate_version.strip(),
                    "raw": line,
                }
            )
            continue

        parts = line.split()
        if len(parts) < 2:
            continue
        packages.append(
            {
                "name": parts[0].strip(),
                "candidate_version": parts[1].strip(),
                "raw": line,
            }
        )

    return packages


def _parse_zypper_updates(output: str) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("loading repository data"):
            continue
        if lowered.startswith("reading installed packages"):
            continue
        if "|" not in line:
            continue

        parts = [item.strip() for item in line.split("|")]
        if len(parts) < 6:
            continue

        package_name = parts[2]
        if not package_name or package_name.lower() == "name":
            continue
        if set(package_name) <= {"-", "+"}:
            continue

        packages.append(
            {
                "name": package_name,
                "installed_version": parts[3] or None,
                "candidate_version": parts[4] or None,
                "architecture": parts[5] or None,
                "raw": line,
            }
        )

    return packages


@dataclass(frozen=True)
class _UpdateCommand:
    name: str
    command: tuple[str, ...]
    parse_output: Callable[[str], list[dict[str, Any]]]
    success_exit_codes: frozenset[int]
    no_updates_exit_codes: frozenset[int]


class SystemInfoSensor(Sensor):
    id = "system_info"

    def __init__(
        self,
        *,
        updates_enabled: bool,
        updates_check_interval_sec: int,
        updates_command_timeout_sec: int,
        updates_max_packages: int,
    ) -> None:
        self._updates_enabled = updates_enabled
        self._updates_check_interval_sec = max(updates_check_interval_sec, 3600)
        self._updates_command_timeout_sec = max(updates_command_timeout_sec, 5)
        self._updates_max_packages = max(updates_max_packages, 1)
        self._os_release = _read_os_release()
        self._update_command = self._select_update_command(self._os_release)
        self._lock = threading.Lock()
        self._last_check_monotonic = 0.0
        self._refresh_in_progress = False
        self._cached_updates = self._initial_updates_state()

    def collect(self) -> dict[str, Any]:
        payload = {
            "hostname": socket.gethostname(),
            "os_name": platform.system() or "Linux",
            "distribution": _preferred_distribution(self._os_release),
            "distribution_name": str(self._os_release.get("NAME", "")).strip() or None,
            "distribution_id": str(self._os_release.get("ID", "")).strip() or None,
            "distribution_like": str(self._os_release.get("ID_LIKE", "")).strip() or None,
            "distribution_version": str(self._os_release.get("VERSION_ID", "")).strip() or None,
            "distribution_codename": _distribution_codename(self._os_release),
            "kernel_release": platform.release(),
            "kernel_version": platform.version(),
            "architecture": platform.machine() or None,
            "package_manager": self._update_command.name if self._update_command is not None else "unsupported",
        }
        payload.update(self._collect_updates())
        return payload

    def _collect_updates(self) -> dict[str, Any]:
        if not self._updates_enabled:
            return {
                **self._initial_updates_state(),
                "updates_state": "disabled",
                "updates_supported": self._update_command is not None,
            }

        if self._update_command is None:
            return {
                **self._initial_updates_state(),
                "updates_state": "unsupported",
                "updates_supported": False,
                "updates_last_error": "No supported package manager found",
            }

        self._schedule_refresh_if_needed()
        with self._lock:
            return self._snapshot_updates_locked()

    def _schedule_refresh_if_needed(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_check_monotonic
            if self._refresh_in_progress:
                return
            if self._last_check_monotonic > 0 and elapsed < self._updates_check_interval_sec:
                return
            self._refresh_in_progress = True

        worker = threading.Thread(
            target=self._refresh_updates,
            name="ha4linux-system-updates",
            daemon=True,
        )
        worker.start()

    def _refresh_updates(self) -> None:
        try:
            result = self._check_updates()
        except Exception as exc:  # Keep polling alive if parsing fails unexpectedly.
            result = self._error_updates_state(
                message=f"Unexpected update check failure: {exc}",
                error=str(exc),
            )

        with self._lock:
            self._last_check_monotonic = time.monotonic()
            self._cached_updates = dict(result)
            self._refresh_in_progress = False

    def _snapshot_updates_locked(self) -> dict[str, Any]:
        payload = dict(self._cached_updates)
        payload["updates_refresh_in_progress"] = self._refresh_in_progress
        if self._refresh_in_progress and self._last_check_monotonic <= 0:
            payload["updates_state"] = "checking"
        return payload

    def _check_updates(self) -> dict[str, Any]:
        assert self._update_command is not None
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        env["LANGUAGE"] = "C"

        try:
            completed = subprocess.run(
                self._update_command.command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._updates_command_timeout_sec,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return self._error_updates_state(
                message=f"Command timed out after {self._updates_command_timeout_sec}s",
                error=str(exc),
            )
        except OSError as exc:
            return self._error_updates_state(
                message=f"Unable to execute update check: {exc}",
                error=str(exc),
            )

        packages = self._update_command.parse_output(completed.stdout)
        exit_code = int(completed.returncode)
        if exit_code not in self._update_command.success_exit_codes:
            stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            return self._error_updates_state(message=stderr, error=stderr)

        if exit_code in self._update_command.no_updates_exit_codes:
            packages = []

        return {
            "updates_enabled": True,
            "updates_supported": True,
            "updates_state": "idle",
            "updates_pending_count": len(packages),
            "updates_last_checked_at": _now_iso(),
            "updates_last_error": None,
            "updates_error": None,
            "updates_check_interval_sec": self._updates_check_interval_sec,
            "updates_packages": packages[: self._updates_max_packages],
            "updates_packages_total": len(packages),
            "updates_packages_truncated": len(packages) > self._updates_max_packages,
        }

    def _error_updates_state(self, *, message: str, error: Optional[str] = None) -> dict[str, Any]:
        return {
            **self._initial_updates_state(),
            "updates_state": "error",
            "updates_supported": self._update_command is not None,
            "updates_last_checked_at": _now_iso(),
            "updates_last_error": message,
            "updates_error": error or message,
        }

    def _initial_updates_state(self) -> dict[str, Any]:
        return {
            "updates_enabled": self._updates_enabled,
            "updates_supported": self._update_command is not None,
            "updates_refresh_in_progress": False,
            "updates_state": "idle",
            "updates_pending_count": 0,
            "updates_last_checked_at": None,
            "updates_last_error": None,
            "updates_error": None,
            "updates_check_interval_sec": self._updates_check_interval_sec,
            "updates_packages": [],
            "updates_packages_total": 0,
            "updates_packages_truncated": False,
        }

    @classmethod
    def _select_update_command(cls, os_release: dict[str, str]) -> Optional[_UpdateCommand]:
        distro_id = str(os_release.get("ID", "")).strip().lower()
        distro_like = {
            item.strip().lower()
            for item in str(os_release.get("ID_LIKE", "")).split()
            if item.strip()
        }

        candidates: list[_UpdateCommand] = []

        if distro_id in {"debian", "ubuntu", "linuxmint", "pop"} or distro_like & {"debian", "ubuntu"}:
            candidates.extend(cls._apt_candidates())
        if distro_id in {"arch", "manjaro"} or distro_like & {"archlinux", "arch"}:
            candidates.extend(cls._pacman_candidates())
        if distro_id in {"fedora", "rhel", "centos", "rocky", "almalinux"} or distro_like & {
            "fedora",
            "rhel",
        }:
            candidates.extend(cls._dnf_candidates())
        if distro_id in {"opensuse-tumbleweed", "opensuse-leap", "opensuse", "sles", "sled"} or distro_like & {
            "suse",
            "opensuse",
        }:
            candidates.extend(cls._zypper_candidates())

        candidates.extend(cls._apt_candidates())
        candidates.extend(cls._dnf_candidates())
        candidates.extend(cls._pacman_candidates())
        candidates.extend(cls._zypper_candidates())

        seen: set[str] = set()
        for candidate in candidates:
            if candidate.name in seen:
                continue
            seen.add(candidate.name)
            if shutil.which(candidate.command[0]) is not None:
                return candidate

        return None

    @staticmethod
    def _apt_candidates() -> list[_UpdateCommand]:
        return [
            _UpdateCommand(
                name="apt",
                command=("apt", "list", "--upgradable"),
                parse_output=_parse_apt_updates,
                success_exit_codes=frozenset({0}),
                no_updates_exit_codes=frozenset(),
            )
        ]

    @staticmethod
    def _dnf_candidates() -> list[_UpdateCommand]:
        candidates: list[_UpdateCommand] = []
        for command_name in ("dnf", "yum"):
            candidates.append(
                _UpdateCommand(
                    name=command_name,
                    command=(command_name, "check-update", "-q"),
                    parse_output=_parse_dnf_updates,
                    success_exit_codes=frozenset({0, 100}),
                    no_updates_exit_codes=frozenset({0}),
                )
            )
        return candidates

    @staticmethod
    def _pacman_candidates() -> list[_UpdateCommand]:
        return [
            _UpdateCommand(
                name="pacman",
                command=("checkupdates",),
                parse_output=_parse_pacman_updates,
                success_exit_codes=frozenset({0, 2}),
                no_updates_exit_codes=frozenset({2}),
            ),
            _UpdateCommand(
                name="pacman",
                command=("pacman", "-Qu"),
                parse_output=_parse_pacman_updates,
                success_exit_codes=frozenset({0}),
                no_updates_exit_codes=frozenset(),
            ),
        ]

    @staticmethod
    def _zypper_candidates() -> list[_UpdateCommand]:
        return [
            _UpdateCommand(
                name="zypper",
                command=("zypper", "--non-interactive", "--no-refresh", "list-updates"),
                parse_output=_parse_zypper_updates,
                success_exit_codes=frozenset({0, 100}),
                no_updates_exit_codes=frozenset(),
            )
        ]
