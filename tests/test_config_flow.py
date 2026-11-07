"""Tests for the alarm-light config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    CONF_TRIGGER_CHANNELS,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
)
from tests.fakes import FakeHikvisionClient

NVR_INPUT = {
    CONF_NVR_HOST: "192.0.2.2",
    CONF_NVR_PORT: 80,
    CONF_NVR_USE_SSL: False,
    CONF_NVR_VERIFY_SSL: False,
    CONF_NVR_USERNAME: "admin",
    CONF_NVR_PASSWORD: "secret",
    CONF_TRIGGER_CHANNELS: "2, 6",
}
CAMERA_INPUT = {
    CONF_CAMERA_HOST: "192.0.2.10",
    CONF_CAMERA_PORT: 80,
    CONF_CAMERA_USE_SSL: False,
    CONF_CAMERA_VERIFY_SSL: False,
    CONF_CAMERA_USERNAME: "admin",
    CONF_CAMERA_PASSWORD: "secret",
    CONF_CAMERA_CHANNEL: 1,
    CONF_NAME: "后院入侵补光联动",
    CONF_NIGHT_START: "18:00",
    CONF_NIGHT_END: "06:00",
    CONF_HOLD_SECONDS: 120,
    CONF_MAX_BOOST_SECONDS: 300,
    CONF_BRIGHTNESS: 100,
}

OPTIONS_INPUT = {
    CONF_NAME: "后院入侵补光联动",
    CONF_TRIGGER_CHANNELS: "2,6",
    CONF_NIGHT_START: "18:00",
    CONF_NIGHT_END: "06:00",
    CONF_HOLD_SECONDS: 300,
    CONF_MAX_BOOST_SECONDS: 900,
    CONF_BRIGHTNESS: 100,
    CONF_PRESET_LIGHT_ON: 0,
    CONF_PRESET_DAY: 39,
    CONF_PRESET_NIGHT: 40,
    CONF_PRESET_AUTO: 46,
    CONF_PRESET_INTERVAL: 2,
}


def _patch_client():
    return patch(
        "custom_components.hikvision_alarm_light.config_flow.HikvisionIsapiClient",
        new=FakeHikvisionClient,
    )


def make_existing_entry() -> MockConfigEntry:
    data = {
        **{k: v for k, v in NVR_INPUT.items() if k != CONF_TRIGGER_CHANNELS},
        **CAMERA_INPUT,
        "trigger_channel": 2,
    }
    return MockConfigEntry(
        domain=DOMAIN,
        title="后院入侵补光联动",
        unique_id="old-unique-id",
        version=CONFIG_ENTRY_VERSION,
        data=data,
    )


async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    """The two-step flow validates both devices and creates an entry."""
    with _patch_client():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], NVR_INPUT
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "camera"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CAMERA_INPUT
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY

    assert result["title"] == "后院入侵补光联动"
    assert result["data"][CONF_NVR_HOST] == "192.0.2.2"
    assert result["data"][CONF_TRIGGER_CHANNELS] == [2, 6]
    assert result["data"][CONF_CAMERA_HOST] == "192.0.2.10"
    assert result["data"][CONF_CAMERA_CHANNEL] == 1
    assert result["data"][CONF_HOLD_SECONDS] == 120
    assert result["data"][CONF_PRESET_LIGHT_ON] == 0
    assert result["data"][CONF_PRESET_NIGHT] == 40
    assert result["result"].unique_id == "SERIAL-192.0.2.2:2+6->SERIAL-192.0.2.10:1"


async def test_config_flow_rejects_invalid_times(hass: HomeAssistant) -> None:
    """Equal night start/end is rejected before creating the entry."""
    with _patch_client():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], NVR_INPUT
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**CAMERA_INPUT, CONF_NIGHT_START: "18:00", CONF_NIGHT_END: "18:00"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "camera"
    assert result["errors"] == {"base": "invalid_night_window"}


async def test_config_flow_rejects_invalid_channels(hass: HomeAssistant) -> None:
    """Non-numeric or out-of-range channels are rejected."""
    with _patch_client():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**NVR_INPUT, CONF_TRIGGER_CHANNELS: "2,abc"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_trigger_channels"}


async def test_options_flow_updates_channels_and_presets(hass: HomeAssistant) -> None:
    entry = make_existing_entry()
    entry.add_to_hass(hass)

    with _patch_client():
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], OPTIONS_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_TRIGGER_CHANNELS] == [2, 6]
    assert entry.options[CONF_NIGHT_START] == "18:00"
    assert entry.options[CONF_HOLD_SECONDS] == 300
    assert entry.options[CONF_PRESET_LIGHT_ON] == 0
    assert entry.options[CONF_PRESET_DAY] == 39
    assert entry.options[CONF_PRESET_NIGHT] == 40
    assert entry.options[CONF_PRESET_AUTO] == 46
    assert entry.options[CONF_PRESET_INTERVAL] == 2


async def test_options_flow_rejects_invalid_channels(hass: HomeAssistant) -> None:
    entry = make_existing_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**OPTIONS_INPUT, CONF_TRIGGER_CHANNELS: "0,6"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {"base": "invalid_trigger_channels"}
