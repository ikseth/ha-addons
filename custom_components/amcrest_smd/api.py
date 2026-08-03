"""Cliente HTTP para el CGI de camaras Amcrest/Dahua.

Implementa autenticacion Digest sin dependencias externas y la lectura del
stream de eventos (`eventManager.cgi?action=attach`), que es una unica conexion
HTTP persistente por la que la camara empuja los eventos segun ocurren.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Tope de seguridad del buffer del parser, por si la camara enviara datos
# malformados y nunca se completara un bloque.
_MAX_BUFFER = 1 << 20


class AmcrestSmdApiError(Exception):
    """Error generico de comunicacion con la camara."""


class AmcrestSmdAuthError(AmcrestSmdApiError):
    """Las credenciales no son validas."""


def _parse_challenge(header: str) -> dict[str, str]:
    """Extrae los parametros de una cabecera WWW-Authenticate Digest."""
    values: dict[str, str] = {}
    for key, quoted, bare in re.findall(
        r'(\w+)=(?:"([^"]*)"|([^,\s]+))', header
    ):
        values[key.lower()] = quoted or bare
    return values


def _digest_header(
    challenge: dict[str, str],
    username: str,
    password: str,
    method: str,
    uri: str,
    nonce_count: int,
) -> str:
    """Construye la cabecera Authorization para Digest (MD5, qop=auth)."""
    realm = challenge.get("realm", "")
    nonce = challenge.get("nonce", "")
    qop = challenge.get("qop")
    opaque = challenge.get("opaque")

    ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()

    parts = [
        f'username="{username}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{uri}"',
    ]

    if qop:
        # qop exige contador y cnonce; la camara anuncia qop="auth".
        cnonce = os.urandom(8).hex()
        nc = f"{nonce_count:08x}"
        response = hashlib.md5(
            f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}".encode()
        ).hexdigest()
        parts += [f'response="{response}"', "qop=auth", f"nc={nc}", f'cnonce="{cnonce}"']
    else:
        response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        parts.append(f'response="{response}"')

    if opaque:
        parts.append(f'opaque="{opaque}"')

    return "Digest " + ", ".join(parts)


class MultipartEventParser:
    """Parser incremental del stream `multipart/x-mixed-replace` de la camara.

    Cada bloque llega como cabeceras + linea en blanco + cuerpo de exactamente
    `Content-Length` bytes. Usamos la longitud declarada en vez de buscar el
    separador porque el cuerpo de un evento incluye JSON con saltos de linea.
    """

    def __init__(self) -> None:
        self._buffer = b""

    def feed(self, chunk: bytes) -> list[str]:
        """Incorpora datos y devuelve los cuerpos completos disponibles."""
        self._buffer += chunk
        if len(self._buffer) > _MAX_BUFFER:
            _LOGGER.warning("Buffer del stream desbordado; se descarta y resincroniza")
            self._buffer = b""
            return []

        payloads: list[str] = []
        while True:
            separator = self._buffer.find(b"\r\n\r\n")
            if separator == -1:
                break

            head = self._buffer[:separator].decode("ascii", "replace")
            match = re.search(r"Content-Length:\s*(\d+)", head, re.IGNORECASE)
            if match is None:
                # Bloque sin longitud declarada: lo saltamos y seguimos.
                self._buffer = self._buffer[separator + 4 :]
                continue

            length = int(match.group(1))
            start = separator + 4
            if len(self._buffer) < start + length:
                # Cuerpo incompleto: esperamos a la siguiente lectura.
                break

            payloads.append(
                self._buffer[start : start + length].decode("utf-8", "replace")
            )
            self._buffer = self._buffer[start + length :]

        return payloads


def parse_event(payload: str) -> tuple[str, str] | None:
    """Devuelve (codigo, accion) de un cuerpo de evento, o None si no lo es.

    Los heartbeats llegan como el literal `Heartbeat` y no son eventos.
    """
    match = re.match(r"Code=(\w+);action=(\w+)", payload.strip())
    if match is None:
        return None
    return match.group(1), match.group(2)


class AmcrestSmdClient:
    """Acceso al CGI de la camara: sondeo puntual y stream de eventos."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._nonce_count = 0

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def _authorized_request(
        self, path: str, timeout: aiohttp.ClientTimeout
    ) -> aiohttp.ClientResponse:
        """Hace una peticion resolviendo el reto Digest de la camara.

        La camara responde 401 con el reto; se recalcula la cabecera y se
        reintenta. El llamante es responsable de cerrar la respuesta.
        """
        url = f"{self.base_url}{path}"
        uri = urlparse(url).path
        if urlparse(url).query:
            uri = f"{uri}?{urlparse(url).query}"

        response = await self._session.get(url, timeout=timeout)
        if response.status != 401:
            return response

        challenge_header = response.headers.get("WWW-Authenticate", "")
        response.release()

        if "digest" not in challenge_header.lower():
            raise AmcrestSmdAuthError("La camara no ofrecio autenticacion Digest")

        self._nonce_count += 1
        header = _digest_header(
            _parse_challenge(challenge_header),
            self._username,
            self._password,
            "GET",
            uri,
            self._nonce_count,
        )
        response = await self._session.get(
            url, headers={"Authorization": header}, timeout=timeout
        )
        if response.status == 401:
            response.release()
            raise AmcrestSmdAuthError("Credenciales rechazadas por la camara")
        return response

    async def _get_text(self, path: str, timeout_seconds: float = 15.0) -> str:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        try:
            response = await self._authorized_request(path, timeout)
        except AmcrestSmdApiError:
            raise
        except Exception as err:  # noqa: BLE001 - se normaliza a error propio
            raise AmcrestSmdApiError(f"Fallo de conexion: {err}") from err

        async with response:
            if response.status != 200:
                raise AmcrestSmdApiError(f"HTTP {response.status} en {path}")
            return await response.text()

    async def async_device_info(self) -> dict[str, Any]:
        """Datos de identificacion de la camara.

        La MAC se obtiene en modo best-effort: leerla requiere permiso de red y
        solo sirve para engancharse al dispositivo que ya creo ONVIF. Si no se
        puede leer, la integracion sigue funcionando con su propio dispositivo.
        """
        raw = await self._get_text("/cgi-bin/magicBox.cgi?action=getSystemInfo")
        info: dict[str, Any] = {}
        for line in raw.splitlines():
            key, _, value = line.partition("=")
            if key:
                info[key.strip()] = value.strip()

        result = {
            "serial_number": info.get("serialNumber", ""),
            "device_type": info.get("deviceType", ""),
            "mac": None,
        }

        try:
            network = await self._get_text(
                "/cgi-bin/configManager.cgi?action=getConfig&name=Network"
            )
        except AmcrestSmdApiError as err:
            _LOGGER.debug("No se pudo leer la MAC de la camara: %s", err)
            return result

        mac = re.search(
            r"eth0\.PhysicalAddress=([0-9a-fA-F:]+)", network
        )
        if mac:
            result["mac"] = mac.group(1).lower()
        return result

    async def async_event_active(self, code: str) -> bool:
        """Consulta puntual de si un evento esta activo ahora mismo.

        Se usa una unica vez al conectar, para inicializar el estado sin quedar
        a ciegas hasta el siguiente evento. No es un sondeo periodico.
        """
        raw = await self._get_text(
            f"/cgi-bin/eventManager.cgi?action=getEventIndexes&code={code}"
        )
        # Con evento activo la camara responde `channels[0]=0`; si no, `Error`.
        return "channels[" in raw

    async def async_stream_events(
        self, heartbeat: int
    ) -> AsyncIterator[tuple[str, str]]:
        """Itera los eventos que la camara empuja por la conexion persistente.

        `heartbeat` hace que la camara emita un keepalive periodico, lo que
        permite distinguir "no pasa nada" de "la conexion esta muerta".
        """
        path = (
            "/cgi-bin/eventManager.cgi?action=attach"
            "&codes=%5BSmartMotionHuman%2CSmartMotionVehicle%5D"
            f"&heartbeat={heartbeat}"
        )
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=15,
            sock_read=heartbeat * 3,
        )

        try:
            response = await self._authorized_request(path, timeout)
        except AmcrestSmdApiError:
            raise
        except Exception as err:  # noqa: BLE001 - se normaliza a error propio
            raise AmcrestSmdApiError(f"No se pudo abrir el stream: {err}") from err

        async with response:
            if response.status != 200:
                raise AmcrestSmdApiError(
                    f"HTTP {response.status} al abrir el stream de eventos"
                )

            parser = MultipartEventParser()
            try:
                async for chunk in response.content.iter_any():
                    for payload in parser.feed(chunk):
                        event = parse_event(payload)
                        if event is not None:
                            yield event
            except (aiohttp.ClientError, TimeoutError, ConnectionError) as err:
                # Corte esperable: la camara se reinicio, hubo un corte de red o
                # dejaron de llegar heartbeats. No es un fallo del programa.
                raise AmcrestSmdApiError(
                    f"Stream interrumpido: {type(err).__name__}: {err}"
                ) from err
