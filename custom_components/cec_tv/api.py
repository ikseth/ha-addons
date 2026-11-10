"""Cliente JSON-RPC minimo para Kodi y el addon script.cec.control."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import ADDON_ID

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=10)


class CecTvApiError(Exception):
    """Error generico de comunicacion con Kodi."""


class CecTvAuthError(CecTvApiError):
    """Las credenciales del servidor web de Kodi no son validas."""


class CecTvAddonError(CecTvApiError):
    """El addon no esta instalado, esta deshabilitado o es demasiado antiguo."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class KodiCecClient:
    """Habla con un Kodi por su servidor web (JSON-RPC sobre HTTP)."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int,
                 username: str, password: str) -> None:
        self._session = session
        self._url = f"http://{host}:{port}/jsonrpc"
        self._auth = aiohttp.BasicAuth(username, password) if username else None
        self._request_id = 0

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._request_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            async with self._session.post(self._url, json=payload, auth=self._auth,
                                          timeout=_TIMEOUT) as response:
                if response.status in (401, 403):
                    raise CecTvAuthError("Kodi rechazo las credenciales")
                response.raise_for_status()
                body = await response.json(content_type=None)
        except CecTvApiError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise CecTvApiError(f"{method}: {err}") from err
        if not isinstance(body, dict):
            raise CecTvApiError(f"{method}: respuesta no valida")
        if "error" in body:
            raise CecTvApiError(f"{method}: {body['error']}")
        return body.get("result")

    async def async_friendly_name(self) -> str:
        result = await self._call("XBMC.GetInfoLabels", {"labels": ["System.FriendlyName"]})
        return str((result or {}).get("System.FriendlyName") or "").strip()

    async def async_addon(self) -> dict[str, Any]:
        """Detalles del addon. Lanza CecTvAddonError si no esta instalado."""
        try:
            result = await self._call("Addons.GetAddonDetails", {
                "addonid": ADDON_ID, "properties": ["version", "enabled"]})
        except CecTvAuthError:
            raise
        except CecTvApiError as err:
            # Kodi responde "Invalid params" cuando el addon no existe.
            if "Invalid params" in str(err) or "-32602" in str(err):
                raise CecTvAddonError("addon_missing") from err
            raise
        addon = (result or {}).get("addon")
        if not isinstance(addon, dict):
            raise CecTvAddonError("addon_missing")
        return addon

    async def async_get_labels(self, labels: list[str]) -> dict[str, str]:
        result = await self._call("XBMC.GetInfoLabels", {"labels": labels})
        return result if isinstance(result, dict) else {}

    async def async_run_action(self, action: str) -> None:
        await self._call("Addons.ExecuteAddon", {"addonid": ADDON_ID, "params": {"action": action}})
