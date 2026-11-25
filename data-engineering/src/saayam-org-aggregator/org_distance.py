"""
Distance calculation helpers for saayam-org-aggregator (Issue #433).

Computes straight-line distance from the BENEFICIARY / REQUEST location
(never the viewer's location) to each recommended organization.

Beneficiary location priority:
    1. coordinates sent with the request body / requests.req_loc
    2. user_locations.curr_loc        (via beneficiary_id)
    3. users + cities/states/countries (profile address -> geocode)
    4. nothing found                  -> distance=None, status="unknown_location"

Design rules from the issue:
    - Geocoding provider is NOT finalized -> pluggable, never hard-coded.
    - Geocoding results are cached (reused across warm Lambda invocations).
    - Distance failures must never break the Organizations API.
    - Unknown distance is None, never 0. A real 0 stays 0.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

EARTH_RADIUS_MILES = 3958.8

DISTANCE_UNIT = "miles"
DISTANCE_METHOD = "straight_line"
DISTANCE_COLUMNS = ["distance", "distance_unit", "distance_method", "distance_status"]

STATUS_OK = "ok"
STATUS_ONLINE = "online"
STATUS_UNKNOWN_LOCATION = "unknown_location"
STATUS_NOT_FOUND = "not_found"
STATUS_DEFERRED = "deferred"
STATUS_ERROR = "error"

Coords = Tuple[float, float]  # (latitude, longitude)


# --------------------------------------------------------------------------
# Settings (schema comes from SSM in the Lambda; table names may differ by env)
# --------------------------------------------------------------------------

SETTINGS: Dict[str, str] = {
    "schema": os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms"),
    # Issue says plural "countries"; older local DBs have "country".
    "country_table": os.environ.get("COUNTRY_TABLE", "countries"),
    # Column on requests that holds the beneficiary – confirm against dev schema.
    "beneficiary_column": os.environ.get("REQUEST_BENEFICIARY_COLUMN", "req_user_id"),
}


def configure(**overrides: Optional[str]) -> None:
    """e.g. configure(schema=_db_name) from helpers.py."""
    SETTINGS.update({k: v for k, v in overrides.items() if v})


def _sql(template: str) -> str:
    return template.format(
        schema=SETTINGS["schema"],
        country=SETTINGS["country_table"],
        benef_col=SETTINGS["beneficiary_column"],
    )


# --------------------------------------------------------------------------
# Coordinates & distance
# --------------------------------------------------------------------------

def _valid(lat: float, lon: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lon <= 180


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):  # pandas NaN
        return True
    return not str(value).strip()


def parse_coordinates(value: Any) -> Optional[Coords]:
    """
    Parse a stored location into (lat, lon). Accepts:
        "longitude:-121.9780,latitude:37.7799"
        "POINT(-121.9780 37.7799)"            (WKT: lon lat)
        '{"latitude": 37.77, "longitude": -121.97}'
        {"lat": 37.77, "lng": -121.97}
        (37.77, -121.97)
    Returns None if nothing usable is found (e.g. a plain city name).
    """
    if _is_blank(value):
        return None
    try:
        if isinstance(value, (tuple, list)) and len(value) == 2:
            lat, lon = float(value[0]), float(value[1])
            return (lat, lon) if _valid(lat, lon) else None

        if isinstance(value, dict):
            lat = value.get("latitude", value.get("lat"))
            lon = value.get("longitude", value.get("lng", value.get("lon")))
            if lat is None or lon is None:
                return None
            lat, lon = float(lat), float(lon)
            return (lat, lon) if _valid(lat, lon) else None

        text = str(value).strip()
        if text.startswith("{"):
            return parse_coordinates(json.loads(text))

        wkt = re.match(r"(?i)^\s*(?:SRID=\d+;)?POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)", text)
        if wkt:
            lon, lat = float(wkt.group(1)), float(wkt.group(2))
            return (lat, lon) if _valid(lat, lon) else None

        lat_m = re.search(r"(?i)lat(?:itude)?\s*[:=]\s*(-?[\d.]+)", text)
        lon_m = re.search(r"(?i)(?:lon(?:gitude)?|lng)\s*[:=]\s*(-?[\d.]+)", text)
        if lat_m and lon_m:
            lat, lon = float(lat_m.group(1)), float(lon_m.group(1))
            return (lat, lon) if _valid(lat, lon) else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    return None


def haversine_miles(a: Coords, b: Coords) -> float:
    """Straight-line (great-circle) distance in miles. Not driving distance."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(h)))


# --------------------------------------------------------------------------
# Geocoding (pluggable provider)
# --------------------------------------------------------------------------

@dataclass
class GeocodeResult:
    coords: Optional[Coords]
    status: str  # ok | not_found | deferred | error | unknown_location


class Geocoder:
    """Interface. Implement `lookup` for the approved provider later."""

    def lookup(self, address: str) -> GeocodeResult:  # pragma: no cover
        raise NotImplementedError


class PendingProviderGeocoder(Geocoder):
    """Default until a provider is approved: geocoding is postponed."""

    def lookup(self, address: str) -> GeocodeResult:
        return GeocodeResult(None, STATUS_DEFERRED)


# Register providers here once approved, e.g. {"aws_location": AwsLocationGeocoder}
GEOCODER_REGISTRY: Dict[str, Callable[[], Geocoder]] = {}


def get_geocoder() -> Geocoder:
    """Pick provider from the GEOCODER_PROVIDER env var; never hard-coded."""
    name = os.environ.get("GEOCODER_PROVIDER", "").strip().lower()
    factory = GEOCODER_REGISTRY.get(name)
    return factory() if factory else PendingProviderGeocoder()


def normalize_address(address: str) -> str:
    return re.sub(r"\s+", " ", address or "").strip().lower()


class CoordinateCache:
    """
    Module-level dict, so results are reused across warm Lambda invocations.
    Only definitive results (ok / not_found) are cached; deferred/error are
    retried next time. A persistent DB cache table can be added once approved.
    """

    _memory: Dict[str, GeocodeResult] = {}

    def get(self, key: str) -> Optional[GeocodeResult]:
        return self._memory.get(key)

    def put(self, key: str, result: GeocodeResult) -> None:
        if result.status in (STATUS_OK, STATUS_NOT_FOUND):
            self._memory[key] = result


def geocode_address(
    address: Optional[str],
    geocoder: Optional[Geocoder] = None,
    cache: Optional[CoordinateCache] = None,
) -> GeocodeResult:
    """Reusable entry point: cache -> provider -> cache. Never raises."""
    if _is_blank(address):
        return GeocodeResult(None, STATUS_UNKNOWN_LOCATION)
    key = normalize_address(address)
    cache = cache or CoordinateCache()
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        result = (geocoder or get_geocoder()).lookup(address)
    except TimeoutError:
        return GeocodeResult(None, STATUS_DEFERRED)
    except Exception as exc:
        logger.warning("geocoding failed for %r: %s", address, exc)
        return GeocodeResult(None, STATUS_ERROR)
    cache.put(key, result)
    return result


# --------------------------------------------------------------------------
# DB helpers (shared pg8000 connection – always roll back on failure)
# --------------------------------------------------------------------------

def _rollback(conn: Any) -> None:
    """A failed query leaves the shared connection in an aborted transaction,
    which would break get_orgs_from_db on the next call. Reset it."""
    try:
        conn.rollback()
    except Exception:
        pass


def _query(conn: Any, sql: str, params: Tuple, many: bool = False):
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall() if many else cur.fetchone()
    except Exception:
        _rollback(conn)
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Address building
# --------------------------------------------------------------------------

def join_address(*parts: Any) -> Optional[str]:
    clean = [str(p).strip() for p in parts if not _is_blank(p)]
    return ", ".join(clean) if clean else None


def build_org_address(org: Dict[str, Any]) -> Optional[str]:
    """Full address from DB org fields (names, not IDs)."""
    return join_address(
        org.get("street"), org.get("city"), org.get("state"),
        org.get("zip_code"), org.get("country"),
    )


# Confirmed against organizations / states / country DDL.
SQL_ORG_ADDRESSES = """
    SELECT o.org_id, o.street, o.city_name, s.state_name, o.zip_code, co.country_name
    FROM {schema}.organizations o
    LEFT JOIN {schema}.states s ON s.state_id = o.state_id
    LEFT JOIN {schema}.{country} co ON co.country_id = s.country_id
    WHERE o.org_id = ANY(%s)
"""


def fetch_org_addresses(conn: Any, org_ids: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    """One query for all DB orgs -> {org_id: {street, city, state, zip_code, country}}."""
    ids = [str(i) for i in org_ids if not _is_blank(i)]
    if not ids or conn is None:
        return {}
    try:
        rows = _query(conn, _sql(SQL_ORG_ADDRESSES), (ids,), many=True) or []
    except Exception as exc:
        logger.warning("org address lookup failed: %s", exc)
        return {}
    return {
        str(r[0]): {"street": r[1], "city": r[2], "state": r[3], "zip_code": r[4], "country": r[5]}
        for r in rows
    }


# --------------------------------------------------------------------------
# Beneficiary location (priority chain)
# --------------------------------------------------------------------------
# !! requests / users / user_locations / cities were not available locally.
# !! Column names below are best guesses – confirm against the dev schema.

SQL_REQUEST = """
    SELECT r.req_loc, r.{benef_col}
    FROM {schema}.requests r
    WHERE r.req_id = %s
"""

SQL_USER_LOCATION = """
    SELECT ul.curr_loc
    FROM {schema}.user_locations ul
    WHERE ul.user_id = %s AND ul.curr_loc IS NOT NULL
    LIMIT 1
"""

SQL_PROFILE_ADDRESS = """
    SELECT u.street_address, c.city_name, s.state_name, u.zip_code, co.country_name
    FROM {schema}.users u
    LEFT JOIN {schema}.cities    c  ON c.city_id     = u.city_id
    LEFT JOIN {schema}.states    s  ON s.state_id    = u.state_id
    LEFT JOIN {schema}.{country} co ON co.country_id = u.country_id
    WHERE u.user_id = %s
"""


@dataclass
class BeneficiaryLocation:
    coords: Optional[Coords]
    source: str  # request | user_location | profile_address | none
    status: str


UNKNOWN_BENEFICIARY = BeneficiaryLocation(None, "none", STATUS_UNKNOWN_LOCATION)


def resolve_beneficiary_location(
    conn: Any,
    request_id: Any = None,
    beneficiary_id: Any = None,
    geocoder: Optional[Geocoder] = None,
    cache: Optional[CoordinateCache] = None,
) -> BeneficiaryLocation:
    """Walk the priority chain. Each step's failure falls through to the next."""
    if conn is None:
        return UNKNOWN_BENEFICIARY

    # 1. requests.req_loc
    if not _is_blank(request_id):
        try:
            row = _query(conn, _sql(SQL_REQUEST), (request_id,))
            if row:
                beneficiary_id = beneficiary_id or row[1]
                coords = parse_coordinates(row[0])
                if coords:
                    return BeneficiaryLocation(coords, "request", STATUS_OK)
        except Exception as exc:
            logger.warning("req_loc lookup failed: %s", exc)

    if _is_blank(beneficiary_id):
        return UNKNOWN_BENEFICIARY

    # 2. user_locations.curr_loc
    try:
        row = _query(conn, _sql(SQL_USER_LOCATION), (beneficiary_id,))
        coords = parse_coordinates(row[0]) if row else None
        if coords:
            return BeneficiaryLocation(coords, "user_location", STATUS_OK)
    except Exception as exc:
        logger.warning("user_locations lookup failed: %s", exc)

    # 3. profile address -> geocode
    try:
        row = _query(conn, _sql(SQL_PROFILE_ADDRESS), (beneficiary_id,))
        # A bare country (e.g. "United States") is not a usable location.
        if row and len([p for p in row if not _is_blank(p)]) > 1:
            result = geocode_address(join_address(*row), geocoder, cache)
            if result.coords:
                return BeneficiaryLocation(result.coords, "profile_address", STATUS_OK)
            return BeneficiaryLocation(None, "profile_address", result.status)
    except Exception as exc:
        logger.warning("profile address lookup failed: %s", exc)

    # 4. give up – never fall back to a default location
    return UNKNOWN_BENEFICIARY


def beneficiary_from_body(
    body: Dict[str, Any],
    conn: Any,
    geocoder: Optional[Geocoder] = None,
    cache: Optional[CoordinateCache] = None,
) -> BeneficiaryLocation:
    """
    Request coordinates sent in the body win (req_loc / latitude+longitude);
    otherwise look up by request_id / beneficiary_id. The body's plain
    `location` (a city name used for the org search) is NOT geocoded – it is
    not the beneficiary's precise location. Never raises.
    """
    try:
        body = body or {}
        coords = (
            parse_coordinates(body.get("req_loc"))
            or parse_coordinates({"latitude": body.get("latitude"), "longitude": body.get("longitude")})
            or parse_coordinates(body.get("location"))
        )
        if coords:
            return BeneficiaryLocation(coords, "request", STATUS_OK)
        return resolve_beneficiary_location(
            conn, body.get("request_id"), body.get("beneficiary_id"), geocoder, cache
        )
    except Exception as exc:
        logger.warning("beneficiary location failed: %s", exc)
        return UNKNOWN_BENEFICIARY


# --------------------------------------------------------------------------
# Enrichment (call from saayam-org-aggregator)
# --------------------------------------------------------------------------

ONLINE_MARKERS = {"online", "remote", "virtual", "online only", "online-only"}


def _distance_fields(distance: Optional[float], status: str) -> Dict[str, Any]:
    return {
        "distance": distance,
        "distance_unit": DISTANCE_UNIT,
        "distance_method": DISTANCE_METHOD,
        "distance_status": status,
    }


def org_location_text(org: Dict[str, Any]) -> Optional[str]:
    """DB orgs: build from parts. GenAI orgs: use the returned address/location."""
    return build_org_address(org) or join_address(org.get("address")) or join_address(org.get("location"))


def compute_org_distance(
    org: Dict[str, Any],
    beneficiary: BeneficiaryLocation,
    geocoder: Optional[Geocoder] = None,
    cache: Optional[CoordinateCache] = None,
) -> Dict[str, Any]:
    try:
        location = org_location_text(org)
        if location and normalize_address(location) in ONLINE_MARKERS:
            return _distance_fields(None, STATUS_ONLINE)
        if beneficiary.coords is None:
            status = beneficiary.status if beneficiary.status != STATUS_OK else STATUS_UNKNOWN_LOCATION
            return _distance_fields(None, status)
        if not location:
            return _distance_fields(None, STATUS_UNKNOWN_LOCATION)

        org_coords = parse_coordinates(org.get("coordinates"))
        if org_coords is None:
            result = geocode_address(location, geocoder, cache)
            if result.coords is None:
                return _distance_fields(None, result.status)
            org_coords = result.coords

        return _distance_fields(round(haversine_miles(beneficiary.coords, org_coords), 1), STATUS_OK)
    except Exception as exc:
        logger.warning("distance calc failed for %r: %s", org.get("name"), exc)
        return _distance_fields(None, STATUS_ERROR)


def add_distances(
    orgs: Iterable[Dict[str, Any]],
    beneficiary: BeneficiaryLocation,
    geocoder: Optional[Geocoder] = None,
    cache: Optional[CoordinateCache] = None,
) -> List[Dict[str, Any]]:
    """Return orgs with distance fields merged in. Existing fields untouched."""
    geocoder = geocoder or get_geocoder()
    cache = cache or CoordinateCache()
    return [{**org, **compute_org_distance(org, beneficiary, geocoder, cache)} for org in orgs]


def distance_fields_for_db_orgs(
    records: List[Dict[str, Any]],
    beneficiary: BeneficiaryLocation,
    conn: Any,
    geocoder: Optional[Geocoder] = None,
    cache: Optional[CoordinateCache] = None,
) -> List[Dict[str, Any]]:
    """
    DB org rows (from SELECT * FROM organizations) -> list of distance-field dicts,
    same order. Uses full address with state/country names.
    """
    addresses = fetch_org_addresses(conn, [r.get("org_id") for r in records]) if beneficiary.coords else {}
    prepared = []
    for r in records:
        addr = addresses.get(str(r.get("org_id")))
        if addr is None:  # fall back to the columns already on the row
            addr = {"street": r.get("street"), "city": r.get("city_name"), "zip_code": r.get("zip_code")}
        prepared.append({"name": r.get("org_name"), **addr})
    return [{k: o[k] for k in DISTANCE_COLUMNS} for o in add_distances(prepared, beneficiary, geocoder, cache)]


def distance_fields_for_ai_orgs(
    records: List[Dict[str, Any]],
    beneficiary: BeneficiaryLocation,
    geocoder: Optional[Geocoder] = None,
    cache: Optional[CoordinateCache] = None,
) -> List[Dict[str, Any]]:
    """GenAI org rows -> distance-field dicts, using their returned address/location."""
    prepared = [
        {"name": r.get("organization_name") or r.get("name"),
         "address": r.get("address"), "location": r.get("location"),
         "coordinates": r.get("coordinates")}
        for r in records
    ]
    return [{k: o[k] for k in DISTANCE_COLUMNS} for o in add_distances(prepared, beneficiary, geocoder, cache)]


def sort_by_distance(orgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Nearest first; unknown (None) last. Stable, so ties keep original order."""
    return sorted(orgs, key=lambda o: (o.get("distance") is None, o.get("distance") or 0))
