#!/usr/bin/env python3
"""Live smoke test for the Hikvision alarm-light link.

Example:
    export NVR_HOST=192.168.1.10
    export NVR_USERNAME=admin
    export NVR_PASSWORD='...'
    export CAMERA_HOST=192.168.1.11
    export CAMERA_USERNAME=admin
    export CAMERA_PASSWORD='...'
    python scripts/smoke_test.py --boost

``--boost`` turns the white light to maximum and restores the original smart
mode afterwards.  Without it the script only reads state.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.hikvision_alarm_light.api import (
    HikvisionError,
    HikvisionIsapiClient,
    build_boost_xml,
)


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Environment variable {name} is required")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nvr-channel", type=int, default=2)
    parser.add_argument("--camera-channel", type=int, default=1)
    parser.add_argument("--boost", action="store_true")
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()

    nvr = HikvisionIsapiClient(
        env("NVR_HOST"),
        env("NVR_USERNAME"),
        env("NVR_PASSWORD"),
        port=int(os.environ.get("NVR_PORT", "80")),
        use_ssl=os.environ.get("NVR_SSL", "0") in ("1", "true", "yes"),
        verify_ssl=os.environ.get("VERIFY_SSL", "0") in ("1", "true", "yes"),
        timeout=args.timeout,
    )
    camera = HikvisionIsapiClient(
        env("CAMERA_HOST"),
        env("CAMERA_USERNAME"),
        env("CAMERA_PASSWORD"),
        port=int(os.environ.get("CAMERA_PORT", "80")),
        use_ssl=os.environ.get("CAMERA_SSL", "0") in ("1", "true", "yes"),
        verify_ssl=os.environ.get("VERIFY_SSL", "0") in ("1", "true", "yes"),
        timeout=args.timeout,
    )
    try:
        nvr_info = nvr.get_device_info()
        camera_info = camera.get_device_info()
        print(f"NVR: {nvr_info.name} / {nvr_info.model}")
        print(f"Camera: {camera_info.name} / {camera_info.model}")
        print("NVR fielddetection trigger:")
        print(nvr.get_linkage_state(args.nvr_channel)[:200])

        original = camera.get_supplement_light(args.camera_channel)
        print(
            f"Camera channel {args.camera_channel}: mode={original.mode}, "
            f"white={original.white_light_brightness}"
        )
        if not args.boost:
            return 0

        try:
            camera.put_supplement_light(args.camera_channel, build_boost_xml(100))
            time.sleep(1)
            boosted = camera.get_supplement_light(args.camera_channel)
            print(
                f"Boosted: mode={boosted.mode}, white={boosted.white_light_brightness}"
            )
        finally:
            camera.put_supplement_light(args.camera_channel, original.raw_xml)
            time.sleep(1)
            restored = camera.get_supplement_light(args.camera_channel)
            print(
                f"Restored: mode={restored.mode}, "
                f"white={restored.white_light_brightness}"
            )
        return 0
    except HikvisionError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    finally:
        nvr.close()
        camera.close()


if __name__ == "__main__":
    raise SystemExit(main())
