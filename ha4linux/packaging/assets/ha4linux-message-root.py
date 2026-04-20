#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_ALLOWED_TARGETS = {"broadcast", "x11"}


def _error_result(message: str, *, deliveries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "error": message}
    if deliveries is not None:
        result["deliveries"] = deliveries
    return result


def _load_payload() -> dict[str, Any]:
    raw_payload = sys.stdin.read().strip()
    if not raw_payload:
        return {}

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object")

    return payload


def _normalize_targets(raw_targets: Any) -> list[str]:
    if raw_targets is None:
        return ["broadcast"]

    if isinstance(raw_targets, str):
        values = [part.strip().lower() for part in raw_targets.split(",")]
    elif isinstance(raw_targets, (list, tuple, set)):
        values = [str(part).strip().lower() for part in raw_targets]
    else:
        raise ValueError("Invalid 'targets' parameter")

    normalized: list[str] = []
    seen_targets: set[str] = set()
    invalid_targets: list[str] = []

    for value in values:
        if not value:
            continue
        if value not in _ALLOWED_TARGETS:
            invalid_targets.append(value)
            continue
        if value in seen_targets:
            continue
        seen_targets.add(value)
        normalized.append(value)

    if invalid_targets:
        raise ValueError(
            "Unsupported message targets requested: " + ", ".join(sorted(set(invalid_targets)))
        )

    return normalized or ["broadcast"]


def _format_message(*, title: str, message: str) -> str:
    if title:
        return f"{title}\n\n{message}"
    return message


def _run_command(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    user: str | None = None,
    input_text: str | None = None,
    timeout: int = 15,
) -> subprocess.CompletedProcess[str]:
    preexec_fn = None

    if user is not None:
        pw = pwd.getpwnam(user)

        def _demote() -> None:
            os.initgroups(pw.pw_name, pw.pw_gid)
            os.setgid(pw.pw_gid)
            os.setuid(pw.pw_uid)

        preexec_fn = _demote

    return subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        preexec_fn=preexec_fn,
    )


def _deliver_broadcast(*, title: str, message: str) -> dict[str, Any]:
    wall = shutil.which("wall")
    if wall is None:
        return {
            "target": "broadcast",
            "ok": False,
            "error": "wall command not available",
        }

    try:
        process = _run_command(
            [wall],
            input_text=_format_message(title=title, message=message),
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return {
            "target": "broadcast",
            "ok": False,
            "method": "wall",
            "error": "wall command timed out",
        }

    result = {
        "target": "broadcast",
        "ok": process.returncode == 0,
        "method": "wall",
        "returncode": process.returncode,
        "stdout": process.stdout.strip(),
        "stderr": process.stderr.strip(),
    }
    if process.returncode != 0:
        result["error"] = process.stderr.strip() or process.stdout.strip() or "wall command failed"
    return result


def _parse_key_value_output(raw_text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _show_session(session_id: str) -> dict[str, Any]:
    loginctl = shutil.which("loginctl")
    if loginctl is None:
        raise RuntimeError("loginctl command not available")

    process = _run_command(
        [
            loginctl,
            "show-session",
            session_id,
            "--property=Id",
            "--property=Name",
            "--property=User",
            "--property=Display",
            "--property=Type",
            "--property=Class",
            "--property=State",
            "--property=Active",
            "--property=Leader",
            "--property=Remote",
        ],
        timeout=10,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "Unable to inspect session")

    values = _parse_key_value_output(process.stdout)
    uid = values.get("User", "").strip()
    user_name = values.get("Name", "").strip()

    if uid.isdigit() and not user_name:
        try:
            user_name = pwd.getpwuid(int(uid)).pw_name
        except KeyError:
            user_name = uid

    leader = values.get("Leader", "").strip()
    return {
        "id": values.get("Id", "").strip() or session_id,
        "user": user_name,
        "uid": int(uid) if uid.isdigit() else None,
        "display": values.get("Display", "").strip(),
        "type": values.get("Type", "").strip().lower(),
        "class": values.get("Class", "").strip().lower(),
        "state": values.get("State", "").strip().lower(),
        "active": values.get("Active", "").strip().lower() == "yes",
        "leader": int(leader) if leader.isdigit() else None,
        "remote": values.get("Remote", "").strip().lower() == "yes",
    }


def _list_graphical_sessions() -> list[dict[str, Any]]:
    loginctl = shutil.which("loginctl")
    if loginctl is None:
        raise RuntimeError("loginctl command not available")

    process = _run_command([loginctl, "list-sessions", "--no-legend", "--no-pager"], timeout=10)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "Unable to list sessions")

    sessions: list[dict[str, Any]] = []
    for raw_line in process.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        session_id = line.split()[0]
        details = _show_session(session_id)
        if details.get("type") not in {"x11", "wayland"}:
            continue
        if details.get("remote"):
            continue
        if not details.get("user"):
            continue
        sessions.append(details)

    active_sessions = [session for session in sessions if session.get("active")]
    return active_sessions or sessions


def _session_environment(session: dict[str, Any]) -> tuple[str, dict[str, str]] | None:
    user = str(session.get("user", "")).strip()
    uid = session.get("uid")
    if not user or not isinstance(uid, int):
        return None

    try:
        pw = pwd.getpwnam(user)
    except KeyError:
        return None

    environment: dict[str, str] = {}
    leader = session.get("leader")
    if isinstance(leader, int) and leader > 0:
        environ_path = Path("/proc") / str(leader) / "environ"
        try:
            raw_environ = environ_path.read_bytes()
        except OSError:
            raw_environ = b""

        for chunk in raw_environ.split(b"\0"):
            if not chunk or b"=" not in chunk:
                continue
            key_bytes, _, value_bytes = chunk.partition(b"=")
            key = key_bytes.decode("utf-8", errors="ignore").strip()
            value = value_bytes.decode("utf-8", errors="ignore").strip()
            if key and value:
                environment[key] = value

    runtime_dir = Path("/run") / "user" / str(uid)
    environment.setdefault("HOME", pw.pw_dir)
    environment.setdefault("USER", user)
    environment.setdefault("LOGNAME", user)
    if runtime_dir.is_dir():
        environment.setdefault("XDG_RUNTIME_DIR", str(runtime_dir))

    if "DBUS_SESSION_BUS_ADDRESS" not in environment:
        bus_path = runtime_dir / "bus"
        if bus_path.exists():
            environment["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"

    display = environment.get("DISPLAY", "").strip() or str(session.get("display", "")).strip()
    if not display and session.get("type") == "x11":
        x11_socket_dir = Path("/tmp/.X11-unix")
        if x11_socket_dir.is_dir():
            for candidate in sorted(x11_socket_dir.iterdir()):
                if candidate.name.startswith("X") and candidate.name[1:].isdigit():
                    display = f":{candidate.name[1:]}"
                    break
    if display:
        environment["DISPLAY"] = display

    xauthority = environment.get("XAUTHORITY", "").strip()
    if not xauthority:
        default_xauthority = Path(pw.pw_dir) / ".Xauthority"
        if default_xauthority.is_file():
            xauthority = str(default_xauthority)
    if xauthority:
        environment["XAUTHORITY"] = xauthority

    return user, environment


def _deliver_to_session(session: dict[str, Any], *, title: str, message: str) -> dict[str, Any]:
    session_id = str(session.get("id", "")).strip() or "unknown"
    payload = {
        "session_id": session_id,
        "user": session.get("user"),
        "type": session.get("type"),
        "display": session.get("display"),
    }

    session_env = _session_environment(session)
    if session_env is None:
        payload["ok"] = False
        payload["error"] = "Unable to resolve session environment"
        return payload

    user, environment = session_env
    notify_send = shutil.which("notify-send")
    xmessage = shutil.which("xmessage")
    formatted_message = _format_message(title=title, message=message)

    if notify_send and environment.get("DBUS_SESSION_BUS_ADDRESS"):
        try:
            process = _run_command(
                [
                    notify_send,
                    "--app-name",
                    "HA4Linux",
                    "--expire-time",
                    "15000",
                    title or "Home Assistant",
                    message,
                ],
                env=environment,
                user=user,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            process = None
            notify_error = "notify-send timed out"
        else:
            if process.returncode == 0:
                payload.update(
                    {
                        "ok": True,
                        "method": "notify-send",
                        "returncode": process.returncode,
                        "stdout": process.stdout.strip(),
                        "stderr": process.stderr.strip(),
                    }
                )
                return payload
            notify_error = (
                process.stderr.strip() or process.stdout.strip() or "notify-send command failed"
            )
    else:
        notify_error = "notify-send not available for this session"

    if xmessage and session.get("type") == "x11" and environment.get("DISPLAY"):
        try:
            process = _run_command(
                [
                    xmessage,
                    "-center",
                    "-timeout",
                    "15",
                    formatted_message,
                ],
                env=environment,
                user=user,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            process = None
            xmessage_error = "xmessage timed out"
        else:
            if process.returncode == 0:
                payload.update(
                    {
                        "ok": True,
                        "method": "xmessage",
                        "returncode": process.returncode,
                        "stdout": process.stdout.strip(),
                        "stderr": process.stderr.strip(),
                    }
                )
                return payload
            xmessage_error = process.stderr.strip() or process.stdout.strip() or "xmessage failed"
    else:
        xmessage_error = "xmessage not available for this session"

    payload["ok"] = False
    payload["error"] = f"{notify_error}; {xmessage_error}"
    return payload


def _deliver_x11(*, title: str, message: str) -> dict[str, Any]:
    try:
        sessions = _list_graphical_sessions()
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        return {
            "target": "x11",
            "ok": False,
            "error": str(exc),
        }

    if not sessions:
        return {
            "target": "x11",
            "ok": False,
            "error": "No active graphical session candidates found",
        }

    session_results = [_deliver_to_session(session, title=title, message=message) for session in sessions]
    delivered_sessions = [result for result in session_results if result.get("ok")]

    result: dict[str, Any] = {
        "target": "x11",
        "ok": bool(delivered_sessions),
        "sessions": session_results,
        "delivered_sessions": len(delivered_sessions),
    }
    if not delivered_sessions:
        errors = [str(item.get("error", "")).strip() for item in session_results if item.get("error")]
        result["error"] = "; ".join(error for error in errors if error) or "Unable to deliver to X11"
    return result


def main() -> int:
    try:
        payload = _load_payload()
        message = str(payload.get("message", "")).strip()
        title = str(payload.get("title", "")).strip()
        targets = _normalize_targets(payload.get("targets"))
    except ValueError as exc:
        print(json.dumps(_error_result(str(exc))))
        return 1

    if not message:
        print(json.dumps(_error_result("Missing 'message' parameter")))
        return 1

    deliveries: list[dict[str, Any]] = []
    for target in targets:
        if target == "broadcast":
            deliveries.append(_deliver_broadcast(title=title, message=message))
            continue
        if target == "x11":
            deliveries.append(_deliver_x11(title=title, message=message))

    delivered_targets = [
        str(item.get("target", "")).strip()
        for item in deliveries
        if bool(item.get("ok", False))
    ]
    result: dict[str, Any] = {
        "ok": bool(delivered_targets),
        "targets_requested": targets,
        "targets_delivered": delivered_targets,
        "deliveries": deliveries,
    }
    if not result["ok"]:
        errors = [str(item.get("error", "")).strip() for item in deliveries if item.get("error")]
        result["error"] = "; ".join(error for error in errors if error) or "Unable to deliver message"

    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
