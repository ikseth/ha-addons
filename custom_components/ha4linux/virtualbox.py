from __future__ import annotations

from typing import Any


_DEFAULT_VM_BUTTON_ORDER = ("start", "acpi_shutdown", "savestate", "poweroff", "reset")


def virtualbox_items(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []

    sensors = data.get("sensors", {})
    if not isinstance(sensors, dict):
        return []

    module = sensors.get("virtualbox", {})
    if not isinstance(module, dict):
        return []

    payload = module.get("data", {})
    if not isinstance(payload, dict):
        payload = {}

    items = payload.get("vms", [])
    if isinstance(items, list) and items:
        return items

    virtualbox_status = data.get("virtualbox", {})
    if not isinstance(virtualbox_status, dict):
        return []

    status_items = virtualbox_status.get("vms", [])
    if isinstance(status_items, list):
        return status_items

    single_item = virtualbox_status.get("vm")
    if isinstance(single_item, dict):
        return [single_item]

    return []


def find_virtualbox_item(data: dict[str, Any] | None, vm_uuid: str) -> dict[str, Any] | None:
    target_uuid = str(vm_uuid).strip().lower()
    if not target_uuid:
        return None

    for item in virtualbox_items(data):
        if str(item.get("uuid", "")).strip().lower() == target_uuid:
            return item
    return None


def virtualbox_actuator_details(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}

    capabilities = data.get("capabilities", {})
    if not isinstance(capabilities, dict):
        return {}

    details = capabilities.get("actuator_details", {})
    if not isinstance(details, dict):
        return {}

    payload = details.get("virtualbox_manager", {})
    return payload if isinstance(payload, dict) else {}


def virtualbox_actuator_available(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False

    capabilities = data.get("capabilities", {})
    if not isinstance(capabilities, dict):
        return False

    actuators = capabilities.get("actuators", [])
    return isinstance(actuators, list) and "virtualbox_manager" in actuators


def virtualbox_allowed_actions(data: dict[str, Any] | None) -> set[str]:
    details = virtualbox_actuator_details(data)
    actions = details.get("allowed_actions", [])
    if not isinstance(actions, list):
        return set()
    return {str(action).strip().lower() for action in actions if str(action).strip()}


def virtualbox_allowed_vm_tokens(data: dict[str, Any] | None) -> set[str]:
    details = virtualbox_actuator_details(data)
    allowed_vms = details.get("allowed_vms", [])
    if not isinstance(allowed_vms, list):
        return set()
    return {str(token).strip().lower() for token in allowed_vms if str(token).strip()}


def virtualbox_switch_turn_off_action(data: dict[str, Any] | None) -> str:
    details = virtualbox_actuator_details(data)
    return str(details.get("switch_turn_off_action") or "acpi_shutdown").strip().lower()


def virtualbox_vm_controllable(data: dict[str, Any] | None, item: dict[str, Any]) -> bool:
    if not virtualbox_actuator_available(data):
        return False

    allowed_tokens = virtualbox_allowed_vm_tokens(data)
    if not allowed_tokens:
        return True

    name = str(item.get("name", "")).strip().lower()
    uuid = str(item.get("uuid", "")).strip().lower()
    return bool(name and name in allowed_tokens) or bool(uuid and uuid in allowed_tokens)


def virtualbox_vm_switch_supported(data: dict[str, Any] | None, item: dict[str, Any]) -> bool:
    if not virtualbox_vm_controllable(data, item):
        return False

    details = virtualbox_actuator_details(data)
    switch_supported = details.get("switch_supported", {})
    if isinstance(switch_supported, dict):
        return bool(switch_supported.get("turn_on", False)) and bool(
            switch_supported.get("turn_off", False)
        )

    actions = virtualbox_allowed_actions(data)
    return "start" in actions and virtualbox_switch_turn_off_action(data) in actions


def virtualbox_vm_button_actions(data: dict[str, Any] | None, item: dict[str, Any]) -> list[str]:
    if not virtualbox_vm_controllable(data, item):
        return []

    actions = virtualbox_allowed_actions(data)
    if not actions:
        return []

    off_action = virtualbox_switch_turn_off_action(data)
    ordered_actions: list[str] = []
    for action in _DEFAULT_VM_BUTTON_ORDER:
        if action not in actions:
            continue
        if action == "start" and virtualbox_vm_switch_supported(data, item):
            continue
        if action == off_action and virtualbox_vm_switch_supported(data, item):
            continue
        ordered_actions.append(action)
    return ordered_actions


def virtualbox_vm_is_on(item: dict[str, Any] | None) -> bool:
    if not isinstance(item, dict):
        return False
    if "powered_on" in item:
        return bool(item.get("powered_on", False))
    return bool(item.get("running", False))
