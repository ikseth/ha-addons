from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class HA4LinuxApiError(Exception):
    pass


class HA4LinuxAuthError(HA4LinuxApiError):
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
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    raise HA4LinuxAuthError("Unauthorized")
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

    async def sensors(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/sensors")

    async def session_status(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/actuators/session_manager/status", payload={})

    async def session_activate(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/actuators/session_manager/activate", payload={})

    async def session_terminate(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/actuators/session_manager/terminate", payload={})
