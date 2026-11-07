"""Runtime data for the Hikvision alarm-light link integration."""

from __future__ import annotations

from dataclasses import dataclass

from .api import DeviceInfo, HikvisionIsapiClient
from .controller import AlarmLightController, LinkSettings
from .coordinator import AlarmLightCoordinator


@dataclass(slots=True)
class RuntimeData:
    """Objects shared by the entities and diagnostics."""

    settings: LinkSettings
    nvr_client: HikvisionIsapiClient
    camera_client: HikvisionIsapiClient
    controller: AlarmLightController
    coordinator: AlarmLightCoordinator
    nvr_device: DeviceInfo
    camera_device: DeviceInfo
