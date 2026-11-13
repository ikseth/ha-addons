"""Compatibilidad y alta dinamica de entidades de unidades systemd."""
from __future__ import annotations

from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha4linux.api import HA4LinuxApiClient
from custom_components.ha4linux.const import DOMAIN


class FakeAgent:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items

    def patches(self):
        async def health(client):
            return {"status": "ok"}

        async def capabilities(client):
            return {"sensors": ["services"], "actuators": []}

        async def version(client):
            return {"api_version": "0.5.15", "min_integration_version": "0.3.0", "max_integration_version": "0.6.x"}

        async def sensors(client):
            return {"services": {"available": True, "data": {"services": self.items}}}

        async def update_status(client):
            return {"supported": False}

        return [patch.object(HA4LinuxApiClient, name, new=func) for name, func in {
            "health": health, "capabilities": capabilities, "version": version,
            "sensors": sensors, "update_status": update_status,
        }.items()]


def _item(name: str, unit_type: str | None = None, **extra):
    item = {"name": name, "load_state": "loaded", "active_state": "inactive",
            "sub_state": "dead", "is_active": False, "is_failed": False, "status": "inactive"}
    if unit_type:
        item.update({"unit_type": unit_type, "result": "success", "last_exit_status": 0,
                     "last_run_start": None, "last_run_end": None, "last_trigger": None, "next_trigger": None})
    item.update(extra)
    return item


async def test_old_to_new_payload_and_timestamp_entities(hass, aioclient_mock):
    from custom_components.ha4linux import update as update_platform

    aioclient_mock.get(update_platform.INTEGRATION_UPDATE_MANIFEST_URL,
                       json={"version": "0.5.17"})
    agent = FakeAgent([_item("backup.timer")])
    entry = MockConfigEntry(domain=DOMAIN, title="HA4Linux test", unique_id="192.0.2.10:8099",
                            data={"host": "192.0.2.10", "port": 8099, "token": "t",
                                  "use_https": True, "verify_ssl": False})
    with ExitStack() as stack:
        for item in agent.patches():
            stack.enter_context(item)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        old_id = f"{entry.entry_id}_service_backup_timer"
        state_id = registry.async_get_entity_id("sensor", DOMAIN, old_id)
        assert state_id is not None
        assert "unit_type" not in hass.states.get(state_id).attributes
        last_id = f"{old_id}_last_run"
        assert registry.async_get_entity_id("sensor", DOMAIN, last_id) is None

        agent.items = [_item("backup.timer", "timer", last_trigger="2026-11-13T07:21:48+00:00")]
        await hass.data[DOMAIN][entry.entry_id]["coordinator"].async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(state_id).attributes["last_trigger"] == "2026-11-13T07:21:48+00:00"
        record = registry.async_get(registry.async_get_entity_id("sensor", DOMAIN, last_id))
        assert record.disabled_by is not None
        registry.async_update_entity(record.entity_id, disabled_by=None)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        state = hass.states.get(record.entity_id)
        assert state.state == "2026-11-13T07:21:48+00:00"
        assert state.attributes["device_class"] == "timestamp"
        assert "result" not in state.attributes

        agent.items = [
            _item("backup.service", "service", last_run_start="2026-11-13T07:21:48+00:00"),
            _item("backup.socket", "socket"),
        ]
        await hass.data[DOMAIN][entry.entry_id]["coordinator"].async_refresh()
        await hass.async_block_till_done()
        service_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_service_backup_service_last_run")
        assert registry.async_get(service_id).disabled_by is not None
        assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_service_backup_socket_last_run") is None
        registry.async_update_entity(service_id, disabled_by=None)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get(service_id).state == "2026-11-13T07:21:48+00:00"
        assert hass.states.get(service_id).attributes["result"] == "success"
        agent.items = [_item("backup.service", "service", last_run_start="2026-11-13T07:21:48+00:00",
                             last_run_end="2026-11-13T07:22:00+00:00")]
        await hass.data[DOMAIN][entry.entry_id]["coordinator"].async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(service_id).state == "2026-11-13T07:22:00+00:00"
