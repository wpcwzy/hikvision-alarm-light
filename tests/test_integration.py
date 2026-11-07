"""Tests for the event-driven alarm-light entity behavior."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.hikvision_alarm_light.api import AlertEvent
from custom_components.hikvision_alarm_light.const import (
    CONF_BRIGHTNESS,
    CONF_CAMERA_CHANNEL,
    CONF_CAMERA_HOST,
    CONF_CAMERA_PASSWORD,
    CONF_CAMERA_PORT,
    CONF_CAMERA_USE_SSL,
    CONF_CAMERA_USERNAME,
    CONF_CAMERA_VERIFY_SSL,
    CONF_HOLD_SECONDS,
    CONF_MAX_BOOST_SECONDS,
    CONF_NAME,
    CONF_NIGHT_END,
    CONF_NIGHT_START,
    CONF_NVR_HOST,
    CONF_NVR_PASSWORD,
    CONF_NVR_PORT,
    CONF_NVR_USE_SSL,
    CONF_NVR_USERNAME,
    CONF_NVR_VERIFY_SSL,
    CONF_TRIGGER_CHANNEL,
    DOMAIN,
)
from tests.fakes import FakeAlertReader, FakeHikvisionClient


def make_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="后院入侵补光联动",
        unique_id="SERIAL-192.0.2.2:2->SERIAL-192.0.2.10:1",
        data={
            CONF_NVR_HOST: "192.0.2.2",
            CONF_NVR_PORT: 80,
            CONF_NVR_USE_SSL: False,
            CONF_NVR_VERIFY_SSL: False,
            CONF_NVR_USERNAME: "admin",
            CONF_NVR_PASSWORD: "secret",
            CONF_TRIGGER_CHANNEL: 2,
            CONF_CAMERA_HOST: "192.0.2.10",
            CONF_CAMERA_PORT: 80,
            CONF_CAMERA_USE_SSL: False,
            CONF_CAMERA_VERIFY_SSL: False,
            CONF_CAMERA_USERNAME: "admin",
            CONF_CAMERA_PASSWORD: "secret",
            CONF_CAMERA_CHANNEL: 1,
            CONF_NAME: "后院入侵补光联动",
            CONF_NIGHT_START: "00:00",
            CONF_NIGHT_END: "23:59",
            CONF_HOLD_SECONDS: 120,
            CONF_MAX_BOOST_SECONDS: 300,
            CONF_BRIGHTNESS: 100,
        },
    )


def entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str
) -> str:
    registry = er.async_get(hass)
    found = registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
    assert found is not None
    return found


async def setup_entry(
    hass: HomeAssistant,
) -> tuple[MockConfigEntry, FakeHikvisionClient, FakeAlertReader]:
    entry = make_entry()
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.hikvision_alarm_light.HikvisionIsapiClient",
            FakeHikvisionClient,
        ),
        patch(
            "custom_components.hikvision_alarm_light.controller.AlertStreamReader",
            FakeAlertReader,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    camera = FakeHikvisionClient.for_host("192.0.2.10")
    reader = FakeAlertReader.latest()
    return entry, camera, reader


def event(state: str = "active") -> AlertEvent:
    return AlertEvent(
        event_type="fielddetection",
        event_state=state,
        channel=2,
        channel_name="后院",
        date_time=None,
        raw_xml="<EventNotificationAlert/>",
    )


async def test_alarm_boosts_light_then_restores(hass: HomeAssistant) -> None:
    entry, camera, reader = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert camera.mode == "eventIntelligence"

    boost_id = entity_id(hass, entry, "binary_sensor", "boost_active")
    stream_id = entity_id(hass, entry, "binary_sensor", "stream_connected")
    assert hass.states.get(stream_id).state == "on"
    assert hass.states.get(boost_id).state == "off"

    reader.emit_event(event("active"))
    await hass.async_block_till_done()
    assert camera.aux_on is True
    # The direct aux LIGHT command must not change the supplement mode,
    # otherwise IR behaviour could be disturbed.
    assert camera.mode == "eventIntelligence"
    assert hass.states.get(boost_id).state == "on"

    reader.emit_event(event("inactive"))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
    await hass.async_block_till_done()
    assert camera.aux_on is False
    assert camera.mode == "eventIntelligence"
    assert hass.states.get(boost_id).state == "off"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert camera.closed is True


async def test_button_and_switch(hass: HomeAssistant) -> None:
    entry, camera, reader = await setup_entry(hass)
    test_button = entity_id(hass, entry, "button", "test_boost")
    restore_button = entity_id(hass, entry, "button", "restore_light")
    automation_switch = entity_id(hass, entry, "switch", "automation_enabled")

    await hass.services.async_call(
        "button", "press", {"entity_id": test_button}, blocking=True
    )
    await hass.async_block_till_done()
    assert camera.aux_on is True
    assert camera.mode == "eventIntelligence"

    await hass.services.async_call(
        "button", "press", {"entity_id": restore_button}, blocking=True
    )
    await hass.async_block_till_done()
    assert camera.aux_on is False
    assert camera.mode == "eventIntelligence"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": automation_switch}, blocking=True
    )
    await hass.async_block_till_done()
    reader.emit_event(event("active"))
    await hass.async_block_till_done()
    assert camera.mode == "eventIntelligence"


async def test_mode_fallback_when_aux_light_is_missing(
    hass: HomeAssistant, monkeypatch
) -> None:
    """Cameras without a PTZ LIGHT output fall back to supplement mode."""
    monkeypatch.setattr(FakeHikvisionClient, "aux_supported", False)
    _entry, camera, reader = await setup_entry(hass)

    reader.emit_event(event("active"))
    await hass.async_block_till_done()
    assert camera.aux_on is False
    assert camera.mode == "colorVuWhiteLight"

    reader.emit_event(event("inactive"))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
    await hass.async_block_till_done()
    assert camera.mode == "eventIntelligence"
