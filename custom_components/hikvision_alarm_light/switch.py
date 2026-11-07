"""Automation enable switch for the alarm-light link."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import AlarmLightEntity
from .models import RuntimeData


class AutomationSwitch(AlarmLightEntity, SwitchEntity):
    """Enable or pause automatic alarm handling."""

    _attr_name = "自动联动"
    _attr_icon = "mdi:shield-lightning"

    def __init__(self, entry: ConfigEntry, runtime: RuntimeData) -> None:
        super().__init__(entry, runtime, "automation_enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "trigger_channel": self.runtime.settings.trigger_channel,
            "camera_channel": self.runtime.settings.camera_channel,
            "night_start": self.runtime.settings.night_start.strftime("%H:%M"),
            "night_end": self.runtime.settings.night_end.strftime("%H:%M"),
            "hold_seconds": self.runtime.settings.hold_seconds,
            "brightness": self.runtime.settings.brightness,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.runtime.controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.runtime.controller.async_set_enabled(False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: RuntimeData = entry.runtime_data
    async_add_entities([AutomationSwitch(entry, runtime)])
