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

from custom_components.hikvision_alarm_light.api import AlertEvent, HikvisionError
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
    CONF_TRIGGER_CHANNELS,
    CONF_WHITE_HOLD_SECONDS,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
)
from tests.fakes import FakeAlertReader, FakeHikvisionClient


def make_data(
    *,
    night_start: str = "00:00",
    night_end: str = "23:59",
) -> dict:
    return {
        CONF_NVR_HOST: "192.0.2.2",
        CONF_NVR_PORT: 80,
        CONF_NVR_USE_SSL: False,
        CONF_NVR_VERIFY_SSL: False,
        CONF_NVR_USERNAME: "admin",
        CONF_NVR_PASSWORD: "secret",
        CONF_TRIGGER_CHANNELS: [2, 6],
        CONF_CAMERA_HOST: "192.0.2.10",
        CONF_CAMERA_PORT: 80,
        CONF_CAMERA_USE_SSL: False,
        CONF_CAMERA_VERIFY_SSL: False,
        CONF_CAMERA_USERNAME: "admin",
        CONF_CAMERA_PASSWORD: "secret",
        CONF_CAMERA_CHANNEL: 1,
        CONF_NAME: "后院入侵补光联动",
        CONF_NIGHT_START: night_start,
        CONF_NIGHT_END: night_end,
        CONF_HOLD_SECONDS: 120,
        CONF_MAX_BOOST_SECONDS: 300,
        CONF_BRIGHTNESS: 100,
        CONF_WHITE_HOLD_SECONDS: 0,
    }


def make_entry(
    *,
    version: int = CONFIG_ENTRY_VERSION,
    data: dict | None = None,
    unique_id: str = "SERIAL-192.0.2.2:2+6->SERIAL-192.0.2.10:1",
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="后院入侵补光联动",
        unique_id=unique_id,
        version=version,
        data=make_data() if data is None else data,
    )


def entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str
) -> str:
    registry = er.async_get(hass)
    found = registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
    assert found is not None
    return found


async def setup_entry(
    hass: HomeAssistant, entry: MockConfigEntry | None = None
) -> tuple[MockConfigEntry, FakeHikvisionClient, FakeAlertReader]:
    entry = entry or make_entry()
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


def event(channel: int = 2, state: str = "active") -> AlertEvent:
    return AlertEvent(
        event_type="fielddetection",
        event_state=state,
        channel=channel,
        channel_name="后院",
        date_time=None,
        raw_xml="<EventNotificationAlert/>",
    )


async def test_alarm_on_either_channel_boosts_light(hass: HomeAssistant) -> None:
    entry, camera, reader = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert camera.mode == "eventIntelligence"

    boost_id = entity_id(hass, entry, "binary_sensor", "boost_active")
    stream_id = entity_id(hass, entry, "binary_sensor", "stream_connected")
    assert hass.states.get(stream_id).state == "on"
    assert hass.states.get(boost_id).state == "off"

    # Channel 2 (fixed back-yard camera) triggers the light.
    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.aux_on is True
    # The direct aux LIGHT command must not change the supplement mode,
    # otherwise the B/W (IR) picture could be disturbed.
    assert camera.mode == "eventIntelligence"
    assert camera.supplement_history == []
    assert hass.states.get(boost_id).state == "on"

    reader.emit_event(event(2, "inactive"))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
    await hass.async_block_till_done()
    assert camera.aux_on is False
    assert camera.mode == "eventIntelligence"
    # After the light goes off: IR supplement light first, smart mode second.
    assert camera.supplement_history == ["colorVuWhiteLight", "eventIntelligence"]
    assert hass.states.get(boost_id).state == "off"

    # Channel 6 (the PTZ camera itself) triggers the same light.
    reader.emit_event(event(6, "active"))
    await hass.async_block_till_done()
    assert camera.aux_on is True
    assert hass.states.get(boost_id).state == "on"

    # An unrelated channel must be ignored.
    reader.emit_event(event(3, "active"))
    await hass.async_block_till_done()
    assert camera.aux_on is True

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert camera.closed is True


async def test_restore_switches_white_then_smart(hass: HomeAssistant) -> None:
    entry, camera, reader = await setup_entry(hass)
    restore_id = entity_id(hass, entry, "button", "restore_light")

    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.aux_on is True
    assert camera.supplement_history == []

    await hass.services.async_call(
        "button", "press", {"entity_id": restore_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert camera.aux_on is False
    assert camera.supplement_history == ["colorVuWhiteLight", "eventIntelligence"]
    assert camera.mode == "eventIntelligence"


async def test_restore_white_light_hold_is_configurable(
    hass: HomeAssistant,
) -> None:
    data = make_data()
    data[CONF_WHITE_HOLD_SECONDS] = 30
    _entry, camera, reader = await setup_entry(hass, make_entry(data=data))

    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    reader.emit_event(event(2, "inactive"))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
    await hass.async_block_till_done()

    # White supplement light is on while the configured hold is still running.
    assert camera.supplement_history == ["colorVuWhiteLight"]
    assert camera.mode == "colorVuWhiteLight"

    # Still inside the 30 s hold: smart mode must not be restored yet.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=25))
    await hass.async_block_till_done()
    assert camera.supplement_history == ["colorVuWhiteLight"]

    # After the hold has elapsed the smart supplement light is restored.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=40))
    await hass.async_block_till_done()
    assert camera.supplement_history == ["colorVuWhiteLight", "eventIntelligence"]
    assert camera.mode == "eventIntelligence"


async def test_unload_finishes_pending_smart_restore(hass: HomeAssistant) -> None:
    data = make_data()
    data[CONF_WHITE_HOLD_SECONDS] = 300
    entry, camera, reader = await setup_entry(hass, make_entry(data=data))

    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    reader.emit_event(event(2, "inactive"))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
    await hass.async_block_till_done()
    assert camera.mode == "colorVuWhiteLight"

    # Unloading must not leave the camera in white-light mode.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert camera.supplement_history == ["colorVuWhiteLight", "eventIntelligence"]
    assert camera.mode == "eventIntelligence"


async def test_restore_continues_when_white_step_fails(
    hass: HomeAssistant,
) -> None:
    _entry, camera, reader = await setup_entry(hass)
    original = FakeHikvisionClient.put_supplement_light

    def flaky_put(client, channel: int, xml_text: str) -> None:
        if "<supplementLightMode>colorVuWhiteLight</supplementLightMode>" in xml_text:
            raise HikvisionError("camera busy")
        original(client, channel, xml_text)

    with patch.object(FakeHikvisionClient, "put_supplement_light", flaky_put):
        reader.emit_event(event(2, "active"))
        await hass.async_block_till_done()
        reader.emit_event(event(2, "inactive"))
        await hass.async_block_till_done()
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
        await hass.async_block_till_done()

    # The failed white-light step must not prevent the smart restore.
    assert camera.supplement_history == ["eventIntelligence"]
    assert camera.mode == "eventIntelligence"


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
    assert camera.supplement_history == ["colorVuWhiteLight", "eventIntelligence"]

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": automation_switch}, blocking=True
    )
    await hass.async_block_till_done()
    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.mode == "eventIntelligence"


async def test_migration_from_single_channel_entry(hass: HomeAssistant) -> None:
    data = make_data()
    data[CONF_TRIGGER_CHANNEL] = 2
    data.pop(CONF_TRIGGER_CHANNELS)
    entry = make_entry(
        version=1,
        data=data,
        unique_id="SERIAL-192.0.2.2:2->SERIAL-192.0.2.10:1",
    )
    entry, camera, reader = await setup_entry(hass, entry)

    assert entry.version == CONFIG_ENTRY_VERSION
    assert entry.data[CONF_TRIGGER_CHANNELS] == [2]
    assert entry.state is ConfigEntryState.LOADED

    # The migrated link keeps working for channel 2 and ignores channel 6.
    boost_id = entity_id(hass, entry, "binary_sensor", "boost_active")
    reader.emit_event(event(6, "active"))
    await hass.async_block_till_done()
    assert camera.aux_on is False
    assert hass.states.get(boost_id).state == "off"

    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.aux_on is True
    assert hass.states.get(boost_id).state == "on"


async def test_mode_fallback_when_aux_light_is_missing(
    hass: HomeAssistant, monkeypatch
) -> None:
    """Cameras without a PTZ LIGHT output fall back to supplement mode."""
    monkeypatch.setattr(FakeHikvisionClient, "aux_supported", False)
    _entry, camera, reader = await setup_entry(hass)

    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.aux_on is False
    assert camera.mode == "colorVuWhiteLight"

    reader.emit_event(event(2, "inactive"))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
    await hass.async_block_till_done()
    assert camera.mode == "eventIntelligence"
    # The fallback path only switches modes, no extra IR step is used.
    assert camera.supplement_history == ["colorVuWhiteLight", "eventIntelligence"]
