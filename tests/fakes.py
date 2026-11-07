"""Fakes for the alarm-light integration tests."""

from __future__ import annotations

from typing import Any, ClassVar

from custom_components.hikvision_alarm_light.api import (
    AlertEvent,
    DeviceInfo,
    SupplementLightState,
    build_smart_xml,
    parse_supplement_light,
)


class FakeHikvisionClient:
    """Stateful replacement for HikvisionIsapiClient."""

    instances: ClassVar[list[FakeHikvisionClient]] = []
    aux_supported: ClassVar[bool] = True

    def __init__(self, host: str, username: str, password: str, **kwargs: Any) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.port = int(kwargs.get("port", 80))
        self.base_url = f"http://{host}:{self.port}"
        self.closed = False
        self.mode = "eventIntelligence"
        self.brightness = 100
        self.raw_xml = build_smart_xml()
        self.aux_on = False
        self.presets: list[int] = []
        FakeHikvisionClient.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances.clear()

    @classmethod
    def for_host(cls, host: str) -> FakeHikvisionClient:
        return next(item for item in cls.instances if item.host == host)

    def get_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            name=f"fake-{self.host}",
            model="DS-TEST",
            serial_number=f"SERIAL-{self.host}",
            firmware_version="V1.0",
            device_type="NVR" if self.host.endswith(".2") else "IPDome",
        )

    def get_linkage_state(self, channel: int) -> str:
        return "<EventTrigger><id>fielddetection-2</id></EventTrigger>"

    def get_aux_light_support(self, channel: int) -> bool:
        return self.aux_supported

    def set_aux_light(self, channel: int, on: bool, aux_id: int = 1) -> None:
        self.aux_on = on

    def goto_preset(self, channel: int, preset_id: int) -> None:
        self.presets.append(preset_id)

    def get_supplement_light(self, channel: int) -> SupplementLightState:
        if self.mode == "colorVuWhiteLight":
            self.raw_xml = (
                "<SupplementLight><supplementLightMode>colorVuWhiteLight"
                f"</supplementLightMode><whiteLightBrightness>{self.brightness}"
                "</whiteLightBrightness></SupplementLight>"
            )
        else:
            self.raw_xml = build_smart_xml()
        return parse_supplement_light(self.raw_xml)

    def put_supplement_light(self, channel: int, xml_text: str) -> None:
        state = parse_supplement_light(xml_text)
        self.mode = state.mode
        if state.white_light_brightness is not None:
            self.brightness = state.white_light_brightness
        self.raw_xml = xml_text

    def close(self) -> None:
        self.closed = True


class FakeAlertReader:
    """No-network alert reader used by controller tests."""

    instances: ClassVar[list[FakeAlertReader]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self._on_event = kwargs["on_event"]
        self._on_connection = kwargs["on_connection"]
        self.started = False
        self.stopped = False
        FakeAlertReader.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances.clear()

    @classmethod
    def latest(cls) -> FakeAlertReader:
        return cls.instances[-1]

    def start(self) -> None:
        self.started = True
        self._on_connection(True, None)

    def stop(self) -> None:
        self.stopped = True
        self._on_connection(False, None)

    def emit_event(self, event: AlertEvent) -> None:
        self._on_event(event)

    def emit_connection(self, connected: bool, error: str | None = None) -> None:
        self._on_connection(connected, error)
