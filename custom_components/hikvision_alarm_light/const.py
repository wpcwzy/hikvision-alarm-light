"""Constants for the Hikvision alarm-light link integration."""

from __future__ import annotations

from datetime import time
from typing import Final

DOMAIN: Final = "hikvision_alarm_light"

CONF_NVR_HOST: Final = "nvr_host"
CONF_NVR_PORT: Final = "nvr_port"
CONF_NVR_USE_SSL: Final = "nvr_use_ssl"
CONF_NVR_VERIFY_SSL: Final = "nvr_verify_ssl"
CONF_NVR_USERNAME: Final = "nvr_username"
CONF_NVR_PASSWORD: Final = "nvr_password"
# Legacy single-channel key, only kept so version 1 entries can be migrated.
CONF_TRIGGER_CHANNEL: Final = "trigger_channel"
CONF_TRIGGER_CHANNELS: Final = "trigger_channels"

CONF_CAMERA_HOST: Final = "camera_host"
CONF_CAMERA_PORT: Final = "camera_port"
CONF_CAMERA_USE_SSL: Final = "camera_use_ssl"
CONF_CAMERA_VERIFY_SSL: Final = "camera_verify_ssl"
CONF_CAMERA_USERNAME: Final = "camera_username"
CONF_CAMERA_PASSWORD: Final = "camera_password"
CONF_CAMERA_CHANNEL: Final = "camera_channel"

CONF_NAME: Final = "name"
CONF_NIGHT_START: Final = "night_start"
CONF_NIGHT_END: Final = "night_end"
CONF_HOLD_SECONDS: Final = "hold_seconds"
CONF_MAX_BOOST_SECONDS: Final = "max_boost_seconds"
CONF_BRIGHTNESS: Final = "brightness"

CONF_PRESET_LIGHT_ON: Final = "preset_light_on"
CONF_PRESET_DAY: Final = "preset_day"
CONF_PRESET_NIGHT: Final = "preset_night"
CONF_PRESET_AUTO: Final = "preset_auto"
CONF_PRESET_INTERVAL: Final = "preset_interval"

DEFAULT_NVR_PORT: Final = 80
DEFAULT_CAMERA_PORT: Final = 80
DEFAULT_TRIGGER_CHANNEL: Final = 2
DEFAULT_TRIGGER_CHANNELS: Final = (2,)
DEFAULT_CAMERA_CHANNEL: Final = 1
DEFAULT_NAME: Final = "后院入侵补光联动"
DEFAULT_NIGHT_START: Final = time(18, 0)
DEFAULT_NIGHT_END: Final = time(6, 0)
DEFAULT_HOLD_SECONDS: Final = 300
DEFAULT_MAX_BOOST_SECONDS: Final = 900
DEFAULT_BRIGHTNESS: Final = 100

MIN_CHANNEL: Final = 1
MAX_CHANNEL: Final = 64
MIN_HOLD_SECONDS: Final = 10
MAX_HOLD_SECONDS: Final = 3600
MIN_BOOST_SECONDS: Final = 60
MAX_BOOST_SECONDS: Final = 3600
MIN_BRIGHTNESS: Final = 1
MAX_BRIGHTNESS: Final = 100

# PTZ presets used to restore the day or night picture after the white light is
# switched off, followed by the automatic day/night preset.  Set a preset to 0
# to skip that step.  The light itself is kept in B/W (IR) mode while on, so the
# "light on" preset defaults to 0 (disabled); set it if a colour picture is
# really wanted while the white light is active.
DEFAULT_PRESET_LIGHT_ON: Final = 0
DEFAULT_PRESET_DAY: Final = 39
DEFAULT_PRESET_NIGHT: Final = 40
DEFAULT_PRESET_AUTO: Final = 46
MIN_PRESET_ID: Final = 0
MAX_PRESET_ID: Final = 999

# The camera can silently drop a PTZ command that arrives while it is still
# processing the previous one, so leave a small gap between the two restore
# presets.  0 disables the wait.
DEFAULT_PRESET_INTERVAL_SECONDS: Final = 1
MIN_PRESET_INTERVAL_SECONDS: Final = 0
MAX_PRESET_INTERVAL_SECONDS: Final = 10

CONFIG_ENTRY_VERSION: Final = 2
CONFIG_ENTRY_MINOR_VERSION: Final = 1

EVENT_TYPE_FIELDDETECTION: Final = "fielddetection"

STORE_VERSION: Final = 1
