from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.actuators.base import Actuator

_ALLOWED_ACTIONS = {"send"}
_ALLOWED_TARGETS = {"broadcast", "x11"}
_HELPER_PATH = Path("/opt/ha4linux/ha4linux-message-root.py")


class MessageDispatcherActuator(Actuator):
    id = "message_dispatcher"

    def __init__(self, allowed_targets: list[str]) -> None:
        normalized_targets: list[str] = []
        seen_targets: set[str] = set()
        invalid_targets: list[str] = []

        for raw_target in allowed_targets:
            target = str(raw_target).strip().lower()
            if not target:
                continue
            if target not in _ALLOWED_TARGETS:
                invalid_targets.append(target)
                continue
            if target in seen_targets:
                continue
            seen_targets.add(target)
            normalized_targets.append(target)

        if invalid_targets:
            tokens = ", ".join(sorted(set(invalid_targets)))
            raise ValueError(f"Unsupported message targets configured: {tokens}")

        if not normalized_targets:
            raise ValueError("At least one message delivery target must be configured")

        self.allowed_targets = normalized_targets
        self.available_targets = self._detect_available_targets()

    def describe(self) -> dict[str, Any]:
        return {
            "actions": sorted(_ALLOWED_ACTIONS),
            "allowed_targets": list(self.allowed_targets),
            "available_targets": list(self.available_targets),
            "helper_available": self._helper_available(),
        }

    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        action_key = str(action).strip().lower()
        if action_key not in _ALLOWED_ACTIONS:
            return {"ok": False, "error": f"Action '{action}' not allowed"}

        message = str(params.get("message", "")).strip()
        if not message:
            return {"ok": False, "error": "Missing 'message' parameter"}

        title = str(params.get("title", "")).strip()
        requested_targets = self._resolve_requested_targets(params)
        unavailable_targets = [
            target for target in requested_targets if target not in self.available_targets
        ]
        if unavailable_targets:
            return {
                "ok": False,
                "error": (
                    "Requested delivery targets are not available on this host: "
                    + ", ".join(unavailable_targets)
                ),
                "allowed_targets": list(self.allowed_targets),
                "available_targets": list(self.available_targets),
            }

        if self._helper_available():
            helper_result = self._run_helper(
                {
                    "message": message,
                    "title": title,
                    "targets": requested_targets,
                }
            )
            if helper_result.get("ok", False) or requested_targets != ["broadcast"]:
                return helper_result
            if "broadcast" in self.available_targets:
                return self._send_broadcast(message=message, title=title)
            return helper_result

        if requested_targets != ["broadcast"]:
            return {
                "ok": False,
                "error": "Only broadcast delivery is available without the root helper",
                "allowed_targets": list(self.allowed_targets),
                "available_targets": list(self.available_targets),
            }

        return self._send_broadcast(message=message, title=title)

    def _detect_available_targets(self) -> list[str]:
        available_targets: list[str] = []
        helper_available = self._helper_available()

        for target in self.allowed_targets:
            if target == "broadcast":
                if helper_available or shutil.which("wall"):
                    available_targets.append(target)
                continue

            if (
                target == "x11"
                and helper_available
                and shutil.which("loginctl")
                and (shutil.which("notify-send") or shutil.which("xmessage"))
            ):
                available_targets.append(target)

        return available_targets

    def _helper_available(self) -> bool:
        if not _HELPER_PATH.is_file():
            return False
        if os.geteuid() == 0:
            return os.access(_HELPER_PATH, os.X_OK)
        return os.access(_HELPER_PATH, os.X_OK) and shutil.which("sudo") is not None

    def _resolve_requested_targets(self, params: dict[str, Any]) -> list[str]:
        raw_targets = params.get("targets", self.allowed_targets)
        if isinstance(raw_targets, str):
            tokens = [part.strip().lower() for part in raw_targets.split(",")]
        elif isinstance(raw_targets, (list, tuple, set)):
            tokens = [str(part).strip().lower() for part in raw_targets]
        else:
            tokens = []

        requested_targets: list[str] = []
        seen_targets: set[str] = set()
        invalid_targets: list[str] = []

        for token in tokens:
            if not token:
                continue
            if token not in _ALLOWED_TARGETS:
                invalid_targets.append(token)
                continue
            if token in seen_targets:
                continue
            seen_targets.add(token)
            requested_targets.append(token)

        if invalid_targets:
            raise ValueError(
                "Unsupported message targets requested: " + ", ".join(sorted(set(invalid_targets)))
            )

        if not requested_targets:
            requested_targets = list(self.allowed_targets)

        disallowed_targets = [
            target for target in requested_targets if target not in self.allowed_targets
        ]
        if disallowed_targets:
            raise ValueError(
                "Requested message targets are not allowed by configuration: "
                + ", ".join(disallowed_targets)
            )

        return requested_targets

    def _run_helper(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = [str(_HELPER_PATH)] if os.geteuid() == 0 else ["sudo", "-n", str(_HELPER_PATH)]
        encoded_payload = json.dumps(payload)

        try:
            process = subprocess.run(
                command,
                input=encoded_payload,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Timed out while delivering message"}

        stdout = process.stdout.strip()
        stderr = process.stderr.strip()

        if stdout:
            try:
                result = json.loads(stdout)
            except json.JSONDecodeError:
                result = {
                    "ok": False,
                    "error": "Invalid response from message helper",
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": process.returncode,
                }
            else:
                if isinstance(result, dict):
                    result.setdefault("stdout", stdout)
                    if stderr:
                        result.setdefault("stderr", stderr)
                    result.setdefault("returncode", process.returncode)
                    return result

        error = stderr or stdout or "Message helper failed"
        return {
            "ok": False,
            "error": error,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": process.returncode,
        }

    def _send_broadcast(self, *, message: str, title: str) -> dict[str, Any]:
        wall = shutil.which("wall")
        if wall is None:
            return {"ok": False, "error": "wall command not available"}

        try:
            process = subprocess.run(
                [wall],
                input=_format_message(title=title, message=message),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "wall command timed out"}

        result = {
            "ok": process.returncode == 0,
            "targets_requested": ["broadcast"],
            "targets_delivered": ["broadcast"] if process.returncode == 0 else [],
            "deliveries": [
                {
                    "target": "broadcast",
                    "ok": process.returncode == 0,
                    "method": "wall",
                    "returncode": process.returncode,
                    "stdout": process.stdout.strip(),
                    "stderr": process.stderr.strip(),
                }
            ],
            "returncode": process.returncode,
            "stdout": process.stdout.strip(),
            "stderr": process.stderr.strip(),
        }
        if process.returncode != 0:
            result["error"] = process.stderr.strip() or process.stdout.strip() or "wall command failed"
        return result


def _format_message(*, title: str, message: str) -> str:
    if title:
        return f"{title}\n\n{message}"
    return message
