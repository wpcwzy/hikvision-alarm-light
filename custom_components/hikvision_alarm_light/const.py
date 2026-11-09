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
# Legacy single-channel key, only kept so older entries can be migrated.
CONF_CAMERA_CHANNEL: Final = "camera_channel"
CONF_CAMERA_CHANNELS: Final = "camera_channels"

CONF_NAME: Final = "name"
CONF_NIGHT_START: Final = "night_start"
CONF_NIGHT_END: Final = "night_end"
CONF_HOLD_SECONDS: Final = "hold_seconds"
CONF_MAX_BOOST_SECONDS: Final = "max_boost_seconds"
CONF_BRIGHTNESS: Final = "brightness"

DEFAULT_NVR_PORT: Final = 80
DEFAULT_CAMERA_PORT: Final = 80
DEFAULT_TRIGGER_CHANNEL: Final = 2
DEFAULT_TRIGGER_CHANNELS: Final = (2,)
DEFAULT_CAMERA_CHANNEL: Final = 1
DEFAULT_CAMERA_CHANNELS: Final = (1,)
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

# Boom: while an alarm is active the camera supplement light is switched to
# white light (colorVuWhiteLight) with the brightness regulation mode "on"
# (always on) and the configured brightness.  When the alarm ends (or the
# safety limit is hit) it is switched back to the smart (automatic) mode.
BOOST_LIGHT_MODE: Final = "colorVuWhiteLight"
BOOST_BRIGHTNESS_REGULATION_MODE: Final = "on"
RESTORE_LIGHT_MODE: Final = "eventIntelligence"

CONFIG_ENTRY_VERSION: Final = 3
CONFIG_ENTRY_MINOR_VERSION: Final = 1

EVENT_TYPE_FIELDDETECTION: Final = "fielddetection"

STORE_VERSION: Final = 2
