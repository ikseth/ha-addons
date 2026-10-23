"""Pure logic for host package updates (no Home Assistant imports, unit-testable)."""

from __future__ import annotations

from typing import Any, Iterable

PACKAGES_ATTRIBUTE_LIMIT = 20


def system_info_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}

    sensors = data.get("sensors", {})
    if not isinstance(sensors, dict):
        return {}

    module = sensors.get("system_info", {})
    if not isinstance(module, dict):
        return {}

    payload = module.get("data", {})
    return payload if isinstance(payload, dict) else {}


def updates_ready(payload: dict[str, Any]) -> bool:
    """True when the host reports a valid package updates sample."""
    if not payload:
        return False
    return (
        bool(payload.get("updates_enabled", False))
        and bool(payload.get("updates_supported", False))
        and str(payload.get("updates_state") or "").strip().lower() == "idle"
    )


def pending_count(payload: dict[str, Any]) -> int | None:
    if not updates_ready(payload):
        return None
    count = payload.get("updates_pending_count")
    return int(count) if isinstance(count, (int, float)) else None


def should_notify(payload: dict[str, Any]) -> bool:
    return (pending_count(payload) or 0) > 0


def notification_signature(payload: dict[str, Any]) -> tuple[object, ...]:
    packages = payload.get("updates_packages", [])
    package_signature: tuple[str, ...] = ()
    if isinstance(packages, list):
        package_signature = tuple(
            str(item.get("raw") or item.get("name") or "")
            for item in packages
            if isinstance(item, dict)
        )

    return (
        payload.get("updates_pending_count"),
        payload.get("updates_last_checked_at"),
        payload.get("distribution"),
        payload.get("package_manager"),
        package_signature,
    )


def notification_message(host: str, payload: dict[str, Any]) -> str:
    host = host.strip() or "linux"
    distribution = str(payload.get("distribution") or "Linux").strip()
    package_manager = str(payload.get("package_manager") or "unknown").strip()
    checked_at = str(payload.get("updates_last_checked_at") or "unknown").strip()
    count = int(payload.get("updates_pending_count") or 0)
    packages = payload.get("updates_packages", [])

    lines = [
        f"Host: `{host}`",
        f"Distribution: `{distribution}`",
        f"Package manager: `{package_manager}`",
        f"Pending updates: `{count}`",
        f"Last checked at: `{checked_at}`",
    ]

    if isinstance(packages, list) and packages:
        lines.append("")
        lines.append("Preview:")
        for item in packages:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "package").strip()
            candidate_version = str(item.get("candidate_version") or "").strip()
            if candidate_version:
                lines.append(f"- `{name}` -> `{candidate_version}`")
            else:
                lines.append(f"- `{name}`")

    if bool(payload.get("updates_packages_truncated", False)):
        total = int(payload.get("updates_packages_total") or count)
        shown = len(packages) if isinstance(packages, list) else 0
        remaining = max(total - shown, 0)
        if remaining > 0:
            lines.append(f"- ... and `{remaining}` more packages")

    return "\n".join(lines)


def package_names(payload: dict[str, Any], limit: int = PACKAGES_ATTRIBUTE_LIMIT) -> list[str]:
    packages = payload.get("updates_packages", [])
    if not isinstance(packages, list):
        return []
    names = [
        str(item.get("name") or "").strip()
        for item in packages
        if isinstance(item, dict)
    ]
    return [name for name in names if name][:limit]


def availability_attributes(payload: dict[str, Any], limit: int = PACKAGES_ATTRIBUTE_LIMIT) -> dict[str, Any]:
    """Compact attributes for the per-host "updates available" entity."""
    count = pending_count(payload) or 0
    names = package_names(payload, limit)
    reported_total = payload.get("updates_packages_total")
    total = int(reported_total) if isinstance(reported_total, (int, float)) else count
    return {
        "pending_count": count,
        "packages": names,
        "packages_truncated": max(total, count) > len(names),
        "package_manager": payload.get("package_manager"),
        "last_checked_at": payload.get("updates_last_checked_at"),
    }


def summarize(hosts: Iterable[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Aggregate (host, system_info payload) pairs; hosts without a valid sample are skipped."""
    reporting = 0
    total = 0
    with_updates: dict[str, int] = {}
    for host, payload in hosts:
        count = pending_count(payload)
        if count is None:
            continue
        reporting += 1
        total += count
        if count > 0:
            with_updates[host] = count

    return {
        "hosts_reporting": reporting,
        "hosts_with_updates": len(with_updates),
        "pending_total": total,
        "hosts": dict(sorted(with_updates.items())),
    }
