from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path("/var/lib/ha4linux")
RUNTIME_STATE_FILE = DATA_DIR / "runtime-state.json"
MESSAGE_HISTORY_FILE = DATA_DIR / "message-history.jsonl"
MAX_MESSAGES = 100


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def load_runtime_state() -> dict[str, Any]:
    try:
        payload = json.loads(RUNTIME_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def record_authenticated_client(
    *,
    host: str | None,
    user_agent: str | None,
    path: str,
) -> None:
    if not host:
        return

    state = load_runtime_state()
    state["last_authenticated_client"] = {
        "host": host,
        "user_agent": user_agent or "",
        "path": path,
        "seen_at": _utc_now(),
    }
    _atomic_write_json(RUNTIME_STATE_FILE, state)


def append_message_history(
    *,
    title: str,
    message: str,
    targets_requested: list[str],
    result: dict[str, Any],
) -> None:
    MESSAGE_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "received_at": _utc_now(),
        "title": title,
        "message": message,
        "targets_requested": targets_requested,
        "ok": bool(result.get("ok", False)),
        "targets_delivered": result.get("targets_delivered", []),
        "error": result.get("error", ""),
    }

    entries = load_message_history(limit=MAX_MESSAGES - 1)
    entries.append(entry)
    with MESSAGE_HISTORY_FILE.open("w", encoding="utf-8") as handle:
        for item in entries[-MAX_MESSAGES:]:
            handle.write(json.dumps(item, sort_keys=True) + "\n")


def load_message_history(limit: int = 20) -> list[dict[str, Any]]:
    try:
        lines = MESSAGE_HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    messages: list[dict[str, Any]] = []
    for line in lines[-max(limit, 1) :]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            messages.append(payload)
    return messages
