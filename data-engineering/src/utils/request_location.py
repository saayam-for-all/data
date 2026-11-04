"""Convert PostGIS point WKB/EWKB values into readable WKT points."""

import math
import struct
from typing import TypeAlias

LocationValue: TypeAlias = str | bytes | bytearray | memoryview | None

_EWKB_Z = 0x80000000
_EWKB_M = 0x40000000
_EWKB_SRID = 0x20000000
_EWKB_TYPE_MASK = 0x1FFFFFFF


def convert_req_loc(value: LocationValue) -> str | None:
    """Return a POINT(longitude latitude), or None for null/invalid values.

    String values are interpreted as hexadecimal WKB/EWKB. Binary values are
    interpreted as raw WKB/EWKB. Only point geometries with finite coordinates
    are converted; malformed or unsupported values are safe to export as null.
    """
    if value is None:
        return None

    try:
        if isinstance(value, str):
            encoded = value.strip()
            if encoded.startswith("\\x") or encoded.startswith("\\X"):
                encoded = encoded[2:]
            elif encoded.startswith(("0x", "0X")):
                encoded = encoded[2:]
            if not encoded:
                return None
            data = bytes.fromhex(encoded)
        elif isinstance(value, (bytes, bytearray, memoryview)):
            data = bytes(value)
        else:
            return None

        if len(data) < 5:
            return None

        byte_order = data[0]
        if byte_order not in (0, 1):
            return None
        endian = "<" if byte_order == 1 else ">"

        type_word = struct.unpack_from(f"{endian}I", data, 1)[0]
        has_z = bool(type_word & _EWKB_Z)
        has_m = bool(type_word & _EWKB_M)
        has_srid = bool(type_word & _EWKB_SRID)
        geometry_type = type_word & _EWKB_TYPE_MASK

        if 3000 <= geometry_type < 4000:
            geometry_type -= 3000
            has_z = has_m = True
        elif 2000 <= geometry_type < 3000:
            geometry_type -= 2000
            has_m = True
        elif 1000 <= geometry_type < 2000:
            geometry_type -= 1000
            has_z = True

        if geometry_type != 1:
            return None

        dimensions = 2 + int(has_z) + int(has_m)
        coordinate_offset = 5 + (4 if has_srid else 0)
        expected_length = coordinate_offset + 8 * dimensions
        if len(data) != expected_length:
            return None

        longitude, latitude = struct.unpack_from(
            f"{endian}{'d' * dimensions}", data, coordinate_offset
        )[:2]
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            return None

        return f"POINT({longitude!r} {latitude!r})"
    except (OverflowError, struct.error, ValueError):
        return None
