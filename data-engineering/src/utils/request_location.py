"""Convert PostGIS WKB/EWKB request locations to readable WKT POINT text."""

from __future__ import annotations

import math
import re
import struct
from typing import Final

_NUMBER: Final[str] = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_POINT_RE: Final[re.Pattern[str]] = re.compile(
    rf"^POINT\s*\(\s*({_NUMBER})\s+({_NUMBER})\s*\)$",
    re.IGNORECASE,
)
_HEX_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-fA-F]+$")


def _format_coordinate(value: float) -> str:
    """Return the shortest round-trippable representation without negative zero."""
    if value == 0:
        value = 0.0
    return repr(value)


def _point_wkt(longitude: float, latitude: float) -> str:
    """Return canonical POINT text, or an empty string for invalid coordinates."""
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        return ""
    if not -180.0 <= longitude <= 180.0:
        return ""
    if not -90.0 <= latitude <= 90.0:
        return ""
    return f"POINT({_format_coordinate(longitude)} {_format_coordinate(latitude)})"


def _existing_point_wkt(value: str) -> str | None:
    """Normalize already-readable POINT text; return None when it is not WKT."""
    match = _POINT_RE.fullmatch(value.strip())
    if match is None:
        return None
    try:
        return _point_wkt(float(match.group(1)), float(match.group(2)))
    except ValueError:
        return ""


def _location_bytes(value: object) -> bytes | None:
    """Convert supported binary or hexadecimal inputs to bytes."""
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if not isinstance(value, str):
        return None

    text = "".join(value.strip().split())
    if text.startswith(("\\x", "\\X", "0x", "0X")):
        text = text[2:]
    if not text or len(text) % 2 or _HEX_RE.fullmatch(text) is None:
        return None
    try:
        return bytes.fromhex(text)
    except ValueError:
        return None


def convert_req_loc(value: object) -> str:
    """Convert a WKB/EWKB POINT into POINT(longitude latitude).

    The function accepts hexadecimal text (optionally prefixed with \\x or 0x),
    raw bytes, bytearray, memoryview, and already-readable POINT text. It
    supports little- and big-endian WKB/EWKB, optional SRID metadata, and
    ISO/EWKB Z or M dimensions while exporting only longitude and latitude.

    Null, blank, malformed, unsupported, non-finite, and out-of-range inputs
    return an empty string so a CSV export can retain the request row with an
    empty req_loc field.
    """
    if value is None:
        return ""

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        existing = _existing_point_wkt(text)
        if existing is not None:
            return existing

    raw = _location_bytes(value)
    if raw is None or len(raw) < 21:
        return ""

    byte_order = raw[0]
    if byte_order == 0:
        endian = ">"
    elif byte_order == 1:
        endian = "<"
    else:
        return ""

    try:
        type_word = struct.unpack_from(f"{endian}I", raw, 1)[0]
        has_z = bool(type_word & 0x80000000)
        has_m = bool(type_word & 0x40000000)
        has_srid = bool(type_word & 0x20000000)

        geometry_type = type_word & 0x1FFFFFFF
        iso_dimension = geometry_type // 1000
        base_type = geometry_type % 1000
        if base_type != 1 or iso_dimension not in (0, 1, 2, 3):
            return ""

        has_z = has_z or iso_dimension in (1, 3)
        has_m = has_m or iso_dimension in (2, 3)
        dimensions = 2 + int(has_z) + int(has_m)

        offset = 5
        if has_srid:
            if len(raw) < offset + 4:
                return ""
            struct.unpack_from(f"{endian}I", raw, offset)
            offset += 4

        expected_length = offset + dimensions * 8
        if len(raw) != expected_length:
            return ""

        coordinates = struct.unpack_from(f"{endian}{dimensions}d", raw, offset)
    except (struct.error, ValueError):
        return ""

    return _point_wkt(coordinates[0], coordinates[1])


__all__ = ["convert_req_loc"]
