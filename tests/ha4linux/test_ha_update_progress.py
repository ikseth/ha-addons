"""Remote update progress across an agent restart."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha4linux import update as update_platform
from custom_components.ha4linux.api import HA4LinuxApiClient, HA4LinuxApiError
from custom_components.ha4linux.const import DOMAIN


async def test_install_progress_and_second_install(hass, aioclient_mock):
    aioclient_mock.get(update_platform.INTEGRATION_UPDATE_MANIFEST_URL, json={"version": "0.5.18"})
    started = asyncio.Event()
    proceed = asyncio.Event()
    agent = {"status": {"ok": True, "supported": True, "enabled": True, "supports_apply": True,
                        "installed_version": "0.5.17", "target_version": "0.5.18", "state": "idle"},
             "apply_calls": 0, "offline": False}

    async def capabilities(_self):
        if agent["offline"]:
            raise HA4LinuxApiError("offline")
        return {"sensors": [], "actuators": []}

    async def health(_self):
        return {"status": "ok"}

    async def version(_self):
        return {"api_version": "0.5.17", "min_integration_version": "0.3.0", "max_integration_version": "0.6.x"}

    async def sensors(_self):
        return {}

    async def update_status(_self):
        return dict(agent["status"])

    async def update_check(_self):
        started.set()
        await proceed.wait()
        return {"ok": True}

    async def update_apply(_self, target_version=None):
        agent["apply_calls"] += 1
        return {**agent["status"], "state": "restarting"}

    methods = {"health": health, "capabilities": capabilities, "version": version, "sensors": sensors,
               "update_status": update_status, "update_check": update_check, "update_apply": update_apply}
    patches = [patch.object(HA4LinuxApiClient, name, new=method) for name, method in methods.items()]
    for item in patches:
        item.start()
    try:
        entry = MockConfigEntry(domain=DOMAIN, title="HA4Linux test", unique_id="192.0.2.10:8099",
                                data={"host": "192.0.2.10", "port": 8099, "token": "t",
                                      "use_https": True, "verify_ssl": False})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entity_id = er.async_get(hass).async_get_entity_id("update", DOMAIN, f"{entry.entry_id}_api_update")
        assert entity_id
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        first = hass.async_create_task(hass.services.async_call("update", "install", {"entity_id": entity_id}, blocking=True))
        await asyncio.wait_for(started.wait(), 5)
        assert hass.states.get(entity_id).attributes["in_progress"] is True
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call("update", "install", {"entity_id": entity_id}, blocking=True)
        assert agent["apply_calls"] == 0
        proceed.set()
        await first
        agent["offline"] = True
        await coordinator.async_refresh()
        assert hass.states.get(entity_id).attributes["in_progress"] is True
        agent["offline"] = False
        agent["status"] = {**agent["status"], "installed_version": "0.5.18", "state": "idle"}
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=False)
        assert hass.states.get(entity_id).attributes["in_progress"] is False
        assert hass.states.get(entity_id).state == "off"
        assert agent["apply_calls"] == 1
    finally:
        for item in reversed(patches):
            item.stop()
