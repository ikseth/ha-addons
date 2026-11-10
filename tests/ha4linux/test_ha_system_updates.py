"""Pruebas con Home Assistant: opcion de notificacion, entidades de actualizaciones y update de la integracion."""
from __future__ import annotations

import json
from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp import ClientSession, ContentTypeError, web
from aiohttp.test_utils import TestServer
from homeassistant.components.persistent_notification import _async_get_or_create_notifications
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha4linux.api import HA4LinuxApiClient
from custom_components.ha4linux.const import CONF_NOTIFY_SYSTEM_UPDATES, DOMAIN, INTEGRATION_VERSION
from custom_components.ha4linux import update as update_platform

HOST_A = "192.0.2.10"
HOST_B = "192.0.2.11"
MANIFEST_URL = update_platform.INTEGRATION_UPDATE_MANIFEST_URL


def _payload(count: int, state: str = "idle") -> dict[str, Any]:
    return {
        "updates_enabled": True,
        "updates_supported": True,
        "updates_state": state,
        "updates_pending_count": count,
        "updates_packages": [{"name": f"pkg{i}", "raw": f"pkg{i}"} for i in range(count)],
        "updates_packages_total": count,
        "updates_packages_truncated": False,
        "updates_last_checked_at": "2026-10-23T10:00:00+00:00",
        "distribution": "Debian",
        "package_manager": "apt",
    }


class FakeHosts:
    """Respuestas del agente por host; se pueden cambiar durante la prueba."""

    def __init__(self) -> None:
        self.system_info: dict[str, dict[str, Any]] = {HOST_A: _payload(3), HOST_B: _payload(0)}

    def _host(self, client: HA4LinuxApiClient) -> str:
        return client._base.split("://", 1)[1].rsplit(":", 1)[0]

    def patches(self) -> list:
        fake = self

        async def health(client):
            return {"status": "ok"}

        async def capabilities(client):
            return {"sensors": ["system_info"], "actuators": []}

        async def version(client):
            return {"api_version": "0.5.15", "min_integration_version": "0.3.0", "max_integration_version": "0.6.x"}

        async def sensors(client):
            return {"system_info": {"available": True, "data": fake.system_info[fake._host(client)]}}

        async def update_status(client):
            return {"supported": False}

        return [
            patch.object(HA4LinuxApiClient, name, new=func)
            for name, func in {
                "health": health,
                "capabilities": capabilities,
                "version": version,
                "sensors": sensors,
                "update_status": update_status,
            }.items()
        ]


@pytest.fixture
def fake_hosts():
    hosts = FakeHosts()
    with ExitStack() as stack:
        for item in hosts.patches():
            stack.enter_context(item)
        yield hosts


@pytest.fixture(autouse=True)
def manifest(aioclient_mock):
    aioclient_mock.get(
        MANIFEST_URL,
        text=json.dumps({"version": "9.9.9", "notes": "test"}),
        headers={"content-type": "text/plain; charset=utf-8"},
    )


def _entry(host: str, **options: Any) -> MockConfigEntry:
    data = {"host": host, "port": 8099, "token": "t", "use_https": True, "verify_ssl": False}
    return MockConfigEntry(domain=DOMAIN, title=f"HA4Linux {host}", data=data, options=options, unique_id=f"{host}:8099")


async def _setup(hass: HomeAssistant, *entries: MockConfigEntry) -> None:
    for entry in entries:
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _notification_id(entry: MockConfigEntry) -> str:
    return f"{DOMAIN}_system_updates_{entry.entry_id}"


def _notifications(hass: HomeAssistant) -> dict:
    return _async_get_or_create_notifications(hass)


def _entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None, unique_id
    return entity_id


async def _set_notify_option(hass: HomeAssistant, entry: MockConfigEntry, enabled: bool) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    user_input = {key.schema: key.default() for key in result["data_schema"].schema}
    user_input[CONF_NOTIFY_SYSTEM_UPDATES] = enabled
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input=user_input)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def test_notificacion_activada_por_defecto(hass, fake_hosts):
    entry_a, entry_b = _entry(HOST_A), _entry(HOST_B)
    await _setup(hass, entry_a, entry_b)

    notifications = _notifications(hass)
    assert _notification_id(entry_a) in notifications
    assert "Pending updates: `3`" in notifications[_notification_id(entry_a)]["message"]
    assert _notification_id(entry_b) not in notifications


async def test_opcion_desactivada_no_crea_notificacion(hass, fake_hosts):
    entry = _entry(HOST_A, **{CONF_NOTIFY_SYSTEM_UPDATES: False})
    await _setup(hass, entry)

    assert _notification_id(entry) not in _notifications(hass)


async def test_opciones_muestran_la_opcion_activada_por_defecto(hass, fake_hosts):
    entry = _entry(HOST_A)
    await _setup(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    defaults = {key.schema: key.default() for key in result["data_schema"].schema}
    assert defaults[CONF_NOTIFY_SYSTEM_UPDATES] is True


async def test_cambio_en_caliente_descarta_y_restaura_la_notificacion(hass, fake_hosts):
    entry = _entry(HOST_A)
    await _setup(hass, entry)
    assert _notification_id(entry) in _notifications(hass)

    await _set_notify_option(hass, entry, False)
    assert entry.state is ConfigEntryState.LOADED
    assert _notification_id(entry) not in _notifications(hass)

    # Nuevos datos del agente con la opcion desactivada: sigue sin notificacion.
    fake_hosts.system_info[HOST_A] = _payload(5)
    await hass.data[DOMAIN][entry.entry_id]["coordinator"].async_refresh()
    await hass.async_block_till_done()
    assert _notification_id(entry) not in _notifications(hass)

    await _set_notify_option(hass, entry, True)
    assert "Pending updates: `5`" in _notifications(hass)[_notification_id(entry)]["message"]


async def test_binary_sensor_por_equipo(hass, fake_hosts):
    entry_a, entry_b = _entry(HOST_A), _entry(HOST_B)
    await _setup(hass, entry_a, entry_b)

    state_a = hass.states.get(_entity_id(hass, "binary_sensor", f"{entry_a.entry_id}_system_updates_available"))
    assert state_a.state == STATE_ON
    assert state_a.attributes["device_class"] == "update"
    assert state_a.attributes["pending_count"] == 3
    assert state_a.attributes["packages"] == ["pkg0", "pkg1", "pkg2"]

    state_b = hass.states.get(_entity_id(hass, "binary_sensor", f"{entry_b.entry_id}_system_updates_available"))
    assert state_b.state == STATE_OFF

    fake_hosts.system_info[HOST_B] = _payload(0, state="checking")
    await hass.data[DOMAIN][entry_b.entry_id]["coordinator"].async_refresh()
    await hass.async_block_till_done()
    state_b = hass.states.get(state_b.entity_id)
    assert state_b.state == STATE_UNAVAILABLE


async def test_resumen_global(hass, fake_hosts):
    entry_a, entry_b = _entry(HOST_A), _entry(HOST_B)
    await _setup(hass, entry_a, entry_b)

    hosts_id = _entity_id(hass, "sensor", f"{DOMAIN}_system_updates_hosts_with_updates")
    total_id = _entity_id(hass, "sensor", f"{DOMAIN}_system_updates_pending_total")
    assert hass.states.get(hosts_id).state == "1"
    assert hass.states.get(total_id).state == "3"
    assert hass.states.get(total_id).attributes["state_class"] == "measurement"
    assert hass.states.get(hosts_id).attributes["hosts"] == {HOST_A: 3}

    fake_hosts.system_info[HOST_B] = _payload(4)
    await hass.data[DOMAIN][entry_b.entry_id]["coordinator"].async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(hosts_id).state == "2"
    assert hass.states.get(total_id).state == "7"

    # Se descarga un equipo: el resumen deja de contarlo.
    assert await hass.config_entries.async_unload(entry_b.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(total_id).state == "3"


async def test_resumen_cambia_de_propietario_al_borrar_la_entrada(hass, fake_hosts):
    entry_a, entry_b = _entry(HOST_A), _entry(HOST_B)
    await _setup(hass, entry_a, entry_b)
    owner = er.async_get(hass).async_get(
        _entity_id(hass, "sensor", f"{DOMAIN}_system_updates_pending_total")
    ).config_entry_id
    other = entry_b if owner == entry_a.entry_id else entry_a

    assert await hass.config_entries.async_remove(owner)
    await hass.async_block_till_done()

    registry_entry = er.async_get(hass).async_get(
        _entity_id(hass, "sensor", f"{DOMAIN}_system_updates_pending_total")
    )
    assert registry_entry.config_entry_id == other.entry_id
    assert hass.states.get(registry_entry.entity_id).state not in (STATE_UNAVAILABLE, None)


async def test_update_de_integracion_disponible_con_manifiesto_text_plain(hass, fake_hosts):
    entry = _entry(HOST_A)
    await _setup(hass, entry)

    state = hass.states.get(_entity_id(hass, "update", "ha4linux_integration_update"))
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == INTEGRATION_VERSION
    assert state.attributes["latest_version"] == "9.9.9"


async def test_update_de_integracion_lee_json_servido_como_text_plain(hass, socket_enabled):
    """Regresion: aiohttp real rechaza .json() con text/plain si no se desactiva la comprobacion."""

    async def handler(request):
        return web.Response(text=json.dumps({"version": "9.9.9"}), content_type="text/plain")

    app = web.Application()
    app.router.add_get("/update-manifest.json", handler)
    server = TestServer(app)
    await server.start_server()
    url = str(server.make_url("/update-manifest.json"))
    try:
        async with ClientSession() as session:
            # Causa del fallo original: .json() por defecto exige application/json.
            async with session.get(url) as response:
                with pytest.raises(ContentTypeError):
                    await response.json()

            entity = update_platform.HA4LinuxIntegrationUpdateEntity(hass)
            entity._session = session
            with patch.object(update_platform, "INTEGRATION_UPDATE_MANIFEST_URL", url):
                await entity.async_update()
        assert entity.available
        assert entity.latest_version == "9.9.9"
        assert entity.extra_state_attributes["error"] is None
    finally:
        await server.close()


async def test_update_de_integracion_conserva_el_ultimo_dato_si_falla(hass, aioclient_mock):
    entity = update_platform.HA4LinuxIntegrationUpdateEntity(hass)
    await entity.async_update()
    assert entity.latest_version == "9.9.9"

    aioclient_mock.clear_requests()
    aioclient_mock.get(MANIFEST_URL, status=500)
    await entity.async_update()
    assert entity.available
    assert entity.latest_version == "9.9.9"
    assert entity.extra_state_attributes["error"]
