"""Tests for the standalone IA_NEST edge client; Home Assistant is not imported."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import subprocess
import sys
import socket
from contextlib import asynccontextmanager
from functools import wraps
import tempfile
from types import ModuleType

import aiohttp
from aiohttp import web
import pytest


_COMPONENT_PATH = Path(__file__).parents[2] / "custom_components" / "ia_nest_conversation"
_PACKAGE_NAME = "ia_nest_conversation_test"
_PACKAGE = ModuleType(_PACKAGE_NAME)
_PACKAGE.__path__ = [str(_COMPONENT_PATH)]
sys.modules[_PACKAGE_NAME] = _PACKAGE


def _load_component_module(name: str):
    """Load a module without importing the component's HA-dependent package init."""
    spec = importlib.util.spec_from_file_location(
        f"{_PACKAGE_NAME}.{name}", _COMPONENT_PATH / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


edge_client = _load_component_module("edge_client")
stream = _load_component_module("stream")


def _certificate(directory: Path, name: str, loopback: str) -> tuple[Path, Path]:
    """Generate a short-lived self-signed certificate for this isolated test."""
    certificate = directory / f"{name}.pem"
    key = directory / f"{name}.key"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt",
            "ec_paramgen_curve:prime256v1", "-nodes",
            "-keyout", str(key), "-out", str(certificate), "-days", "1",
            "-subj", "/CN=test", "-addext", f"subjectAltName=IP:{loopback}",
        ],
        check=True,
        capture_output=True,
    )
    return certificate, key


@asynccontextmanager
async def https_server():
    """Start a local HTTPS app and return its base URL plus captured requests."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        loopback = socket.inet_ntoa(bytes((127, 0, 0, 1)))
        cert, key = _certificate(tmp_path, "server", loopback)
        received: list[dict[str, object]] = []
        state: dict[str, object] = {"parts": [b"data: [DONE]\n\n"], "models_error": None, "delay": 0}

        async def models(request: web.Request) -> web.Response:
            received.append({"headers": dict(request.headers)})
            if error := state["models_error"]:
                return web.json_response({"error": error}, status=401)
            return web.json_response({"data": [{"id": "casa"}]})

        async def chat(request: web.Request) -> web.StreamResponse:
            received.append({"headers": dict(request.headers), "body": await request.json()})
            if delay := state["delay"]:
                await asyncio.sleep(delay)
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            for part in state["parts"]:
                await response.write(part)
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_get("/v1/models", models)
        app.router.add_post("/v1/chat/completions", chat)
        runner = web.AppRunner(app)
        await runner.setup()
        ssl_context = __import__("ssl").SSLContext(__import__("ssl").PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(cert, key)
        site = web.TCPSite(runner, loopback, 0, ssl_context=ssl_context)
        await site.start()
        sockets = site._server.sockets
        port = sockets[0].getsockname()[1]
        try:
            yield f"https://{loopback}:{port}", cert.read_text(), state, received, tmp_path
        finally:
            await runner.cleanup()


def async_test(function):
    """Run async test functions without depending on pytest-asyncio."""
    @wraps(function)
    def wrapper():
        return asyncio.run(function())
    return wrapper


async def _client(base_url: str, ca_pem: str, *, timeout: float = 2):
    session = aiohttp.ClientSession()
    client = edge_client.EdgeClient(
        session, base_url, "test-token", ca_pem, "casa", "X-Session", timeout
    )
    return client, session


@async_test
async def test_models_and_split_sse_send_only_one_user_message():
    async with https_server() as (base_url, ca_pem, state, received, _):
        state["parts"] = [
            b'data: {"choices":[{"delta":{"content":"Ho',
            b'la"}}]}\n\ndata: {"choices":[{"delta":{"content":"!"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]
        client, session = await _client(base_url, ca_pem)
        try:
            assert await client.async_models() == ["casa"]
            assert [part async for part in client.async_stream_chat("saludo", "turno-1")] == ["Hola", "!"]
        finally:
            await session.close()

        request = received[-1]
        headers = request["headers"]
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["X-Session"] == "turno-1"
        body = request["body"]
        assert body == {
            "model": "casa",
            "stream": True,
            "messages": [{"role": "user", "content": "saludo"}],
        }
        assert "system" not in body and "tools" not in body


@async_test
async def test_split_utf8_character_is_reassembled_before_sse_parsing():
    async with https_server() as (base_url, ca_pem, state, _, _):
        state["parts"] = [
            b'data: {"choices":[{"delta":{"content":"canci\xc3',
            b'\xb3n"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]
        client, session = await _client(base_url, ca_pem)
        try:
            assert [part async for part in client.async_stream_chat("x", None)] == ["canción"]
        finally:
            await session.close()


@async_test
async def test_invalid_utf8_is_translated_to_sse_error():
    async with https_server() as (base_url, ca_pem, state, _, _):
        state["parts"] = [b"data: \xff\n\n"]
        client, session = await _client(base_url, ca_pem)
        try:
            with pytest.raises(edge_client.EdgeSseError, match="invalid UTF-8"):
                await anext(client.async_stream_chat("x", None))
        finally:
            await session.close()


async def _deltas(*parts: str):
    for part in parts:
        yield part


async def _failed_deltas():
    raise edge_client.EdgeSseError("unavailable")
    yield ""  # pragma: no cover - makes this an async generator for type checkers


@async_test
async def test_stream_mapping_starts_with_assistant_role_and_maps_failures():
    assert [delta async for delta in stream.map_edge_turn(_deltas("Hola"), "es-ES")] == [
        {"role": "assistant"},
        {"content": "Hola"},
    ]
    assert [delta async for delta in stream.map_edge_turn(_failed_deltas(), "es-MX")] == [
        {"role": "assistant"},
        {"content": "No he podido contestar ahora. Intentalo de nuevo."},
    ]

    async def partial_then_failure():
        yield "Partial"
        raise edge_client.EdgeSseError("unavailable")

    assert [delta async for delta in stream.map_edge_turn(partial_then_failure(), "en-US")] == [
        {"role": "assistant"},
        {"content": "Partial"},
        {"content": " I couldn't answer right now. Please try again."},
    ]


@async_test
async def test_http_error_exposes_code():
    async with https_server() as (base_url, ca_pem, state, _, _):
        state["models_error"] = {"message": "denied", "code": "bad_key"}
        client, session = await _client(base_url, ca_pem)
        try:
            with pytest.raises(edge_client.EdgeHttpError, match="denied") as error:
                await client.async_models()
            assert error.value.status == 401
            assert error.value.code == "bad_key"
        finally:
            await session.close()


@async_test
async def test_sse_error_and_missing_done():
    async with https_server() as (base_url, ca_pem, state, _, _):
        client, session = await _client(base_url, ca_pem)
        try:
            state["parts"] = [b'data: {"error":{"message":"overloaded","code":"busy"}}\n\n']
            with pytest.raises(edge_client.EdgeSseError, match="overloaded") as error:
                await anext(client.async_stream_chat("x", None))
            assert error.value.code == "busy"

            state["parts"] = [b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n']
            with pytest.raises(edge_client.EdgeStreamIncompleteError):
                assert [part async for part in client.async_stream_chat("x", None)] == ["partial"]
        finally:
            await session.close()


@async_test
async def test_tls_wrong_root_connection_and_timeout():
    async with https_server() as (base_url, ca_pem, state, _, tmp_path):
        loopback = socket.inet_ntoa(bytes((127, 0, 0, 1)))
        other_cert, _ = _certificate(tmp_path, "other", loopback)
        client, session = await _client(base_url, other_cert.read_text())
        try:
            with pytest.raises(edge_client.EdgeTlsError):
                await client.async_models()
        finally:
            await session.close()

        client, session = await _client(f"https://{loopback}:1", ca_pem)
        try:
            with pytest.raises(edge_client.EdgeConnectionError):
                await client.async_models()
        finally:
            await session.close()

        state["delay"] = 0.1
        client, session = await _client(base_url, ca_pem, timeout=0.01)
        try:
            with pytest.raises(edge_client.EdgeTimeoutError):
                await anext(client.async_stream_chat("x", None))
        finally:
            await session.close()
