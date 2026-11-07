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
    DOMAIN,
    MAX_BOOST_SECONDS,
    MAX_BRIGHTNESS,
    MAX_HOLD_SECONDS,
    MIN_BOOST_SECONDS,
    MIN_BRIGHTNESS,
    MIN_HOLD_SECONDS,
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
            CONF_TRIGGER_CHANNEL, default=DEFAULT_TRIGGER_CHANNEL
        ): NumberSelector(
            NumberSelectorConfig(min=1, max=64, mode=NumberSelectorMode.BOX, step=1)
        ),
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


class HikvisionAlarmLightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one NVR-channel -> camera-light link."""

    VERSION = 1

    def __init__(self) -> None:
        self._nvr_data: dict[str, Any] = {}
        self._nvr_serial = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for NVR credentials and the alarm channel."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host, port, use_ssl = _normalise_host_port(
                user_input[CONF_NVR_HOST],
                user_input[CONF_NVR_PORT],
                user_input[CONF_NVR_USE_SSL],
            )
            username = str(user_input[CONF_NVR_USERNAME]).strip()
            password = str(user_input[CONF_NVR_PASSWORD])
            if not host:
                errors["base"] = "invalid_host"
            elif not username:
                errors["base"] = "invalid_auth"
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
                    await self.hass.async_add_executor_job(
                        client.get_linkage_state, int(user_input[CONF_TRIGGER_CHANNEL])
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
                        CONF_TRIGGER_CHANNEL: int(user_input[CONF_TRIGGER_CHANNEL]),
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
                    unique_id = (
                        f"{self._nvr_serial}:"
                        f"{self._nvr_data[CONF_TRIGGER_CHANNEL]}->"
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
                "trigger_channel": str(self._nvr_data.get(CONF_TRIGGER_CHANNEL, "")),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HikvisionAlarmLightOptionsFlow()


class HikvisionAlarmLightOptionsFlow(OptionsFlow):
    """Change timing and brightness without touching credentials."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.hass.config_entries.async_get_entry(self.handler)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        merged = {**dict(entry.data), **dict(entry.options)}
        current_name = str(merged.get(CONF_NAME, DEFAULT_NAME))
        current_start = str(merged.get(CONF_NIGHT_START, "18:00"))
        current_end = str(merged.get(CONF_NIGHT_END, "06:00"))
        current_hold = int(merged.get(CONF_HOLD_SECONDS, DEFAULT_HOLD_SECONDS))
        current_max = int(merged.get(CONF_MAX_BOOST_SECONDS, DEFAULT_MAX_BOOST_SECONDS))
        current_brightness = int(merged.get(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS))
        errors: dict[str, str] = {}

        if user_input is not None:
            name = str(user_input.get(CONF_NAME, "")).strip() or DEFAULT_NAME
            night_start = _parse_time(user_input.get(CONF_NIGHT_START))
            night_end = _parse_time(user_input.get(CONF_NIGHT_END))
            try:
                hold_seconds = int(user_input[CONF_HOLD_SECONDS])
                max_boost_seconds = int(user_input[CONF_MAX_BOOST_SECONDS])
                brightness = int(user_input[CONF_BRIGHTNESS])
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_values"
            else:
                if night_start is None or night_end is None or night_start == night_end:
                    errors["base"] = "invalid_night_window"
                elif not MIN_HOLD_SECONDS <= hold_seconds <= MAX_HOLD_SECONDS:
                    errors["base"] = "invalid_hold_seconds"
                elif not MIN_BOOST_SECONDS <= max_boost_seconds <= MAX_BOOST_SECONDS:
                    errors["base"] = "invalid_max_boost"
                elif not MIN_BRIGHTNESS <= brightness <= MAX_BRIGHTNESS:
                    errors["base"] = "invalid_brightness"
                if not errors:
                    options = {
                        CONF_NAME: name,
                        CONF_NIGHT_START: night_start.strftime("%H:%M"),
                        CONF_NIGHT_END: night_end.strftime("%H:%M"),
                        CONF_HOLD_SECONDS: hold_seconds,
                        CONF_MAX_BOOST_SECONDS: max_boost_seconds,
                        CONF_BRIGHTNESS: brightness,
                    }
                    self.hass.config_entries.async_update_entry(
                        entry, title=name, options=options
                    )
                    return self.async_create_entry(title="", data=options)
            current_name = name
            current_start = str(user_input.get(CONF_NIGHT_START, current_start))
            current_end = str(user_input.get(CONF_NIGHT_END, current_end))
            try:
                current_hold = int(user_input[CONF_HOLD_SECONDS])
                current_max = int(user_input[CONF_MAX_BOOST_SECONDS])
                current_brightness = int(user_input[CONF_BRIGHTNESS])
            except (KeyError, TypeError, ValueError):
                pass

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=current_name): TextSelector(),
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
                }
            ),
            errors=errors,
            description_placeholders={
                "nvr_host": str(entry.data.get(CONF_NVR_HOST, "")),
                "nvr_channel": str(entry.data.get(CONF_TRIGGER_CHANNEL, "")),
                "camera_host": str(entry.data.get(CONF_CAMERA_HOST, "")),
                "camera_channel": str(entry.data.get(CONF_CAMERA_CHANNEL, "")),
            },
        )
