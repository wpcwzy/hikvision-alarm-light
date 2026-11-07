"""Buttons for testing and restoring the alarm light."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import HikvisionError
from .const import DOMAIN
from .entity import AlarmLightEntity
from .models import RuntimeData


class TestBoostButton(AlarmLightEntity, ButtonEntity):
    """Turn the light on at max brightness for the configured hold time."""

    _attr_name = "测试补光"
    _attr_icon = "mdi:lightbulb-on-outline"

    def __init__(self, entry: ConfigEntry, runtime: RuntimeData) -> None:
        super().__init__(entry, runtime, "test_boost")

    async def async_press(self) -> None:
        try:
            await self.runtime.controller.async_test_boost()
        except HikvisionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_boost",
                translation_placeholders={"error": str(err)},
            ) from err


class RestoreSmartLightButton(AlarmLightEntity, ButtonEntity):
    """Immediately restore the camera's smart supplement-light mode."""

    _attr_name = "恢复智能补光"
    _attr_icon = "mdi:lightbulb-off-outline"

    def __init__(self, entry: ConfigEntry, runtime: RuntimeData) -> None:
        super().__init__(entry, runtime, "restore_light")

    async def async_press(self) -> None:
        try:
            await self.runtime.controller.async_restore_light()
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
            TestBoostButton(entry, runtime),
            RestoreSmartLightButton(entry, runtime),
        ]
    )
