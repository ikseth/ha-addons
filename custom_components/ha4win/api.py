"""HTTP client for the HA4Win v1 API."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import aiohttp


class HA4WinApiError(Exception):
    """Base exception for HA4Win API errors."""


class HA4WinAuthError(HA4WinApiError):
    """Raised when the API rejects the bearer token."""


class HA4WinForbiddenError(HA4WinApiError):
    """Raised when the client address is not allowed."""


class HA4WinNotSupportedError(HA4WinApiError):
    """Raised when an endpoint is not exposed by the host."""


class HA4WinFingerprintError(HA4WinApiError):
    """Raised for an invalid or mismatched TLS fingerprint."""


def _normalize_fingerprint(value: str) -> bytes | None:
    token = value.strip().lower().replace(":", "").replace(" ", "")
    if not token:
        return None
    if len(token) != hashlib.sha256().digest_size * 2:
        raise HA4WinFingerprintError("SHA-256 fingerprint must contain 64 hex digits")
    try:
        return bytes.fromhex(token)
    except ValueError as exc:
        raise HA4WinFingerprintError("SHA-256 fingerprint is not hexadecimal") from exc


def _format_host(host: str) -> str:
    token = host.strip()
    if ":" in token and not token.startswith("["):
        return f"[{token}]"
    return token


class HA4WinApiClient:
    """Small aiohttp client implementing the HA4Win v1 contract."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        token: str,
        use_https: bool,
        verify_ssl: bool,
        tls_fingerprint: str = "",
    ) -> None:
        scheme = "https" if use_https else "http"
        self._base = f"{scheme}://{_format_host(host)}:{port}"
        self._session = session
        self._token = token
        fingerprint = _normalize_fingerprint(tls_fingerprint)
        if fingerprint is not None and not use_https:
            raise HA4WinFingerprintError("TLS pinning requires HTTPS")
        if fingerprint is not None:
            self._ssl: bool | aiohttp.Fingerprint | None = aiohttp.Fingerprint(fingerprint)
        else:
            self._ssl = None if verify_ssl else False

    @property
    def base_url(self) -> str:
        """Return the configured API base URL."""
        return self._base

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        auth: bool = True,
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
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
            ) as response:
                if response.status == 401:
                    raise HA4WinAuthError("Unauthorized")
                if response.status == 403:
                    raise HA4WinForbiddenError("Client address is not allowed")
                if response.status == 404:
                    raise HA4WinNotSupportedError(f"Endpoint not available: {path}")
                if response.status >= 400:
                    body = await response.text()
                    raise HA4WinApiError(f"HTTP {response.status}: {body}")

                data = await response.json()
                if not isinstance(data, dict):
                    raise HA4WinApiError("Invalid API response")
                return data
        except aiohttp.ServerFingerprintMismatch as exc:
            raise HA4WinFingerprintError("TLS certificate fingerprint mismatch") from exc
        except asyncio.TimeoutError as exc:
            raise HA4WinApiError("API timeout") from exc
        except aiohttp.ClientError as exc:
            raise HA4WinApiError(f"Connection error: {exc}") from exc

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health", auth=False)

    async def version(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/version")

    async def capabilities(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/capabilities")

    async def sensors(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/sensors")

    async def update_status(self) -> dict[str, Any]:
        try:
            return await self._request("GET", "/v1/update/status")
        except HA4WinNotSupportedError as exc:
            return {
                "ok": False,
                "supported": False,
                "enabled": False,
                "update_available": False,
                "state": "unsupported",
                "error": str(exc),
            }

    async def update_check(self) -> dict[str, Any]:
        return await self._request(
            "POST", "/v1/update/check", payload={}, timeout_seconds=30
        )

    async def update_apply(self, target_version: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if target_version:
            payload["target_version"] = target_version
        return await self._request(
            "POST", "/v1/update/apply", payload=payload, timeout_seconds=300
        )

    async def update_rollback(self) -> dict[str, Any]:
        return await self._request(
            "POST", "/v1/update/rollback", payload={}, timeout_seconds=300
        )

    async def actuator_action(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/actuators/power_manager/{action}",
            payload=payload or {},
            timeout_seconds=timeout_seconds,
        )
