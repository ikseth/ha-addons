from __future__ import annotations

import getpass
import os
import re
import signal
import shutil
import subprocess
from typing import Any

_LIST_RE = re.compile(r'^"(?P<name>.*)"\s+\{(?P<uuid>[^}]+)\}$')
_OFF_STATES = {"", "poweroff", "saved", "aborted", "inaccessible"}


class VirtualBoxCommandError(RuntimeError):
    pass


class VirtualBoxClient:
    _LIST_TIMEOUT_SECONDS = 10
    _INFO_TIMEOUT_SECONDS = 10
    _ACTION_TIMEOUT_SECONDS = 30

    def __init__(self, user: str) -> None:
        self.user = user.strip()
        if not self.user:
            raise ValueError("virtualbox user must not be empty")

        binary = shutil.which("VBoxManage") or shutil.which("vboxmanage")
        if binary is None:
            raise ValueError("VBoxManage command not found")
        self._binary = binary

    def list_vms(self) -> list[dict[str, Any]]:
        all_vms = self._run_list("vms")
        running_vms = self._run_list("runningvms")
        running_ids = {str(item["uuid"]).strip().lower() for item in running_vms}

        vms: list[dict[str, Any]] = []
        for vm in all_vms:
            name = str(vm.get("name", "")).strip()
            uuid = str(vm.get("uuid", "")).strip()
            if not uuid:
                continue

            inaccessible = name == "<inaccessible>"
            info: dict[str, str] = {}
            raw_state = ""
            if not inaccessible:
                try:
                    info = self.show_vm_info(uuid)
                    raw_state = str(info.get("VMState", "")).strip().lower()
                except VirtualBoxCommandError:
                    info = {}

            running = raw_state == "running" or uuid.lower() in running_ids
            powered_on = self._is_powered_on(raw_state, running)
            status = self._normalize_state(raw_state, running=running, inaccessible=inaccessible)

            vms.append(
                {
                    "name": name,
                    "uuid": uuid,
                    "status": status,
                    "state_raw": raw_state or None,
                    "running": running,
                    "powered_on": powered_on,
                    "inaccessible": inaccessible,
                    "user": self.user,
                    "session_name": info.get("sessionName") or None,
                    "os_type": info.get("ostype") or None,
                }
            )

        vms.sort(key=lambda item: str(item.get("name", "")))
        return vms

    def resolve_vm(
        self,
        *,
        vm_uuid: str | None = None,
        vm_name: str | None = None,
        vm_id: str | None = None,
    ) -> dict[str, Any]:
        raw_identifier = vm_id or vm_uuid or vm_name
        identifier = str(raw_identifier or "").strip()
        if not identifier:
            raise ValueError("Missing VM identifier")

        identifier_lower = identifier.lower()
        matches = [
            item
            for item in self.list_vms()
            if str(item.get("uuid", "")).strip().lower() == identifier_lower
            or str(item.get("name", "")).strip().lower() == identifier_lower
        ]
        if not matches:
            raise ValueError(f"VM '{identifier}' not found")
        if len(matches) > 1:
            raise ValueError(f"VM identifier '{identifier}' is ambiguous")
        return matches[0]

    def show_vm_info(self, vm_identifier: str) -> dict[str, str]:
        command = self._command_prefix() + [self._binary, "showvminfo", vm_identifier, "--machinereadable"]
        result = self._run(command, timeout_seconds=self._INFO_TIMEOUT_SECONDS)
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise VirtualBoxCommandError(f"VBoxManage showvminfo failed: {stderr}")
        return self._parse_machine_readable(result.stdout)

    def start_vm(self, vm_identifier: str, *, start_type: str) -> subprocess.CompletedProcess[str]:
        return self._run(
            self._command_prefix() + [self._binary, "startvm", vm_identifier, "--type", start_type],
            timeout_seconds=self._ACTION_TIMEOUT_SECONDS,
        )

    def control_vm(self, vm_identifier: str, command: str) -> subprocess.CompletedProcess[str]:
        return self._run(
            self._command_prefix() + [self._binary, "controlvm", vm_identifier, command],
            timeout_seconds=self._ACTION_TIMEOUT_SECONDS,
        )

    def _run_list(self, list_type: str) -> list[dict[str, str]]:
        command = self._command_prefix() + [self._binary, "list", list_type]
        result = self._run(command, timeout_seconds=self._LIST_TIMEOUT_SECONDS)
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise VirtualBoxCommandError(f"VBoxManage list {list_type} failed: {stderr}")

        vms: list[dict[str, str]] = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = _LIST_RE.match(line)
            if match is None:
                continue
            vms.append(
                {
                    "name": match.group("name"),
                    "uuid": match.group("uuid"),
                }
            )
        return vms

    def _run(self, command: list[str], *, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            self._terminate_process_tree(process)
            stdout, stderr = process.communicate()
            raise VirtualBoxCommandError(
                f"Command '{' '.join(command)}' timed out after {timeout_seconds} seconds"
            ) from exc

        return subprocess.CompletedProcess(
            command,
            process.returncode,
            stdout,
            stderr,
        )

    def _terminate_process_tree(self, process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

        try:
            process.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            pass

        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    def _command_prefix(self) -> list[str]:
        try:
            current_user = getpass.getuser().strip()
        except Exception:
            current_user = os.getenv("USER", "").strip()
        if current_user == self.user:
            return []
        return ["sudo", "-n", "-H", "-u", self.user]

    def _normalize_state(self, raw_state: str, *, running: bool, inaccessible: bool) -> str:
        if inaccessible:
            return "inaccessible"
        if raw_state == "poweroff":
            return "stopped"
        if raw_state:
            return raw_state
        if running:
            return "running"
        return "stopped"

    def _is_powered_on(self, raw_state: str, running: bool) -> bool:
        if raw_state:
            return raw_state not in _OFF_STATES
        return running

    def _parse_machine_readable(self, raw_output: str) -> dict[str, str]:
        data: dict[str, str] = {}
        for raw_line in raw_output.splitlines():
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                value = value[1:-1]
            data[key] = value
        return data
