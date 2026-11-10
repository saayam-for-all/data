
import struct


def convert_req_loc(req_loc):
    """
    Convert WKB/EWKB hexadecimal location to POINT(longitude latitude).

    Returns an empty string for null, invalid, or non-POINT data.
    """
    if req_loc is None or req_loc == "":
        return ""

    try:
        if isinstance(req_loc, bytes):
            data = req_loc
        elif isinstance(req_loc, str):
            value = req_loc.strip()
            if value.startswith("\\x") or value.lower().startswith("0x"):
                value = value[2:]
            data = bytes.fromhex(value)
        else:
            return ""

        if len(data) < 21:
            return ""

        byte_order = data[0]
        if byte_order not in (0, 1):
            return ""

        endian = "<" if byte_order == 1 else ">"
        geometry_type = struct.unpack_from(endian + "I", data, 1)[0]

        has_srid = bool(geometry_type & 0x20000000)
        has_z = bool(geometry_type & 0x80000000)
        has_m = bool(geometry_type & 0x40000000)

        base_type = geometry_type & 0x0FFFFFFF

        # Only accept two-dimensional POINT geometries.
        if base_type != 1 or has_z or has_m:
            return ""

        offset = 5 + (4 if has_srid else 0)

        if len(data) != offset + 16:
            return ""

        longitude, latitude = struct.unpack_from(
            endian + "dd", data, offset
        )

        import math
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            return ""

        return f"POINT({longitude} {latitude})"

    except (ValueError, TypeError, struct.error):
        return ""
