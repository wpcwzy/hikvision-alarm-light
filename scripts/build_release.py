#!/usr/bin/env python3
"""Build the HACS release archives for this integration.

Example:
    python scripts/build_release.py --version 1.2.0

Produces:

* ``dist/hikvision_alarm_light_manual_install.zip`` -- component files at the
  archive root (this is the asset referenced by ``hacs.json``).
* ``dist/hikvision_alarm_light_custom_components.zip`` -- component files
  prefixed with ``custom_components/hikvision_alarm_light/`` for manual installs.
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "hikvision_alarm_light"
DIST = ROOT / "dist"
MANUAL_INSTALL_ASSET = "hikvision_alarm_light_manual_install.zip"
CUSTOM_COMPONENTS_ASSET = "hikvision_alarm_light_custom_components.zip"


def _component_files() -> list[Path]:
    files = [
        path
        for path in COMPONENT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    return sorted(files)


def _write_zip(output: Path, prefix: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in _component_files():
            archive.write(path, f"{prefix}{path.relative_to(COMPONENT).as_posix()}")
    print(f"Wrote {output.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Version, e.g. 1.2.0")
    args = parser.parse_args()

    manifest = (COMPONENT / "manifest.json").read_text(encoding="utf-8")
    if f'"version": "{args.version}"' not in manifest:
        raise SystemExit(
            f"manifest.json does not declare version {args.version}; "
            "update it before building a release"
        )

    _write_zip(DIST / MANUAL_INSTALL_ASSET, "")
    _write_zip(
        DIST / CUSTOM_COMPONENTS_ASSET, "custom_components/hikvision_alarm_light/"
    )
    print(f"Version: {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
