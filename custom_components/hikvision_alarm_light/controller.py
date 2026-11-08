"""Event-driven controller for the Hikvision alarm-light link."""

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
    DEFAULT_TRIGGER_CHANNEL,
    DEFAULT_WHITE_HOLD_SECONDS,
    DOMAIN,
    EVENT_TYPE_FIELDDETECTION,
    MAX_WHITE_HOLD_SECONDS,
    MIN_WHITE_HOLD_SECONDS,
    STORE_VERSION,
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
    camera_channel: int
    night_start: time
    night_end: time
    hold_seconds: int
    max_boost_seconds: int
    brightness: int
    white_hold_seconds: int

    @classmethod
    def from_entry(cls, data: dict) -> LinkSettings:
        return cls(
            name=str(data.get(CONF_NAME) or "后院入侵补光联动"),
            nvr_host=str(data[CONF_NVR_HOST]),
            nvr_port=int(data[CONF_NVR_PORT]),
            nvr_use_ssl=bool(data[CONF_NVR_USE_SSL]),
            nvr_verify_ssl=bool(data[CONF_NVR_VERIFY_SSL]),
            nvr_username=str(data[CONF_NVR_USERNAME]),
            nvr_password=str(data[CONF_NVR_PASSWORD]),
            trigger_channels=normalise_trigger_channels(
                data.get(CONF_TRIGGER_CHANNELS, data.get(CONF_TRIGGER_CHANNEL))
            ),
            camera_host=str(data[CONF_CAMERA_HOST]),
            camera_port=int(data[CONF_CAMERA_PORT]),
            camera_use_ssl=bool(data[CONF_CAMERA_USE_SSL]),
            camera_verify_ssl=bool(data[CONF_CAMERA_VERIFY_SSL]),
            camera_username=str(data[CONF_CAMERA_USERNAME]),
            camera_password=str(data[CONF_CAMERA_PASSWORD]),
            camera_channel=int(data[CONF_CAMERA_CHANNEL]),
            night_start=_parse_time(data[CONF_NIGHT_START]),
            night_end=_parse_time(data[CONF_NIGHT_END]),
            hold_seconds=int(data[CONF_HOLD_SECONDS]),
            max_boost_seconds=int(data[CONF_MAX_BOOST_SECONDS]),
            brightness=int(data[CONF_BRIGHTNESS]),
            white_hold_seconds=_parse_white_hold_seconds(
                data.get(CONF_WHITE_HOLD_SECONDS)
            ),
        )


def normalise_trigger_channels(value: object) -> tuple[int, ...]:
    """Return a stable, de-duplicated tuple of trigger channel numbers.

    Version 1 entries stored a single ``trigger_channel`` integer, while
    current entries store a list in ``trigger_channels``.  Both (and a
    comma-separated string from manual configuration) are accepted here.
    """
    if value is None:
        value = DEFAULT_TRIGGER_CHANNEL
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
        raise ValueError("At least one trigger channel is required")
    return tuple(sorted(channels))


def _parse_white_hold_seconds(value: object) -> int:
    """Return how long white-light supplement light is kept after switch-off."""
    if value is None or value == "":
        return DEFAULT_WHITE_HOLD_SECONDS
    try:
        hold = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_WHITE_HOLD_SECONDS
    if not MIN_WHITE_HOLD_SECONDS <= hold <= MAX_WHITE_HOLD_SECONDS:
        return DEFAULT_WHITE_HOLD_SECONDS
    return hold


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
    light_control: str | None


class AlarmLightController:
    """Subscribe to NVR alerts and control the camera's white light."""

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
        self._restore_xml: str | None = None
        self._light_control: str | None = None
        self._aux_supported = False
        self._restore_unsub: CALLBACK_TYPE | None = None
        self._guard_unsub: CALLBACK_TYPE | None = None
        self._smart_unsub: CALLBACK_TYPE | None = None
        self._smart_pending = False
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
            light_control=self._light_control,
        )

    async def async_start(self) -> None:
        """Load persisted state, recover an interrupted boost, start the stream."""
        await self._async_detect_light_control()
        stored = await self._store.async_load() or {}
        self._enabled = bool(stored.get("enabled", True))

        if stored.get("boost_active"):
            self._boost_active = True
            if self._light_control == "mode":
                self._restore_xml = stored.get("restore_xml") or build_smart_xml()
            try:
                await self._async_restore_light()
            except HikvisionError as err:
                _LOGGER.warning("Could not recover interrupted light boost: %s", err)
                self._last_error = str(err)
                self._schedule_restore(30)
        elif stored.get("smart_pending"):
            _LOGGER.info(
                "Recovering interrupted white-light hold; restoring smart light"
            )
            self._smart_pending = True
            try:
                await self._async_finish_smart_restore()
            except HikvisionError as err:
                _LOGGER.warning("Could not restore smart supplement light: %s", err)
                self._last_error = str(err)
        else:
            await self._async_read_camera_mode()

        self._reader.start()
        self._notify()

    async def _async_detect_light_control(self) -> None:
        """Prefer the camera's direct aux LIGHT switch; fall back to mode."""
        try:
            self._aux_supported = await self.hass.async_add_executor_job(
                self.camera_client.get_aux_light_support,
                self.settings.camera_channel,
            )
        except HikvisionError as err:
            _LOGGER.warning(
                "Could not query PTZ aux-light capability; falling back to mode: %s",
                err,
            )
            self._aux_supported = False
        self._light_control = "aux" if self._aux_supported else "mode"
        _LOGGER.debug("Camera light control method: %s", self._light_control)

    async def async_stop(self) -> None:
        """Stop the stream and restore the light if it is currently boosted."""
        self._running = False
        self._cancel_restore()
        self._cancel_guard()
        self._cancel_smart_restore()
        self._reader.stop()
        if self._smart_pending:
            try:
                await self._async_finish_smart_restore()
            except HikvisionError as err:
                _LOGGER.warning(
                    "Could not restore smart supplement light while stopping: %s", err
                )
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
        """Manually boost the light for the configured hold time."""
        await self._async_boost()
        self._schedule_guard()
        self._schedule_restore(self.settings.hold_seconds)
        self._notify()

    async def async_restore_light(self) -> None:
        """Manually restore the smart supplement-light mode."""
        self._cancel_restore()
        self._cancel_guard()
        self._cancel_smart_restore()
        await self._async_restore_light()
        self._notify()

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
            if self._enabled and is_night(
                now, self.settings.night_start, self.settings.night_end
            ):
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

    async def _async_boost(self) -> None:
        if self._boost_active:
            return

        if self._light_control == "aux":
            await self._async_boost_aux()
            return

        state = await self.hass.async_add_executor_job(
            self.camera_client.get_supplement_light, self.settings.camera_channel
        )
        self._camera_mode = state.mode
        restore_xml = (
            state.raw_xml if state.mode == "eventIntelligence" else build_smart_xml()
        )
        boost_xml = build_boost_xml(self.settings.brightness)

        try:
            await self.hass.async_add_executor_job(
                self.camera_client.put_supplement_light,
                self.settings.camera_channel,
                boost_xml,
            )
            new_state = await self.hass.async_add_executor_job(
                self.camera_client.get_supplement_light,
                self.settings.camera_channel,
            )
            if new_state.mode != "colorVuWhiteLight":
                raise HikvisionError(
                    f"Camera stayed in {new_state.mode} mode instead of white light."
                )
            if (
                new_state.white_light_brightness is not None
                and new_state.white_light_brightness != self.settings.brightness
            ):
                _LOGGER.warning(
                    "Camera reports white-light brightness %s instead of %s",
                    new_state.white_light_brightness,
                    self.settings.brightness,
                )
        except HikvisionError:
            # Try not to leave the camera in an unknown boosted state.
            try:
                await self.hass.async_add_executor_job(
                    self.camera_client.put_supplement_light,
                    self.settings.camera_channel,
                    restore_xml,
                )
            except HikvisionError:
                _LOGGER.exception("Could not roll back failed light boost")
            raise

        self._boost_active = True
        self._restore_xml = restore_xml
        self._camera_mode = new_state.mode
        self._boost_ends_at = dt_util.now() + timedelta(
            seconds=self.settings.max_boost_seconds
        )
        self._last_error = None
        await self._save_state()
        self._notify()
        _LOGGER.info(
            "Boosted camera %s channel %s to white light at %s%%",
            self.settings.camera_host,
            self.settings.camera_channel,
            self.settings.brightness,
        )

    async def _async_boost_aux(self) -> None:
        """Use the same direct PTZ aux LIGHT command as the camera web UI."""
        state = await self.hass.async_add_executor_job(
            self.camera_client.get_supplement_light, self.settings.camera_channel
        )
        try:
            await self.hass.async_add_executor_job(
                self.camera_client.set_aux_light,
                self.settings.camera_channel,
                True,
            )
            new_state = await self.hass.async_add_executor_job(
                self.camera_client.get_supplement_light,
                self.settings.camera_channel,
            )
            if new_state.mode != state.mode:
                _LOGGER.warning(
                    "Aux LIGHT command unexpectedly changed supplement mode "
                    "from %s to %s",
                    state.mode,
                    new_state.mode,
                )
        except HikvisionError:
            try:
                await self.hass.async_add_executor_job(
                    self.camera_client.set_aux_light,
                    self.settings.camera_channel,
                    False,
                )
            except HikvisionError:
                _LOGGER.exception("Could not roll back failed aux-light boost")
            raise

        self._boost_active = True
        self._restore_xml = None
        self._camera_mode = new_state.mode
        self._boost_ends_at = dt_util.now() + timedelta(
            seconds=self.settings.max_boost_seconds
        )
        self._last_error = None
        await self._save_state()
        self._notify()
        _LOGGER.info(
            "Boosted camera %s channel %s via PTZ aux LIGHT",
            self.settings.camera_host,
            self.settings.camera_channel,
        )

    def _schedule_smart_restore(self, hold_seconds: int) -> None:
        """Switch back to smart supplement light after *hold_seconds*."""
        self._cancel_smart_restore()
        self._smart_pending = True
        self._smart_unsub = async_call_later(
            self.hass, max(0, hold_seconds), self._async_smart_restore_timer
        )

    def _cancel_smart_restore(self) -> None:
        if self._smart_unsub is not None:
            self._smart_unsub()
            self._smart_unsub = None

    async def _async_smart_restore_timer(self, _now: datetime) -> None:
        self._smart_unsub = None
        try:
            await self._async_finish_smart_restore()
        except HikvisionError as err:
            self._last_error = str(err)
            _LOGGER.error("Could not restore smart supplement light: %s", err)
            self._notify()

    async def _async_finish_smart_restore(self) -> None:
        """Switch the supplement light back to the smart/automatic mode."""
        smart_ok = await self._async_set_supplement_mode(
            build_smart_xml(), "smart/automatic"
        )
        state = await self.hass.async_add_executor_job(
            self.camera_client.get_supplement_light,
            self.settings.camera_channel,
        )
        self._camera_mode = state.mode
        self._smart_pending = False
        if smart_ok:
            self._last_error = None
        await self._save_state()
        self._notify()
        _LOGGER.info(
            "Restored smart supplement light; camera mode is now %s", state.mode
        )

    async def _async_set_supplement_mode(self, xml_text: str, label: str) -> bool:
        """Switch the camera supplement light to a mode; failures are logged."""
        try:
            await self.hass.async_add_executor_job(
                self.camera_client.put_supplement_light,
                self.settings.camera_channel,
                xml_text,
            )
        except HikvisionError as err:
            _LOGGER.warning("Could not switch supplement light to %s: %s", label, err)
            self._last_error = str(err)
            return False
        _LOGGER.debug("Supplement light switched to %s", label)
        return True

    async def _async_restore_light(self) -> None:
        if self._light_control == "aux":
            await self.hass.async_add_executor_job(
                self.camera_client.set_aux_light,
                self.settings.camera_channel,
                False,
            )
            # The PTZ presets used previously for day/night switching also moved
            # the camera and could be dropped by the device.  Use the supplement
            # light API instead: switch to white-light supplement first, keep it
            # on for the configured hold time, then hand the light back to the
            # smart/automatic mode.  The delayed smart switch runs as an HA timer
            # so the button/service call does not block for the whole hold time.
            white_ok = await self._async_set_supplement_mode(
                build_boost_xml(self.settings.brightness), "white light"
            )
            self._boost_active = False
            self._restore_xml = None
            if white_ok:
                self._camera_mode = "colorVuWhiteLight"
            self._boost_ends_at = None
            self._cancel_restore()
            self._cancel_guard()
            hold_seconds = self.settings.white_hold_seconds if white_ok else 0
            self._schedule_smart_restore(hold_seconds)
            await self._save_state()
            self._notify()
            _LOGGER.info(
                "Switched off PTZ aux LIGHT; white supplement light will be held "
                "for %ss before restoring smart mode",
                hold_seconds,
            )
            return

        restore_xml = self._restore_xml or build_smart_xml()
        await self.hass.async_add_executor_job(
            self.camera_client.put_supplement_light,
            self.settings.camera_channel,
            restore_xml,
        )
        state = await self.hass.async_add_executor_job(
            self.camera_client.get_supplement_light,
            self.settings.camera_channel,
        )
        if state.mode == "colorVuWhiteLight":
            raise HikvisionError("Camera still reports white-light mode after restore.")
        self._boost_active = False
        self._restore_xml = None
        self._camera_mode = state.mode
        self._boost_ends_at = None
        self._last_error = None
        self._cancel_restore()
        self._cancel_guard()
        await self._save_state()
        _LOGGER.info(
            "Restored camera %s channel %s to %s mode",
            self.settings.camera_host,
            self.settings.camera_channel,
            state.mode,
        )

    async def _async_read_camera_mode(self) -> None:
        try:
            state = await self.hass.async_add_executor_job(
                self.camera_client.get_supplement_light,
                self.settings.camera_channel,
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
                "restore_xml": self._restore_xml if self._boost_active else None,
                "smart_pending": self._smart_pending,
            }
        )

    def _notify(self) -> None:
        if self._coordinator is not None:
            self._coordinator.async_set_updated_data(self.snapshot)
