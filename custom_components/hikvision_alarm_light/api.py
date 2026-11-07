"""Low-level Hikvision ISAPI helpers for the alarm-light link integration.

The NVR exposes alarm events on a long-lived multipart ``alertStream``.  The
camera exposes its supplement-light configuration (including the smart /
white-light modes) under ``/ISAPI/Image/channels/<n>/supplementLight``.

This module is synchronous and Home Assistant independent so it can be unit
tested in isolation and run from a worker thread.
"""

from __future__ import annotations

import logging
import re
import threading
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

_LOGGER = logging.getLogger(__name__)

DEVICE_INFO_PATH = "/ISAPI/System/deviceInfo"
FIELD_DETECTION_TRIGGER_PATH = "/ISAPI/Event/triggers/fielddetection-{channel}"
ALERT_STREAM_PATH = "/ISAPI/Event/notification/alertStream"
SUPPLEMENT_LIGHT_PATH = "/ISAPI/Image/channels/{channel}/supplementLight"

XML_CONTENT_TYPE = "application/xml; charset=UTF-8"
BOOST_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<supplementLightMode>colorVuWhiteLight</supplementLightMode>
<whiteLightBrightness>{brightness}</whiteLightBrightness>
</SupplementLight>
"""

SMART_XML = """<?xml version="1.0" encoding="UTF-8"?>
<SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<supplementLightMode>eventIntelligence</supplementLightMode>
<EventIntelligenceModeCfg>
<brightnessRegulatMode>auto</brightnessRegulatMode>
<whiteLightBrightness>100</whiteLightBrightness>
<irLightBrightness>100</irLightBrightness>
</EventIntelligenceModeCfg>
</SupplementLight>
"""


class HikvisionError(Exception):
    """Base error for ISAPI operations."""


class HikvisionConnectionError(HikvisionError):
    """The device could not be reached."""


class HikvisionAuthError(HikvisionError):
    """The device rejected the credentials."""


class HikvisionResponseError(HikvisionError):
    """The device returned an error document."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        status_code: str | None = None,
        status_string: str | None = None,
        sub_status_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.status_code = status_code
        self.status_string = status_string
        self.sub_status_code = sub_status_code


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Basic device information."""

    name: str
    model: str
    serial_number: str
    firmware_version: str
    device_type: str


@dataclass(frozen=True, slots=True)
class SupplementLightState:
    """Current supplement-light configuration of a camera channel."""

    mode: str
    white_light_brightness: int | None
    ir_light_brightness: int | None
    raw_xml: str


@dataclass(frozen=True, slots=True)
class AlertEvent:
    """One alert event received from the NVR alert stream."""

    event_type: str
    event_state: str
    channel: int | None
    channel_name: str | None
    date_time: str | None
    raw_xml: str


def local_name(tag: str) -> str:
    """Return an XML tag without its namespace."""
    return tag.rsplit("}", 1)[-1]


def _first_child(element: ET.Element, name: str) -> ET.Element | None:
    for child in element:
        if local_name(child.tag) == name:
            return child
    return None


def _child_text(element: ET.Element, name: str, default: str = "") -> str:
    child = _first_child(element, name)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _parse_xml(text: str) -> ET.Element:
    if not text or not text.strip():
        raise HikvisionResponseError("The device returned an empty response.")
    try:
        return ET.fromstring(text)
    except ET.ParseError as err:
        raise HikvisionResponseError(f"The device returned invalid XML: {err}") from err


def _response_status(root: ET.Element) -> tuple[str, str, str]:
    return (
        _child_text(root, "statusCode"),
        _child_text(root, "statusString"),
        _child_text(root, "subStatusCode"),
    )


def parse_alert_event(payload: bytes | str) -> AlertEvent | None:
    """Parse one XML part of the NVR alert stream.

    Returns ``None`` for keepalive frames or documents that are not
    ``EventNotificationAlert``.
    """
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = payload.decode("utf-8", errors="replace")
    else:
        text = payload
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    if local_name(root.tag) != "EventNotificationAlert":
        return None

    channel_text = ""
    for channel_key in (
        "channelID",
        "dynChannelID",
        "dynVideoInputChannelID",
        "videoInputChannelID",
    ):
        channel_text = _child_text(root, channel_key)
        if channel_text:
            break
    try:
        channel = int(channel_text)
    except (TypeError, ValueError):
        channel = None

    return AlertEvent(
        event_type=_child_text(root, "eventType").lower(),
        event_state=_child_text(root, "eventState").lower(),
        channel=channel,
        channel_name=_child_text(root, "channelName") or None,
        date_time=_child_text(root, "dateTime") or None,
        raw_xml=text,
    )


def parse_supplement_light(xml_text: str) -> SupplementLightState:
    """Parse a SupplementLight document."""
    root = _parse_xml(xml_text)
    if local_name(root.tag) == "ResponseStatus":
        raise _supplement_error(root)
    if local_name(root.tag) != "SupplementLight":
        raise HikvisionResponseError(
            f"Unexpected supplement-light document: <{local_name(root.tag)}>."
        )

    mode = _child_text(root, "supplementLightMode")
    white = _child_text(root, "whiteLightBrightness")
    ir = _child_text(root, "irLightBrightness")
    event_cfg = _first_child(root, "EventIntelligenceModeCfg")
    if event_cfg is not None:
        if not white:
            white = _child_text(event_cfg, "whiteLightBrightness")
        if not ir:
            ir = _child_text(event_cfg, "irLightBrightness")

    def _int_or_none(value: str) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return SupplementLightState(
        mode=mode,
        white_light_brightness=_int_or_none(white),
        ir_light_brightness=_int_or_none(ir),
        raw_xml=xml_text,
    )


def build_boost_xml(brightness: int = 100) -> str:
    """Return XML that turns the white light on at the requested brightness."""
    return BOOST_XML_TEMPLATE.format(brightness=max(1, min(100, int(brightness))))


def build_smart_xml() -> str:
    """Return the canonical "smart supplement light" XML."""
    return SMART_XML


def extract_multipart_parts(
    buffer: bytes, boundary: str | bytes
) -> tuple[list[bytes], bytes]:
    """Split completed Hikvision multipart frames out of *buffer*.

    Returns ``(completed_parts, remaining_buffer)``.  Hikvision sends
    ``Content-Length`` for every part, so binary-safe parsing is possible.
    """
    if isinstance(boundary, str):
        boundary = boundary.encode()
    delimiter = b"--" + boundary
    parts: list[bytes] = []

    while True:
        index = buffer.find(delimiter)
        if index == -1:
            # Keep a possibly split boundary at the end of the buffer.
            keep = 0
            for size in range(1, min(len(delimiter), len(buffer)) + 1):
                if delimiter.startswith(buffer[-size:]):
                    keep = size
            return parts, buffer[-keep:] if keep else b""
        pos = index + len(delimiter)
        if buffer[pos : pos + 2] == b"--":
            return parts, b""
        line_end = buffer.find(b"\r\n", pos)
        if line_end == -1:
            return parts, buffer[index:]
        header_start = line_end + 2
        header_end = buffer.find(b"\r\n\r\n", header_start)
        if header_end == -1:
            return parts, buffer[index:]
        headers = buffer[header_start:header_end]
        length_match = re.search(rb"Content-Length:\s*(\d+)", headers, re.IGNORECASE)
        if length_match is None:
            buffer = buffer[header_end + 4 :]
            continue
        length = int(length_match.group(1))
        body_start = header_end + 4
        body_end = body_start + length
        if len(buffer) < body_end:
            return parts, buffer[index:]
        parts.append(buffer[body_start:body_end])
        buffer = buffer[body_end:]
        if buffer.startswith(b"\r\n"):
            buffer = buffer[2:]
        elif buffer.startswith(b"\n"):
            buffer = buffer[1:]


def _supplement_error(root: ET.Element) -> HikvisionResponseError:
    status_code, status_string, sub_status_code = _response_status(root)
    message = status_string or "The camera rejected the supplement-light request."
    if status_code:
        message += f" (statusCode={status_code}"
        if sub_status_code:
            message += f", subStatusCode={sub_status_code}"
        message += ")"
    return HikvisionResponseError(
        message,
        status_code=status_code or None,
        status_string=status_string or None,
        sub_status_code=sub_status_code or None,
    )


def _decode_response(response: requests.Response) -> str:
    content = response.content
    if not content:
        return ""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


class HikvisionIsapiClient:
    """Small HTTP Digest client for an NVR or camera."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 80,
        use_ssl: bool = False,
        verify_ssl: bool = False,
        timeout: int = 12,
        session: requests.Session | None = None,
    ) -> None:
        self.host = host.strip()
        self.port = int(port)
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.scheme = "https" if use_ssl else "http"
        self._session = session or requests.Session()
        # These are LAN devices; ignore desktop HTTP proxy environment vars.
        self._session.trust_env = False
        self._session.auth = HTTPDigestAuth(username, password)
        self._session.headers.update(
            {
                "Accept": "application/xml",
                "User-Agent": "HomeAssistant-HikvisionAlarmLight/1.0",
            }
        )

    @property
    def base_url(self) -> str:
        host = self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        default_port = 443 if self.use_ssl else 80
        if self.port == default_port:
            return f"{self.scheme}://{host}"
        return f"{self.scheme}://{host}:{self.port}"

    def close(self) -> None:
        self._session.close()

    def _request(self, method: str, path: str, *, body: str | None = None) -> str:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {}
        if body is not None:
            headers["Content-Type"] = XML_CONTENT_TYPE
        try:
            response = self._session.request(
                method,
                url,
                data=body.encode("utf-8") if body is not None else None,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
                allow_redirects=False,
            )
        except requests.exceptions.Timeout as err:
            raise HikvisionConnectionError(
                f"Timed out while connecting to {self.base_url}."
            ) from err
        except requests.exceptions.SSLError as err:
            raise HikvisionConnectionError(
                f"TLS error while connecting to {self.base_url}: {err}"
            ) from err
        except requests.exceptions.RequestException as err:
            raise HikvisionConnectionError(
                f"Could not connect to {self.base_url}: {err}"
            ) from err

        text = _decode_response(response)
        if response.status_code == 401:
            auth_header = response.headers.get("WWW-Authenticate", "")
            if (
                isinstance(self._session.auth, HTTPDigestAuth)
                and "basic" in auth_header.lower()
                and "digest" not in auth_header.lower()
            ):
                self._session.auth = HTTPBasicAuth(self.username, self.password)
                return self._request(method, path, body=body)
            raise HikvisionAuthError(
                f"Authentication with {self.base_url} failed (HTTP 401)."
            )
        if response.status_code >= 400:
            raise _make_response_error(response, text, method, path)
        try:
            root = ET.fromstring(text) if text.strip() else None
        except ET.ParseError:
            root = None
        if root is not None and local_name(root.tag) == "ResponseStatus":
            status_code, _, _ = _response_status(root)
            if status_code not in ("", "1"):
                raise _supplement_error(root)
        return text

    def get_device_info(self) -> DeviceInfo:
        root = _parse_xml(self._request("GET", DEVICE_INFO_PATH))
        if local_name(root.tag) == "ResponseStatus":
            raise _supplement_error(root)
        if local_name(root.tag) != "DeviceInfo":
            raise HikvisionResponseError(
                f"Unexpected device info document: <{local_name(root.tag)}>."
            )
        return DeviceInfo(
            name=_child_text(root, "deviceName") or "Hikvision device",
            model=_child_text(root, "model") or "Hikvision device",
            serial_number=_child_text(root, "serialNumber")
            or _child_text(root, "deviceID"),
            firmware_version=_child_text(root, "firmwareVersion"),
            device_type=_child_text(root, "deviceType"),
        )

    def get_linkage_state(self, channel: int) -> str:
        """Read and validate the field-detection event trigger."""
        text = self._request(
            "GET", FIELD_DETECTION_TRIGGER_PATH.format(channel=channel)
        )
        root = _parse_xml(text)
        if local_name(root.tag) == "ResponseStatus":
            raise _supplement_error(root)
        if local_name(root.tag) != "EventTrigger":
            raise HikvisionResponseError(
                "The NVR channel does not exist or does not support field detection."
            )
        return text

    def get_supplement_light(self, channel: int) -> SupplementLightState:
        return parse_supplement_light(
            self._request("GET", SUPPLEMENT_LIGHT_PATH.format(channel=channel))
        )

    def put_supplement_light(self, channel: int, xml_text: str) -> None:
        response_text = self._request(
            "PUT",
            SUPPLEMENT_LIGHT_PATH.format(channel=channel),
            body=xml_text,
        )
        try:
            root = ET.fromstring(response_text) if response_text.strip() else None
        except ET.ParseError:
            root = None
        if root is None:
            return
        if local_name(root.tag) != "ResponseStatus":
            raise HikvisionResponseError(
                f"Unexpected supplement-light response: <{local_name(root.tag)}>."
            )
        status_code, status_string, sub_status_code = _response_status(root)
        if status_code != "1":
            raise HikvisionResponseError(
                status_string or "The camera rejected the supplement-light update.",
                status_code=status_code or None,
                status_string=status_string or None,
                sub_status_code=sub_status_code or None,
            )


def _make_response_error(
    response: requests.Response, text: str, method: str, path: str
) -> HikvisionResponseError:
    status_code = status_string = sub_status_code = ""
    try:
        root = ET.fromstring(text) if text.strip() else None
    except ET.ParseError:
        root = None
    if root is not None and local_name(root.tag) == "ResponseStatus":
        status_code, status_string, sub_status_code = _response_status(root)
    message = f"ISAPI {method} {path} failed with HTTP {response.status_code}"
    if status_string:
        message += f": {status_string}"
    if status_code and status_code != "1":
        message += f" (statusCode={status_code}"
        if sub_status_code:
            message += f", subStatusCode={sub_status_code}"
        message += ")"
    return HikvisionResponseError(
        message,
        http_status=response.status_code,
        status_code=status_code or None,
        status_string=status_string or None,
        sub_status_code=sub_status_code or None,
    )


class AlertStreamReader:
    """Background reader for the NVR's multipart alert stream.

    ``on_event`` and ``on_connection`` are called from the reader thread.
    Home Assistant callers must marshal them back to the event loop.
    """

    def __init__(
        self,
        *,
        host: str,
        username: str,
        password: str,
        port: int = 80,
        use_ssl: bool = False,
        verify_ssl: bool = False,
        on_event: Callable[[AlertEvent], None],
        on_connection: Callable[[bool, str | None], None],
        connect_timeout: float = 10,
        read_timeout: float = 60,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.port = int(port)
        self.use_ssl = use_ssl
        self.verify_ssl = verify_ssl
        self._on_event = on_event
        self._on_connection = on_connection
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._response: requests.Response | None = None
        self._response_lock = threading.Lock()

    @property
    def base_url(self) -> str:
        host = self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        default_port = 443 if self.use_ssl else 80
        scheme = "https" if self.use_ssl else "http"
        if self.port == default_port:
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{self.port}"

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="hikvision-alarm-alert-stream",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._response_lock:
            response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                _LOGGER.debug("Error while closing alert stream", exc_info=True)

    def _run(self) -> None:
        session = requests.Session()
        session.trust_env = False
        session.auth = HTTPDigestAuth(self.username, self.password)
        session.headers.update(
            {
                "Accept": "application/xml",
                "User-Agent": "HomeAssistant-HikvisionAlarmLight/1.0",
            }
        )
        url = f"{self.base_url}{ALERT_STREAM_PATH}"
        backoff = 5
        try:
            while not self._stop.is_set():
                try:
                    response = session.get(
                        url,
                        stream=True,
                        timeout=(self._connect_timeout, self._read_timeout),
                        verify=self.verify_ssl,
                    )
                    if response.status_code == 401:
                        response.close()
                        raise HikvisionAuthError(
                            f"Alert stream authentication failed on {self.base_url}."
                        )
                    response.raise_for_status()
                    with self._response_lock:
                        self._response = response
                    content_type = response.headers.get("Content-Type", "")
                    match = re.search(r"boundary=([^;]+)", content_type, re.IGNORECASE)
                    boundary = (
                        match.group(1).strip().strip('"') if match else "boundary"
                    )
                    self._on_connection(True, None)
                    backoff = 5
                    buffer = b""
                    for chunk in response.iter_content(chunk_size=1024):
                        if self._stop.is_set():
                            break
                        if not chunk:
                            continue
                        buffer += chunk
                        parts, buffer = extract_multipart_parts(buffer, boundary)
                        for part in parts:
                            event = parse_alert_event(part)
                            if event is not None:
                                self._on_event(event)
                    if not self._stop.is_set():
                        self._on_connection(False, "Alert stream ended.")
                except HikvisionAuthError as err:
                    self._on_connection(False, str(err))
                    if self._stop.wait(30):
                        break
                    continue
                except requests.exceptions.Timeout:
                    self._on_connection(False, "Alert stream read timeout.")
                except requests.exceptions.RequestException as err:
                    self._on_connection(False, str(err))
                except Exception as err:
                    _LOGGER.exception("Unexpected alert stream error")
                    self._on_connection(False, str(err))
                finally:
                    with self._response_lock:
                        if self._response is not None:
                            try:
                                self._response.close()
                            except Exception:
                                _LOGGER.debug(
                                    "Error while closing alert stream", exc_info=True
                                )
                            self._response = None
                if self._stop.wait(backoff):
                    break
                backoff = min(backoff * 2, 60)
        finally:
            session.close()
            self._on_connection(False, None)
