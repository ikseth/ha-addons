from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class HA4LinuxApiError(Exception):
    pass


class HA4LinuxAuthError(HA4LinuxApiError):
    pass


class HA4LinuxNotSupportedError(HA4LinuxApiError):
    pass


class HA4LinuxApiClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        token: str,
        use_https: bool,
        verify_ssl: bool,
    ) -> None:
        scheme = "https" if use_https else "http"
        self._base = f"{scheme}://{host}:{port}"
        self._session = session
        self._token = token
        self._ssl: bool | None = None if verify_ssl else False

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        auth: bool = True,
        timeout_seconds: int = 10,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            async with self._session.request(
                method,
                f"{self._base}{path}",
                headers=headers,
                json=payload,
                ssl=self._ssl,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            ) as resp:
                if resp.status == 401:
                    raise HA4LinuxAuthError("Unauthorized")
                if resp.status == 404:
                    raise HA4LinuxNotSupportedError(f"Endpoint not available: {path}")
                if resp.status >= 400:
                    text = await resp.text()
                    raise HA4LinuxApiError(f"HTTP {resp.status}: {text}")

                data = await resp.json()
                if not isinstance(data, dict):
                    raise HA4LinuxApiError("Invalid API response")
                return data
        except asyncio.TimeoutError as exc:
            raise HA4LinuxApiError("API timeout") from exc
        except aiohttp.ClientError as exc:
            raise HA4LinuxApiError(f"Connection error: {exc}") from exc

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health", auth=False)

    async def capabilities(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/capabilities")

    async def version(self) -> dict[str, Any]:
        try:
            return await self._request("GET", "/v1/version")
        except HA4LinuxApiError as exc:
            # Keep backward compatibility with older APIs that do not expose
            # /v1/version yet.
            return {
                "api_version": "unknown",
                "schema_version": "unknown",
                "min_integration_version": "0.0.0",
                "max_integration_version": "999.999.999",
                "available": False,
                "error": str(exc),
            }

    async def update_status(self) -> dict[str, Any]:
        try:
            result = await self._request("GET", "/v1/update/status")
            result.setdefault("supported", True)
            result.setdefault("enabled", False)
            result.setdefault("update_available", False)
            result.setdefault("state", "idle")
            return result
        except HA4LinuxNotSupportedError as exc:
            return {
                "ok": False,
                "supported": False,
                "enabled": False,
                "update_available": False,
                "state": "unsupported",
                "error": str(exc),
            }
        except HA4LinuxApiError as exc:
            return {
                "ok": False,
                "supported": True,
                "enabled": False,
                "update_available": False,
                "state": "error",
                "error": str(exc),
            }

    async def update_check(self) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/update/check",
            payload={},
            timeout_seconds=30,
        )

    async def update_apply(self, target_version: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if target_version:
            payload["target_version"] = target_version
        return await self._request(
            "POST",
            "/v1/update/apply",
            payload=payload,
            timeout_seconds=300,
        )

    async def update_rollback(self) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/update/rollback",
            payload={},
            timeout_seconds=300,
        )

    async def sensors(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/sensors")

    async def actuator_action(
        self,
        actuator_id: str,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/actuators/{actuator_id}/{action}",
            payload=payload or {},
            timeout_seconds=timeout_seconds,
        )

    async def session_status(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/actuators/session_manager/status", payload={})

    async def session_activate(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/actuators/session_manager/activate", payload={})

    async def session_terminate(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/actuators/session_manager/terminate", payload={})

    async def app_policy_status(self, app_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if app_id:
            payload["app_id"] = app_id
        return await self._request("POST", "/v1/actuators/app_policy/status", payload=payload)

    async def app_policy_allow(self, app_id: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/actuators/app_policy/allow",
            payload={"app_id": app_id},
        )

    async def app_policy_block(self, app_id: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/actuators/app_policy/block",
            payload={"app_id": app_id},
        )

    async def virtualbox_action(
        self,
        action: str,
        *,
        vm_uuid: str | None = None,
        vm_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if vm_uuid:
            payload["vm_uuid"] = vm_uuid
        if vm_name:
            payload["vm_name"] = vm_name
        return await self.actuator_action(
            "virtualbox_manager",
            action,
            payload=payload,
            timeout_seconds=60,
        )

    async def virtualbox_status(
        self,
        *,
        vm_uuid: str | None = None,
        vm_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if vm_uuid:
            payload["vm_uuid"] = vm_uuid
        if vm_name:
            payload["vm_name"] = vm_name
        return await self.actuator_action(
            "virtualbox_manager",
            "status",
            payload=payload,
            timeout_seconds=60,
        )
