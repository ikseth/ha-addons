from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional


def evaluate_update_preflight(
    *,
    apply_command: str,
    rollback_command: str,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    warnings: list[str] = []
    reason: Optional[str] = None

    apply_path = Path(apply_command).expanduser() if apply_command else None
    rollback_path = Path(rollback_command).expanduser() if rollback_command else None
    systemctl_path = shutil.which("systemctl")
    systemd_run_path = shutil.which("systemd-run")

    checks["apply_command"] = {
        "configured": bool(apply_command),
        "path": str(apply_path) if apply_path is not None else None,
        "exists": bool(apply_path and apply_path.exists()),
    }
    checks["rollback_command"] = {
        "configured": bool(rollback_command),
        "path": str(rollback_path) if rollback_path is not None else None,
        "exists": bool(rollback_path and rollback_path.exists()),
    }
    checks["systemctl"] = {
        "available": bool(systemctl_path),
        "path": systemctl_path,
    }
    checks["systemd_run"] = {
        "available": bool(systemd_run_path),
        "path": systemd_run_path,
    }

    root_mount = _mount_details("/")
    checks["root_mount"] = root_mount
    service_mount = _mount_details("/etc/systemd/system")
    checks["service_mount"] = service_mount

    boot_snapshot = _detect_btrfs_snapshot_boot(root_mount)
    checks["boot_snapshot"] = boot_snapshot

    service_file = Path("/etc/systemd/system/ha4linux.service")
    checks["service_file"] = {
        "exists": service_file.exists(),
        "path": str(service_file),
    }

    if not checks["apply_command"]["configured"]:
        reason = "apply command not configured"
    elif not checks["apply_command"]["exists"]:
        reason = f"apply command not found: {checks['apply_command']['path']}"
    elif not checks["systemctl"]["available"]:
        reason = "systemctl command not available"
    elif not checks["systemd_run"]["available"]:
        reason = "systemd-run command not available"
    elif root_mount.get("exists") and not root_mount.get("writable", False):
        reason = "root filesystem is not writable"
    elif service_mount.get("exists") and not service_mount.get("writable", False):
        reason = "systemd service mount is not writable"
    elif bool(boot_snapshot.get("active", False)):
        reason = "host is booted from a Btrfs snapshot; remote apply is blocked"

    if bool(boot_snapshot.get("active", False)):
        warnings.append("booted from Btrfs snapshot")

    return {
        "ok": reason is None,
        "can_apply": reason is None,
        "reason": reason,
        "warnings": warnings,
        "checks": checks,
    }


def _mount_details(target: str) -> dict[str, Any]:
    command = ["findmnt", "-no", "TARGET,SOURCE,FSTYPE,OPTIONS", target]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return {
            "exists": False,
            "target": target,
            "source": None,
            "fstype": None,
            "options": [],
            "writable": True,
            "error": completed.stderr.strip() or completed.stdout.strip() or "mount not found",
        }

    raw = completed.stdout.strip()
    if not raw:
        return {
            "exists": False,
            "target": target,
            "source": None,
            "fstype": None,
            "options": [],
            "writable": True,
            "error": "mount not found",
        }

    parts = raw.split(maxsplit=3)
    if len(parts) < 4:
        return {
            "exists": True,
            "target": target,
            "source": None,
            "fstype": None,
            "options": [],
            "writable": True,
            "error": f"unexpected findmnt output: {raw}",
        }

    mount_target, source, fstype, options_raw = parts
    options = [item.strip() for item in options_raw.split(",") if item.strip()]
    return {
        "exists": True,
        "target": mount_target,
        "source": source,
        "fstype": fstype,
        "options": options,
        "writable": "rw" in options,
    }


def _detect_btrfs_snapshot_boot(root_mount: dict[str, Any]) -> dict[str, Any]:
    fstype = str(root_mount.get("fstype") or "").strip().lower()
    source = str(root_mount.get("source") or "").strip()
    active = fstype == "btrfs" and "/.snapshots/" in source

    subvolume = None
    if "[" in source and "]" in source:
        subvolume = source.split("[", 1)[1].rsplit("]", 1)[0]

    return {
        "active": active,
        "subvolume": subvolume,
        "source": source or None,
    }
