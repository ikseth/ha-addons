from typing import Any

from app.sensors.base import Sensor


class MemorySensor(Sensor):
    id = "memory"

    def collect(self) -> dict[str, Any]:
        data: dict[str, int] = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                key, value = line.split(":", 1)
                amount = int(value.strip().split()[0])
                data[key] = amount

        total = data.get("MemTotal", 0)
        available = data.get("MemAvailable", 0)
        used = max(total - available, 0)

        return {
            "total_kb": total,
            "available_kb": available,
            "used_kb": used,
            "used_percent": round((used / total) * 100, 2) if total else 0,
        }
