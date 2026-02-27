from typing import Any

from app.actuators.base import Actuator
from app.core.app_policy_manager import AppPolicyManager

_ALLOWED_ACTIONS = {"status", "allow", "block", "enforce", "reload"}


class AppPolicyActuator(Actuator):
    id = "app_policy"

    def __init__(self, manager: AppPolicyManager) -> None:
        self.manager = manager

    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action not in _ALLOWED_ACTIONS:
            return {"ok": False, "error": f"Action '{action}' not allowed"}

        app_id = str(params.get("app_id", "")).strip() or None

        if action == "reload":
            return self.manager.load()

        if action == "status":
            return self.manager.status(app_id=app_id)

        if action == "enforce":
            return self.manager.enforce(app_id=app_id)

        if app_id is None:
            return {"ok": False, "error": "Missing 'app_id' parameter"}

        if action == "allow":
            return self.manager.set_allowed(app_id=app_id, allowed=True)

        return self.manager.set_allowed(app_id=app_id, allowed=False)
