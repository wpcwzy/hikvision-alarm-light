"""Binary sensors for the alarm-light link."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import AlarmLightEntity
from .models import RuntimeData


class _BaseBinarySensor(AlarmLightEntity, BinarySensorEntity):
    _key = "binary"
    _name = "Binary sensor"

    def __init__(self, entry: ConfigEntry, runtime: RuntimeData) -> None:
        super().__init__(entry, runtime, self._key)
        self._attr_name = self._name


class AlarmActiveBinarySensor(_BaseBinarySensor):
    _key = "alarm_active"
    _name = "区域入侵报警"
    _attr_device_class = BinarySensorDeviceClass.MOTION

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.alarm_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "last_event_type": data.last_event_type,
            "last_event_channel": data.last_event_channel,
            "last_event_at": data.last_event_at.isoformat()
            if data.last_event_at
            else None,
            "stream_connected": data.stream_connected,
            "stream_error": data.stream_error,
            "camera_mode": data.camera_mode,
            "boost_active": data.boost_active,
            "last_error": data.last_error,
        }


class BoostBinarySensor(_BaseBinarySensor):
    _key = "boost_active"
    _name = "照明增强中"
    _attr_icon = "mdi:lightbulb-on-outline"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.boost_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "boost_ends_at": data.boost_ends_at.isoformat()
            if data.boost_ends_at
            else None,
            "camera_mode": data.camera_mode,
            "camera_channels": list(self.runtime.settings.camera_channels),
            "brightness": self.runtime.settings.brightness,
            "hold_seconds": self.runtime.settings.hold_seconds,
        }


class StreamConnectedBinarySensor(_BaseBinarySensor):
    _key = "stream_connected"
    _name = "报警事件流"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.stream_connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"stream_error": self.coordinator.data.stream_error}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: RuntimeData = entry.runtime_data
    async_add_entities(
        [
            AlarmActiveBinarySensor(entry, runtime),
            BoostBinarySensor(entry, runtime),
            StreamConnectedBinarySensor(entry, runtime),
        ]
    )
