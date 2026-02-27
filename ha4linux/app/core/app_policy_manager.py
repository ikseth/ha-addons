import json
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any

_ALLOWED_ACTIONS = {"terminate", "stop_service", "none"}
_VALID_APP_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_VALID_NAME = re.compile(r"^[a-zA-Z0-9_.@-]+$")


@dataclass
class AppPolicy:
    app_id: str
    process_names: list[str]
    service_names: list[str]
    allowed: bool
    action_on_block: str
    monitor_only: bool


class AppPolicyManager:
    def __init__(self, policy_file: str, use_sudo_kill: bool = True) -> None:
        self.policy_file = policy_file
        self.use_sudo_kill = use_sudo_kill
        self._lock = threading.Lock()
        self._policies: dict[str, AppPolicy] = {}
        self._last_error: str | None = None

    def load(self) -> dict[str, Any]:
        try:
            raw = self._read_or_init_policy_file()
            parsed = self._parse(raw)
            with self._lock:
                self._policies = parsed
                self._last_error = None
            return {
                "ok": True,
                "policy_file": self.policy_file,
                "apps_loaded": len(parsed),
            }
        except Exception as exc:
            with self._lock:
                self._policies = {}
                self._last_error = str(exc)
            return {"ok": False, "error": str(exc), "policy_file": self.policy_file}

    def status(self, app_id: str | None = None) -> dict[str, Any]:
        policies, last_error = self._snapshot()
        if app_id is not None:
            policy = policies.get(app_id)
            if policy is None:
                return {"ok": False, "error": f"Unknown app_id '{app_id}'"}
            apps = [self._status_for(policy)]
        else:
            apps = [self._status_for(policy) for policy in policies.values()]

        violation_count = sum(1 for app in apps if app["violating"])

        return {
            "ok": True,
            "policy_file": self.policy_file,
            "load_error": last_error,
            "apps": apps,
            "app_count": len(apps),
            "violation_count": violation_count,
        }

    def set_allowed(self, app_id: str, allowed: bool) -> dict[str, Any]:
        with self._lock:
            policy = self._policies.get(app_id)
            if policy is None:
                return {"ok": False, "error": f"Unknown app_id '{app_id}'"}

            previous = policy.allowed
            policy.allowed = allowed
            try:
                self._persist_locked()
            except Exception as exc:
                policy.allowed = previous
                return {"ok": False, "error": f"Failed to persist policy file: {exc}"}

        enforce_result: dict[str, Any] | None = None
        if not allowed:
            enforce_result = self.enforce(app_id=app_id)

        return {
            "ok": True,
            "app_id": app_id,
            "allowed": allowed,
            "enforce": enforce_result,
            "status": self.status(app_id=app_id),
        }

    def enforce(self, app_id: str | None = None) -> dict[str, Any]:
        policies, _ = self._snapshot()

        targets: list[AppPolicy]
        if app_id is not None:
            single = policies.get(app_id)
            if single is None:
                return {"ok": False, "error": f"Unknown app_id '{app_id}'"}
            targets = [single]
        else:
            targets = list(policies.values())

        results: list[dict[str, Any]] = []
        action_count = 0

        for policy in targets:
            current = self._status_for(policy)
            item: dict[str, Any] = {
                "app_id": policy.app_id,
                "allowed": policy.allowed,
                "monitor_only": policy.monitor_only,
                "action_on_block": policy.action_on_block,
                "before": current,
                "actions": [],
            }

            if policy.allowed or policy.monitor_only or not current["running"]:
                results.append(item)
                continue

            if policy.action_on_block == "terminate":
                for process_name in current["running_process_names"]:
                    action_result = self._terminate_process(process_name)
                    item["actions"].append(action_result)
                    if action_result.get("attempted"):
                        action_count += 1

            elif policy.action_on_block == "stop_service":
                for service_name in current["active_services"]:
                    action_result = self._stop_service(service_name)
                    item["actions"].append(action_result)
                    if action_result.get("attempted"):
                        action_count += 1

            item["after"] = self._status_for(policy)
            results.append(item)

        return {
            "ok": True,
            "app_id": app_id,
            "enforced_apps": len(results),
            "action_count": action_count,
            "results": results,
        }

    def _snapshot(self) -> tuple[dict[str, AppPolicy], str | None]:
        with self._lock:
            return dict(self._policies), self._last_error

    def _read_or_init_policy_file(self) -> dict[str, Any]:
        parent = os.path.dirname(self.policy_file)
        if parent:
            os.makedirs(parent, exist_ok=True)

        if not os.path.exists(self.policy_file):
            with open(self.policy_file, "w", encoding="utf-8") as handle:
                json.dump({"apps": []}, handle, indent=2, sort_keys=True)

        with open(self.policy_file, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)

        if not isinstance(parsed, dict):
            raise RuntimeError("Policy file must contain a JSON object")

        return parsed

    def _parse(self, payload: dict[str, Any]) -> dict[str, AppPolicy]:
        raw_apps = payload.get("apps", [])
        if not isinstance(raw_apps, list):
            raise RuntimeError("'apps' must be a list")

        parsed: dict[str, AppPolicy] = {}
        for raw in raw_apps:
            if not isinstance(raw, dict):
                raise RuntimeError("Each app policy must be an object")

            app_id = str(raw.get("id", "")).strip()
            if not _VALID_APP_ID.match(app_id):
                raise RuntimeError(f"Invalid app id '{app_id}'")

            if app_id in parsed:
                raise RuntimeError(f"Duplicated app id '{app_id}'")

            process_names = self._extract_names(raw.get("process_names", []), "process_names")
            service_names = self._extract_names(raw.get("service_names", []), "service_names")

            if not process_names and not service_names:
                raise RuntimeError(
                    f"App '{app_id}' must define at least one process or service name"
                )

            action_on_block = str(raw.get("action_on_block", "terminate")).strip().lower()
            if action_on_block not in _ALLOWED_ACTIONS:
                raise RuntimeError(
                    f"Invalid action_on_block '{action_on_block}' for app '{app_id}'"
                )

            parsed[app_id] = AppPolicy(
                app_id=app_id,
                process_names=process_names,
                service_names=service_names,
                allowed=bool(raw.get("allowed", True)),
                action_on_block=action_on_block,
                monitor_only=bool(raw.get("monitor_only", False)),
            )

        return parsed

    def _extract_names(self, value: Any, field_name: str) -> list[str]:
        if not isinstance(value, list):
            raise RuntimeError(f"{field_name} must be a list")

        names: list[str] = []
        for raw in value:
            name = str(raw).strip()
            if not name:
                continue
            if not _VALID_NAME.match(name):
                raise RuntimeError(f"Invalid name '{name}' in {field_name}")
            names.append(name)

        return sorted(set(names))

    def _persist_locked(self) -> None:
        payload = {
            "apps": [
                {
                    "id": policy.app_id,
                    "process_names": policy.process_names,
                    "service_names": policy.service_names,
                    "allowed": policy.allowed,
                    "action_on_block": policy.action_on_block,
                    "monitor_only": policy.monitor_only,
                }
                for policy in self._policies.values()
            ]
        }

        tmp_file = f"{self.policy_file}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

        os.replace(tmp_file, self.policy_file)

    def _status_for(self, policy: AppPolicy) -> dict[str, Any]:
        running_processes = [
            process_name
            for process_name in policy.process_names
            if self._is_process_running(process_name)
        ]

        active_services = [
            service_name
            for service_name in policy.service_names
            if self._is_service_active(service_name)
        ]

        running = bool(running_processes or active_services)
        violating = running and not policy.allowed

        return {
            "app_id": policy.app_id,
            "allowed": policy.allowed,
            "monitor_only": policy.monitor_only,
            "action_on_block": policy.action_on_block,
            "running": running,
            "violating": violating,
            "running_process_names": running_processes,
            "active_services": active_services,
            "process_names": policy.process_names,
            "service_names": policy.service_names,
        }

    def _is_process_running(self, process_name: str) -> bool:
        return bool(self._process_pids(process_name))

    def _is_service_active(self, service_name: str) -> bool:
        proc = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=4,
        )
        return proc.returncode == 0 and proc.stdout.strip() == "active"

    def _terminate_process(self, process_name: str) -> dict[str, Any]:
        pids_before = self._process_pids(process_name)
        if not pids_before:
            return {
                "type": "process",
                "target": process_name,
                "attempted": False,
                "ok": True,
                "message": "Process was not running",
            }

        term_errors: list[str] = []
        kill_errors: list[str] = []

        for pid in pids_before:
            error = self._send_signal(pid=pid, sig=signal.SIGTERM)
            if error is not None:
                term_errors.append(f"{pid}:{error}")

        time.sleep(0.5)
        pids_after_term = self._process_pids(process_name)

        if pids_after_term:
            for pid in pids_after_term:
                error = self._send_signal(pid=pid, sig=signal.SIGKILL)
                if error is not None:
                    kill_errors.append(f"{pid}:{error}")
            time.sleep(0.2)

        still_running = bool(self._process_pids(process_name))

        return {
            "type": "process",
            "target": process_name,
            "attempted": True,
            "ok": not still_running,
            "pids_before": pids_before,
            "term_errors": term_errors,
            "kill_errors": kill_errors,
        }

    def _process_pids(self, process_name: str) -> list[int]:
        pids: list[int] = []
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            comm_file = f"/proc/{pid}/comm"
            try:
                with open(comm_file, "r", encoding="utf-8") as handle:
                    comm = handle.read().strip()
            except OSError:
                continue

            if comm == process_name:
                pids.append(pid)

        return pids

    def _send_signal(self, pid: int, sig: signal.Signals) -> str | None:
        try:
            os.kill(pid, sig)
            return None
        except OSError as exc:
            # Fallback for processes owned by other users.
            if self.use_sudo_kill and exc.errno == 1:
                sudo = subprocess.run(
                    ["sudo", "-n", "kill", f"-{int(sig)}", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=6,
                )
                if sudo.returncode == 0:
                    return None
                return sudo.stderr.strip() or f"sudo kill rc={sudo.returncode}"
            return str(exc)

    def _stop_service(self, service_name: str) -> dict[str, Any]:
        active_before = self._is_service_active(service_name)
        if not active_before:
            return {
                "type": "service",
                "target": service_name,
                "attempted": False,
                "ok": True,
                "message": "Service was not active",
            }

        result = subprocess.run(
            ["sudo", "-n", "systemctl", "stop", service_name],
            capture_output=True,
            text=True,
            timeout=10,
        )

        active_after = self._is_service_active(service_name)

        return {
            "type": "service",
            "target": service_name,
            "attempted": True,
            "ok": result.returncode == 0 and not active_after,
            "rc": result.returncode,
            "stderr": result.stderr.strip(),
        }
