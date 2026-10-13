"""Distance calculation for saayam-org-aggregator (issue #433).

Kept in its own module so the existing helpers stay untouched. The database
connection is passed in by the caller.
"""

import logging
import math
import os
import re

import pandas as pd

logger = logging.getLogger(__name__)


def _join_parts(parts, sep=", "):
    """Join values with `sep`, skipping None, NaN, and empty strings."""
    cleaned = [
        str(p).strip()
        for p in parts
        if p is not None
        and not (isinstance(p, float) and pd.isna(p))
        and str(p).strip()
    ]
    return sep.join(cleaned) if cleaned else None


# ---------------------------------------------------------------------------
# Distance calculation (issue #433)
#
# Distance is measured from the beneficiary/request location to each
# organization. It never uses the viewer's location, and it must never break
# the Organizations API: every public function below returns a result instead
# of raising, and an organization is always returned even when its distance is
# unknown (distance = None, never 0).
# ---------------------------------------------------------------------------

DISTANCE_UNIT = "miles"
DISTANCE_METHOD = "straight_line"
EARTH_RADIUS_MILES = 3958.7613

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

_ONLINE_RE = re.compile(
    r"^\s*(online|virtual|remote)(\s*[-/]?\s*only)?\s*$", re.IGNORECASE
)
_LAT_RE = re.compile(r"\blat(?:itude)?\s*[:=]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_LON_RE = re.compile(
    r"\b(?:lon|lng|long|longitude)\s*[:=]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE
)
_POINT_RE = re.compile(
    r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", re.IGNORECASE
)


def parse_coordinates(value):
    """Return (latitude, longitude) from a stored location value, or None.

    Understands "longitude:-121.9780,latitude:37.7799" (the format used by
    requests.req_loc), "POINT(lon lat)", and dicts with latitude/longitude keys.
    """
    if value is None:
        return None

    try:
        if isinstance(value, dict):
            lat = value.get("latitude", value.get("lat"))
            lon = value.get("longitude", value.get("lng", value.get("lon")))
        else:
            text = str(value)
            point = _POINT_RE.search(text)
            if point:
                lon, lat = point.group(1), point.group(2)
            else:
                lat_match = _LAT_RE.search(text)
                lon_match = _LON_RE.search(text)
                if not (lat_match and lon_match):
                    return None
                lat, lon = lat_match.group(1), lon_match.group(1)

        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    return lat, lon


def haversine_miles(lat1, lon1, lat2, lon2):
    """Straight-line (great-circle) distance in miles. Not driving distance."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


# --- Geocoding -------------------------------------------------------------
# The provider is not finalized, so nothing vendor-specific lives here.
# Register a provider with register_geocoder(name, fn) and select it with the
# GEOCODING_PROVIDER environment variable. A provider is any callable that
# takes an address string and returns (latitude, longitude), or None when the
# address cannot be found. It may raise GeocodingDeferred for rate/API limits.


class GeocodingDeferred(Exception):
    """Geocoding was postponed (no provider configured, or rate/API limit)."""


_GEOCODE_PROVIDERS = {}
_NOT_FOUND = object()
_GEOCODE_CACHE = {}
_GEOCODE_CACHE_MAX = 5000


def register_geocoder(name, provider):
    """Plug in a geocoding provider without touching the rest of the Lambda."""
    _GEOCODE_PROVIDERS[name] = provider


def _normalize_address(address):
    return re.sub(r"\s+", " ", str(address)).strip().lower()


def geocode_address(address):
    """Return (latitude, longitude) for an address, or None if not found.

    Results (including definitive "not found") are cached so the same address
    is not geocoded again on every Organizations page load. Raises
    GeocodingDeferred when no provider is configured; other provider errors
    propagate and are mapped to a status by the caller.

    The cache here is in-memory, so it lasts for a warm Lambda container. A
    persistent coordinate store is a schema decision still to be confirmed;
    swap the two cache lines below when it is.
    """
    key = _normalize_address(address)

    cached = _GEOCODE_CACHE.get(key)
    if cached is not None:
        return None if cached is _NOT_FOUND else cached

    provider = _GEOCODE_PROVIDERS.get(os.environ.get("GEOCODING_PROVIDER", ""))
    if provider is None:
        raise GeocodingDeferred("No geocoding provider configured")

    result = provider(address)
    coords = None
    if result is not None:
        coords = parse_coordinates(
            {"latitude": result[0], "longitude": result[1]}
        )

    if len(_GEOCODE_CACHE) >= _GEOCODE_CACHE_MAX:
        _GEOCODE_CACHE.clear()
    _GEOCODE_CACHE[key] = coords if coords is not None else _NOT_FOUND

    return coords


# --- Beneficiary location --------------------------------------------------


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def _safe_query_one(conn, sql, params):
    """Run a read query and return the first row as a dict, or None.

    On a database error the shared connection is rolled back; otherwise the
    open transaction stays aborted and every later query (including the
    existing org lookups) would fail.
    """
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        finally:
            cursor.close()
    except Exception as e:
        logger.warning("Distance lookup query failed: %s", e)
        _rollback(conn)
        return None


def _beneficiary_profile_address(conn, db_name, beneficiary_id):
    """Build the beneficiary's profile address from users (+ state/country)."""
    row = _safe_query_one(
        conn,
        f"""
        SELECT u.addr_ln1, u.addr_ln2, u.addr_ln3, u.city_name, u.zip_code,
               s.state_name, c.country_name
        FROM {db_name}.users AS u
        LEFT JOIN {db_name}.states AS s ON u.state_id = s.state_id
        LEFT JOIN {db_name}.countries AS c ON u.country_id = c.country_id
        WHERE u.user_id = %s
        """,
        (beneficiary_id,),
    )

    if row is None:
        # Fall back to the plain users lookup the aggregator already relies on.
        row = _safe_query_one(
            conn,
            f"SELECT * FROM {db_name}.users WHERE user_id = %s",
            (beneficiary_id,),
        )
        if row is None:
            return None

    has_place = any(row.get(k) for k in ("addr_ln1", "city_name", "zip_code"))
    if not has_place:
        return None

    return _join_parts(
        [
            row.get("addr_ln1"),
            row.get("addr_ln2"),
            row.get("addr_ln3"),
            row.get("city_name"),
            row.get("state_name"),
            row.get("zip_code"),
            row.get("country_name"),
        ]
    )


def resolve_beneficiary_coordinates(conn, db_name, request_id, beneficiary_id):
    """Find the beneficiary/request coordinates. Never raises.

    Order: requests.req_loc, then user_locations.curr_loc, then the profile
    address (geocoded). Returns (coords, status): coords is (lat, lon) or
    None, and status is None on success or the reason it is unknown. No
    default location is ever substituted.
    """
    if not request_id or not beneficiary_id:
        # Nothing to look up; never fall back to a default location.
        return None, STATUS_UNKNOWN_LOCATION

    try:
        row = _safe_query_one(
            conn,
            f"""
            SELECT req_loc
            FROM {db_name}.requests
            WHERE req_id = %s AND beneficiary_id = %s
            """,
            (request_id, beneficiary_id),
        )
        coords = parse_coordinates(row.get("req_loc")) if row else None
        if coords:
            return coords, None

        row = _safe_query_one(
            conn,
            f"""
            SELECT curr_loc
            FROM {db_name}.user_locations
            WHERE user_id = %s
            """,
            (beneficiary_id,),
        )
        coords = parse_coordinates(row.get("curr_loc")) if row else None
        if coords:
            return coords, None

        address = _beneficiary_profile_address(conn, db_name, beneficiary_id)
        if not address:
            return None, STATUS_UNKNOWN_LOCATION

        try:
            coords = geocode_address(address)
        except GeocodingDeferred:
            return None, STATUS_DEFERRED
        except Exception as e:
            logger.warning("Beneficiary geocoding failed: %s", e)
            return None, STATUS_ERROR

        if coords is None:
            return None, STATUS_NOT_FOUND
        return coords, None

    except Exception as e:
        logger.warning("Beneficiary location lookup failed: %s", e)
        return None, STATUS_ERROR


# --- Organization address and distance -------------------------------------


def get_org_address_parts(conn, db_name, org_ids):
    """Map str(org_id) -> (state_name, country_name) for DB organizations.

    Best effort: returns {} on any failure, so addresses simply fall back to
    the fields already on the organization row.
    """
    ids = [i.item() if hasattr(i, "item") else i for i in org_ids if i is not None]
    if not ids:
        return {}

    try:
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"""
                SELECT o.org_id, s.state_name, c.country_name
                FROM {db_name}.organizations AS o
                LEFT JOIN {db_name}.states AS s ON o.state_id = s.state_id
                LEFT JOIN {db_name}.countries AS c ON s.country_id = c.country_id
                WHERE o.org_id = ANY(%s)
                """,
                (ids,),
            )
            return {str(r[0]): (r[1], r[2]) for r in cursor.fetchall()}
        finally:
            cursor.close()
    except Exception as e:
        logger.warning("Org address lookup failed: %s", e)
        _rollback(conn)
        return {}


def _clean(value):
    """Return a stripped string, or None for None/NaN/empty values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _db_org_address(row, address_parts):
    """Full address for a DB organization, using names rather than IDs."""
    state_name, country_name = address_parts.get(str(row.get("org_id")), (None, None))

    state = _clean(state_name)
    if state is None:
        # Only a short alphabetic code (e.g. "TX") is usable as a place name.
        raw_state = _clean(row.get("state_id"))
        if raw_state and raw_state.isalpha():
            state = raw_state

    street = _clean(row.get("street"))
    city = _clean(row.get("city_name"))
    zip_code = _clean(row.get("zip_code"))

    if not (street or city or zip_code):
        return None

    return _join_parts([street, city, state, zip_code, _clean(country_name)])


def _ai_org_address(row):
    """Address/location as returned by GenAI, or None if it gave none."""
    for key in ("address", "full_address", "location"):
        value = _clean(row.get(key))
        if value:
            return value
    return None


def _is_online_org(row, address):
    flag = row.get("is_online")
    if flag is True or str(flag).strip().lower() in ("true", "1", "yes"):
        return True
    return bool(address and _ONLINE_RE.match(address))


def _distance_result(distance, status):
    return {
        "distance": distance,
        "distance_unit": DISTANCE_UNIT,
        "distance_method": DISTANCE_METHOD,
        "distance_status": status,
    }


def compute_org_distance(beneficiary_coords, beneficiary_status, address, online=False):
    """Distance fields for one organization. Never raises."""
    try:
        if online:
            return _distance_result(None, STATUS_ONLINE)

        if beneficiary_coords is None:
            return _distance_result(None, beneficiary_status or STATUS_UNKNOWN_LOCATION)

        if not address:
            return _distance_result(None, STATUS_UNKNOWN_LOCATION)

        try:
            org_coords = geocode_address(address)
        except GeocodingDeferred:
            return _distance_result(None, STATUS_DEFERRED)
        except Exception as e:
            logger.warning("Geocoding failed for %r: %s", address, e)
            return _distance_result(None, STATUS_ERROR)

        if org_coords is None:
            return _distance_result(None, STATUS_NOT_FOUND)

        miles = haversine_miles(
            beneficiary_coords[0],
            beneficiary_coords[1],
            org_coords[0],
            org_coords[1],
        )
        # round() keeps a genuine 0 as 0.0; unknown is always None.
        return _distance_result(round(miles, 1), STATUS_OK)

    except Exception as e:
        logger.warning("Distance calculation failed: %s", e)
        return _distance_result(None, STATUS_ERROR)


def add_distance_to_orgs(
    df, beneficiary_coords, beneficiary_status, source, conn=None, db_name=None
):
    """Return df with distance, distance_unit, distance_method and
    distance_status columns. Rows are never dropped or reordered, and a
    failure only changes the distance fields.

    source is "db" or "ai": it decides how the organization address is built.
    Call this before merge_organizations, which drops the address columns.
    """
    if df is None:
        return df

    df = df.copy()

    try:
        if df.empty:
            for column in DISTANCE_COLUMNS:
                df[column] = pd.Series(dtype=object)
            return df

        address_parts = {}
        if source == "db" and conn is not None and "org_id" in df.columns:
            address_parts = get_org_address_parts(conn, db_name, df["org_id"].tolist())

        results = []
        for _, row in df.iterrows():
            try:
                if source == "db":
                    address = _db_org_address(row, address_parts)
                else:
                    address = _ai_org_address(row)

                results.append(
                    compute_org_distance(
                        beneficiary_coords,
                        beneficiary_status,
                        address,
                        online=_is_online_org(row, address),
                    )
                )
            except Exception as e:
                logger.warning("Distance failed for one organization: %s", e)
                results.append(_distance_result(None, STATUS_ERROR))

    except Exception as e:
        logger.warning("Distance step failed: %s", e)
        results = [_distance_result(None, STATUS_ERROR) for _ in range(len(df))]

    for column in DISTANCE_COLUMNS:
        df[column] = pd.Series(
            [r[column] for r in results], index=df.index, dtype=object
        )

    return df


def finalize_distance_columns(df):
    """Turn NaN distances into None so the JSON response has null, not NaN."""
    for column in DISTANCE_COLUMNS:
        if column in df.columns:
            df[column] = df[column].astype(object).where(df[column].notna(), None)
    return df


def sort_by_distance(df):
    """Nearest first, farther next, unknown (null) distances last."""
    order = pd.to_numeric(df["distance"], errors="coerce")
    return (
        df.assign(_distance_order=order)
        .sort_values("_distance_order", kind="stable", na_position="last")
        .drop(columns="_distance_order")
        .reset_index(drop=True)
    )
