from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.sensors.base import Sensor


class RaidMdstatSensor(Sensor):
    id = "raid_mdstat"

    _MDSTAT_PATH = Path("/proc/mdstat")
    _ARRAY_RE = re.compile(r"^(md\d+)\s*:\s*(.+)$")
    _LEVEL_RE = re.compile(r"\b(raid\d+)\b")
    _COUNT_RE = re.compile(r"\[(\d+)/(\d+)\]")
    _MEMBER_STATE_RE = re.compile(r"\[([U_]+)\]")

    def collect(self) -> dict[str, Any]:
        if not self._MDSTAT_PATH.exists():
            raise RuntimeError("/proc/mdstat is not available")

        lines = self._MDSTAT_PATH.read_text(encoding="utf-8").splitlines()
        arrays: list[dict[str, Any]] = []

        idx = 0
        while idx < len(lines):
            line = lines[idx].strip()
            match = self._ARRAY_RE.match(line)
            if match is None:
                idx += 1
                continue

            name = match.group(1)
            header = match.group(2)
            idx += 1

            detail_lines: list[str] = []
            while idx < len(lines):
                next_line = lines[idx].strip()
                if not next_line:
                    idx += 1
                    break
                if self._ARRAY_RE.match(next_line):
                    break
                detail_lines.append(next_line)
                idx += 1

            level_match = self._LEVEL_RE.search(header)
            level = level_match.group(1) if level_match is not None else "unknown"
            combined = " ".join([header, *detail_lines])

            expected_disks = 0
            active_disks = 0
            count_match = self._COUNT_RE.search(combined)
            if count_match is not None:
                active_disks = int(count_match.group(1))
                expected_disks = int(count_match.group(2))

            member_state = ""
            member_state_match = self._MEMBER_STATE_RE.search(combined)
            if member_state_match is not None:
                member_state = member_state_match.group(1)

            degraded = (
                "_" in member_state
                or (expected_disks > 0 and active_disks < expected_disks)
            )
            rebuilding = any(
                token in combined
                for token in (
                    "recovery",
                    "resync",
                    "reshape",
                    "check =",
                )
            )
            state = "rebuilding" if rebuilding else ("degraded" if degraded else "healthy")

            arrays.append(
                {
                    "name": name,
                    "level": level,
                    "active_disks": active_disks,
                    "expected_disks": expected_disks,
                    "member_state": member_state,
                    "degraded": degraded,
                    "rebuilding": rebuilding,
                    "state": state,
                }
            )

        arrays.sort(key=lambda item: str(item.get("name", "")))
        arrays_degraded = sum(1 for item in arrays if bool(item.get("degraded", False)))
        arrays_rebuilding = sum(1 for item in arrays if bool(item.get("rebuilding", False)))

        return {
            "arrays_total": len(arrays),
            "arrays_degraded": arrays_degraded,
            "arrays_rebuilding": arrays_rebuilding,
            "arrays": arrays,
        }
