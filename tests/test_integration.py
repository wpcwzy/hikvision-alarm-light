"""Tests for the event-driven alarm-light entity behavior."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

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
    CONF_PRESET_AUTO,
    CONF_PRESET_DAY,
    CONF_PRESET_INTERVAL,
    CONF_PRESET_LIGHT_ON,
    CONF_PRESET_NIGHT,
    CONF_TRIGGER_CHANNEL,
    CONF_TRIGGER_CHANNELS,
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
        CONF_PRESET_LIGHT_ON: 0,
        CONF_PRESET_DAY: 39,
        CONF_PRESET_NIGHT: 40,
        CONF_PRESET_AUTO: 46,
        CONF_PRESET_INTERVAL: 0,
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
    # otherwise IR behaviour could be disturbed.
    assert camera.mode == "eventIntelligence"
    # B/W (IR) picture is kept while the light is on: no preset is called.
    assert camera.presets == []
    assert hass.states.get(boost_id).state == "on"

    reader.emit_event(event(2, "inactive"))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
    await hass.async_block_till_done()
    assert camera.aux_on is False
    assert camera.mode == "eventIntelligence"
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


async def test_presets_only_on_restore(hass: HomeAssistant) -> None:
    _entry, camera, reader = await setup_entry(hass)

    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    # The B/W picture is kept while the light is on.
    assert camera.presets == []

    reader.emit_event(event(2, "inactive"))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
    await hass.async_block_till_done()
    # The whole test window is "night", so preset 40 is used before the
    # automatic day/night preset 46.
    assert camera.presets == [40, 46]
    assert camera.aux_on is False


async def test_light_on_preset_can_be_enabled(hass: HomeAssistant) -> None:
    data = make_data()
    data[CONF_PRESET_LIGHT_ON] = 39
    _entry, camera, reader = await setup_entry(hass, make_entry(data=data))

    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.presets == [39]


async def test_restore_presets_use_configured_interval(
    hass: HomeAssistant,
) -> None:
    data = make_data()
    data[CONF_PRESET_INTERVAL] = 3
    entry, camera, reader = await setup_entry(hass, make_entry(data=data))
    controller = entry.runtime_data.controller

    reader.emit_event(event(2, "active"))
    await hass.async_block_till_done()
    assert camera.presets == []

    with patch.object(
        type(controller), "_async_preset_delay", new=AsyncMock()
    ) as delay:
        reader.emit_event(event(2, "inactive"))
        await hass.async_block_till_done()
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
        await hass.async_block_till_done()

    delay.assert_awaited_once_with(3)
    assert camera.presets == [40, 46]


async def test_day_restore_uses_day_preset(hass: HomeAssistant) -> None:
    # Pick a "night" window that does not contain the current time so the
    # restore path has to use the day preset.
    now = dt_util.now()
    night_start = (now + timedelta(minutes=2)).strftime("%H:%M")
    night_end = (now + timedelta(minutes=3)).strftime("%H:%M")
    entry, camera, _reader = await setup_entry(
        hass,
        make_entry(data=make_data(night_start=night_start, night_end=night_end)),
    )
    test_id = entity_id(hass, entry, "button", "test_boost")
    restore_id = entity_id(hass, entry, "button", "restore_light")

    # Manual test boost always works, even outside the night window.
    await hass.services.async_call(
        "button", "press", {"entity_id": test_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert camera.presets == []

    await hass.services.async_call(
        "button", "press", {"entity_id": restore_id}, blocking=True
    )
    await hass.async_block_till_done()
    # Daytime: preset 39 (day) first, then preset 46 (automatic).
    assert camera.presets == [39, 46]
    assert camera.aux_on is False


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
    # Presets are only used together with the PTZ aux LIGHT output.
    assert camera.presets == []

    reader.emit_event(event(2, "inactive"))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=130))
    await hass.async_block_till_done()
    assert camera.mode == "eventIntelligence"
    assert camera.presets == []
