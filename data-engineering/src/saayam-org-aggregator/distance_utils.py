"""Distance helpers for saayam-org-aggregator (issue #433).

Pure Python plus pandas: no AWS or database imports, so every function here
can be tested without a Lambda environment or a database connection.

What lives here:
  - parse_point():      read a coordinate from the formats found in Saayam data
  - haversine_miles():  straight-line distance between two coordinates
  - geocode_address():  provider-agnostic geocoding with a cache
  - add_distance():     attach distance fields to the merged organization list
  - sort_by_distance(): nearest first, unknown distance last

The geocoding provider is NOT finalized. Nothing here is tied to a specific
provider: register one with register_geocoder() and select it with the
GEOCODER_PROVIDER environment variable. Until one is registered, addresses
that need geocoding come back with distance_status "deferred".
"""

import logging
import math
import os
import re
import struct

import pandas as pd

logger = logging.getLogger(__name__)

EARTH_RADIUS_MILES = 3958.7613
DISTANCE_UNIT = "miles"
DISTANCE_METHOD = "straight_line"

STATUS_OK = "ok"
STATUS_ONLINE = "online"
STATUS_UNKNOWN_LOCATION = "unknown_location"
STATUS_NOT_FOUND = "not_found"
STATUS_DEFERRED = "deferred"
STATUS_ERROR = "error"

DISTANCE_COLUMNS = [
    "distance",
    "distance_unit",
    "distance_method",
    "distance_status",
]

# Internal column carrying the address used for geocoding. It is removed by
# add_distance() so it never appears in the API response.
ADDRESS_COLUMN = "_geocode_address"

# Max live geocoding calls per invocation; the rest are "deferred" so one
# request can never stall the Organizations page.
DEFAULT_MAX_GEOCODES = 25

_NUMBER = r"-?\d+(?:\.\d+)?"
_NAMED_LON = re.compile(rf"longitude\s*[:=]\s*({_NUMBER})", re.IGNORECASE)
_NAMED_LAT = re.compile(rf"latitude\s*[:=]\s*({_NUMBER})", re.IGNORECASE)
_WKT_POINT = re.compile(
    rf"POINT\s*\(\s*({_NUMBER})\s+({_NUMBER})\s*\)", re.IGNORECASE
)
_LAT_LON_PAIR = re.compile(rf"^\(?\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\)?$")
_HEX_EWKB = re.compile(r"^(?:[0-9a-fA-F]{2})+$")
_ONLINE = re.compile(r"\b(online|virtual|remote)\b", re.IGNORECASE)


# ---------------------------------------------------------------- coordinates
def _valid_coordinates(lat, lon):
    return (
        lat is not None
        and lon is not None
        and math.isfinite(lat)
        and math.isfinite(lon)
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    )


def _decode_hex_ewkb_point(text):
    """Decode a PostGIS hex EWKB/WKB point (geography::text) -> (lat, lon)."""
    raw = bytes.fromhex(text)
    if len(raw) < 21:
        return None
    endian = "<" if raw[0] == 1 else ">"
    (geom_type,) = struct.unpack(endian + "I", raw[1:5])
    offset = 5
    if geom_type & 0x20000000:  # an SRID follows the type
        offset += 4
    if (geom_type & 0xFF) != 1 or len(raw) < offset + 16:  # 1 = Point
        return None
    lon, lat = struct.unpack(endian + "dd", raw[offset:offset + 16])
    return lat, lon


def parse_point(value):
    """Return (lat, lon) from a stored location value, or None.

    Accepted formats:
      "longitude:-121.9780,latitude:37.7799"  (requests.req_loc)
      "SRID=4326;POINT(-121.9780 37.7799)"    (EWKT; lon lat order)
      "POINT(-121.9780 37.7799)"              (WKT)
      "0101000020E6100000..."                 (hex EWKB, geography::text)
      "(37.7799, -121.9780)"                  (lat, lon pair)
      {"lat"/"latitude": .., "lon"/"lng"/"longitude": ..}
    Anything else, including out-of-range numbers, returns None.
    """
    if value is None:
        return None
    try:
        if isinstance(value, dict):
            lat = value.get("lat", value.get("latitude"))
            lon = value.get("lon", value.get("lng", value.get("longitude")))
            lat, lon = float(lat), float(lon)
            return (lat, lon) if _valid_coordinates(lat, lon) else None

        text = str(value).strip()
        if not text:
            return None

        lat = lon = None
        named_lon, named_lat = _NAMED_LON.search(text), _NAMED_LAT.search(text)
        wkt = _WKT_POINT.search(text)
        pair = _LAT_LON_PAIR.match(text)

        if named_lon and named_lat:
            lat, lon = float(named_lat.group(1)), float(named_lon.group(1))
        elif wkt:
            lon, lat = float(wkt.group(1)), float(wkt.group(2))
        elif pair:
            lat, lon = float(pair.group(1)), float(pair.group(2))
        elif _HEX_EWKB.match(text):
            decoded = _decode_hex_ewkb_point(text)
            if decoded:
                lat, lon = decoded

        return (lat, lon) if _valid_coordinates(lat, lon) else None
    except (TypeError, ValueError, struct.error):
        return None


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle (straight-line) distance in miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


# ------------------------------------------------------------------ geocoding
# Provider registry. A provider is a function: address -> (lat, lon) or None
# (None means "address not found"). It may raise on timeout/failure.
_GEOCODERS = {}

# address -> (lat, lon, status). Only "ok" and "not_found" are cached, never
# errors or deferrals, so a later invocation can retry those. This lives for
# the life of a warm Lambda container; swap it for a persistent store (for
# example a DB table) once the team decides where coordinates should be kept.
_CACHE = {}


def register_geocoder(name, func):
    """Plug in a geocoding provider under `name` (see GEOCODER_PROVIDER)."""
    _GEOCODERS[name] = func


def clear_geocode_cache():
    _CACHE.clear()


def _cache_key(address):
    return " ".join(str(address).lower().split())


def is_cached(address):
    return bool(address) and _cache_key(address) in _CACHE


def geocode_address(address):
    """Convert an address to coordinates.

    Returns (lat, lon, status). On success status is "ok". Failures return
    (None, None, status) with status one of unknown_location, not_found,
    deferred or error. This function never raises.
    """
    if address is None or not str(address).strip():
        return None, None, STATUS_UNKNOWN_LOCATION

    key = _cache_key(address)
    if key in _CACHE:
        return _CACHE[key]

    provider = _GEOCODERS.get(os.environ.get("GEOCODER_PROVIDER", ""))
    if provider is None:
        return None, None, STATUS_DEFERRED  # no provider configured yet

    try:
        result = provider(str(address))
    except Exception as exc:  # timeout, HTTP error, bad payload...
        logger.warning("Geocoding failed for %r: %s", address, exc)
        return None, None, STATUS_ERROR

    point = parse_point(result) if result is not None else None
    if result is not None and point is None and isinstance(result, (tuple, list)):
        try:
            point = parse_point({"lat": result[0], "lon": result[1]})
        except (IndexError, TypeError):
            point = None

    if point is None:
        _CACHE[key] = (None, None, STATUS_NOT_FOUND)
        return _CACHE[key]

    _CACHE[key] = (point[0], point[1], STATUS_OK)
    return _CACHE[key]


# ------------------------------------------------------------- organizations
def _fields(distance, status):
    return {
        "distance": distance,
        "distance_unit": DISTANCE_UNIT,
        "distance_method": DISTANCE_METHOD,
        "distance_status": status,
    }


def _distance_for_org(address, origin, geocodes_left):
    """Return (fields, geocodes_used) for one organization."""
    if origin is None:
        return _fields(None, STATUS_UNKNOWN_LOCATION), 0

    if address is None or (isinstance(address, float) and pd.isna(address)):
        return _fields(None, STATUS_UNKNOWN_LOCATION), 0
    address = str(address).strip()
    if not address:
        return _fields(None, STATUS_UNKNOWN_LOCATION), 0

    if _ONLINE.search(address):
        return _fields(None, STATUS_ONLINE), 0

    used = 0
    if not is_cached(address):
        if geocodes_left <= 0:
            return _fields(None, STATUS_DEFERRED), 0
        used = 1

    lat, lon, status = geocode_address(address)
    if status != STATUS_OK:
        return _fields(None, status), used

    miles = haversine_miles(origin[0], origin[1], lat, lon)
    return _fields(round(miles, 1), STATUS_OK), used


def add_distance(df, origin, max_geocodes=None):
    """Add distance columns to the merged organization DataFrame.

    `origin` is the beneficiary's (lat, lon), or None when unknown. Each
    organization is handled on its own: a failure for one organization marks
    only that row with status "error". Unknown distance is None (JSON null),
    never 0. The internal address column is removed from the result.
    """
    if max_geocodes is None:
        max_geocodes = int(
            os.environ.get("MAX_GEOCODES_PER_REQUEST", DEFAULT_MAX_GEOCODES)
        )

    addresses = (
        df[ADDRESS_COLUMN].tolist()
        if ADDRESS_COLUMN in df.columns
        else [None] * len(df)
    )

    rows = []
    geocodes_left = max_geocodes
    for address in addresses:
        try:
            fields, used = _distance_for_org(address, origin, geocodes_left)
            geocodes_left -= used
        except Exception as exc:
            logger.warning("Distance calculation failed for %r: %s", address, exc)
            fields = _fields(None, STATUS_ERROR)
        rows.append(fields)

    df = df.drop(columns=[ADDRESS_COLUMN], errors="ignore").copy()
    for column in DISTANCE_COLUMNS:
        # object dtype keeps None as None (NaN would break JSON output)
        df[column] = pd.Series([r[column] for r in rows], index=df.index, dtype=object)
    return df


def sort_by_distance(df):
    """Nearest first, farther next, unknown distance last (stable)."""
    if df.empty or "distance" not in df.columns:
        return df
    order = pd.to_numeric(df["distance"], errors="coerce")
    return df.assign(_sort=order).sort_values(
        "_sort", kind="stable", na_position="last"
    ).drop(columns="_sort")


def mark_all_error(df):
    """Fallback if the whole distance step fails: keep orgs, distance null."""
    df = df.drop(columns=[ADDRESS_COLUMN], errors="ignore").copy()
    for column, value in _fields(None, STATUS_ERROR).items():
        df[column] = pd.Series([value] * len(df), index=df.index, dtype=object)
    return df