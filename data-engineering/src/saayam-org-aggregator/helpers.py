import math
import os
import re
import boto3
import json
import logging
from typing import Optional, Tuple

import pandas as pd
import pg8000
from aws_lambda_powertools.utilities import parameters

logger = logging.getLogger(__name__)

GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"

lambda_client = boto3.client("lambda")

_creds = json.loads(
    parameters.get_parameter(
        "/dev/saayam/db/Virginia/Analytics/user",
        decrypt=True,
        max_age=3600,
    )
)
_db_name = _creds["DATABASE NAME"]
_db_conn = pg8000.connect(
    host=_creds["HOST"],
    user=_creds["USERNAME"],
    password=_creds["PASSWORD"],
    database=_db_name,
    port=int(_creds["PORT"]),
    ssl_context=True,
)

# In-memory geocoding cache: normalized address -> ((lat, lon), status) or None.
# Only "ok" and "not_found" are cached.
# "deferred" and "error" are NOT cached so they are retried on the next invocation.
_geocode_cache: dict = {}

# Keywords indicating an org is online-only and has no physical location.
_ONLINE_KEYWORDS = frozenset({"online", "nationwide", "virtual", "remote", "internet"})

EARTH_RADIUS_MILES = 3958.8


# Geocoding provider registry (pluggable — no provider hard-coded)

class _DeferredError(Exception):
    """Raised by _PendingGeocoder to signal geocoding is not yet configured."""


class _GeocoderBase:
    """Interface. Register concrete implementations in GEOCODER_REGISTRY."""
    def lookup(self, address: str) -> Optional[Tuple[float, float]]:  # pragma: no cover
        raise NotImplementedError


class _PendingGeocoder(_GeocoderBase):
    """Default until a provider is approved. Raises _DeferredError on every call."""
    def lookup(self, address: str) -> Optional[Tuple[float, float]]:
        raise _DeferredError()


# Register approved providers here, e.g. {"aws_location": AwsLocationGeocoder}
GEOCODER_REGISTRY: dict = {}


def _get_geocoder() -> _GeocoderBase:
    """Pick provider from the GEOCODER_PROVIDER env var; never hard-coded."""
    name = os.environ.get("GEOCODER_PROVIDER", "").strip().lower()
    factory = GEOCODER_REGISTRY.get(name)
    return factory() if factory else _PendingGeocoder()


def geocode_address(address: str) -> Tuple[Optional[Tuple[float, float]], str]:
    """Convert a free-form address string to ((lat, lon), status).

    Status values:
      "ok"        — coordinates found
      "not_found" — provider returned no result (cached)
      "deferred"  — no provider configured yet (not cached, retried next invocation)
      "error"     — exception from provider (not cached)

    Results are cached for "ok" and "not_found" so the same address is never
    sent to the geocoding provider more than once in a warm Lambda container.
    """
    if not address or not address.strip():
        return None, "not_found"

    normalized = address.strip().lower()

    if normalized in _geocode_cache:
        return _geocode_cache[normalized]

    try:
        coords = _get_geocoder().lookup(address)
        result = (coords, "ok") if coords else (None, "not_found")
    except _DeferredError:
        return None, "deferred"   # not cached — retry next invocation
    except TimeoutError:
        return None, "deferred"   # not cached
    except Exception as exc:
        logger.warning("geocode_address: error for address=%r: %s", address, exc)
        return None, "error"      # not cached

    _geocode_cache[normalized] = result
    return result


# DB connection safety

def _rollback(conn) -> None:
    """Rollback the shared DB connection after a failed query.

    pg8000 leaves the connection in an aborted-transaction state after any
    unhandled exception. Without an explicit rollback, the next query also
    fails. Call this in every except block that touches _db_conn.
    """
    try:
        conn.rollback()
    except Exception:
        pass


# Beneficiary / request location resolution

def _parse_req_loc(req_loc: str) -> Optional[Tuple[float, float]]:
    """Parse the req_loc column value into (lat, lon).

    Accepted formats:
      "longitude:-121.9780,latitude:37.7799"
      "latitude:37.7799,longitude:-121.9780"
      WKT: "POINT(-121.9780 37.7799)"
    Returns None if the string cannot be parsed.
    """
    if not req_loc:
        return None

    # Key=value format (order-insensitive)
    lat_m = re.search(r"latitude\s*:\s*(-?\d+(?:\.\d+)?)", req_loc, re.IGNORECASE)
    lon_m = re.search(r"longitude\s*:\s*(-?\d+(?:\.\d+)?)", req_loc, re.IGNORECASE)
    if lat_m and lon_m:
        return (float(lat_m.group(1)), float(lon_m.group(1)))

    # WKT POINT (lon lat order)
    wkt = re.match(
        r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)",
        req_loc,
        re.IGNORECASE,
    )
    if wkt:
        lon, lat = float(wkt.group(1)), float(wkt.group(2))
        return (lat, lon)

    logger.warning("_parse_req_loc: unrecognised format: %r", req_loc)
    return None


def get_beneficiary_location(
    beneficiary_id: str,
) -> Tuple[Optional[Tuple[float, float]], str]:
    """Resolve the beneficiary's coordinates using a 3-step fallback.

    Returns (coordinates, status) where coordinates is (lat, lon) or None.
    Status values:
      "req_loc"          — from request.req_loc
      "user_loc"         — from user_locations.curr_loc (PostGIS)
      "profile_address"  — geocoded from users + state/country tables
      "unknown_location" — could not determine location

    NOTE: Looks up the most recent request for the given beneficiary_id.
    Use get_beneficiary_location_by_request() when you have a specific request_id.
    """
    if not beneficiary_id:
        return None, "unknown_location"

    cursor = _db_conn.cursor()
    try:
        # Step 1: request.req_loc
        cursor.execute(
            f"""
            SELECT req_loc
            FROM {_db_name}.request
            WHERE req_user_id = %s
            ORDER BY submission_date DESC
            LIMIT 1
            """,
            (beneficiary_id,),
        )
        row = cursor.fetchone()
        if row and row[0]:
            coords = _parse_req_loc(row[0])
            if coords:
                return coords, "req_loc"

        # Step 2: user_locations.curr_loc
        cursor.execute(
            f"""
            SELECT ST_Y(curr_loc::geometry) AS lat,
                   ST_X(curr_loc::geometry) AS lon
            FROM {_db_name}.user_locations
            WHERE user_id = %s
              AND curr_loc IS NOT NULL
            """,
            (beneficiary_id,),
        )
        row = cursor.fetchone()
        if row and row[0] is not None and row[1] is not None:
            return (float(row[0]), float(row[1])), "user_loc"

        # Step 3: geocode profile address
        cursor.execute(
            f"""
            SELECT u.addr_ln1, u.addr_ln2, u.city_name,
                   s.state_name, c.country_name, u.zip_code
            FROM {_db_name}.users u
            LEFT JOIN {_db_name}.state s ON s.state_id = u.state_id
            LEFT JOIN {_db_name}.country c ON c.country_id = u.country_id
            WHERE u.user_id = %s
            """,
            (beneficiary_id,),
        )
        row = cursor.fetchone()
        if row:
            addr_ln1, addr_ln2, city_name, state_name, country_name, zip_code = row
            parts = [
                p for p in [addr_ln1, addr_ln2, city_name, state_name, zip_code, country_name]
                if p and str(p).strip()
            ]
            if parts:
                coords, _ = geocode_address(", ".join(parts))
                if coords:
                    return coords, "profile_address"

        return None, "unknown_location"

    except Exception as exc:
        logger.error(
            "get_beneficiary_location: error for beneficiary_id=%r: %s",
            beneficiary_id, exc,
        )
        _rollback(_db_conn)
        return None, "unknown_location"
    finally:
        cursor.close()


def get_beneficiary_location_by_request(
    request_id: str,
) -> Tuple[Optional[Tuple[float, float]], str]:
    """Same 3-step fallback anchored to a specific request_id.

    Step 1 reads req_loc from the specific request.
    Steps 2-3 fall back via the request's req_user_id.
    """
    if not request_id:
        return None, "unknown_location"

    cursor = _db_conn.cursor()
    try:
        cursor.execute(
            f"""
            SELECT req_loc, req_user_id
            FROM {_db_name}.request
            WHERE req_id = %s
            """,
            (request_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None, "unknown_location"

        req_loc, beneficiary_id = row[0], row[1]
        if req_loc:
            coords = _parse_req_loc(req_loc)
            if coords:
                return coords, "req_loc"

        return get_beneficiary_location(beneficiary_id)

    except Exception as exc:
        logger.error(
            "get_beneficiary_location_by_request: error for request_id=%r: %s",
            request_id, exc,
        )
        _rollback(_db_conn)
        return None, "unknown_location"
    finally:
        cursor.close()


# Distance calculation

def calculate_distance(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
) -> float:
    """Return straight-line distance in miles using the haversine formula.
    Not driving distance or travel time.
    """
    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = map(math.radians, destination)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(h))), 1)


def _is_online_location(location: Optional[str]) -> bool:
    """Return True if the location string indicates an online-only org."""
    if not location:
        return False
    return str(location).strip().lower() in _ONLINE_KEYWORDS


def _resolve_org_coords(org: dict) -> Tuple[Optional[Tuple[float, float]], str]:
    """Geocode an org's address. Returns (coords, status).

    Tries structured DB fields first (street/city/state/zip), then falls
    back to the plain 'location' string for GenAI orgs.
    Returns the geocode status so the caller can propagate it correctly.
    """
    location = org.get("location")

    # Online-only orgs have no physical address — don't geocode them
    if _is_online_location(location):
        return None, "online"

    # DB orgs: prefer structured address for higher geocoding accuracy
    parts = [
        org.get("street"),
        org.get("city_name") or location,
        org.get("state_code"),
        org.get("zip_code"),
    ]
    structured = ", ".join(p for p in parts if p and str(p).strip())
    if structured:
        coords, status = geocode_address(structured)
        if coords:
            return coords, "ok"
        # Propagate deferred/error; fall through to plain location on not_found
        if status in ("deferred", "error"):
            return None, status

    # GenAI orgs / fallback: plain location string
    if location and str(location).strip():
        coords, status = geocode_address(str(location))
        return coords, status

    return None, "not_found"


def _nan_to_none(value):
    """Convert float NaN to None so json.dumps produces valid JSON null."""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def attach_distance(
    org: dict,
    beneficiary_coords: Optional[Tuple[float, float]],
) -> dict:
    """Add distance fields to an organisation dict.

    Fields added:
      distance        — float (miles) or null
      distance_unit   — "miles"
      distance_method — "straight_line"
      distance_status — "ok" | "unknown_location" | "not_found" |
                        "online" | "deferred" | "error"

    Status meanings:
      ok               — calculated successfully
      unknown_location — beneficiary location could not be determined
      not_found        — org address could not be geocoded
      online           — org is online-only, no physical location
      deferred         — geocoding provider not yet configured
      error            — unexpected exception

    The org is always returned even if distance fails.
    NaN values in org fields are sanitized to None (valid JSON null).
    A real distance of 0 is returned as 0, never as null.
    """
    # Sanitize any NaN values from pandas to avoid invalid JSON
    org = {k: _nan_to_none(v) for k, v in org.items()}

    try:
        if beneficiary_coords is None:
            org.update({
                "distance": None, "distance_unit": "miles",
                "distance_method": "straight_line", "distance_status": "unknown_location",
            })
            return org

        org_coords, geo_status = _resolve_org_coords(org)
        if org_coords is None:
            org.update({
                "distance": None, "distance_unit": "miles",
                "distance_method": "straight_line", "distance_status": geo_status,
            })
            return org

        org.update({
            "distance": calculate_distance(beneficiary_coords, org_coords),
            "distance_unit": "miles",
            "distance_method": "straight_line",
            "distance_status": "ok",
        })
        return org

    except Exception as exc:
        logger.error("attach_distance: error for org=%r: %s", org.get("name"), exc)
        org.update({
            "distance": None, "distance_unit": "miles",
            "distance_method": "straight_line", "distance_status": "error",
        })
        return org


# DB + GenAI fetchers

def get_orgs_from_db(location: str, category: str) -> pd.DataFrame:
    """Fetch matching organisations from the database.

    Selects address columns (street, state_code, zip_code) in addition to the
    standard display columns so that distance calculation has structured data.
    """
    try:
        cursor = _db_conn.cursor()
        cursor.execute(
            f"""
            SELECT org_id, org_name, city_name, phone, email, web_url,
                   mission, source, org_type, is_collaborator, size,
                   rating, street, state_code, zip_code
            FROM {_db_name}.organizations
            WHERE mission = %s AND city_name = %s
            """,
            (category, location),
        )
        rows = cursor.fetchall()
        columns = [
            "org_id", "org_name", "city_name", "phone", "email", "web_url",
            "mission", "source", "org_type", "is_collaborator", "size",
            "rating", "street", "state_code", "zip_code",
        ]
        df = pd.DataFrame(rows, columns=columns)
        df["db_or_ai"] = "db"
        cursor.close()
        return df
    except pg8000.DatabaseError as exc:
        raise Exception(f"Database error while fetching orgs: {exc}") from exc
    except Exception as exc:
        raise Exception(f"Error fetching orgs from DB: {exc}") from exc


def get_ai_orgs(subject: str, description: str, location: str) -> pd.DataFrame:
    """Fetch organisations from the GenAI Lambda.

    Degrades gracefully: any failure returns an empty DataFrame so DB results
    are still surfaced. Never raises.
    """
    _empty = pd.DataFrame(columns=[
        "name", "location", "contact", "email", "web_url", "mission", "source",
        "db_or_ai", "org_type", "is_collaborator", "size", "rating",
        "street", "state_code", "zip_code",
    ])

    try:
        response = lambda_client.invoke(
            FunctionName=GEN_AI_LAMBDA,
            InvocationType="RequestResponse",
            Payload=json.dumps(
                {"subject": subject, "description": description, "location": location}
            ),
        )
        payload = json.loads(response["Payload"].read())
        status_code = payload.get("statusCode")

        body = payload.get("body", {})
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                body = {}

        # Graceful degradation: GenAI explicitly unavailable
        if status_code == 502 and body.get("code") == "ORG_SEARCH_UNAVAILABLE":
            logger.warning("GenAI org search unavailable; using DB results only")
            return _empty

        if status_code != 200:
            logger.warning(
                "GenAI Lambda returned status %s; using DB results only", status_code
            )
            return _empty

        org_records = body.get("organizations", [])
        if not org_records:
            return _empty

        orgs = pd.DataFrame(org_records)
        orgs["db_or_ai"] = "ai"
        orgs["is_collaborator"] = False
        return orgs

    except Exception as exc:
        logger.warning("get_ai_orgs: error, using DB results only: %s", exc)
        return _empty


def merge_organizations(
    db_organizations: pd.DataFrame,
    genAI_organizations: pd.DataFrame,
) -> pd.DataFrame:
    """Merge DB and GenAI organisation DataFrames into a unified shape.

    Address columns (street, state_code, zip_code) are carried through from
    DB orgs so distance calculation has structured data.
    GenAI orgs have those columns as None; _resolve_org_coords falls back to
    the plain 'location' field for them.
    """
    FINAL_COLS = [
        "name", "location", "contact", "email", "web_url",
        "mission", "source", "db_or_ai",
        "org_type", "is_collaborator", "size", "rating",
        "street", "state_code", "zip_code",
    ]

    def _normalise(df: pd.DataFrame, rename_map: dict) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=FINAL_COLS)
        df = df.rename(columns=rename_map).copy()
        for col in FINAL_COLS:
            if col not in df.columns:
                df[col] = None
        return df[FINAL_COLS]

    try:
        db_norm = _normalise(
            db_organizations,
            {"org_name": "name", "city_name": "location", "phone": "contact"},
        )
        ai_norm = _normalise(genAI_organizations, {"organization_name": "name"})
        return pd.concat([db_norm, ai_norm], ignore_index=True)

    except KeyError as exc:
        raise Exception(f"Missing expected column during merge: {exc}") from exc
    except Exception as exc:
        raise Exception(f"Error merging organizations: {exc}") from exc
