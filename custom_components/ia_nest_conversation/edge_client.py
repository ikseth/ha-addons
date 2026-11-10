"""Small, Home Assistant-independent client for IA_NEST's OpenAI-compatible edge."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import codecs
import json
import ssl
from typing import Any
from urllib.parse import urlsplit

import aiohttp


class EdgeClientError(Exception):
    """Base error returned by the edge client."""

    kind = "edge"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class EdgeHttpError(EdgeClientError):
    """The edge returned a non-success HTTP response."""

    kind = "http"

    def __init__(self, message: str, *, status: int, code: str | None = None) -> None:
        super().__init__(message, code=code)
        self.status = status


class EdgeSseError(EdgeClientError):
    """The edge emitted an error in its SSE stream."""

    kind = "sse"


class EdgeStreamIncompleteError(EdgeClientError):
    """The SSE stream ended before its required done marker."""

    kind = "stream_incomplete"


class EdgeTimeoutError(EdgeClientError):
    """The configured response deadline elapsed."""

    kind = "timeout"


class EdgeConnectionError(EdgeClientError):
    """The edge could not be reached."""

    kind = "connection"


class EdgeTlsError(EdgeClientError):
    """TLS verification or negotiation with the edge failed."""

    kind = "tls"


def _error_details(payload: Any) -> tuple[str, str | None]:
    """Extract a safe message and optional error code from an edge error body."""
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or error.get("detail") or "Edge request failed"
        code = error.get("code")
        return str(message), str(code) if code is not None else None
    if error is not None:
        return str(error), None
    return "Edge request failed", None


class EdgeClient:
    """Client with strict TLS verification and the narrow chat contract we need."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        api_key: str,
        ca_pem: str,
        menu_entry: str,
        session_header: str,
        timeout: float,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("base_url must be an HTTPS URL")
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._menu_entry = menu_entry
        self._session_header = session_header
        self._timeout = timeout
        try:
            self._ssl_context = ssl.create_default_context(cadata=ca_pem)
        except ssl.SSLError as err:
            raise EdgeTlsError("The supplied trust root is not a valid PEM certificate") from err

    @property
    def request_body_template(self) -> dict[str, Any]:
        """Return the fixed non-conversational request shape (for inspection/tests)."""
        return {"model": self._menu_entry, "stream": True}

    def _headers(self, conversation_id: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if conversation_id:
            headers[self._session_header] = conversation_id
        return headers

    def _timeout_config(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(total=self._timeout)

    async def async_models(self) -> list[str]:
        """Fetch the visible menu entries for this credential."""
        try:
            async with self._session.get(
                f"{self._base_url}/v1/models",
                headers=self._headers(),
                ssl=self._ssl_context,
                timeout=self._timeout_config(),
            ) as response:
                if not 200 <= response.status < 300:
                    raise await self._http_error(response)
                payload = await response.json(content_type=None)
        except EdgeClientError:
            raise
        except asyncio.TimeoutError as err:
            raise EdgeTimeoutError("The edge did not answer before the deadline") from err
        except (aiohttp.ClientConnectorCertificateError, aiohttp.ClientSSLError, ssl.SSLError) as err:
            raise EdgeTlsError("TLS verification with the edge failed") from err
        except aiohttp.ClientError as err:
            raise EdgeConnectionError("Could not connect to the edge") from err

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise EdgeHttpError("The edge returned an invalid models response", status=200)
        return [item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]

    async def _http_error(self, response: aiohttp.ClientResponse) -> EdgeHttpError:
        try:
            payload = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, json.JSONDecodeError):
            payload = None
        message, code = _error_details(payload)
        return EdgeHttpError(message, status=response.status, code=code)

    async def async_stream_chat(
        self, text: str, conversation_id: str | None
    ) -> AsyncGenerator[str]:
        """Stream content deltas from one user turn, and require ``[DONE]``."""
        body = {
            **self.request_body_template,
            "messages": [{"role": "user", "content": text}],
        }
        done = False
        try:
            async with self._session.post(
                f"{self._base_url}/v1/chat/completions",
                headers=self._headers(conversation_id),
                json=body,
                ssl=self._ssl_context,
                timeout=self._timeout_config(),
            ) as response:
                if not 200 <= response.status < 300:
                    raise await self._http_error(response)
                async for event in _sse_events(response.content):
                    if event == "[DONE]":
                        done = True
                        break
                    try:
                        payload = json.loads(event)
                    except json.JSONDecodeError as err:
                        raise EdgeSseError("The edge sent invalid SSE JSON") from err
                    if isinstance(payload, dict) and "error" in payload:
                        message, code = _error_details(payload)
                        raise EdgeSseError(message, code=code)
                    yield _content_delta(payload)
        except EdgeClientError:
            raise
        except asyncio.TimeoutError as err:
            raise EdgeTimeoutError("The edge did not answer before the deadline") from err
        except (aiohttp.ClientConnectorCertificateError, aiohttp.ClientSSLError, ssl.SSLError) as err:
            raise EdgeTlsError("TLS verification with the edge failed") from err
        except aiohttp.ClientError as err:
            raise EdgeConnectionError("Could not connect to the edge") from err
        if not done:
            raise EdgeStreamIncompleteError("The edge stream ended without [DONE]")


async def _sse_events(content: aiohttp.StreamReader) -> AsyncGenerator[str]:
    """Parse data-only SSE frames even when TCP reads split lines or frames."""
    buffer = ""
    data_lines: list[str] = []
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    try:
        async for chunk in content.iter_any():
            buffer += decoder.decode(chunk)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.rstrip("\r")
                if not line:
                    if data_lines:
                        yield "\n".join(data_lines)
                        data_lines = []
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
        decoder.decode(b"", final=True)
    except UnicodeDecodeError as err:
        raise EdgeSseError("The edge sent invalid UTF-8 in its SSE stream") from err


def _content_delta(payload: Any) -> str:
    """Return a content delta from the OpenAI chat-completions stream."""
    if not isinstance(payload, dict):
        raise EdgeSseError("The edge sent an invalid SSE event")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""
