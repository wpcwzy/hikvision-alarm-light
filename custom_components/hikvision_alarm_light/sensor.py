"""Sensors for the alarm-light link."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import AlarmLightEntity
from .models import RuntimeData


class LastAlarmSensor(AlarmLightEntity, SensorEntity):
    """Timestamp of the last intrusion alarm."""

    _attr_name = "上次入侵"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:shield-alert-outline"

    def __init__(self, entry: ConfigEntry, runtime: RuntimeData) -> None:
        super().__init__(entry, runtime, "last_alarm")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.last_alarm

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "event_type": data.last_event_type,
            "nvr_channel": data.last_event_channel,
            "camera_mode": data.camera_mode,
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: RuntimeData = entry.runtime_data
    async_add_entities([LastAlarmSensor(entry, runtime)])
