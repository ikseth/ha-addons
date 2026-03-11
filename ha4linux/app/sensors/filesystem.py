from __future__ import annotations

import os
from typing import Any

from app.sensors.base import Sensor


def _decode_mount_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


class FilesystemSensor(Sensor):
    id = "filesystem"
    _BYTES_PER_GIB = 1024**3
    _GIB_PRECISION = 2
    _PERCENT_PRECISION = 2

    def __init__(self, *, exclude_types: list[str], exclude_mounts: list[str]) -> None:
        self._exclude_types = {item.strip().lower() for item in exclude_types if item.strip()}
        self._exclude_mounts = {item.strip() for item in exclude_mounts if item.strip()}

    def collect(self) -> dict[str, Any]:
        filesystems: list[dict[str, Any]] = []
        seen_mounts: set[str] = set()
        mounts_path = "/proc/1/mounts" if os.path.exists("/proc/1/mounts") else "/proc/mounts"

        with open(mounts_path, "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.strip().split()
                if len(parts) < 4:
                    continue

                device_raw, mount_raw, fs_type_raw, opts_raw = parts[:4]
                mountpoint = _decode_mount_field(mount_raw)
                if not mountpoint or mountpoint in seen_mounts:
                    continue
                if not os.path.isdir(mountpoint):
                    continue
                if self._is_excluded_mount(mountpoint):
                    continue

                fs_type = fs_type_raw.strip().lower()
                if fs_type in self._exclude_types:
                    continue

                try:
                    stat = os.statvfs(mountpoint)
                except OSError:
                    continue

                total_bytes = int(stat.f_blocks * stat.f_frsize)
                if total_bytes <= 0:
                    continue

                free_bytes = int(stat.f_bavail * stat.f_frsize)
                used_bytes = max(total_bytes - free_bytes, 0)
                used_percent = round((used_bytes / total_bytes) * 100, self._PERCENT_PRECISION)
                readonly = "ro" in {item.strip() for item in opts_raw.split(",")}

                seen_mounts.add(mountpoint)
                filesystems.append(
                    {
                        "device": _decode_mount_field(device_raw),
                        "mountpoint": mountpoint,
                        "fs_type": fs_type_raw.strip(),
                        "readonly": readonly,
                        "total_bytes": total_bytes,
                        "used_bytes": used_bytes,
                        "free_bytes": free_bytes,
                        "total_gib": round(total_bytes / self._BYTES_PER_GIB, self._GIB_PRECISION),
                        "used_gib": round(used_bytes / self._BYTES_PER_GIB, self._GIB_PRECISION),
                        "free_gib": round(free_bytes / self._BYTES_PER_GIB, self._GIB_PRECISION),
                        "used_percent": used_percent,
                    }
                )

        filesystems.sort(key=lambda item: str(item.get("mountpoint", "")))

        return {
            "filesystems_total": len(filesystems),
            "filesystems_readonly": sum(1 for item in filesystems if bool(item.get("readonly", False))),
            "filesystems_over_90": sum(1 for item in filesystems if float(item.get("used_percent", 0)) >= 90.0),
            "filesystems": filesystems,
        }

    def _is_excluded_mount(self, mountpoint: str) -> bool:
        for prefix in self._exclude_mounts:
            if mountpoint == prefix or mountpoint.startswith(f"{prefix}/"):
                return True
        return False
