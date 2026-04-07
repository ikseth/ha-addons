from __future__ import annotations

from typing import Any

from app.core.virtualbox import VirtualBoxClient
from app.sensors.base import Sensor


class VirtualBoxSensor(Sensor):
    id = "virtualbox"

    def __init__(self, client: VirtualBoxClient) -> None:
        self._client = client

    def collect(self) -> dict[str, Any]:
        snapshot = self._client.list_vms_snapshot()
        vms = snapshot.get("vms", [])
        inaccessible = sum(1 for item in vms if bool(item.get("inaccessible", False)))
        payload = {
            "user": self._client.user,
            "vms_total": len(vms),
            "vms_running": sum(1 for item in vms if bool(item.get("running", False))),
            "vms_inaccessible": inaccessible,
            "vms": vms,
        }
        cache = snapshot.get("cache", {})
        if isinstance(cache, dict):
            payload["cache"] = cache
        return payload
