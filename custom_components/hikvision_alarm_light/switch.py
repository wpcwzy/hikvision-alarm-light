"""Switches for the alarm-light link."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import HikvisionError
from .const import DOMAIN
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
            "trigger_channels": list(self.runtime.settings.trigger_channels),
            "camera_channel": self.runtime.settings.camera_channel,
            "night_start": self.runtime.settings.night_start.strftime("%H:%M"),
            "night_end": self.runtime.settings.night_end.strftime("%H:%M"),
            "hold_seconds": self.runtime.settings.hold_seconds,
            "brightness": self.runtime.settings.brightness,
            "white_hold_seconds": self.runtime.settings.white_hold_seconds,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.runtime.controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.runtime.controller.async_set_enabled(False)


class LightSwitch(AlarmLightEntity, SwitchEntity):
    """Switch the camera's alarm light on or off manually.

    Unlike the alarm automation this is a plain on/off switch (e.g. for the
    HomeKit / Apple Home app): turning it on keeps the light on until it is
    switched off again or the safety guard expires.
    """

    _attr_has_entity_name = False
    _attr_name = "后院灯"
    _attr_icon = "mdi:lightbulb-on-outline"

    def __init__(self, entry: ConfigEntry, runtime: RuntimeData) -> None:
        super().__init__(entry, runtime, "light")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.boost_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "camera_channel": self.runtime.settings.camera_channel,
            "max_boost_seconds": self.runtime.settings.max_boost_seconds,
            "white_hold_seconds": self.runtime.settings.white_hold_seconds,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        try:
            await self.runtime.controller.async_turn_light_on()
        except HikvisionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_boost",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self.runtime.controller.async_turn_light_off()
        except HikvisionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_restore",
                translation_placeholders={"error": str(err)},
            ) from err


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: RuntimeData = entry.runtime_data
    async_add_entities(
        [
            LightSwitch(entry, runtime),
            AutomationSwitch(entry, runtime),
        ]
    )
