from typing import Any

from app.core.app_policy_manager import AppPolicyManager
from app.sensors.base import Sensor


class AppPoliciesSensor(Sensor):
    id = "app_policies"

    def __init__(self, manager: AppPolicyManager) -> None:
        self.manager = manager

    def collect(self) -> dict[str, Any]:
        status = self.manager.status()
        if not status.get("ok", False):
            raise RuntimeError(status.get("error", "Unable to collect app policy status"))
        return status
