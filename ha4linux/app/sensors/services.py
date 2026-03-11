from __future__ import annotations

import shutil
import subprocess
from typing import Any

from app.sensors.base import Sensor


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
                "--property=Id,LoadState,ActiveState,SubState",
                "--value",
                unit,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=self._TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise RuntimeError(f"systemctl show {unit} failed: {stderr}")

        lines = [line.strip() for line in result.stdout.splitlines()]
        while len(lines) < 4:
            lines.append("")

        _, load_state, active_state, sub_state = lines[:4]
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
