"""Config and options flows for the Hikvision alarm-light link."""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    HikvisionAuthError,
    HikvisionConnectionError,
    HikvisionError,
    HikvisionIsapiClient,
    HikvisionResponseError,
)
from .const import (
    CONF_BRIGHTNESS,
    CONF_CAMERA_CHANNEL,
    CONF_CAMERA_HOST,
    CONF_CAMERA_PASSWORD,
    CONF_CAMERA_PORT,
    CONF_CAMERA_USE_SSL,
    CONF_CAMERA_USERNAME,
    CONF_CAMERA_VERIFY_SSL,
    CONF_HOLD_SECONDS,
    CONF_MAX_BOOST_SECONDS,
    CONF_NAME,
    CONF_NIGHT_END,
    CONF_NIGHT_START,
    CONF_NVR_HOST,
    CONF_NVR_PASSWORD,
    CONF_NVR_PORT,
    CONF_NVR_USE_SSL,
    CONF_NVR_USERNAME,
    CONF_NVR_VERIFY_SSL,
    CONF_TRIGGER_CHANNEL,
    CONF_TRIGGER_CHANNELS,
    CONF_WHITE_HOLD_SECONDS,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DEFAULT_BRIGHTNESS,
    DEFAULT_CAMERA_CHANNEL,
    DEFAULT_CAMERA_PORT,
    DEFAULT_HOLD_SECONDS,
    DEFAULT_MAX_BOOST_SECONDS,
    DEFAULT_NAME,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DEFAULT_NVR_PORT,
    DEFAULT_TRIGGER_CHANNEL,
    DEFAULT_WHITE_HOLD_SECONDS,
    DOMAIN,
    MAX_BOOST_SECONDS,
    MAX_BRIGHTNESS,
    MAX_CHANNEL,
    MAX_HOLD_SECONDS,
    MAX_WHITE_HOLD_SECONDS,
    MIN_BOOST_SECONDS,
    MIN_BRIGHTNESS,
    MIN_CHANNEL,
    MIN_HOLD_SECONDS,
    MIN_WHITE_HOLD_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


NVR_CONNECT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NVR_HOST): TextSelector(),
        vol.Required(CONF_NVR_PORT, default=DEFAULT_NVR_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX, step=1)
        ),
        vol.Required(CONF_NVR_USE_SSL, default=False): BooleanSelector(),
        vol.Required(CONF_NVR_VERIFY_SSL, default=False): BooleanSelector(),
        vol.Required(CONF_NVR_USERNAME, default="admin"): TextSelector(),
        vol.Required(CONF_NVR_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(
            CONF_TRIGGER_CHANNELS, default=str(DEFAULT_TRIGGER_CHANNEL)
        ): TextSelector(),
    }
)

CAMERA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CAMERA_HOST): TextSelector(),
        vol.Required(CONF_CAMERA_PORT, default=DEFAULT_CAMERA_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX, step=1)
        ),
        vol.Required(CONF_CAMERA_USE_SSL, default=False): BooleanSelector(),
        vol.Required(CONF_CAMERA_VERIFY_SSL, default=False): BooleanSelector(),
        vol.Required(CONF_CAMERA_USERNAME, default="admin"): TextSelector(),
        vol.Required(CONF_CAMERA_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(
            CONF_CAMERA_CHANNEL, default=DEFAULT_CAMERA_CHANNEL
        ): NumberSelector(
            NumberSelectorConfig(min=1, max=64, mode=NumberSelectorMode.BOX, step=1)
        ),
        vol.Required(CONF_NAME, default=DEFAULT_NAME): TextSelector(),
        vol.Required(
            CONF_NIGHT_START, default=DEFAULT_NIGHT_START.strftime("%H:%M")
        ): TextSelector(),
        vol.Required(
            CONF_NIGHT_END, default=DEFAULT_NIGHT_END.strftime("%H:%M")
        ): TextSelector(),
        vol.Required(CONF_HOLD_SECONDS, default=DEFAULT_HOLD_SECONDS): NumberSelector(
            NumberSelectorConfig(
                min=MIN_HOLD_SECONDS,
                max=MAX_HOLD_SECONDS,
                mode=NumberSelectorMode.BOX,
                step=1,
                unit_of_measurement="s",
            )
        ),
        vol.Required(
            CONF_MAX_BOOST_SECONDS, default=DEFAULT_MAX_BOOST_SECONDS
        ): NumberSelector(
            NumberSelectorConfig(
                min=MIN_BOOST_SECONDS,
                max=MAX_BOOST_SECONDS,
                mode=NumberSelectorMode.BOX,
                step=1,
                unit_of_measurement="s",
            )
        ),
        vol.Required(CONF_BRIGHTNESS, default=DEFAULT_BRIGHTNESS): NumberSelector(
            NumberSelectorConfig(
                min=MIN_BRIGHTNESS,
                max=MAX_BRIGHTNESS,
                mode=NumberSelectorMode.BOX,
                step=1,
                unit_of_measurement="%",
            )
        ),
    }
)


def _normalise_host_port(
    host_value: Any, port_value: Any, use_ssl_value: Any
) -> tuple[str, int, bool]:
    host = str(host_value).strip()
    use_ssl = bool(use_ssl_value)
    port = int(float(port_value))
    if "://" in host:
        parsed = urlsplit(host)
        if parsed.scheme:
            use_ssl = parsed.scheme.lower() == "https"
        if parsed.hostname:
            host = parsed.hostname
        if parsed.port:
            port = parsed.port
    return host, port, use_ssl


def _client(
    host: str,
    port: int,
    use_ssl: bool,
    verify_ssl: bool,
    username: str,
    password: str,
) -> HikvisionIsapiClient:
    return HikvisionIsapiClient(
        host,
        username,
        password,
        port=port,
        use_ssl=use_ssl,
        verify_ssl=verify_ssl,
    )


def _parse_time(value: Any) -> time | None:
    try:
        parsed = datetime.strptime(str(value).strip(), "%H:%M")
    except (TypeError, ValueError):
        try:
            parsed = datetime.strptime(str(value).strip(), "%H:%M:%S")
        except (TypeError, ValueError):
            return None
    return parsed.time()


def _parse_channels(value: Any) -> list[int] | None:
    """Parse comma separated NVR channel numbers into a sorted list."""
    if value is None:
        return None
    items = value if isinstance(value, (list, tuple, set)) else [value]
    channels: list[int] = []
    for item in items:
        for part in str(item).replace("，", ",").replace("+", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                channel = int(part)
            except (TypeError, ValueError):
                return None
            if not MIN_CHANNEL <= channel <= MAX_CHANNEL:
                return None
            if channel not in channels:
                channels.append(channel)
    if not channels:
        return None
    return sorted(channels)


def _parse_white_hold_seconds(value: Any) -> int | None:
    """Parse how long the white supplement light is kept after switch-off."""
    if value is None or str(value).strip() == "":
        return DEFAULT_WHITE_HOLD_SECONDS
    try:
        hold = int(value)
    except (TypeError, ValueError):
        return None
    if not MIN_WHITE_HOLD_SECONDS <= hold <= MAX_WHITE_HOLD_SECONDS:
        return None
    return hold


def _format_channels(channels: list[int] | tuple[int, ...]) -> str:
    return ", ".join(str(channel) for channel in channels)


def _current_channels(data: dict) -> list[int]:
    channels = data.get(CONF_TRIGGER_CHANNELS)
    if channels is None:
        channels = [data.get(CONF_TRIGGER_CHANNEL, DEFAULT_TRIGGER_CHANNEL)]
    parsed = _parse_channels(channels)
    if parsed is None:
        return [DEFAULT_TRIGGER_CHANNEL]
    return parsed


class HikvisionAlarmLightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one NVR-channel -> camera-light link."""

    VERSION = CONFIG_ENTRY_VERSION
    MINOR_VERSION = CONFIG_ENTRY_MINOR_VERSION

    def __init__(self) -> None:
        self._nvr_data: dict[str, Any] = {}
        self._nvr_serial = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for NVR credentials and the alarm channels."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host, port, use_ssl = _normalise_host_port(
                user_input[CONF_NVR_HOST],
                user_input[CONF_NVR_PORT],
                user_input[CONF_NVR_USE_SSL],
            )
            username = str(user_input[CONF_NVR_USERNAME]).strip()
            password = str(user_input[CONF_NVR_PASSWORD])
            trigger_channels = _parse_channels(user_input[CONF_TRIGGER_CHANNELS])
            if not host:
                errors["base"] = "invalid_host"
            elif not username:
                errors["base"] = "invalid_auth"
            elif trigger_channels is None:
                errors["base"] = "invalid_trigger_channels"
            else:
                client = _client(
                    host,
                    port,
                    use_ssl,
                    bool(user_input[CONF_NVR_VERIFY_SSL]),
                    username,
                    password,
                )
                try:
                    device = await self.hass.async_add_executor_job(
                        client.get_device_info
                    )
                    for trigger_channel in trigger_channels:
                        await self.hass.async_add_executor_job(
                            client.get_linkage_state, trigger_channel
                        )
                except HikvisionAuthError:
                    errors["base"] = "invalid_auth"
                except HikvisionConnectionError:
                    errors["base"] = "cannot_connect"
                except (HikvisionResponseError, HikvisionError) as err:
                    _LOGGER.debug("NVR validation failed: %s", err)
                    errors["base"] = "nvr_invalid"
                else:
                    self._nvr_data = {
                        CONF_NVR_HOST: host,
                        CONF_NVR_PORT: port,
                        CONF_NVR_USE_SSL: use_ssl,
                        CONF_NVR_VERIFY_SSL: bool(user_input[CONF_NVR_VERIFY_SSL]),
                        CONF_NVR_USERNAME: username,
                        CONF_NVR_PASSWORD: password,
                        CONF_TRIGGER_CHANNELS: trigger_channels,
                    }
                    self._nvr_serial = device.serial_number or host
                    return await self.async_step_camera()
                finally:
                    await self.hass.async_add_executor_job(client.close)

        return self.async_show_form(
            step_id="user",
            data_schema=NVR_CONNECT_SCHEMA,
            errors=errors,
        )

    async def async_step_camera(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for camera credentials and lighting behavior."""
        if not self._nvr_data:
            return await self.async_step_user()

        errors: dict[str, str] = {}
        if user_input is not None:
            host, port, use_ssl = _normalise_host_port(
                user_input[CONF_CAMERA_HOST],
                user_input[CONF_CAMERA_PORT],
                user_input[CONF_CAMERA_USE_SSL],
            )
            username = str(user_input[CONF_CAMERA_USERNAME]).strip()
            password = str(user_input[CONF_CAMERA_PASSWORD])
            camera_channel = int(user_input[CONF_CAMERA_CHANNEL])
            night_start = _parse_time(user_input[CONF_NIGHT_START])
            night_end = _parse_time(user_input[CONF_NIGHT_END])
            hold_seconds = int(user_input[CONF_HOLD_SECONDS])
            max_boost_seconds = int(user_input[CONF_MAX_BOOST_SECONDS])
            brightness = int(user_input[CONF_BRIGHTNESS])
            name = str(user_input[CONF_NAME]).strip() or DEFAULT_NAME

            if not host:
                errors["base"] = "invalid_host"
            elif not username:
                errors["base"] = "invalid_auth"
            elif night_start is None or night_end is None or night_start == night_end:
                errors["base"] = "invalid_night_window"
            elif not MIN_HOLD_SECONDS <= hold_seconds <= MAX_HOLD_SECONDS:
                errors["base"] = "invalid_hold_seconds"
            elif not MIN_BOOST_SECONDS <= max_boost_seconds <= MAX_BOOST_SECONDS:
                errors["base"] = "invalid_max_boost"
            elif not MIN_BRIGHTNESS <= brightness <= MAX_BRIGHTNESS:
                errors["base"] = "invalid_brightness"
            else:
                client = _client(
                    host,
                    port,
                    use_ssl,
                    bool(user_input[CONF_CAMERA_VERIFY_SSL]),
                    username,
                    password,
                )
                try:
                    device = await self.hass.async_add_executor_job(
                        client.get_device_info
                    )
                    await self.hass.async_add_executor_job(
                        client.get_supplement_light, camera_channel
                    )
                except HikvisionAuthError:
                    errors["base"] = "invalid_auth"
                except HikvisionConnectionError:
                    errors["base"] = "cannot_connect"
                except (HikvisionResponseError, HikvisionError) as err:
                    _LOGGER.debug("Camera validation failed: %s", err)
                    errors["base"] = "camera_invalid"
                else:
                    channels_key = "+".join(
                        str(channel)
                        for channel in self._nvr_data[CONF_TRIGGER_CHANNELS]
                    )
                    unique_id = (
                        f"{self._nvr_serial}:{channels_key}->"
                        f"{device.serial_number or host}:{camera_channel}"
                    )
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    data = {
                        **self._nvr_data,
                        CONF_CAMERA_HOST: host,
                        CONF_CAMERA_PORT: port,
                        CONF_CAMERA_USE_SSL: use_ssl,
                        CONF_CAMERA_VERIFY_SSL: bool(
                            user_input[CONF_CAMERA_VERIFY_SSL]
                        ),
                        CONF_CAMERA_USERNAME: username,
                        CONF_CAMERA_PASSWORD: password,
                        CONF_CAMERA_CHANNEL: camera_channel,
                        CONF_NAME: name,
                        CONF_NIGHT_START: night_start.strftime("%H:%M"),
                        CONF_NIGHT_END: night_end.strftime("%H:%M"),
                        CONF_HOLD_SECONDS: hold_seconds,
                        CONF_MAX_BOOST_SECONDS: max_boost_seconds,
                        CONF_BRIGHTNESS: brightness,
                        CONF_WHITE_HOLD_SECONDS: DEFAULT_WHITE_HOLD_SECONDS,
                    }
                    return self.async_create_entry(title=name, data=data)
                finally:
                    await self.hass.async_add_executor_job(client.close)

        return self.async_show_form(
            step_id="camera",
            data_schema=CAMERA_SCHEMA,
            errors=errors,
            description_placeholders={
                "nvr_host": str(self._nvr_data.get(CONF_NVR_HOST, "")),
                "trigger_channels": _format_channels(
                    self._nvr_data.get(CONF_TRIGGER_CHANNELS, [])
                ),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HikvisionAlarmLightOptionsFlow()


class HikvisionAlarmLightOptionsFlow(OptionsFlow):
    """Change channels, timing, brightness and the restore interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.hass.config_entries.async_get_entry(self.handler)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        merged = {**dict(entry.data), **dict(entry.options)}
        current_channels = _current_channels(merged)
        current_name = str(merged.get(CONF_NAME, DEFAULT_NAME))
        current_start = str(merged.get(CONF_NIGHT_START, "18:00"))
        current_end = str(merged.get(CONF_NIGHT_END, "06:00"))
        current_hold = int(merged.get(CONF_HOLD_SECONDS, DEFAULT_HOLD_SECONDS))
        current_max = int(merged.get(CONF_MAX_BOOST_SECONDS, DEFAULT_MAX_BOOST_SECONDS))
        current_brightness = int(merged.get(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS))
        current_white_hold = _parse_white_hold_seconds(
            merged.get(CONF_WHITE_HOLD_SECONDS)
        )
        if current_white_hold is None:
            current_white_hold = DEFAULT_WHITE_HOLD_SECONDS
        errors: dict[str, str] = {}

        if user_input is not None:
            name = str(user_input.get(CONF_NAME, "")).strip() or DEFAULT_NAME
            channels = _parse_channels(user_input.get(CONF_TRIGGER_CHANNELS))
            night_start = _parse_time(user_input.get(CONF_NIGHT_START))
            night_end = _parse_time(user_input.get(CONF_NIGHT_END))
            white_hold = _parse_white_hold_seconds(
                user_input.get(CONF_WHITE_HOLD_SECONDS)
            )
            try:
                hold_seconds = int(user_input[CONF_HOLD_SECONDS])
                max_boost_seconds = int(user_input[CONF_MAX_BOOST_SECONDS])
                brightness = int(user_input[CONF_BRIGHTNESS])
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_values"
            else:
                if channels is None:
                    errors["base"] = "invalid_trigger_channels"
                elif white_hold is None:
                    errors["base"] = "invalid_white_hold"
                elif (
                    night_start is None or night_end is None or night_start == night_end
                ):
                    errors["base"] = "invalid_night_window"
                elif not MIN_HOLD_SECONDS <= hold_seconds <= MAX_HOLD_SECONDS:
                    errors["base"] = "invalid_hold_seconds"
                elif not MIN_BOOST_SECONDS <= max_boost_seconds <= MAX_BOOST_SECONDS:
                    errors["base"] = "invalid_max_boost"
                elif not MIN_BRIGHTNESS <= brightness <= MAX_BRIGHTNESS:
                    errors["base"] = "invalid_brightness"
                elif (
                    channels != current_channels
                    and not await self._async_validate_channels(entry, channels)
                ):
                    errors["base"] = "nvr_invalid"
                if not errors:
                    options = {
                        CONF_TRIGGER_CHANNELS: channels,
                        CONF_NAME: name,
                        CONF_NIGHT_START: night_start.strftime("%H:%M"),
                        CONF_NIGHT_END: night_end.strftime("%H:%M"),
                        CONF_HOLD_SECONDS: hold_seconds,
                        CONF_MAX_BOOST_SECONDS: max_boost_seconds,
                        CONF_BRIGHTNESS: brightness,
                        CONF_WHITE_HOLD_SECONDS: white_hold,
                    }
                    self.hass.config_entries.async_update_entry(
                        entry, title=name, options=options
                    )
                    return self.async_create_entry(title="", data=options)
            current_name = name
            current_channels = channels if channels is not None else current_channels
            current_start = str(user_input.get(CONF_NIGHT_START, current_start))
            current_end = str(user_input.get(CONF_NIGHT_END, current_end))
            try:
                current_hold = int(user_input[CONF_HOLD_SECONDS])
                current_max = int(user_input[CONF_MAX_BOOST_SECONDS])
                current_brightness = int(user_input[CONF_BRIGHTNESS])
            except (KeyError, TypeError, ValueError):
                pass
            if white_hold is not None:
                current_white_hold = white_hold

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=current_name): TextSelector(),
                    vol.Required(
                        CONF_TRIGGER_CHANNELS,
                        default=_format_channels(current_channels),
                    ): TextSelector(),
                    vol.Required(
                        CONF_NIGHT_START, default=current_start
                    ): TextSelector(),
                    vol.Required(CONF_NIGHT_END, default=current_end): TextSelector(),
                    vol.Required(
                        CONF_HOLD_SECONDS, default=current_hold
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_HOLD_SECONDS,
                            max=MAX_HOLD_SECONDS,
                            mode=NumberSelectorMode.BOX,
                            step=1,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Required(
                        CONF_MAX_BOOST_SECONDS, default=current_max
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_BOOST_SECONDS,
                            max=MAX_BOOST_SECONDS,
                            mode=NumberSelectorMode.BOX,
                            step=1,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Required(
                        CONF_BRIGHTNESS, default=current_brightness
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_BRIGHTNESS,
                            max=MAX_BRIGHTNESS,
                            mode=NumberSelectorMode.BOX,
                            step=1,
                            unit_of_measurement="%",
                        )
                    ),
                    vol.Required(
                        CONF_WHITE_HOLD_SECONDS, default=current_white_hold
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_WHITE_HOLD_SECONDS,
                            max=MAX_WHITE_HOLD_SECONDS,
                            mode=NumberSelectorMode.BOX,
                            step=1,
                            unit_of_measurement="s",
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "nvr_host": str(entry.data.get(CONF_NVR_HOST, "")),
                "nvr_channels": _format_channels(current_channels),
                "camera_host": str(entry.data.get(CONF_CAMERA_HOST, "")),
                "camera_channel": str(entry.data.get(CONF_CAMERA_CHANNEL, "")),
            },
        )

    async def _async_validate_channels(
        self, entry: ConfigEntry, channels: list[int]
    ) -> bool:
        """Check that the new NVR channels expose field detection."""
        client = _client(
            str(entry.data[CONF_NVR_HOST]),
            int(entry.data[CONF_NVR_PORT]),
            bool(entry.data[CONF_NVR_USE_SSL]),
            bool(entry.data[CONF_NVR_VERIFY_SSL]),
            str(entry.data[CONF_NVR_USERNAME]),
            str(entry.data[CONF_NVR_PASSWORD]),
        )
        try:
            for channel in channels:
                await self.hass.async_add_executor_job(
                    client.get_linkage_state, channel
                )
        except (HikvisionAuthError, HikvisionConnectionError):
            _LOGGER.debug("Could not validate NVR channels", exc_info=True)
            return False
        except (HikvisionResponseError, HikvisionError) as err:
            _LOGGER.debug("NVR channel validation failed: %s", err)
            return False
        finally:
            await self.hass.async_add_executor_job(client.close)
        return True
