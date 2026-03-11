import os
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException

from app.core.config import Settings
from app.core.registry import ModuleRegistry
from app.core.update_manager import UpdateManager

settings = Settings()
registry = ModuleRegistry(settings=settings)
registry.load()

API_VERSION = "0.4.1"
API_SCHEMA_VERSION = "1.0"
API_MIN_INTEGRATION_VERSION = "0.3.0"
API_MAX_INTEGRATION_VERSION = "0.6.x"

update_manager = UpdateManager(
    api_version=API_VERSION,
    enabled=settings.remote_update_enabled,
    readonly_mode=settings.readonly_mode,
    allow_in_readonly=settings.remote_update_allow_in_readonly,
    manifest_url=settings.remote_update_manifest_url,
    channel=settings.remote_update_channel,
    check_interval_sec=settings.remote_update_check_interval_sec,
    check_timeout_sec=settings.remote_update_check_timeout_sec,
    command_timeout_sec=settings.remote_update_command_timeout_sec,
    apply_command=settings.remote_update_apply_command,
    rollback_command=settings.remote_update_rollback_command,
)

app = FastAPI(title="HA4Linux", version=API_VERSION)


def require_auth(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {settings.api_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/capabilities")
def capabilities(_: None = Depends(require_auth)) -> dict[str, Any]:
    return {
        "transport": "https" if settings.tls_enabled else "http",
        "sensors": sorted(registry.sensors.keys()),
        "actuators": sorted(registry.actuators.keys()),
        "management": {
            "remote_update": {
                "enabled": settings.remote_update_enabled,
                "readonly_mode": settings.readonly_mode,
                "allow_in_readonly": settings.remote_update_allow_in_readonly,
                "channel": settings.remote_update_channel,
            }
        },
    }


@app.get("/v1/version")
def version(_: None = Depends(require_auth)) -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "schema_version": API_SCHEMA_VERSION,
        "min_integration_version": API_MIN_INTEGRATION_VERSION,
        "max_integration_version": API_MAX_INTEGRATION_VERSION,
        "build": {
            "commit": os.getenv("HA4LINUX_BUILD_COMMIT", "unknown"),
            "date": os.getenv("HA4LINUX_BUILD_DATE", "unknown"),
            "channel": os.getenv("HA4LINUX_BUILD_CHANNEL", "stable"),
        },
    }


@app.get("/v1/sensors")
def sensors(_: None = Depends(require_auth)) -> dict[str, Any]:
    return registry.collect_sensors()


@app.get("/v1/update/status")
def update_status(_: None = Depends(require_auth)) -> dict[str, Any]:
    return update_manager.status()


@app.post("/v1/update/check")
def update_check(_: None = Depends(require_auth)) -> dict[str, Any]:
    return update_manager.check()


@app.post("/v1/update/apply")
def update_apply(
    payload: dict[str, Any] | None = None,
    _: None = Depends(require_auth),
) -> dict[str, Any]:
    requested = payload or {}
    target_version = requested.get("target_version")
    return update_manager.apply(target_version=str(target_version).strip() if target_version else None)


@app.post("/v1/update/rollback")
def update_rollback(_: None = Depends(require_auth)) -> dict[str, Any]:
    return update_manager.rollback()


@app.post("/v1/actuators/{actuator_id}/{action}")
def actuator_action(
    actuator_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
    _: None = Depends(require_auth),
) -> dict[str, Any]:
    return registry.execute_actuator(
        actuator_id=actuator_id,
        action=action,
        params=payload or {},
    )


if __name__ == "__main__":
    uvicorn_args: dict[str, Any] = {
        "app": app,
        "host": settings.bind_host,
        "port": settings.bind_port,
    }

    if settings.tls_enabled:
        uvicorn_args["ssl_certfile"] = settings.tls_certfile
        uvicorn_args["ssl_keyfile"] = settings.tls_keyfile

    uvicorn.run(**uvicorn_args)
