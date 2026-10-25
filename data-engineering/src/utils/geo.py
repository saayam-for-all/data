"""Parse geographic coordinates and calculate straight-line miles."""

import json
import math
import re
import struct

EARTH_RADIUS_MILES = 3958.7613

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_LATITUDE = re.compile(
    rf"\b(?:latitude|lat)\s*[:=]\s*({_NUMBER})", re.IGNORECASE
)
_LONGITUDE = re.compile(
    rf"\b(?:longitude|lng|lon|long)\s*[:=]\s*({_NUMBER})",
    re.IGNORECASE,
)
_POINT = re.compile(
    rf"^\s*(?:SRID\s*=\s*(\d+)\s*;\s*)?"
    rf"POINT(?:\s+Z|\s+M|\s+ZM)?\s*"
    rf"\(\s*({_NUMBER})\s+({_NUMBER})(?:\s+{_NUMBER})*\s*\)\s*$",
    re.IGNORECASE,
)
_PAIR = re.compile(
    rf"^\s*\(?\s*({_NUMBER})\s*[,; ]\s*({_NUMBER})\s*\)?\s*$"
)


def _valid_pair(latitude, longitude):
    """Return a valid (latitude, longitude) pair, or None."""
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    return latitude, longitude


def _coordinates_from_mapping(value):
    """Read coordinates from a dictionary."""
    normalized = {str(key).lower(): item for key, item in value.items()}

    latitude = next(
        (normalized[key] for key in ("latitude", "lat") if key in normalized),
        None,
    )
    longitude = next(
        (
            normalized[key]
            for key in ("longitude", "lng", "lon", "long")
            if key in normalized
        ),
        None,
    )

    if latitude is not None and longitude is not None:
        return _valid_pair(latitude, longitude)

    # GeoJSON Point coordinates are [longitude, latitude].
    point = normalized.get("coordinates")
    if (
        normalized.get("type") == "point"
        and isinstance(point, (list, tuple))
        and len(point) >= 2
    ):
        return _valid_pair(point[1], point[0])

    return None


def _coordinates_from_wkb(data):
    """Read a 2D/3D WKB Point in WGS84; return None for unsupported data."""
    if len(data) < 21 or data[0] not in (0, 1):
        return None

    endian = "<" if data[0] == 1 else ">"
    geometry_type = struct.unpack_from(endian + "I", data, 1)[0]
    offset = 5
    srid = None

    # EWKB SRID flag.
    if geometry_type & 0x20000000:
        if len(data) < offset + 4:
            return None
        srid = struct.unpack_from(endian + "I", data, offset)[0]
        offset += 4

    if srid not in (None, 0, 4326):
        return None

    # Remove EWKB Z, M, and SRID flags. Accept only Point types.
    base_type = geometry_type & ~0xE0000000
    if base_type % 1000 != 1 or len(data) < offset + 16:
        return None

    longitude, latitude = struct.unpack_from(endian + "dd", data, offset)
    return _valid_pair(latitude, longitude)


def parse_coordinates(value):
    """Return (latitude, longitude), or None if the value isn't parseable."""
    if value is None:
        return None

    if isinstance(value, dict):
        return _coordinates_from_mapping(value)

    if isinstance(value, (bytes, bytearray, memoryview)):
        return _coordinates_from_wkb(bytes(value))

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None

        if isinstance(parsed, dict):
            return _coordinates_from_mapping(parsed)

    latitude_match = _LATITUDE.search(text)
    longitude_match = _LONGITUDE.search(text)
    if latitude_match and longitude_match:
        return _valid_pair(
            latitude_match.group(1),
            longitude_match.group(1),
        )

    # WKT uses longitude first, latitude second.
    point_match = _POINT.match(text)
    if point_match:
        srid = int(point_match.group(1)) if point_match.group(1) else None
        if srid in (None, 0, 4326):
            return _valid_pair(
                point_match.group(3),
                point_match.group(2),
            )

    pair_match = _PAIR.match(text)
    if pair_match:
        first = float(pair_match.group(1))
        second = float(pair_match.group(2))

        # If only the first value could be longitude, switch to lat/lon.
        if abs(first) > 90 and abs(second) <= 90:
            first, second = second, first

        # Otherwise, a plain pair is interpreted as latitude, longitude.
        return _valid_pair(first, second)

    # Some database drivers return WKB as a hexadecimal string.
    if len(text) >= 42 and len(text) % 2 == 0:
        try:
            return _coordinates_from_wkb(bytes.fromhex(text))
        except ValueError:
            return None

    return None


def haversine_miles(origin, destination):
    """Return straight-line miles between (latitude, longitude) pairs."""
    origin = _valid_pair(*origin)
    destination = _valid_pair(*destination)

    if origin is None or destination is None:
        raise ValueError("Invalid latitude/longitude coordinate pair")

    lat1, lon1 = origin
    lat2, lon2 = destination

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    lat_delta = math.radians(lat2 - lat1)
    lon_delta = math.radians(lon2 - lon1)

    value = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(lon_delta / 2) ** 2
    )

    return 2 * EARTH_RADIUS_MILES * math.asin(
        min(1.0, math.sqrt(value))
    )