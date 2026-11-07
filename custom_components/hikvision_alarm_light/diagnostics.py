"""Diagnostics for the alarm-light link."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_CAMERA_PASSWORD, CONF_NVR_PASSWORD
from .models import RuntimeData

TO_REDACT = {CONF_NVR_PASSWORD, CONF_CAMERA_PASSWORD}


def _snapshot_dict(runtime: RuntimeData) -> dict[str, Any]:
    data = runtime.coordinator.data
    return {
        "enabled": data.enabled,
        "alarm_active": data.alarm_active,
        "boost_active": data.boost_active,
        "last_alarm": data.last_alarm.isoformat() if data.last_alarm else None,
        "last_event_type": data.last_event_type,
        "last_event_channel": data.last_event_channel,
        "last_event_at": data.last_event_at.isoformat() if data.last_event_at else None,
        "stream_connected": data.stream_connected,
        "stream_error": data.stream_error,
        "camera_mode": data.camera_mode,
        "boost_ends_at": data.boost_ends_at.isoformat() if data.boost_ends_at else None,
        "last_error": data.last_error,
        "light_control": data.light_control,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    runtime: RuntimeData = entry.runtime_data
    settings = asdict(runtime.settings)
    for key in TO_REDACT:
        settings[key] = "**REDACTED**"
    return {
        "entry": {
            "title": entry.title,
            "unique_id": entry.unique_id,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "settings": settings,
        "nvr": {
            "device": asdict(runtime.nvr_device),
            "base_url": runtime.nvr_client.base_url,
            "trigger_channels": list(runtime.settings.trigger_channels),
        },
        "camera": {
            "device": asdict(runtime.camera_device),
            "base_url": runtime.camera_client.base_url,
            "channel": runtime.settings.camera_channel,
        },
        "state": _snapshot_dict(runtime),
    }
