"""Coordinator for the alarm-light link."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .controller import AlarmLightController, LinkSnapshot

_LOGGER = logging.getLogger(__name__)


class AlarmLightCoordinator(DataUpdateCoordinator[LinkSnapshot]):
    """Event-driven coordinator with no periodic polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        controller: AlarmLightController,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"hikvision_alarm_light_{entry.entry_id}",
            update_interval=None,
        )
        self.controller = controller

    async def _async_update_data(self) -> LinkSnapshot:
        return self.controller.snapshot
