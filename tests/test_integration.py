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
    BOOST_LIGHT_MODE,
    CONF_BRIGHTNESS,
    CONF_CAMERA_CHANNEL,
    CONF_CAMERA_CHANNELS,
    CONF_CAMERA_HOST,
    CONF_CAMERA_PASSWORD,
    CONF_CAMERA_PORT,
    CONF_CAMERA_USE_SSL,
    CONF_CAMERA_USERNAME,
    CONF_CAMERA_VERIFY_SSL,
    CONF_FOLLOW_SUN,
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
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    RESTORE_LIGHT_MODE,
)
from tests.fakes import FakeAlertReader, FakeHikvisionClient

WHITE = BOOST_LIGHT_MODE
SMART = RESTORE_LIGHT_MODE


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
        CONF_CAMERA_CHANNELS: [1, 2],
        CONF_NAME: "后院入侵补光联动",
        CONF_NIGHT_START: night_start,
        CONF_NIGHT_END: night_end,
        CONF_FOLLOW_SUN: False,
        CONF_HOLD_SECONDS: 120,
        CONF_MAX_BOOST_SECONDS: 300,
        CONF_BRIGHTNESS: 100,
    }


def make_entry(
    *,
    version: int = CONFIG_ENTRY_VERSION,
    data: dict | None = None,
    unique_id: str = "SERIAL-192.0.2.2:2+6->SERIAL-192.0.2.10:1+2",
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


def white_calls(channels: tuple[int, ...] = (1, 2)) -> list[tuple[int, str]]:
    return [(channel, WHITE) for channel in channels]


def smart_calls(channels: tuple[int, ...] = (1, 2)) -> list[tuple[int, str]]:
    return [(channel, SMART) for channel in channels]


async def test_alarm_on_either_channel_boosts_light(hass: HomeAssistant) -> None:
    entry, camera, reader = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED

    boost_id = entity_id(hass, entry, "binary_sensor", "boost_active")
    stream_id = entity_id(hass, entry, "binary_sensor", "stream_connected")
    assert hass.states.get(stream_id).state == "on"
    assert hass.states.get(boost_id).state == "off"

    # An alarm on any configured NVR channel switches both camera channels to
    # white light with the brightness regulation mode always on.
    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.put_calls == white_calls()
    assert camera.modes == {1: WHITE, 2: WHITE}
    assert hass.states.get(boost_id).state == "on"

    reader.emit_event(event(2, "inactive"))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
    await hass.async_block_till_done()
    assert camera.put_calls == white_calls() + smart_calls()
    assert camera.modes == {1: SMART, 2: SMART}
    assert hass.states.get(boost_id).state == "off"

    # The second configured alarm channel works as well.
    reader.emit_event(event(6, "active"))
    await hass.async_block_till_done()
    assert camera.modes == {1: WHITE, 2: WHITE}
    assert hass.states.get(boost_id).state == "on"

    # An unrelated channel must be ignored.
    before = len(camera.put_calls)
    reader.emit_event(event(3, "active"))
    await hass.async_block_till_done()
    assert len(camera.put_calls) == before

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert camera.closed is True
    # Unloading with an active boost must restore the smart mode.
    assert camera.modes == {1: SMART, 2: SMART}


async def test_guard_restores_after_max_boost(hass: HomeAssistant) -> None:
    _entry, camera, reader = await setup_entry(hass)

    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.modes == {1: WHITE, 2: WHITE}

    # No inactive event: the safety limit (300 s) restores the smart mode.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=310))
    await hass.async_block_till_done()
    assert camera.modes == {1: SMART, 2: SMART}


async def test_manual_light_switch(hass: HomeAssistant) -> None:
    entry, camera, _reader = await setup_entry(hass)
    light_id = entity_id(hass, entry, "switch", "light")
    assert hass.states.get(light_id).state == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": light_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert camera.put_calls == white_calls()
    assert hass.states.get(light_id).state == "on"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": light_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert camera.put_calls == white_calls() + smart_calls()
    assert hass.states.get(light_id).state == "off"


async def test_light_switch_follows_alarm(hass: HomeAssistant) -> None:
    entry, camera, reader = await setup_entry(hass)
    light_id = entity_id(hass, entry, "switch", "light")

    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.modes == {1: WHITE, 2: WHITE}
    assert hass.states.get(light_id).state == "on"

    reader.emit_event(event(2, "inactive"))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
    await hass.async_block_till_done()
    assert camera.modes == {1: SMART, 2: SMART}
    assert hass.states.get(light_id).state == "off"


async def test_button_and_switch(hass: HomeAssistant) -> None:
    entry, camera, reader = await setup_entry(hass)
    test_button = entity_id(hass, entry, "button", "test_boost")
    restore_button = entity_id(hass, entry, "button", "restore_light")
    automation_switch = entity_id(hass, entry, "switch", "automation_enabled")

    await hass.services.async_call(
        "button", "press", {"entity_id": test_button}, blocking=True
    )
    await hass.async_block_till_done()
    assert camera.modes == {1: WHITE, 2: WHITE}

    await hass.services.async_call(
        "button", "press", {"entity_id": restore_button}, blocking=True
    )
    await hass.async_block_till_done()
    assert camera.modes == {1: SMART, 2: SMART}

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": automation_switch}, blocking=True
    )
    await hass.async_block_till_done()
    before = len(camera.put_calls)
    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert len(camera.put_calls) == before


async def test_boost_failure_rolls_back(hass: HomeAssistant) -> None:
    entry, camera, reader = await setup_entry(hass)
    original = FakeHikvisionClient.put_supplement_light

    def flaky_put(client, channel: int, xml_text: str) -> None:
        if channel == 2 and "<supplementLightMode>colorVuWhiteLight" in xml_text:
            raise HikvisionError("camera busy")
        original(client, channel, xml_text)

    with patch.object(FakeHikvisionClient, "put_supplement_light", flaky_put):
        reader.emit_event(event(2, "active"))
        await hass.async_block_till_done()

    # Channel 1 was already switched; it must be rolled back to smart mode.
    assert camera.modes == {1: SMART}
    boost_id = entity_id(hass, entry, "binary_sensor", "boost_active")
    assert hass.states.get(boost_id).state == "off"


async def test_migration_from_v2_entry(hass: HomeAssistant) -> None:
    data = make_data()
    data[CONF_TRIGGER_CHANNELS] = [2, 6]
    data[CONF_CAMERA_CHANNEL] = 1
    data.pop(CONF_CAMERA_CHANNELS)
    entry = make_entry(
        version=2,
        data=data,
        unique_id="SERIAL-192.0.2.2:2+6->SERIAL-192.0.2.10:1",
    )
    entry, camera, reader = await setup_entry(hass, entry)

    assert entry.version == CONFIG_ENTRY_VERSION
    assert entry.data[CONF_CAMERA_CHANNELS] == [1]
    assert entry.state is ConfigEntryState.LOADED

    reader.emit_event(event(6, "active"))
    await hass.async_block_till_done()
    # Only the migrated camera channel 1 is switched.
    assert camera.modes == {1: WHITE}


async def test_migration_from_v1_entry(hass: HomeAssistant) -> None:
    data = make_data()
    data[CONF_TRIGGER_CHANNEL] = 2
    data[CONF_CAMERA_CHANNEL] = 1
    data.pop(CONF_TRIGGER_CHANNELS)
    data.pop(CONF_CAMERA_CHANNELS)
    entry = make_entry(
        version=1,
        data=data,
        unique_id="SERIAL-192.0.2.2:2->SERIAL-192.0.2.10:1",
    )
    entry, camera, reader = await setup_entry(hass, entry)

    assert entry.version == CONFIG_ENTRY_VERSION
    assert entry.data[CONF_TRIGGER_CHANNELS] == [2]
    assert entry.data[CONF_CAMERA_CHANNELS] == [1]

    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.modes == {1: WHITE}


async def test_follow_sun_controls_alarm_trigger(hass: HomeAssistant) -> None:
    """With follow_sun the alarm only lights up when the sun is down."""
    data = make_data()
    data[CONF_FOLLOW_SUN] = True
    _entry, camera, reader = await setup_entry(hass, make_entry(data=data))

    hass.states.async_set("sun.sun", "above_horizon")
    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.put_calls == []

    hass.states.async_set("sun.sun", "below_horizon")
    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.modes == {1: WHITE, 2: WHITE}


async def test_follow_sun_falls_back_to_fixed_window(
    hass: HomeAssistant,
) -> None:
    """Without a sun entity the configured fixed window is used."""
    data = make_data()
    data[CONF_FOLLOW_SUN] = True
    _entry, camera, reader = await setup_entry(hass, make_entry(data=data))

    # The test data window covers the whole day, so the alarm is treated as
    # night even though no sun.sun state exists.
    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.modes == {1: WHITE, 2: WHITE}
