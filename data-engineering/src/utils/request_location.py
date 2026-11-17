"""Convert a PostGIS request location (requests.req_loc) to readable WKT.

Issue #578: the database returns ``req_loc`` as a hexadecimal EWKB string such
as ``0101000020E61000...``. This module turns it into ``POINT(longitude
latitude)`` so the archived file can be read in Athena or Excel.

Standard library only; it has no AWS or database dependency.

Behaviour (the contract for the archive export):

* A valid point becomes ``POINT(<longitude> <latitude>)``. Coordinate order
  and full double precision are preserved. Numbers use the shortest text that
  round-trips to the same double, never scientific notation, and a whole
  number has no trailing ``.0`` (``-74`` rather than ``-74.0``), as WKT writers
  such as GEOS do.
* ``None``, an empty string, ``NaN`` and whitespace-only values are "no
  location" and give an empty string.
* Anything that is not a valid 2D point (not hex, truncated, a different
  geometry type such as a polygon, NaN/infinite or out-of-range coordinates)
  is invalid and also gives an empty string. Conversion never raises, so one
  bad value can never make the export fail or drop the request row.
* Accepted inputs: hex EWKB or plain hex WKB, either byte order, upper or
  lower case, an optional ``\\x`` / ``0x`` prefix, and ``bytes`` / ``bytearray``
  / ``memoryview`` (what a DB driver returns for binary columns). Z and M
  values, if present, are ignored; only longitude and latitude are exported.
"""

import logging
import math
import re
import struct
from decimal import Decimal

logger = logging.getLogger(__name__)

_WKB_POINT = 1
_FLAG_Z = 0x80000000
_FLAG_M = 0x40000000
_FLAG_SRID = 0x20000000
_ISO_Z = 1000   # ISO WKB: type + 1000 (Z), 2000 (M), 3000 (ZM)
_HEX = re.compile(r"^(?:[0-9a-fA-F]{2})+$")

STATUS_OK = "ok"
STATUS_NULL = "null"
STATUS_INVALID = "invalid"


def _format_number(value):
    """Shortest round-trip decimal text, no exponent, no trailing '.0'."""
    text = format(Decimal(repr(value)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _is_null(value):
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _to_bytes(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        # A driver may hand back the hex text as bytes; accept that too.
        try:
            as_text = raw.decode("ascii")
        except UnicodeDecodeError:
            return raw
        if _HEX.match(as_text.strip()) and len(as_text.strip()) >= 42:
            return bytes.fromhex(as_text.strip())
        return raw
    if not isinstance(value, str):
        raise ValueError("unsupported type")
    text = value.strip()
    if text[:2] in ("\\x", "0x", "0X"):
        text = text[2:]
    if not _HEX.match(text):
        raise ValueError("not hexadecimal")
    return bytes.fromhex(text)


def _decode_point(raw):
    """Return (longitude, latitude) from WKB/EWKB bytes, or raise ValueError."""
    if len(raw) < 5 or raw[0] not in (0, 1):
        raise ValueError("bad header")
    order = "<" if raw[0] == 1 else ">"
    (geom_type,) = struct.unpack(order + "I", raw[1:5])
    offset = 5

    has_srid = bool(geom_type & _FLAG_SRID)
    base_type = geom_type & 0x0FFFFFFF
    dims = 2 + bool(geom_type & _FLAG_Z) + bool(geom_type & _FLAG_M)
    if base_type >= _ISO_Z:  # ISO WKB dimension encoding
        dims = 2 + (base_type // 1000 in (1, 3)) + (base_type // 1000 in (2, 3))
        base_type %= 1000
    if base_type != _WKB_POINT:
        raise ValueError("not a point")

    if has_srid:
        offset += 4
    if len(raw) != offset + 8 * dims:
        raise ValueError("wrong length")
    lon, lat = struct.unpack(order + "dd", raw[offset:offset + 16])
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise ValueError("non-finite coordinate")
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("coordinate out of range")
    return lon, lat


def req_loc_to_wkt_status(value):
    """Return (text, status). text is "" unless status is "ok"."""
    if _is_null(value):
        return "", STATUS_NULL
    try:
        lon, lat = _decode_point(_to_bytes(value))
    except (ValueError, struct.error, TypeError):
        return "", STATUS_INVALID
    return f"POINT({_format_number(lon)} {_format_number(lat)})", STATUS_OK


def req_loc_to_wkt(value):
    """Convert req_loc to ``POINT(longitude latitude)``; "" for null/invalid."""
    text, status = req_loc_to_wkt_status(value)
    if status == STATUS_INVALID:
        logger.warning("Invalid req_loc value; exporting an empty location")
    return text
