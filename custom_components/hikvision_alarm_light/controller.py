"""Event-driven controller for the Hikvision alarm-light link.

The integration only uses the camera's ``supplementLight`` ISAPI interface: an
intrusion alarm switches every configured camera channel to white light
(``colorVuWhiteLight``) with the brightness regulation mode ``on`` (always on)
and the configured brightness.  When the alarm has been inactive for the
configured hold time (or the safety limit is reached) all channels are switched
back to smart supplement light (``eventIntelligence``).

The PTZ auxiliary ``LIGHT`` output is intentionally not used: on affected
firmware it also switches off the IR illuminator after the light is turned off.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import (
    AlertEvent,
    AlertStreamReader,
    HikvisionError,
    HikvisionIsapiClient,
    build_boost_xml,
    build_smart_xml,
)
from .const import (
    BOOST_LIGHT_MODE,
    CONF_BRIGHTNESS,
    CONF_CAMERA_CHANNEL,
    CONF_CAMERA_CHANNELS,
    CONF_CAMERA_HOST,
    CONF_CAMERA_PASSWORD,
    CONF_CAMERA_PORT,
    CONF_CAMERA_USE_SSL,
    CONF_CAMERA_USERNAME,
    CONF_CAMERA_VERIFY_SSL,
    CONF_FOLLOW_SUN,
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
    DEFAULT_CAMERA_CHANNEL,
    DEFAULT_FOLLOW_SUN,
    DEFAULT_NAME,
    DEFAULT_TRIGGER_CHANNEL,
    DOMAIN,
    EVENT_TYPE_FIELDDETECTION,
    RESTORE_LIGHT_MODE,
    STORE_VERSION,
    SUN_ENTITY_ID,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LinkSettings:
    """Resolved settings of a link config entry."""

    name: str
    nvr_host: str
    nvr_port: int
    nvr_use_ssl: bool
    nvr_verify_ssl: bool
    nvr_username: str
    nvr_password: str
    trigger_channels: tuple[int, ...]
    camera_host: str
    camera_port: int
    camera_use_ssl: bool
    camera_verify_ssl: bool
    camera_username: str
    camera_password: str
    camera_channels: tuple[int, ...]
    follow_sun: bool
    night_start: time
    night_end: time
    hold_seconds: int
    max_boost_seconds: int
    brightness: int

    @classmethod
    def from_entry(cls, data: dict) -> LinkSettings:
        return cls(
            name=str(data.get(CONF_NAME) or DEFAULT_NAME),
            nvr_host=str(data[CONF_NVR_HOST]),
            nvr_port=int(data[CONF_NVR_PORT]),
            nvr_use_ssl=bool(data[CONF_NVR_USE_SSL]),
            nvr_verify_ssl=bool(data[CONF_NVR_VERIFY_SSL]),
            nvr_username=str(data[CONF_NVR_USERNAME]),
            nvr_password=str(data[CONF_NVR_PASSWORD]),
            trigger_channels=_normalise_channels(
                data.get(CONF_TRIGGER_CHANNELS, data.get(CONF_TRIGGER_CHANNEL)),
                DEFAULT_TRIGGER_CHANNEL,
            ),
            camera_host=str(data[CONF_CAMERA_HOST]),
            camera_port=int(data[CONF_CAMERA_PORT]),
            camera_use_ssl=bool(data[CONF_CAMERA_USE_SSL]),
            camera_verify_ssl=bool(data[CONF_CAMERA_VERIFY_SSL]),
            camera_username=str(data[CONF_CAMERA_USERNAME]),
            camera_password=str(data[CONF_CAMERA_PASSWORD]),
            camera_channels=_normalise_channels(
                data.get(CONF_CAMERA_CHANNELS, data.get(CONF_CAMERA_CHANNEL)),
                DEFAULT_CAMERA_CHANNEL,
            ),
            follow_sun=bool(data.get(CONF_FOLLOW_SUN, DEFAULT_FOLLOW_SUN)),
            night_start=_parse_time(data[CONF_NIGHT_START]),
            night_end=_parse_time(data[CONF_NIGHT_END]),
            hold_seconds=int(data[CONF_HOLD_SECONDS]),
            max_boost_seconds=int(data[CONF_MAX_BOOST_SECONDS]),
            brightness=int(data[CONF_BRIGHTNESS]),
        )


def _normalise_channels(value: object, default: int) -> tuple[int, ...]:
    """Return a stable, de-duplicated tuple of channel numbers.

    Entries written by older versions stored a single channel as an integer;
    newer entries store a list.  Both (and a comma-separated string from manual
    configuration) are accepted here.
    """
    if value is None:
        value = default
    elif isinstance(value, (int, str)):
        value = (value,)
    channels: list[int] = []
    for item in value:
        for part in str(item).replace("，", ",").replace("+", ",").split(","):
            part = part.strip()
            if not part:
                continue
            channel = int(part)
            if channel not in channels:
                channels.append(channel)
    if not channels:
        raise ValueError("At least one channel is required")
    return tuple(sorted(channels))


def normalise_trigger_channels(value: object) -> tuple[int, ...]:
    """Normalise the NVR alarm channel selection."""
    return _normalise_channels(value, DEFAULT_TRIGGER_CHANNEL)


def normalise_camera_channels(value: object) -> tuple[int, ...]:
    """Normalise the camera supplement-light channel selection."""
    return _normalise_channels(value, DEFAULT_CAMERA_CHANNEL)


def _parse_time(value: str | time) -> time:
    if isinstance(value, time):
        return value
    parts = str(value).strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time value: {value!r}")
    return time(int(parts[0]), int(parts[1]))


def is_night(now: datetime, start: time, end: time) -> bool:
    """Return whether *now* falls inside the night window."""
    if start == end:
        return False
    current = now.time()
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _format_modes(modes: list[str]) -> str | None:
    unique = sorted({mode for mode in modes if mode})
    if not unique:
        return None
    return ",".join(unique)


@dataclass(frozen=True, slots=True)
class LinkSnapshot:
    """Current state exposed to the entities."""

    enabled: bool
    alarm_active: bool
    boost_active: bool
    last_alarm: datetime | None
    last_event_type: str | None
    last_event_channel: int | None
    last_event_at: datetime | None
    stream_connected: bool
    stream_error: str | None
    camera_mode: str | None
    boost_ends_at: datetime | None
    last_error: str | None


class AlarmLightController:
    """Subscribe to NVR alerts and control the cameras' supplement light."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        settings: LinkSettings,
        nvr_client: HikvisionIsapiClient,
        camera_client: HikvisionIsapiClient,
        *,
        reader_factory: Callable[..., AlertStreamReader] | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.settings = settings
        self.nvr_client = nvr_client
        self.camera_client = camera_client
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._coordinator = None

        self._enabled = True
        self._alarm_active = False
        self._boost_active = False
        self._last_alarm: datetime | None = None
        self._last_event_type: str | None = None
        self._last_event_channel: int | None = None
        self._last_event_at: datetime | None = None
        self._stream_connected = False
        self._stream_error: str | None = None
        self._camera_mode: str | None = None
        self._boost_ends_at: datetime | None = None
        self._last_error: str | None = None
        self._restore_unsub: CALLBACK_TYPE | None = None
        self._guard_unsub: CALLBACK_TYPE | None = None
        self._sun_missing_logged = False
        self._running = False

        factory = reader_factory or AlertStreamReader
        self._reader = factory(
            host=settings.nvr_host,
            username=settings.nvr_username,
            password=settings.nvr_password,
            port=settings.nvr_port,
            use_ssl=settings.nvr_use_ssl,
            verify_ssl=settings.nvr_verify_ssl,
            on_event=self._reader_on_event,
            on_connection=self._reader_on_connection,
        )

    def attach_coordinator(self, coordinator) -> None:
        """Attach the coordinator used to publish state updates."""
        self._coordinator = coordinator

    @property
    def snapshot(self) -> LinkSnapshot:
        return LinkSnapshot(
            enabled=self._enabled,
            alarm_active=self._alarm_active,
            boost_active=self._boost_active,
            last_alarm=self._last_alarm,
            last_event_type=self._last_event_type,
            last_event_channel=self._last_event_channel,
            last_event_at=self._last_event_at,
            stream_connected=self._stream_connected,
            stream_error=self._stream_error,
            camera_mode=self._camera_mode,
            boost_ends_at=self._boost_ends_at,
            last_error=self._last_error,
        )

    async def async_start(self) -> None:
        """Load persisted state and start the alert stream."""
        stored = await self._store.async_load() or {}
        self._enabled = bool(stored.get("enabled", True))

        if stored.get("boost_active"):
            _LOGGER.info(
                "Recovering interrupted white-light boost; restoring smart mode"
            )
            self._boost_active = True
            try:
                await self._async_restore_light()
            except HikvisionError as err:
                _LOGGER.warning("Could not recover interrupted light boost: %s", err)
                self._last_error = str(err)
                self._schedule_restore(30)
        else:
            await self._async_read_camera_mode()

        self._reader.start()
        self._notify()

    async def async_stop(self) -> None:
        """Stop the stream and restore the smart supplement-light mode."""
        self._running = False
        self._cancel_restore()
        self._cancel_guard()
        self._reader.stop()
        if self._boost_active:
            try:
                await self._async_restore_light()
            except HikvisionError as err:
                _LOGGER.warning("Could not restore light while stopping: %s", err)
        await self._save_state()

    async def async_set_enabled(self, enabled: bool) -> None:
        """Enable or disable automatic alarm handling."""
        self._enabled = enabled
        await self._save_state()
        self._notify()

    async def async_test_boost(self) -> None:
        """Manually switch the white light on for the configured hold time."""
        await self._async_boost()
        self._schedule_guard()
        self._schedule_restore(self.settings.hold_seconds)
        self._notify()

    async def async_restore_light(self) -> None:
        """Manually restore the smart supplement-light mode."""
        self._cancel_restore()
        self._cancel_guard()
        await self._async_restore_light()
        self._notify()

    async def async_turn_light_on(self) -> None:
        """Switch the white light on and keep it on until switched off.

        The safety guard still switches the light off after the configured
        ``max_boost_seconds`` so a forgotten switch cannot leave it on forever.
        """
        if self._boost_active:
            return
        self._cancel_restore()
        await self._async_boost()
        self._schedule_guard()
        self._notify()
        _LOGGER.info("Alarm light switched on manually")

    async def async_turn_light_off(self) -> None:
        """Switch the white light off and restore the smart supplement mode."""
        self._cancel_restore()
        self._cancel_guard()
        if not self._boost_active:
            self._notify()
            return
        await self._async_restore_light()
        self._notify()
        _LOGGER.info("Alarm light switched off manually")

    def _reader_on_event(self, event: AlertEvent) -> None:
        try:
            self.hass.loop.call_soon_threadsafe(self._handle_event, event)
        except RuntimeError:
            # Home Assistant is shutting down.
            pass

    def _reader_on_connection(self, connected: bool, error: str | None) -> None:
        try:
            self.hass.loop.call_soon_threadsafe(
                self._handle_connection, connected, error
            )
        except RuntimeError:
            pass

    @callback
    def _handle_event(self, event: AlertEvent) -> None:
        self.hass.async_create_task(self._async_handle_event(event))

    @callback
    def _handle_connection(self, connected: bool, error: str | None) -> None:
        self._stream_connected = connected
        self._stream_error = None if connected else error
        self._notify()

    async def _async_handle_event(self, event: AlertEvent) -> None:
        if (
            event.event_type != EVENT_TYPE_FIELDDETECTION
            or event.channel not in self.settings.trigger_channels
        ):
            return

        now = dt_util.now()
        self._last_event_type = event.event_type
        self._last_event_channel = event.channel
        self._last_event_at = now

        if event.event_state == "active":
            self._alarm_active = True
            self._last_alarm = now
            if self._enabled and self._is_night_now(now):
                try:
                    await self._async_boost()
                except HikvisionError as err:
                    self._last_error = str(err)
                    _LOGGER.error("Could not enable alarm lighting: %s", err)
            if self._boost_active:
                self._cancel_restore()
                self._schedule_guard()
            self._notify()
        elif event.event_state == "inactive":
            self._alarm_active = False
            if self._boost_active:
                self._schedule_restore(self.settings.hold_seconds)
            self._notify()

    def _is_night_now(self, now: datetime) -> bool:
        """Return whether it is currently night.

        By default the sun integration's ``sun.sun`` entity is used so the
        night window follows the sunrise/sunset times shown by the Home
        Assistant weather card.  If the sun entity is missing the configured
        fixed window is used as a fallback.
        """
        if self.settings.follow_sun:
            sun = self.hass.states.get(SUN_ENTITY_ID)
            if sun is not None:
                self._sun_missing_logged = False
                if sun.state == "below_horizon":
                    _LOGGER.debug("Night check: sun is below the horizon")
                    return True
                if sun.state == "above_horizon":
                    _LOGGER.debug("Night check: sun is above the horizon")
                    return False
                rising = dt_util.parse_datetime(str(sun.attributes.get("next_rising")))
                setting = dt_util.parse_datetime(
                    str(sun.attributes.get("next_setting"))
                )
                if rising is not None and setting is not None:
                    night = rising < setting
                    _LOGGER.debug(
                        "Night check: sun state %s, next rising %s, next setting %s "
                        "-> %s",
                        sun.state,
                        rising,
                        setting,
                        night,
                    )
                    return night
            elif not self._sun_missing_logged:
                self._sun_missing_logged = True
                _LOGGER.warning(
                    "sun.sun entity not found; falling back to the fixed night "
                    "window %s-%s",
                    self.settings.night_start.strftime("%H:%M"),
                    self.settings.night_end.strftime("%H:%M"),
                )
        return is_night(now, self.settings.night_start, self.settings.night_end)

    async def _async_boost(self) -> None:
        """Switch every configured camera channel to white light."""
        if self._boost_active:
            return

        white_xml = build_boost_xml(self.settings.brightness)
        changed: list[int] = []
        try:
            for channel in self.settings.camera_channels:
                await self._async_put_supplement_light(channel, white_xml)
                changed.append(channel)
            for channel in self.settings.camera_channels:
                state = await self.hass.async_add_executor_job(
                    self.camera_client.get_supplement_light, channel
                )
                if state.mode != BOOST_LIGHT_MODE:
                    raise HikvisionError(
                        f"Camera channel {channel} is in {state.mode} mode "
                        "instead of white light."
                    )
        except HikvisionError:
            # Try not to leave the camera in an unknown boosted state.
            for channel in changed:
                try:
                    await self._async_put_supplement_light(channel, build_smart_xml())
                except HikvisionError:
                    _LOGGER.exception("Could not roll back failed light boost")
            raise

        self._boost_active = True
        self._camera_mode = BOOST_LIGHT_MODE
        self._boost_ends_at = dt_util.now() + timedelta(
            seconds=self.settings.max_boost_seconds
        )
        self._last_error = None
        await self._save_state()
        self._notify()
        _LOGGER.info(
            "Boosted camera %s channels %s to white light at %s%% (always on)",
            self.settings.camera_host,
            ", ".join(str(channel) for channel in self.settings.camera_channels),
            self.settings.brightness,
        )

    async def _async_put_supplement_light(self, channel: int, xml_text: str) -> None:
        """Send one supplement-light document to a camera channel."""
        await self.hass.async_add_executor_job(
            self.camera_client.put_supplement_light,
            channel,
            xml_text,
        )

    async def _async_restore_channel(self, channel: int) -> bool:
        """Switch one camera channel back to smart supplement light."""
        try:
            await self._async_put_supplement_light(channel, build_smart_xml())
        except HikvisionError as err:
            _LOGGER.warning(
                "Could not restore smart supplement light on camera channel %s: %s",
                channel,
                err,
            )
            self._last_error = str(err)
            return False
        _LOGGER.debug(
            "Supplement light on camera channel %s switched back to smart mode",
            channel,
        )
        return True

    async def _async_restore_light(self) -> None:
        """Switch every camera channel back to smart supplement light."""
        restored = [
            await self._async_restore_channel(channel)
            for channel in self.settings.camera_channels
        ]

        states = []
        for channel in self.settings.camera_channels:
            try:
                states.append(
                    await self.hass.async_add_executor_job(
                        self.camera_client.get_supplement_light, channel
                    )
                )
            except HikvisionError as err:
                _LOGGER.warning(
                    "Could not read supplement light state of camera channel %s: %s",
                    channel,
                    err,
                )
                states.append(None)

        modes = [state.mode for state in states if state is not None]
        camera_mode = _format_modes(modes)
        if camera_mode is not None:
            self._camera_mode = camera_mode
        if (
            all(restored)
            and modes
            and all(mode == RESTORE_LIGHT_MODE for mode in modes)
        ):
            self._last_error = None
        self._boost_active = False
        self._boost_ends_at = None
        self._cancel_restore()
        self._cancel_guard()
        await self._save_state()
        self._notify()
        _LOGGER.info(
            "Switched camera %s channels %s back to smart supplement light",
            self.settings.camera_host,
            ", ".join(str(channel) for channel in self.settings.camera_channels),
        )

    async def _async_read_camera_mode(self) -> None:
        try:
            state = await self.hass.async_add_executor_job(
                self.camera_client.get_supplement_light,
                self.settings.camera_channels[0],
            )
        except HikvisionError as err:
            _LOGGER.warning("Could not read camera supplement light: %s", err)
            self._last_error = str(err)
            return
        self._camera_mode = state.mode

    async def _async_restore_timer(self, _now: datetime) -> None:
        self._restore_unsub = None
        try:
            await self._async_restore_light()
        except HikvisionError as err:
            self._last_error = str(err)
            _LOGGER.error("Could not restore alarm lighting: %s", err)
            if self._boost_active:
                self._schedule_restore(30)
        self._notify()

    async def _async_guard_timer(self, _now: datetime) -> None:
        self._guard_unsub = None
        if not self._boost_active:
            return
        _LOGGER.warning(
            "Alarm light guard expired after %ss; restoring smart mode",
            self.settings.max_boost_seconds,
        )
        try:
            await self._async_restore_light()
        except HikvisionError as err:
            self._last_error = str(err)
            self._schedule_restore(30)
        self._notify()

    def _schedule_restore(self, delay: int) -> None:
        if not self._boost_active:
            return
        self._cancel_restore()
        self._boost_ends_at = dt_util.now() + timedelta(seconds=delay)
        self._restore_unsub = async_call_later(
            self.hass, delay, self._async_restore_timer
        )
        self._notify()

    def _schedule_guard(self) -> None:
        if not self._boost_active:
            return
        self._cancel_guard()
        self._boost_ends_at = dt_util.now() + timedelta(
            seconds=self.settings.max_boost_seconds
        )
        self._guard_unsub = async_call_later(
            self.hass, self.settings.max_boost_seconds, self._async_guard_timer
        )
        self._notify()

    def _cancel_restore(self) -> None:
        if self._restore_unsub is not None:
            self._restore_unsub()
            self._restore_unsub = None
        self._boost_ends_at = None

    def _cancel_guard(self) -> None:
        if self._guard_unsub is not None:
            self._guard_unsub()
            self._guard_unsub = None

    async def _save_state(self) -> None:
        await self._store.async_save(
            {
                "enabled": self._enabled,
                "boost_active": self._boost_active,
            }
        )

    def _notify(self) -> None:
        if self._coordinator is not None:
            self._coordinator.async_set_updated_data(self.snapshot)
