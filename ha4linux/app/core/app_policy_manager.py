import json
import os
import re
import signal
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple

_ALLOWED_ACTIONS = {"terminate", "stop_service", "none", "disable_exec"}
_VALID_APP_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_VALID_NAME = re.compile(r"^[a-zA-Z0-9_.@-]+$")
_EXEC_STATE_FILE = "/var/lib/ha4linux/app_policy_exec_state.json"


@dataclass
class AppPolicy:
    app_id: str
    process_names: list[str]
    service_names: list[str]
    executable_paths: list[str]
    allowed: bool
    action_on_block: str
    monitor_only: bool


class AppPolicyManager:
    def __init__(self, policy_file: str, use_sudo_kill: bool = True) -> None:
        self.policy_file = policy_file
        self.use_sudo_kill = use_sudo_kill
        self._lock = threading.Lock()
        self._policies: dict[str, AppPolicy] = {}
        self._last_error: Optional[str] = None

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

    def status(self, app_id: Optional[str] = None) -> dict[str, Any]:
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

            restore_result: Optional[dict[str, Any]] = None
            if allowed and policy.action_on_block == "disable_exec":
                restore_result = self._restore_exec(policy)
                if not restore_result.get("ok", False):
                    return {
                        "ok": False,
                        "app_id": app_id,
                        "allowed": previous,
                        "restore": restore_result,
                    }

            policy.allowed = allowed
            try:
                self._persist_locked()
            except Exception as exc:
                policy.allowed = previous
                return {"ok": False, "error": f"Failed to persist policy file: {exc}"}

        enforce_result: Optional[dict[str, Any]] = None
        if not allowed:
            enforce_result = self.enforce(app_id=app_id)

        return {
            "ok": True,
            "app_id": app_id,
            "allowed": allowed,
            "restore": restore_result,
            "enforce": enforce_result,
            "status": self.status(app_id=app_id),
        }

    def enforce(self, app_id: Optional[str] = None) -> dict[str, Any]:
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

            if policy.allowed or policy.monitor_only:
                results.append(item)
                continue

            if policy.action_on_block == "disable_exec":
                action_result = self._disable_exec(policy)
                item["actions"].append(action_result)
                if action_result.get("attempted"):
                    action_count += 1

                for process_name in current["running_process_names"]:
                    action_result = self._terminate_process(process_name)
                    item["actions"].append(action_result)
                    if action_result.get("attempted"):
                        action_count += 1

            elif policy.action_on_block == "terminate":
                if not current["running"]:
                    results.append(item)
                    continue
                for process_name in current["running_process_names"]:
                    action_result = self._terminate_process(process_name)
                    item["actions"].append(action_result)
                    if action_result.get("attempted"):
                        action_count += 1

            elif policy.action_on_block == "stop_service":
                if not current["running"]:
                    results.append(item)
                    continue
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

    def _snapshot(self) -> Tuple[dict[str, AppPolicy], Optional[str]]:
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
            executable_paths = self._extract_paths(
                raw.get("executable_paths", []),
                "executable_paths",
            )

            if not process_names and not service_names and not executable_paths:
                raise RuntimeError(
                    f"App '{app_id}' must define at least one process, service or executable path"
                )

            action_on_block = str(raw.get("action_on_block", "terminate")).strip().lower()
            if action_on_block not in _ALLOWED_ACTIONS:
                raise RuntimeError(
                    f"Invalid action_on_block '{action_on_block}' for app '{app_id}'"
                )
            if action_on_block == "disable_exec" and not executable_paths:
                raise RuntimeError(
                    f"App '{app_id}' with action_on_block=disable_exec must define executable_paths"
                )

            parsed[app_id] = AppPolicy(
                app_id=app_id,
                process_names=process_names,
                service_names=service_names,
                executable_paths=executable_paths,
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

    def _extract_paths(self, value: Any, field_name: str) -> list[str]:
        if not isinstance(value, list):
            raise RuntimeError(f"{field_name} must be a list")

        paths: list[str] = []
        for raw in value:
            path = str(raw).strip()
            if not path:
                continue
            if not path.startswith("/") or "\x00" in path:
                raise RuntimeError(f"Invalid path '{path}' in {field_name}")
            paths.append(path)

        return sorted(set(paths))

    def _persist_locked(self) -> None:
        payload = {
            "apps": [
                {
                    "id": policy.app_id,
                    "process_names": policy.process_names,
                    "service_names": policy.service_names,
                    "executable_paths": policy.executable_paths,
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

        executable_status = [
            self._executable_status(path)
            for path in policy.executable_paths
        ]
        running = bool(running_processes or active_services)
        violating = running and not policy.allowed
        existing_executables = [
            item for item in executable_status if item.get("exists", False)
        ]
        blocking_effective = (
            policy.action_on_block == "disable_exec"
            and bool(existing_executables)
            and all(item.get("blocked", False) for item in existing_executables)
        )

        return {
            "app_id": policy.app_id,
            "allowed": policy.allowed,
            "monitor_only": policy.monitor_only,
            "action_on_block": policy.action_on_block,
            "running": running,
            "violating": violating,
            "blocking_effective": blocking_effective,
            "running_process_names": running_processes,
            "active_services": active_services,
            "process_names": policy.process_names,
            "service_names": policy.service_names,
            "executable_paths": policy.executable_paths,
            "executable_status": executable_status,
        }

    def _executable_status(self, path: str) -> dict[str, Any]:
        try:
            st = os.stat(path)
        except OSError as exc:
            return {
                "path": path,
                "exists": False,
                "blocked": False,
                "error": str(exc),
            }

        mode = stat.S_IMODE(st.st_mode)
        executable = bool(mode & 0o111)
        return {
            "path": path,
            "exists": True,
            "mode": f"{mode:04o}",
            "executable": executable,
            "blocked": not executable,
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

    def _send_signal(self, pid: int, sig: signal.Signals) -> Optional[str]:
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

    def _read_exec_state(self) -> dict[str, Any]:
        try:
            with open(_EXEC_STATE_FILE, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {"paths": {}}

        if not isinstance(payload, dict):
            return {"paths": {}}
        paths = payload.get("paths")
        if not isinstance(paths, dict):
            payload["paths"] = {}
        return payload

    def _write_exec_state(self, payload: dict[str, Any]) -> None:
        parent = os.path.dirname(_EXEC_STATE_FILE)
        if parent:
            os.makedirs(parent, exist_ok=True)

        tmp_file = f"{_EXEC_STATE_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(tmp_file, _EXEC_STATE_FILE)

    def _sudo_chmod(self, mode: int, path: str) -> dict[str, Any]:
        result = subprocess.run(
            ["sudo", "-n", "chmod", f"{mode:04o}", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {
            "path": path,
            "mode": f"{mode:04o}",
            "rc": result.returncode,
            "ok": result.returncode == 0,
            "stderr": result.stderr.strip(),
        }

    def _disable_exec(self, policy: AppPolicy) -> dict[str, Any]:
        state = self._read_exec_state()
        paths_state = state.setdefault("paths", {})
        actions: list[dict[str, Any]] = []

        for path in policy.executable_paths:
            status = self._executable_status(path)
            if not status.get("exists", False):
                actions.append({
                    "path": path,
                    "attempted": False,
                    "ok": False,
                    "error": status.get("error", "Path does not exist"),
                })
                continue

            current_mode = int(str(status["mode"]), 8)
            if path not in paths_state:
                paths_state[path] = {
                    "original_mode": f"{current_mode:04o}",
                    "app_id": policy.app_id,
                }

            blocked_mode = current_mode & ~0o111
            if blocked_mode == current_mode:
                actions.append({
                    "path": path,
                    "attempted": False,
                    "ok": True,
                    "mode": f"{current_mode:04o}",
                    "message": "Executable bits already disabled",
                })
                continue

            chmod_result = self._sudo_chmod(blocked_mode, path)
            chmod_result["attempted"] = True
            actions.append(chmod_result)

        self._write_exec_state(state)
        return {
            "type": "disable_exec",
            "attempted": bool(policy.executable_paths),
            "ok": all(item.get("ok", False) for item in actions),
            "actions": actions,
        }

    def _restore_exec(self, policy: AppPolicy) -> dict[str, Any]:
        state = self._read_exec_state()
        paths_state = state.setdefault("paths", {})
        actions: list[dict[str, Any]] = []

        for path in policy.executable_paths:
            stored = paths_state.get(path)
            if not isinstance(stored, dict) or "original_mode" not in stored:
                actions.append({
                    "path": path,
                    "attempted": False,
                    "ok": True,
                    "message": "No stored executable mode; leaving unchanged",
                })
                continue

            try:
                original_mode = int(str(stored["original_mode"]), 8)
            except ValueError:
                actions.append({
                    "path": path,
                    "attempted": False,
                    "ok": False,
                    "error": f"Invalid stored mode '{stored['original_mode']}'",
                })
                continue

            chmod_result = self._sudo_chmod(original_mode, path)
            chmod_result["attempted"] = True
            actions.append(chmod_result)
            if chmod_result.get("ok", False):
                paths_state.pop(path, None)

        self._write_exec_state(state)
        return {
            "type": "restore_exec",
            "attempted": bool(policy.executable_paths),
            "ok": all(item.get("ok", False) for item in actions),
            "actions": actions,
        }

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
