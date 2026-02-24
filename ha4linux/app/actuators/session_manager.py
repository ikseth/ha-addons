import subprocess
from typing import Any

from app.actuators.base import Actuator

_ALLOWED_ACTIONS = {"activate", "terminate", "status"}


class SessionManagerActuator(Actuator):
    id = "session_manager"

    def __init__(self, allowed_users: set[str]) -> None:
        self.allowed_users = allowed_users

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15)

    def _list_sessions(self) -> list[dict[str, str]]:
        process = self._run(["loginctl", "list-sessions", "--no-legend", "--no-pager"])
        if process.returncode != 0:
            raise RuntimeError(process.stderr.strip() or "Unable to list sessions")

        sessions: list[dict[str, str]] = []
        for raw_line in process.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) < 3:
                continue

            session_id = parts[0]
            user = parts[2]
            details = self._show_session(session_id)
            details["id"] = session_id
            details["user"] = user

            if details.get("type") not in {"x11", "wayland"}:
                continue

            if self.allowed_users and user not in self.allowed_users:
                continue

            sessions.append(details)

        return sessions

    def _show_session(self, session_id: str) -> dict[str, str]:
        process = self._run(
            [
                "loginctl",
                "show-session",
                session_id,
                "--property=Active",
                "--property=Type",
                "--property=State",
                "--property=Class",
                "--value",
            ]
        )
        if process.returncode != 0:
            raise RuntimeError(process.stderr.strip() or "Unable to inspect session")

        values = process.stdout.splitlines()
        active = values[0].strip().lower() == "yes" if len(values) > 0 else False
        session_type = values[1].strip() if len(values) > 1 else ""
        state = values[2].strip() if len(values) > 2 else ""
        session_class = values[3].strip() if len(values) > 3 else ""

        return {
            "active": "yes" if active else "no",
            "type": session_type,
            "state": state,
            "class": session_class,
        }

    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action not in _ALLOWED_ACTIONS:
            return {"ok": False, "error": f"Action '{action}' not allowed"}

        sessions = self._list_sessions()
        if not sessions:
            return {"ok": False, "error": "No active graphical session candidates found"}

        active_session = next((item for item in sessions if item.get("active") == "yes"), None)

        if action == "status":
            return {
                "ok": True,
                "sessions": sessions,
                "active_session": active_session,
            }

        if action == "activate":
            if active_session is not None:
                return {"ok": True, "message": "A graphical session is already active", "session": active_session}

            target = sessions[0]
            process = self._run(["sudo", "-n", "loginctl", "activate", target["id"]])
            return {
                "ok": process.returncode == 0,
                "returncode": process.returncode,
                "stdout": process.stdout.strip(),
                "stderr": process.stderr.strip(),
                "session": target,
            }

        if active_session is None:
            return {"ok": False, "error": "No active graphical session found"}

        process = self._run(["sudo", "-n", "loginctl", "terminate-session", active_session["id"]])
        return {
            "ok": process.returncode == 0,
            "returncode": process.returncode,
            "stdout": process.stdout.strip(),
            "stderr": process.stderr.strip(),
            "session": active_session,
        }
