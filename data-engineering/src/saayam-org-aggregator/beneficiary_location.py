"""Resolve the beneficiary's (request's) coordinates once per invocation (issue #433).

Fallback order:
    1. requests.req_loc ("longitude:<lon>,latitude:<lat>")
    2. user_locations.curr_loc for the beneficiary (PostGIS point)
    3. the beneficiary's profile address (users + states + countries), geocoded
If none works the result is None; there is deliberately no default location.
"""

import logging
import math
import re
import struct
from dataclasses import dataclass
from typing import Callable, Optional

import db_columns as cols
from distance import Point, clean_text, join_address
from geocoding import STATUS_OK, geocode_address

logger = logging.getLogger(__name__)

# run_query(sql, params) -> list of row dicts
QueryFn = Callable[[str, tuple], list]

SOURCE_REQ_LOC = "req_loc"
SOURCE_USER_LOCATIONS = "user_locations"
SOURCE_PROFILE_ADDRESS = "profile_address"

_LAT_KEYS = {"lat", "latitude"}
_LON_KEYS = {"lon", "lng", "long", "longitude"}
_WKT_POINT = re.compile(
    r"^\s*(?:SRID=\d+\s*;\s*)?POINT\s*\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)\s*$",
    re.IGNORECASE,
)
_HEX = re.compile(r"^[0-9a-fA-F]+$")
_EWKB_SRID_FLAG = 0x20000000
_WKB_POINT = 1


@dataclass(frozen=True)
class BeneficiaryLocation:
    """Resolved beneficiary coordinates and which fallback produced them."""

    lat: float
    lon: float
    source: str

    @property
    def point(self) -> Point:
        return (self.lat, self.lon)


def _valid_point(lat: object, lon: object) -> Optional[Point]:
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        return None
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        return None
    return (lat_f, lon_f)


def parse_req_loc(value: object) -> Optional[Point]:
    """Parse "longitude:-121.97,latitude:37.77" by key name (order-independent)."""
    text = clean_text(value)
    if text is None:
        return None
    lat = lon = None
    for part in text.split(","):
        if ":" not in part:
            continue
        key, _, raw = part.partition(":")
        key = key.strip().lower()
        if key in _LAT_KEYS:
            lat = raw.strip()
        elif key in _LON_KEYS:
            lon = raw.strip()
    if lat is None or lon is None:
        return None
    return _valid_point(lat, lon)


def _parse_ewkb_point(raw: bytes) -> Optional[Point]:
    """Parse a (E)WKB 2D point: byte order, type (+SRID flag), [srid], x, y."""
    if len(raw) < 21:
        return None
    endian = "<" if raw[0] == 1 else ">"
    (geom_type,) = struct.unpack_from(endian + "I", raw, 1)
    offset = 5
    if geom_type & _EWKB_SRID_FLAG:
        offset += 4
    if (geom_type & 0xFFFF) != _WKB_POINT or len(raw) < offset + 16:
        return None
    lon, lat = struct.unpack_from(endian + "dd", raw, offset)
    return _valid_point(lat, lon)


def parse_geo_point(value: object) -> Optional[Point]:
    """Parse a PostGIS point as returned by the driver.

    Accepts hex EWKB (what selecting a geography column returns), raw WKB
    bytes, WKT/EWKT ("SRID=4326;POINT(lon lat)") and the req_loc key:value
    format. Returns (lat, lon) or None.
    """
    if value is None:
        return None
    try:
        if isinstance(value, (bytes, bytearray, memoryview)):
            return _parse_ewkb_point(bytes(value))
        text = clean_text(value)
        if text is None:
            return None
        match = _WKT_POINT.match(text)
        if match:
            return _valid_point(match.group(2), match.group(1))
        if _HEX.match(text) and len(text) % 2 == 0:
            return _parse_ewkb_point(bytes.fromhex(text))
        return parse_req_loc(text)
    except (ValueError, struct.error):
        return None


def _fetch_request(query: QueryFn, request_id: str) -> Optional[dict]:
    sql = (
        f"SELECT {cols.REQUEST_LOCATION_COLUMN} AS req_loc, "
        f"{cols.REQUEST_BENEFICIARY_COLUMN} AS beneficiary_id "
        f"FROM {cols.DB_SCHEMA}.{cols.REQUESTS_TABLE} "
        f"WHERE {cols.REQUEST_ID_COLUMN} = %s LIMIT 1"
    )
    rows = query(sql, (request_id,))
    return rows[0] if rows else None


def _fetch_current_location(query: QueryFn, beneficiary_id: str) -> Optional[Point]:
    sql = (
        f"SELECT {cols.USER_LOCATIONS_CURRENT_COLUMN} AS curr_loc "
        f"FROM {cols.DB_SCHEMA}.{cols.USER_LOCATIONS_TABLE} "
        f"WHERE {cols.USER_LOCATIONS_USER_ID_COLUMN} = %s LIMIT 1"
    )
    rows = query(sql, (beneficiary_id,))
    return parse_geo_point(rows[0]["curr_loc"]) if rows else None


def fetch_profile_address(query: QueryFn, beneficiary_id: str) -> Optional[str]:
    """Beneficiary profile address with state/country names, or None if too vague."""
    street_cols = ", ".join(
        f"u.{c} AS street_{i}" for i, c in enumerate(cols.USERS_STREET_COLUMNS)
    )
    sql = (
        f"SELECT {street_cols}, u.{cols.USERS_CITY_COLUMN} AS city, "
        f"s.{cols.STATES_NAME_COLUMN} AS state, u.{cols.USERS_ZIP_COLUMN} AS zip_code, "
        f"c.{cols.COUNTRIES_NAME_COLUMN} AS country "
        f"FROM {cols.DB_SCHEMA}.{cols.USERS_TABLE} u "
        f"LEFT JOIN {cols.DB_SCHEMA}.{cols.STATES_TABLE} s "
        f"ON s.{cols.STATES_ID_COLUMN} = u.{cols.USERS_STATE_ID_COLUMN} "
        f"LEFT JOIN {cols.DB_SCHEMA}.{cols.COUNTRIES_TABLE} c "
        f"ON c.{cols.COUNTRIES_ID_COLUMN} = u.{cols.USERS_COUNTRY_ID_COLUMN} "
        f"WHERE u.{cols.USERS_ID_COLUMN} = %s LIMIT 1"
    )
    rows = query(sql, (beneficiary_id,))
    if not rows:
        return None
    row = rows[0]
    streets = [row.get(f"street_{i}") for i in range(len(cols.USERS_STREET_COLUMNS))]
    # Without a street, city or zip the address is only a state/country,
    # which is far too coarse to measure distance from.
    if not any(clean_text(v) for v in streets + [row.get("city"), row.get("zip_code")]):
        return None
    return join_address(streets + [row.get("city"), row.get("state"),
                                   row.get("zip_code"), row.get("country")])


def _try(step: str, fn: Callable, *args):
    """Run one fallback step; a failure is logged and treated as 'no result'."""
    try:
        return fn(*args)
    except Exception:
        logger.exception("Beneficiary location step %r failed", step)
        return None


def resolve_beneficiary_location(query: QueryFn, request_id: Optional[str] = None,
                                 beneficiary_id: Optional[str] = None
                                 ) -> Optional[BeneficiaryLocation]:
    """Resolve the beneficiary's coordinates. Never raises; None means unknown."""
    request_id = clean_text(request_id)
    beneficiary_id = clean_text(beneficiary_id)
    if request_id is None and beneficiary_id is None:
        return None

    if request_id is not None:
        request = _try("requests", _fetch_request, query, request_id)
        if request is None:
            logger.info("Request %s not found", request_id)
        else:
            point = parse_req_loc(request.get("req_loc"))
            if point is not None:
                return BeneficiaryLocation(point[0], point[1], SOURCE_REQ_LOC)
            # The request's own beneficiary wins over one sent in the body.
            beneficiary_id = clean_text(request.get("beneficiary_id")) or beneficiary_id

    if beneficiary_id is None:
        return None

    point = _try("user_locations", _fetch_current_location, query, beneficiary_id)
    if point is not None:
        return BeneficiaryLocation(point[0], point[1], SOURCE_USER_LOCATIONS)

    address = _try("profile_address", fetch_profile_address, query, beneficiary_id)
    if address is not None:
        result = geocode_address(address)
        if result.status == STATUS_OK:
            return BeneficiaryLocation(result.lat, result.lon, SOURCE_PROFILE_ADDRESS)
        logger.info("Beneficiary profile address geocode status: %s", result.status)
    return None


def fetch_state_names(query: QueryFn, state_ids: list) -> dict:
    """Map state IDs/codes to state names. Returns {} on any failure."""
    ids = sorted({s for s in (clean_text(v) for v in state_ids) if s})
    if not ids:
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    sql = (
        f"SELECT {cols.STATES_ID_COLUMN} AS state_id, {cols.STATES_NAME_COLUMN} AS state_name "
        f"FROM {cols.DB_SCHEMA}.{cols.STATES_TABLE} "
        f"WHERE {cols.STATES_ID_COLUMN} IN ({placeholders})"
    )
    rows = _try("states", query, sql, tuple(ids)) or []
    return {
        str(r["state_id"]): clean_text(r["state_name"])
        for r in rows if clean_text(r.get("state_name"))
    }
