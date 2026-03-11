from __future__ import annotations

import getpass
import os
import re
import shutil
import subprocess
from typing import Any

from app.sensors.base import Sensor


class VirtualBoxSensor(Sensor):
    id = "virtualbox"

    _LIST_RE = re.compile(r'^"(?P<name>.*)"\s+\{(?P<uuid>[^}]+)\}$')
    _TIMEOUT_SECONDS = 10

    def __init__(self, user: str) -> None:
        self._user = user.strip()
        if not self._user:
            raise ValueError("virtualbox user must not be empty")

        binary = shutil.which("VBoxManage") or shutil.which("vboxmanage")
        if binary is None:
            raise ValueError("VBoxManage command not found")
        self._binary = binary

    def collect(self) -> dict[str, Any]:
        all_vms = self._run_list("vms")
        running_vms = self._run_list("runningvms")
        running_ids = {item["uuid"] for item in running_vms}

        vms: list[dict[str, Any]] = []
        inaccessible = 0
        for vm in all_vms:
            name = vm["name"]
            uuid = vm["uuid"]
            is_running = uuid in running_ids
            is_inaccessible = name == "<inaccessible>"
            if is_inaccessible:
                inaccessible += 1

            status = "running" if is_running else ("inaccessible" if is_inaccessible else "stopped")
            vms.append(
                {
                    "name": name,
                    "uuid": uuid,
                    "status": status,
                    "running": is_running,
                    "inaccessible": is_inaccessible,
                    "user": self._user,
                }
            )

        vms.sort(key=lambda item: str(item.get("name", "")))

        return {
            "user": self._user,
            "vms_total": len(vms),
            "vms_running": sum(1 for item in vms if bool(item.get("running", False))),
            "vms_inaccessible": inaccessible,
            "vms": vms,
        }

    def _run_list(self, list_type: str) -> list[dict[str, str]]:
        command = self._command_prefix() + [self._binary, "list", list_type]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=self._TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise RuntimeError(f"VBoxManage list {list_type} failed: {stderr}")

        vms: list[dict[str, str]] = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = self._LIST_RE.match(line)
            if match is None:
                continue
            vms.append(
                {
                    "name": match.group("name"),
                    "uuid": match.group("uuid"),
                }
            )
        return vms

    def _command_prefix(self) -> list[str]:
        try:
            current_user = getpass.getuser().strip()
        except Exception:
            current_user = os.getenv("USER", "").strip()
        if current_user == self._user:
            return []
        # Keep VBoxManage bound to the target user's home/profile directory.
        return ["sudo", "-n", "-H", "-u", self._user]
