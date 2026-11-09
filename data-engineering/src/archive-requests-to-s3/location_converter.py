
import math
import re
import struct


def convert_location(value):
    """Convert WKB/EWKB hexadecimal POINT to readable coordinates."""
    if not isinstance(value, str) or not value.strip():
        return ""

    value = value.strip()

    if value.startswith("\\x"):
        value = value[2:]

    if not re.fullmatch(r"[0-9a-fA-F]+", value):
        return ""

    try:
        data = bytes.fromhex(value)

        if len(data) < 21 or data[0] not in (0, 1):
            return ""

        endian = "<" if data[0] == 1 else ">"
        geometry_type = struct.unpack_from(endian + "I", data, 1)[0]

        has_z = bool(geometry_type & 0x80000000)
        has_m = bool(geometry_type & 0x40000000)
        has_srid = bool(geometry_type & 0x20000000)

        if geometry_type & 0x1FFFFFFF != 1 or has_z or has_m:
            return ""

        offset = 9 if has_srid else 5

        if len(data) != offset + 16:
            return ""

        longitude, latitude = struct.unpack_from(
            endian + "dd", data, offset
        )

        if not (math.isfinite(longitude) and math.isfinite(latitude)):
            return ""

        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            return ""

        return f"POINT({longitude:.17g} {latitude:.17g})"

    except (ValueError, struct.error, OverflowError):
        return ""
