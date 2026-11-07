"""Home Assistant integration: NVR intrusion alarm to camera white light."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import (
    HikvisionAuthError,
    HikvisionConnectionError,
    HikvisionError,
    HikvisionIsapiClient,
    HikvisionResponseError,
)
from .const import (
    CONF_TRIGGER_CHANNEL,
    CONF_TRIGGER_CHANNELS,
    CONFIG_ENTRY_VERSION,
    DEFAULT_TRIGGER_CHANNEL,
)
from .controller import AlarmLightController, LinkSettings
from .coordinator import AlarmLightCoordinator
from .models import RuntimeData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a version 1 entry from a single channel to a channel list."""
    if entry.version > CONFIG_ENTRY_VERSION:
        _LOGGER.error(
            "Cannot migrate entry %s from version %s to %s",
            entry.entry_id,
            entry.version,
            CONFIG_ENTRY_VERSION,
        )
        return False

    if entry.version < CONFIG_ENTRY_VERSION:
        data = dict(entry.data)
        if CONF_TRIGGER_CHANNELS not in data:
            legacy_channel = data.pop(CONF_TRIGGER_CHANNEL, DEFAULT_TRIGGER_CHANNEL)
            data[CONF_TRIGGER_CHANNELS] = [int(legacy_channel)]
        hass.config_entries.async_update_entry(
            entry, data=data, version=CONFIG_ENTRY_VERSION
        )
        _LOGGER.info(
            "Migrated %s to config entry version %s, trigger channels: %s",
            entry.title,
            CONFIG_ENTRY_VERSION,
            data[CONF_TRIGGER_CHANNELS],
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the alarm-light link."""
    merged = {**dict(entry.data), **dict(entry.options)}
    settings = LinkSettings.from_entry(merged)

    nvr_client = HikvisionIsapiClient(
        settings.nvr_host,
        settings.nvr_username,
        settings.nvr_password,
        port=settings.nvr_port,
        use_ssl=settings.nvr_use_ssl,
        verify_ssl=settings.nvr_verify_ssl,
    )
    camera_client = HikvisionIsapiClient(
        settings.camera_host,
        settings.camera_username,
        settings.camera_password,
        port=settings.camera_port,
        use_ssl=settings.camera_use_ssl,
        verify_ssl=settings.camera_verify_ssl,
    )

    try:
        nvr_device = await hass.async_add_executor_job(nvr_client.get_device_info)
        for trigger_channel in settings.trigger_channels:
            await hass.async_add_executor_job(
                nvr_client.get_linkage_state, trigger_channel
            )
        camera_device = await hass.async_add_executor_job(camera_client.get_device_info)
        await hass.async_add_executor_job(
            camera_client.get_supplement_light, settings.camera_channel
        )
    except HikvisionAuthError as err:
        await _close_clients(hass, nvr_client, camera_client)
        raise ConfigEntryAuthFailed(
            "The NVR or camera rejected the stored credentials."
        ) from err
    except (HikvisionConnectionError, HikvisionResponseError) as err:
        await _close_clients(hass, nvr_client, camera_client)
        raise ConfigEntryNotReady(
            f"Could not validate the NVR or camera: {err}"
        ) from err
    except HikvisionError as err:
        await _close_clients(hass, nvr_client, camera_client)
        raise ConfigEntryNotReady(f"Could not set up alarm-light link: {err}") from err

    controller = AlarmLightController(hass, entry, settings, nvr_client, camera_client)
    coordinator = AlarmLightCoordinator(hass, entry, controller)
    await coordinator.async_config_entry_first_refresh()
    controller.attach_coordinator(coordinator)
    await controller.async_start()

    entry.runtime_data = RuntimeData(
        settings=settings,
        nvr_client=nvr_client,
        camera_client=camera_client,
        controller=controller,
        coordinator=coordinator,
        nvr_device=nvr_device,
        camera_device=camera_device,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry and restore the smart light mode."""
    runtime: RuntimeData | None = getattr(entry, "runtime_data", None)
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if runtime is not None:
        await runtime.controller.async_stop()
        await _close_clients(hass, runtime.nvr_client, runtime.camera_client)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _close_clients(
    hass: HomeAssistant,
    nvr_client: HikvisionIsapiClient,
    camera_client: HikvisionIsapiClient,
) -> None:
    await hass.async_add_executor_job(nvr_client.close)
    await hass.async_add_executor_job(camera_client.close)
