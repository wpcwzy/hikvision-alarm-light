"""Shared entity base for the alarm-light link."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AlarmLightCoordinator
from .models import RuntimeData


class AlarmLightEntity(CoordinatorEntity[AlarmLightCoordinator]):
    """Base entity with the shared device and runtime."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: RuntimeData,
        key: str,
    ) -> None:
        super().__init__(runtime.coordinator)
        self._entry = entry
        self.runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=runtime.settings.name,
            manufacturer="Hikvision",
            model=(f"NVR {runtime.nvr_device.model} → {runtime.camera_device.model}"),
            sw_version=runtime.nvr_device.firmware_version or None,
            configuration_url=runtime.nvr_client.base_url,
        )
