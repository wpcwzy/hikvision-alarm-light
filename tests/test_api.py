"""Pure tests for the alarm-light ISAPI helpers."""

from __future__ import annotations

from datetime import UTC, datetime, time

from custom_components.hikvision_alarm_light.api import (
    AlertEvent,
    build_boost_xml,
    build_ir_xml,
    extract_multipart_parts,
    parse_alert_event,
    parse_supplement_light,
)
from custom_components.hikvision_alarm_light.controller import is_night

ALERT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<EventNotificationAlert version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<ipAddress>192.0.2.2</ipAddress>
<channelID>2</channelID>
<dateTime>2026-11-07T22:10:00+08:00</dateTime>
<activePostCount>1</activePostCount>
<eventType>fielddetection</eventType>
<eventState>active</eventState>
<eventDescription>fielddetection alarm</eventDescription>
<channelName>后院</channelName>
</EventNotificationAlert>
"""

SUPPLEMENT_SMART = """<?xml version="1.0" encoding="UTF-8"?>
<SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<supplementLightMode>eventIntelligence</supplementLightMode>
<EventIntelligenceModeCfg>
<brightnessRegulatMode>auto</brightnessRegulatMode>
<whiteLightBrightness>100</whiteLightBrightness>
<irLightBrightness>100</irLightBrightness>
</EventIntelligenceModeCfg>
</SupplementLight>
"""

SUPPLEMENT_BOOST = """<?xml version="1.0" encoding="UTF-8"?>
<SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<supplementLightMode>colorVuWhiteLight</supplementLightMode>
<whiteLightBrightness>100</whiteLightBrightness>
</SupplementLight>
"""


def test_parse_field_detection_event() -> None:
    event = parse_alert_event(ALERT_XML)
    assert event is not None
    assert isinstance(event, AlertEvent)
    assert event.event_type == "fielddetection"
    assert event.event_state == "active"
    assert event.channel == 2
    assert event.channel_name == "后院"
    assert event.date_time == "2026-11-07T22:10:00+08:00"


def test_parse_non_event_document() -> None:
    assert (
        parse_alert_event("<ResponseStatus><statusCode>1</statusCode></ResponseStatus>")
        is None
    )
    assert parse_alert_event(b"not xml") is None


def test_parse_supplement_light_smart() -> None:
    state = parse_supplement_light(SUPPLEMENT_SMART)
    assert state.mode == "eventIntelligence"
    assert state.white_light_brightness == 100
    assert state.ir_light_brightness == 100


def test_parse_supplement_light_boost() -> None:
    state = parse_supplement_light(SUPPLEMENT_BOOST)
    assert state.mode == "colorVuWhiteLight"
    assert state.white_light_brightness == 100


def test_build_boost_xml_clamps_brightness() -> None:
    xml = build_boost_xml(250)
    assert "<supplementLightMode>colorVuWhiteLight</supplementLightMode>" in xml
    assert "<whiteLightBrightness>100</whiteLightBrightness>" in xml
    xml_low = build_boost_xml(-5)
    assert "<whiteLightBrightness>1</whiteLightBrightness>" in xml_low


def test_extract_multipart_parts_complete() -> None:
    data = (
        b"--boundary\r\n"
        b'Content-Type: application/xml; charset="UTF-8"\r\n'
        b"Content-Length: 10\r\n\r\n"
        b"0123456789\r\n"
        b"--boundary\r\n"
        b"Content-Length: 5\r\n\r\n"
        b"abcde\r\n"
        b"--boundary--\r\n"
    )
    parts, remaining = extract_multipart_parts(data, "boundary")
    assert parts == [b"0123456789", b"abcde"]
    assert remaining == b""


def test_extract_multipart_parts_partial() -> None:
    data = b"--boundary\r\nContent-Length: 10\r\n\r\n01234"
    parts, remaining = extract_multipart_parts(data, "boundary")
    assert parts == []
    assert remaining.startswith(b"--boundary")
    # The rest of the body arrives in the next chunk.
    parts, remaining = extract_multipart_parts(remaining + b"56789\r\n", "boundary")
    assert parts == [b"0123456789"]


def test_is_night() -> None:
    start = time(18, 0)
    end = time(6, 0)
    assert is_night(datetime(2026, 11, 7, 22, 0, tzinfo=UTC), start, end)
    assert is_night(datetime(2026, 11, 7, 2, 0, tzinfo=UTC), start, end)
    assert not is_night(datetime(2026, 11, 7, 12, 0, tzinfo=UTC), start, end)
    assert is_night(datetime(2026, 11, 7, 12, 0, tzinfo=UTC), time(0, 0), time(23, 59))


def test_build_ir_xml() -> None:
    xml = build_ir_xml()
    assert "<supplementLightMode>irLight</supplementLightMode>" in xml
    assert "<irLightBrightness>100</irLightBrightness>" in xml


def test_build_aux_light_xml() -> None:
    from custom_components.hikvision_alarm_light.api import build_aux_light_xml

    on = build_aux_light_xml(True)
    off = build_aux_light_xml(False)
    assert "<PTZAux>" in on
    assert "<id>1</id>" in on
    assert "<type>LIGHT</type>" in on
    assert "<status>on</status>" in on
    assert "<status>off</status>" in off
    # Hikvision rejects a namespace on this body.
    assert "xmlns" not in on
