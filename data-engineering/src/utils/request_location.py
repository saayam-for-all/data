import math
import struct
from decimal import Decimal

def _clean_hex(value):
    """Return a clean hex string, or None if the input is null or blank."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("\\x"):   # Postgres sometimes prefixes hex with \x
        text = text[2:]
    return text or None


def _hex_to_bytes(text):
    """Turn hex text into bytes, or None if it is not valid hex."""
    try:
        return bytes.fromhex(text)
    except ValueError:
        return None

def _decode_point(data):
    """Return (longitude, latitude) from point bytes, or None if not a point."""
    if len(data) < 21:                    # smallest possible point is 21 bytes
        return None

    if data[0] == 1:                      # first byte tells us the byte order
        order = "<"                       # little-endian
    elif data[0] == 0:
        order = ">"                       # big-endian
    else:
        return None

    geom_type = struct.unpack(order + "I", data[1:5])[0]
    if geom_type & 0x0FFFFFFF != 1:       # 1 means POINT; anything else is rejected
        return None

    offset = 5
    if geom_type & 0x20000000:            # this flag means a 4-byte SRID follows
        offset += 4

    if len(data) < offset + 16:           # need two 8-byte numbers
        return None

    lon, lat = struct.unpack(order + "dd", data[offset:offset + 16])
    return lon, lat

def _format_number(x):
    """Format a float without trailing zeros: 40.7000 -> 40.7, 0.0 -> 0."""
    x = x + 0.0                                   # turns -0.0 into 0.0
    text = format(Decimal(repr(x)), "f")          # repr keeps full double precision
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def hex_to_wkt(value):
    """Convert a PostGIS hex point to 'POINT(lon lat)'.

    Returns an empty string for null, blank, invalid, non-point,
    NaN or out-of-range input, so the export never fails.
    """
    text = _clean_hex(value)
    if text is None:
        return ""

    data = _hex_to_bytes(text)
    if data is None:
        return ""

    point = _decode_point(data)
    if point is None:
        return ""

    lon, lat = point
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return ""
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return ""

    return f"POINT({_format_number(lon)} {_format_number(lat)})"