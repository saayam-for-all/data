"""Coordinate parsing and straight-line distance helpers.

Pure Python (no third-party dependencies) so it can be bundled into any
Lambda. Used by the org aggregator to turn stored locations such as
``requests.req_loc`` or ``user_locations.curr_loc`` into coordinates and to
compute straight-line (great-circle) distances.

Distances returned here are "as the crow flies". They are NOT driving
distance or travel time and must not be labelled as such.
"""

from __future__ import annotations

import json
import math
import re
import struct
from dataclasses import dataclass
from typing import Any, Optional

EARTH_RADIUS_MILES = 3958.7613
EARTH_RADIUS_KM = 6371.0088

_RADIUS_BY_UNIT = {
    "miles": EARTH_RADIUS_MILES,
    "mi": EARTH_RADIUS_MILES,
    "km": EARTH_RADIUS_KM,
    "kilometers": EARTH_RADIUS_KM,
}

_LAT_KEYS = ("latitude", "lat")
_LON_KEYS = ("longitude", "lng", "lon", "long")

_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_LABELLED_LAT = re.compile(rf"\b(?:latitude|lat)\s*[:=]\s*({_NUMBER})", re.IGNORECASE)
_LABELLED_LON = re.compile(rf"\b(?:longitude|lng|lon|long)\s*[:=]\s*({_NUMBER})", re.IGNORECASE)
_WKT_POINT = re.compile(
    rf"^\s*(?:SRID\s*=\s*(\d+)\s*;\s*)?POINT\s*Z?M?\s*\(\s*({_NUMBER})\s+({_NUMBER})(?:\s+{_NUMBER})*\s*\)\s*$",
    re.IGNORECASE,
)
_BARE_PAIR = re.compile(rf"^\s*\(?\s*({_NUMBER})\s*[,; ]\s*({_NUMBER})\s*\)?\s*$")
_HEX = re.compile(r"^[0-9a-fA-F]+$")

# EWKB flags (PostGIS extended WKB)
_EWKB_Z = 0x80000000
_EWKB_M = 0x40000000
_EWKB_SRID = 0x20000000
_WGS84_SRIDS = {None, 0, 4326}


@dataclass(frozen=True)
class Coordinates:
    """A WGS84 latitude/longitude pair in decimal degrees."""

    latitude: float
    longitude: float

    def as_dict(self) -> dict[str, float]:
        """Return the coordinates as a JSON-friendly dict."""
        return {"latitude": self.latitude, "longitude": self.longitude}


def is_valid_coordinate(latitude: Any, longitude: Any) -> bool:
    """Return True when the pair is a finite, in-range WGS84 coordinate."""
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(lat)
        and math.isfinite(lon)
        and -90.0 <= lat <= 90.0
        and -180.0 <= lon <= 180.0
    )


def make_coordinates(latitude: Any, longitude: Any) -> Optional[Coordinates]:
    """Build Coordinates from raw values, or return None if they are invalid."""
    if not is_valid_coordinate(latitude, longitude):
        return None
    return Coordinates(float(latitude), float(longitude))


def haversine_distance(origin: Coordinates, destination: Coordinates, unit: str = "miles") -> float:
    """Return the straight-line (great-circle) distance between two points.

    Args:
        origin: Starting point.
        destination: End point.
        unit: "miles" (default) or "km".
    """
    try:
        radius = _RADIUS_BY_UNIT[unit.lower()]
    except KeyError as error:
        raise ValueError(f"Unsupported distance unit: {unit!r}") from error

    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(destination.latitude)
    d_lat = lat2 - lat1
    d_lon = math.radians(destination.longitude - origin.longitude)
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(h)))


def parse_coordinates(value: Any) -> Optional[Coordinates]:
    """Extract coordinates from the location formats seen in Saayam data.

    Supported inputs:
      * ``Coordinates`` instances
      * dicts with latitude/lat and longitude/lng/lon/long keys
      * labelled strings, e.g. ``"longitude:-121.9780,latitude:37.7799"``
      * JSON object strings with the keys above
      * WKT / EWKT points, e.g. ``"SRID=4326;POINT(-76.78 38.00)"`` (lon lat order)
      * PostGIS (E)WKB points as hex strings, bytes or memoryview — this is how
        psycopg2 / pg8000 return ``geography``/``geometry`` columns
      * bare pairs, e.g. ``"37.7799,-121.9780"``, read as "latitude, longitude"
        unless the first number can only be a longitude

    Returns None for anything else (including free-text addresses such as
    "Suffolk, VA"), so callers can fall back to the next location source.
    """
    if value is None:
        return None
    if isinstance(value, Coordinates):
        return value
    if isinstance(value, dict):
        return _from_mapping(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _from_wkb(bytes(value))
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
            return _from_mapping(parsed)

    lat_match = _LABELLED_LAT.search(text)
    lon_match = _LABELLED_LON.search(text)
    if lat_match and lon_match:
        return make_coordinates(lat_match.group(1), lon_match.group(1))

    wkt = _WKT_POINT.match(text)
    if wkt:
        srid = int(wkt.group(1)) if wkt.group(1) else None
        if srid not in _WGS84_SRIDS:
            return None
        return make_coordinates(wkt.group(3), wkt.group(2))

    if len(text) >= 42 and len(text) % 2 == 0 and _HEX.match(text):
        try:
            return _from_wkb(bytes.fromhex(text))
        except ValueError:
            return None

    pair = _BARE_PAIR.match(text)
    if pair:
        first, second = float(pair.group(1)), float(pair.group(2))
        if abs(first) > 90 >= abs(second):
            first, second = second, first
        return make_coordinates(first, second)

    return None


def _from_mapping(mapping: dict) -> Optional[Coordinates]:
    lowered = {str(key).lower(): val for key, val in mapping.items()}
    lat = next((lowered[key] for key in _LAT_KEYS if key in lowered), None)
    lon = next((lowered[key] for key in _LON_KEYS if key in lowered), None)
    if lat is None or lon is None:
        return None
    return make_coordinates(lat, lon)


def _from_wkb(data: bytes) -> Optional[Coordinates]:
    """Decode a 2D/3D (E)WKB point. Returns None for other geometries or SRIDs."""
    if len(data) < 21:
        return None
    byte_order = data[0]
    if byte_order not in (0, 1):
        return None
    endian = "<" if byte_order == 1 else ">"
    (geom_type,) = struct.unpack_from(f"{endian}I", data, 1)
    offset = 5
    srid = None
    if geom_type & _EWKB_SRID:
        if len(data) < offset + 4:
            return None
        (srid,) = struct.unpack_from(f"{endian}I", data, offset)
        offset += 4
    base_type = geom_type & ~(_EWKB_Z | _EWKB_M | _EWKB_SRID)
    # ISO WKB encodes Z/M as 1001/2001/3001
    if base_type % 1000 != 1:
        return None
    if srid not in _WGS84_SRIDS:
        return None
    if len(data) < offset + 16:
        return None
    x, y = struct.unpack_from(f"{endian}dd", data, offset)
    return make_coordinates(y, x)
