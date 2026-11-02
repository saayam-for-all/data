"""Convert request locations to readable WKT without database/GIS dependencies."""

import math
import re
import struct
from collections.abc import Iterable, Iterator, Mapping
from decimal import Decimal
from typing import Any

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_POINT = re.compile(rf"POINT\s*\(\s*({_NUMBER})\s+({_NUMBER})\s*\)", re.IGNORECASE)


def _point_text(longitude: float, latitude: float) -> str | None:
    """Format finite geographic coordinates without rounding or swapping axes."""
    if not (math.isfinite(longitude) and math.isfinite(latitude)):
        return None
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None

    def number(value: float) -> str:
        """Expand the shortest round-trip float representation for readability."""
        text = format(Decimal(repr(value)), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    return f"POINT({number(longitude)} {number(latitude)})"


def location_to_point(value: object) -> str | None:
    """Return ``POINT(longitude latitude)`` or None for null/invalid locations.

    Accept 2D WKB and PostGIS EWKB POINTs (SRID 4326), in either byte order,
    as hexadecimal strings, raw bytes, bytearray, or memoryview. Hex may have
    a PostgreSQL ``\\x`` or ``0x`` prefix. Unlabelled WKB is assumed lon/lat.
    Already-readable 2D POINT text is accepted to allow safe reprocessing.
    Unsupported geometry, dimensions, SRIDs, corrupt payloads, and non-finite
    or out-of-range coordinates return None; callers must retain the row.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        # Bound parsing to the supported point representations.
        if len(text) > 1024:
            return None
        match = _POINT.fullmatch(text)
        if match:
            return _point_text(float(match[1]), float(match[2]))
        if text.startswith(("\\x", "\\X", "0x", "0X")):
            text = text[2:]
        if len(text) not in (42, 50) or re.fullmatch(r"[0-9a-fA-F]+", text) is None:
            return None
        raw = bytes.fromhex(text)
    elif isinstance(value, (bytes, bytearray, memoryview)):
        if (value.nbytes if isinstance(value, memoryview) else len(value)) not in (21, 25):
            return None
        raw = bytes(value)
    else:
        return None

    if raw[0] not in (0, 1):
        return None
    byte_order = "<" if raw[0] == 1 else ">"
    geometry_type = struct.unpack_from(f"{byte_order}I", raw, 1)[0]
    if geometry_type == 1 and len(raw) == 21:
        offset = 5
    elif geometry_type == 0x20000001 and len(raw) == 25:
        srid = struct.unpack_from(f"{byte_order}I", raw, 5)[0]
        if srid != 4326:
            return None
        offset = 9
    else:
        return None
    longitude, latitude = struct.unpack_from(f"{byte_order}dd", raw, offset)
    return _point_text(longitude, latitude)


def convert_request_locations(
    rows: Iterable[Mapping[str, Any]],
) -> Iterator[dict[str, Any]]:
    """Yield copies with only req_loc converted, retaining every row/column.

    A missing req_loc column is left missing. Invalid and null locations become
    None (an empty field with csv.DictWriter); input mappings are not mutated.
    """
    for row in rows:
        converted = dict(row)
        if "req_loc" in converted:
            converted["req_loc"] = location_to_point(converted["req_loc"])
        yield converted
