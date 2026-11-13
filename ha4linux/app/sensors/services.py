from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from app.sensors.base import Sensor


def parse_systemd_timestamp(value: str | None) -> str | None:
    """Convert a UTC systemd timestamp to an ISO 8601 value."""
    if not value or value in {"n/a", "0"}:
        return None
    try:
        parsed = datetime.strptime(value, "%a %Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return None
    if not value.endswith(" UTC"):
        return None
    return parsed.replace(tzinfo=timezone.utc).isoformat()


def parse_systemd_properties(output: str) -> dict[str, str]:
    """Read key/value lines independently of systemctl's output order."""
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


class ServicesSensor(Sensor):
    id = "services"

    _TIMEOUT_SECONDS = 8

    def __init__(self, watchlist: list[str]) -> None:
        self._watchlist = self._normalize_watchlist(watchlist)
        if not self._watchlist:
            raise ValueError("services watchlist must contain at least one unit")
        if shutil.which("systemctl") is None:
            raise ValueError("systemctl command not found")

    def collect(self) -> dict[str, Any]:
        services: list[dict[str, Any]] = []
        for unit in self._watchlist:
            service_info = self._service_state(unit)
            if not bool(service_info.get("exists", False)):
                continue
            services.append(service_info)

        services.sort(key=lambda item: str(item.get("name", "")))
        total = len(services)
        active = sum(1 for item in services if bool(item.get("is_active", False)))
        failed = sum(1 for item in services if bool(item.get("is_failed", False)))

        return {
            "services_total": total,
            "services_active": active,
            "services_failed": failed,
            "services": services,
        }

    def _service_state(self, unit: str) -> dict[str, Any]:
        result = subprocess.run(
            [
                "systemctl",
                "show",
                (
                    "--property=Id,LoadState,ActiveState,SubState,Result,"
                    "ExecMainStartTimestamp,ExecMainExitTimestamp,ExecMainStatus,"
                    "LastTriggerUSec,NextElapseUSecRealtime"
                ),
                unit,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=self._TIMEOUT_SECONDS,
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise RuntimeError(f"systemctl show {unit} failed: {stderr}")

        properties = parse_systemd_properties(result.stdout)
        load_state = properties.get("LoadState", "")
        active_state = properties.get("ActiveState", "")
        sub_state = properties.get("SubState", "")
        unit_type = unit.rsplit(".", 1)[-1]
        last_run_start = (
            parse_systemd_timestamp(properties.get("ExecMainStartTimestamp"))
            if unit_type == "service" else None
        )
        last_run_end = (
            parse_systemd_timestamp(properties.get("ExecMainExitTimestamp"))
            if unit_type == "service" else None
        )
        last_exit_status = None
        if unit_type == "service" and last_run_start is not None:
            try:
                last_exit_status = int(properties.get("ExecMainStatus", ""))
            except ValueError:
                pass
        exists = load_state not in {"not-found", ""}
        is_active = active_state == "active"
        is_failed = active_state == "failed"

        return {
            "name": unit,
            "exists": exists,
            "load_state": load_state,
            "active_state": active_state,
            "sub_state": sub_state,
            "is_active": is_active,
            "is_failed": is_failed,
            "status": active_state or "unknown",
            "unit_type": unit_type,
            "result": properties.get("Result") or None,
            "last_run_start": last_run_start,
            "last_run_end": last_run_end,
            "last_exit_status": last_exit_status,
            "last_trigger": (
                parse_systemd_timestamp(properties.get("LastTriggerUSec"))
                if unit_type == "timer" else None
            ),
            "next_trigger": (
                parse_systemd_timestamp(properties.get("NextElapseUSecRealtime"))
                if unit_type == "timer" else None
            ),
        }

    @staticmethod
    def _normalize_watchlist(watchlist: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_unit in watchlist:
            unit = str(raw_unit).strip()
            if not unit:
                continue
            if "." not in unit:
                unit = f"{unit}.service"
            if unit in seen:
                continue
            seen.add(unit)
            normalized.append(unit)
        return normalized
