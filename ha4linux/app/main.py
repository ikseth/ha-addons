import os
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException

from app.core.config import Settings
from app.core.registry import ModuleRegistry

settings = Settings()
registry = ModuleRegistry(settings=settings)
registry.load()

API_VERSION = "0.3.0"
API_SCHEMA_VERSION = "1.0"
API_MIN_INTEGRATION_VERSION = "0.3.0"
API_MAX_INTEGRATION_VERSION = "0.5.x"

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
