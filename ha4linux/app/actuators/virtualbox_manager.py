from __future__ import annotations

from typing import Any, Iterable

from app.actuators.base import Actuator
from app.core.virtualbox import VirtualBoxClient

_ALLOWED_ACTIONS = {"status", "start", "acpi_shutdown", "savestate", "poweroff", "reset"}
_OFF_ACTIONS = {"acpi_shutdown", "savestate", "poweroff"}
_START_TYPES = {"headless", "gui", "separate"}


class VirtualBoxManagerActuator(Actuator):
    id = "virtualbox_manager"

    def __init__(
        self,
        client: VirtualBoxClient,
        allowed_actions: Iterable[str],
        allowed_vms: Iterable[str],
        start_type: str,
        switch_turn_off_action: str,
    ) -> None:
        self.client = client
        self.allowed_actions = {
            str(action).strip().lower() for action in allowed_actions if str(action).strip()
        }
        invalid_actions = sorted(self.allowed_actions - _ALLOWED_ACTIONS)
        if invalid_actions:
            raise ValueError(
                f"Unsupported virtualbox actions configured: {', '.join(invalid_actions)}"
            )

        self.allowed_vm_tokens = {
            str(token).strip().lower() for token in allowed_vms if str(token).strip()
        }

        self.start_type = str(start_type).strip().lower() or "headless"
        if self.start_type not in _START_TYPES:
            raise ValueError(f"Unsupported virtualbox start type '{self.start_type}'")

        self.switch_turn_off_action = str(switch_turn_off_action).strip().lower() or "acpi_shutdown"
        if self.switch_turn_off_action not in _OFF_ACTIONS:
            raise ValueError(
                f"Unsupported virtualbox switch off action '{self.switch_turn_off_action}'"
            )

    def describe(self) -> dict[str, Any]:
        return {
            "allowed_actions": sorted(self.allowed_actions),
            "allowed_vms": sorted(self.allowed_vm_tokens),
            "start_type": self.start_type,
            "switch_turn_off_action": self.switch_turn_off_action,
            "switch_supported": {
                "turn_on": "start" in self.allowed_actions,
                "turn_off": self.switch_turn_off_action in self.allowed_actions,
            },
        }

    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        action_key = str(action).strip().lower()
        if action_key == "status":
            return self._status(params)

        if action_key not in self.allowed_actions:
            return {"ok": False, "error": f"Action '{action}' not allowed"}

        vm = self._resolve_vm(params)
        vm_uuid = str(vm.get("uuid", "")).strip()
        current_status = str(vm.get("status", "")).strip().lower()
        powered_on = bool(vm.get("powered_on", False))

        if action_key == "start":
            if powered_on:
                return {
                    "ok": True,
                    "message": "VM already powered on",
                    "vm": vm,
                }
            process = self.client.start_vm(vm_uuid, start_type=self.start_type)
        else:
            if not powered_on:
                if action_key in _OFF_ACTIONS:
                    return {
                        "ok": True,
                        "message": "VM already powered off",
                        "vm": vm,
                    }
                return {
                    "ok": False,
                    "error": f"VM '{vm.get('name') or vm_uuid}' is not powered on",
                    "vm": vm,
                }
            control_command = {
                "acpi_shutdown": "acpipowerbutton",
                "savestate": "savestate",
                "poweroff": "poweroff",
                "reset": "reset",
            }[action_key]
            process = self.client.control_vm(vm_uuid, control_command)

        updated_vm = self.client.resolve_vm(vm_uuid=vm_uuid)
        result = {
            "ok": process.returncode == 0,
            "action": action_key,
            "returncode": process.returncode,
            "stdout": process.stdout.strip(),
            "stderr": process.stderr.strip(),
            "vm": updated_vm,
            "previous_status": current_status,
        }
        if process.returncode != 0:
            result["error"] = result["stderr"] or result["stdout"] or "VirtualBox command failed"
        return result

    def _status(self, params: dict[str, Any]) -> dict[str, Any]:
        vm_identifier = str(
            params.get("vm_id") or params.get("vm_uuid") or params.get("vm_name") or ""
        ).strip()
        if vm_identifier:
            vm = self._resolve_vm(params)
            return {"ok": True, "vm": vm}

        vms = [vm for vm in self.client.list_vms() if self._is_vm_allowed(vm)]
        return {"ok": True, "vms": vms, "count": len(vms)}

    def _resolve_vm(self, params: dict[str, Any]) -> dict[str, Any]:
        vm = self.client.resolve_vm(
            vm_id=str(params.get("vm_id") or "").strip() or None,
            vm_uuid=str(params.get("vm_uuid") or "").strip() or None,
            vm_name=str(params.get("vm_name") or "").strip() or None,
        )
        if not self._is_vm_allowed(vm):
            vm_label = str(vm.get("name") or vm.get("uuid") or "vm").strip()
            raise ValueError(f"VM '{vm_label}' not allowed")
        return vm

    def _is_vm_allowed(self, vm: dict[str, Any]) -> bool:
        if not self.allowed_vm_tokens:
            return True
        name = str(vm.get("name", "")).strip().lower()
        uuid = str(vm.get("uuid", "")).strip().lower()
        return bool(name and name in self.allowed_vm_tokens) or bool(
            uuid and uuid in self.allowed_vm_tokens
        )
