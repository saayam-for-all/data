
"""Convert hexadecimal WKB/EWKB point locations to readable WKT."""

import math
import struct


def convert_req_loc(value):
    """Return POINT(longitude latitude), or None for invalid locations."""
    if value is None or not isinstance(value, (str, bytes)):
        return None

    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return None

    value = value.strip()

    if not value:
        return None

    # Accept common hexadecimal prefixes.
    if value.startswith("\\x") or value.startswith("0x"):
        value = value[2:]

    try:
        raw = bytes.fromhex(value)
    except ValueError:
        return None

    if len(raw) < 21:
        return None

    if raw[0] not in (0, 1):
        return None

    endian = "<" if raw[0] == 1 else ">"

    try:
        geometry_type = struct.unpack_from(endian + "I", raw, 1)[0]

        # EWKB flags: Z, M, SRID.
        has_z = bool(geometry_type & 0x80000000)
        has_m = bool(geometry_type & 0x40000000)
        has_srid = bool(geometry_type & 0x20000000)

        base_type = geometry_type & 0x1FFFFFFF

        # Only two-dimensional POINT geometry is supported.
        if base_type != 1 or has_z or has_m:
            return None

        offset = 5

        if has_srid:
            if len(raw) < offset + 4:
                return None
            offset += 4

        if len(raw) != offset + 16:
            return None

        longitude, latitude = struct.unpack_from(
            endian + "dd", raw, offset
        )

        if not math.isfinite(longitude) or not math.isfinite(latitude):
            return None

        return f"POINT({longitude!r} {latitude!r})"

    except (struct.error, ValueError, OverflowError):
        return None
