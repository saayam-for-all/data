"""Helpers for saayam-org-aggregator (#433 distance enrichment).

Based on the production aggregator attached to issue #433, with beneficiary-based
straight-line distance fields. Geocoding is provider-neutral: inject a callable
into ``_geocode_address_impl`` once a provider is approved.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import boto3
import pandas as pd
import psycopg2
from aws_lambda_powertools.utilities import parameters

logger = logging.getLogger(__name__)

GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"
MILES_PER_EARTH_RADIUS = 3958.7613

# Final response shape expected by the Request Details Organizations tab.
ORG_COLUMNS = [
    "name",
    "organization_type",
    "collaborator",
    "location",
    "size",
    "rating",
    "contact",
    "email",
    "web_url",
    "mission",
    "source",
]

DISTANCE_COLUMNS = [
    "distance",
    "distance_unit",
    "distance_method",
    "distance_status",
]

# Kept through merge so addresses can be geocoded for distance.
ADDRESS_COLUMNS = [
    "street",
    "city_name",
    "state_id",
    "state_name",
    "zip_code",
    "country_name",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "lng",
    "online_only",
    "is_online",
    "address",
    "full_address",
]

DB_RENAME = {
    "org_name": "name",
    "org_type": "organization_type",
    "is_collaborator": "collaborator",
    "org_rating": "rating",
    "org_size": "size",
    "web_url": "web_url",
    "phone": "contact",
}

AI_RENAME = {
    "organization_name": "name",
    "org_type": "organization_type",
    "is_collaborator": "collaborator",
    "contact": "contact",
    "web_url": "web_url",
}

# --- Cached at module level so Lambda cold-starts are cheap ---
lambda_client = boto3.client("lambda")

_creds = json.loads(
    parameters.get_parameter(
        "/dev/saayam/db/Virginia/Analytics/user",
        decrypt=True,
        max_age=3600,
    )
)
_db_name = _creds["DATABASE NAME"]
_db_conn = psycopg2.connect(
    host=_creds["HOST"],
    user=_creds["USERNAME"],
    password=_creds["PASSWORD"],
    database=_db_name,
    port=_creds["PORT"],
    sslmode="require",
)

# Process-local geocode cache. Durable storage can replace this later.
_GEOCODE_CACHE: Dict[str, Tuple[float, float]] = {}
# Inject an approved provider: Callable[[str], Any] -> coords / mapping / string.
_geocode_address_impl: Optional[Callable[[str], Any]] = None
# -------------------------------------------------------------


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


def _empty_ai_frame():
    """Return an empty AI DataFrame with the final response columns."""
    return pd.DataFrame(columns=ORG_COLUMNS)


def parse_coordinates(value):
    """Parse supported coordinate values into (latitude, longitude).

    Accepts a mapping, a two-item sequence, ``longitude:..,latitude:..``,
    and PostGIS ``POINT(lon lat)``. Invalid values return None; zero is valid.
    """
    latitude = longitude = None
    if isinstance(value, dict):
        latitude = value.get("latitude", value.get("lat"))
        longitude = value.get("longitude", value.get("lon", value.get("lng")))
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        latitude, longitude = value
    elif isinstance(value, str):
        text = value.strip()
        point = re.search(
            r"POINT\s*\(\s*([-+\d.eE]+)\s+([-+\d.eE]+)\s*\)", text, re.I
        )
        if point:
            longitude, latitude = point.group(1), point.group(2)
        else:
            lat_match = re.search(
                r"(?:latitude|lat)\s*[:=]\s*([-+\d.eE]+)", text, re.I
            )
            lon_match = re.search(
                r"(?:longitude|lon|lng)\s*[:=]\s*([-+\d.eE]+)", text, re.I
            )
            if lat_match and lon_match:
                latitude, longitude = lat_match.group(1), lon_match.group(1)
            else:
                pair = re.fullmatch(
                    r"\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*", text
                )
                if pair:
                    latitude, longitude = pair.group(1), pair.group(2)
    if latitude is None or longitude is None:
        return None
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def straight_line_distance_miles(origin, destination):
    """Return the great-circle distance in miles, or None for invalid points."""
    origin = parse_coordinates(origin)
    destination = parse_coordinates(destination)
    if origin is None or destination is None:
        return None
    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = map(math.radians, destination)
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    haversine = min(1.0, max(0.0, haversine))
    return 2 * MILES_PER_EARTH_RADIUS * math.asin(math.sqrt(haversine))


def build_address(record):
    """Build a human-readable address from whichever real fields are present."""
    if not isinstance(record, dict):
        return ""

    def text_value(value):
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except (TypeError, ValueError):
            pass
        return str(value).strip()

    direct = text_value(record.get("address")) or text_value(
        record.get("full_address")
    )
    if direct:
        return direct
    fields = (
        "street",
        "addr_ln1",
        "addr_ln2",
        "addr_ln3",
        "city",
        "city_name",
        "state",
        "state_name",
        "state_code",
        "state_id",
        "zip_code",
        "postal_code",
        "country",
        "country_name",
        "location",
    )
    parts, seen = [], set()
    for field in fields:
        cleaned = text_value(record.get(field))
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key not in seen:
            parts.append(cleaned)
            seen.add(key)
    return ", ".join(parts)


def geocode_address(address):
    """Resolve an address through an injected provider, if one is approved.

    Returns ``(coordinates, status)``. Without a provider the status is
    ``deferred`` rather than inventing a default location.
    """
    address = (address or "").strip()
    if not address:
        return None, "unknown_location"
    cached = _GEOCODE_CACHE.get(address.casefold())
    if cached is not None:
        return cached, "ok"
    if _geocode_address_impl is None:
        return None, "deferred"
    try:
        coordinates = parse_coordinates(_geocode_address_impl(address))
    except TimeoutError:
        return None, "deferred"
    except Exception:
        return None, "error"
    if coordinates is None:
        return None, "not_found"
    _GEOCODE_CACHE[address.casefold()] = coordinates
    return coordinates, "ok"


def _table_columns(table_name):
    """Return known column names for a table in the configured schema."""
    rows = pd.read_sql(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        _db_conn,
        params=(_db_name, table_name),
    )
    return set(rows.get("column_name", []))


def _first_row(sql, params=()):
    """Execute a parameterized lookup and return its first row as a dict."""
    rows = pd.read_sql(sql, _db_conn, params=params)
    return None if rows.empty else rows.iloc[0].to_dict()


def _get_request_and_beneficiary(request_id, beneficiary_id=None):
    """Read request location and beneficiary ID (never the current viewer)."""
    request_row = None
    if request_id:
        request_cols = _table_columns("requests")
        id_col = (
            "req_id"
            if "req_id" in request_cols
            else "request_id"
            if "request_id" in request_cols
            else None
        )
        if id_col:
            select_cols = [id_col]
            if "req_loc" in request_cols:
                select_cols.append("req_loc")
            if "beneficiary_id" in request_cols:
                select_cols.append("beneficiary_id")
            elif "req_for_id" in request_cols:
                select_cols.append("req_for_id")
            request_row = _first_row(
                f"SELECT {', '.join(select_cols)} "
                f"FROM {_db_name}.requests WHERE {id_col} = %s",
                (request_id,),
            )
    if request_row:
        beneficiary_id = (
            request_row.get("beneficiary_id")
            or request_row.get("req_for_id")
            or beneficiary_id
        )
    return request_row or {}, beneficiary_id


def _get_user_coordinates(beneficiary_id):
    """Read the beneficiary's current PostGIS point from user_locations."""
    if not beneficiary_id:
        return None
    location_cols = _table_columns("user_locations")
    id_col = (
        "user_id"
        if "user_id" in location_cols
        else "beneficiary_id"
        if "beneficiary_id" in location_cols
        else None
    )
    if id_col is None or "curr_loc" not in location_cols:
        return None
    updated_col = (
        "updated_at"
        if "updated_at" in location_cols
        else "last_updated_at"
        if "last_updated_at" in location_cols
        else None
    )
    order_clause = (
        f"ORDER BY {updated_col} DESC NULLS LAST " if updated_col else ""
    )
    row = _first_row(
        f"SELECT ST_Y(curr_loc::geometry) AS latitude, "
        f"ST_X(curr_loc::geometry) AS longitude "
        f"FROM {_db_name}.user_locations "
        f"WHERE {id_col} = %s AND curr_loc IS NOT NULL "
        f"{order_clause}LIMIT 1",
        (beneficiary_id,),
    )
    return parse_coordinates(row) if row else None


def _get_profile_address(beneficiary_id):
    """Build the beneficiary profile address using plural Virginia tables."""
    if not beneficiary_id:
        return ""
    user_cols = _table_columns("users")
    state_cols = _table_columns("states")
    country_cols = _table_columns("countries")
    city_cols = _table_columns("cities")
    select = [
        f"u.{column} AS {column}"
        for column in ("addr_ln1", "addr_ln2", "addr_ln3", "city_name", "zip_code")
        if column in user_cols
    ]
    joins: List[str] = []
    if "state_id" in user_cols and {"state_id", "state_name"}.issubset(state_cols):
        select.append("s.state_name AS state_name")
        joins.append(f"LEFT JOIN {_db_name}.states s ON s.state_id = u.state_id")
    if "country_id" in user_cols and {"country_id", "country_name"}.issubset(
        country_cols
    ):
        select.append("co.country_name AS country_name")
        joins.append(
            f"LEFT JOIN {_db_name}.countries co ON co.country_id = u.country_id"
        )
    if "city_id" in user_cols and {"city_id", "city_name"}.issubset(city_cols):
        select = [item for item in select if item != "u.city_name AS city_name"]
        select.append("ci.city_name AS city_name")
        joins.append(f"LEFT JOIN {_db_name}.cities ci ON ci.city_id = u.city_id")
    if not select:
        return ""
    row = _first_row(
        f"SELECT {', '.join(select)} FROM {_db_name}.users u "
        f"{' '.join(joins)} WHERE u.user_id = %s",
        (beneficiary_id,),
    )
    return build_address(row or {})


def resolve_beneficiary_coordinates(request_id=None, beneficiary_id=None):
    """Resolve coordinates: request → user_locations → profile geocode.

    Never uses a default country such as ``United States``.
    """
    request_row = {}
    had_lookup_error = False
    try:
        request_row, beneficiary_id = _get_request_and_beneficiary(
            request_id, beneficiary_id
        )
    except Exception:
        had_lookup_error = True

    coordinates = parse_coordinates(request_row.get("req_loc"))
    if coordinates is not None:
        return {"coordinates": coordinates, "status": "ok"}

    try:
        coordinates = _get_user_coordinates(beneficiary_id)
        if coordinates is not None:
            return {"coordinates": coordinates, "status": "ok"}
    except Exception:
        had_lookup_error = True

    addresses = []
    # req_loc may be free text rather than coordinates.
    req_loc = request_row.get("req_loc")
    if isinstance(req_loc, str) and parse_coordinates(req_loc) is None:
        addresses.append(req_loc.strip())
    try:
        addresses.append(_get_profile_address(beneficiary_id))
    except Exception:
        had_lookup_error = True

    latest_geocode_status = None
    for address in dict.fromkeys(a for a in addresses if a):
        coordinates, status = geocode_address(address)
        if coordinates is not None:
            return {"coordinates": coordinates, "status": "ok"}
        latest_geocode_status = status

    if latest_geocode_status:
        return {"coordinates": None, "status": latest_geocode_status}
    status = "error" if had_lookup_error else "unknown_location"
    return {"coordinates": None, "status": status}


def add_organization_distances(organizations, beneficiary_location):
    """Attach distance fields; never drop organizations on failures."""
    result = organizations.copy()
    result["distance"] = None
    result["distance_unit"] = "miles"
    result["distance_method"] = "straight_line"
    result["distance_status"] = "unknown_location"

    beneficiary_coordinates = parse_coordinates(
        (beneficiary_location or {}).get("coordinates")
    )
    beneficiary_status = (beneficiary_location or {}).get(
        "status", "unknown_location"
    )

    for index, row in result.iterrows():
        values = row.to_dict()
        online_flags = (values.get("online_only"), values.get("is_online"))
        if any(
            str(flag).strip().casefold() in {"true", "1", "yes"}
            for flag in online_flags
            if flag is not None and not (isinstance(flag, float) and pd.isna(flag))
        ):
            result.at[index, "distance_status"] = "online"
            continue

        if beneficiary_coordinates is None:
            result.at[index, "distance_status"] = beneficiary_status
            continue

        org_coordinates = parse_coordinates(values)
        if org_coordinates is None:
            address = build_address(values) or build_address(
                {"address": values.get("location")}
            )
            org_coordinates, status = geocode_address(address)
            if org_coordinates is None:
                result.at[index, "distance_status"] = status
                continue

        distance = straight_line_distance_miles(
            beneficiary_coordinates, org_coordinates
        )
        if distance is None:
            result.at[index, "distance_status"] = "error"
            continue
        result.at[index, "distance"] = round(float(distance), 1)
        result.at[index, "distance_status"] = "ok"

    return result


def sort_organizations_by_distance(organizations):
    """Nearest first; unknown / null distances last. Stable within groups."""
    if organizations is None or organizations.empty:
        return organizations
    frame = organizations.copy()
    frame["_sort_missing"] = frame["distance"].isna().astype(int)
    frame = frame.sort_values(
        by=["_sort_missing", "distance"],
        ascending=[True, True],
        kind="mergesort",
    )
    return frame.drop(columns=["_sort_missing"]).reset_index(drop=True)


def finalize_organization_records(organizations):
    """Keep API columns only and convert NaN → None for JSON."""
    columns = ORG_COLUMNS + DISTANCE_COLUMNS
    frame = organizations.reindex(
        columns=[c for c in columns if c in organizations.columns]
        + [c for c in columns if c not in organizations.columns]
    )
    for column in DISTANCE_COLUMNS:
        if column not in frame.columns:
            if column == "distance":
                frame[column] = None
            elif column == "distance_unit":
                frame[column] = "miles"
            elif column == "distance_method":
                frame[column] = "straight_line"
            else:
                frame[column] = "unknown_location"
    frame = frame.reindex(columns=columns)
    return frame.astype(object).where(pd.notna(frame), None)


def get_beneficiary_location(beneficiary_id):
    """Return beneficiary full location string and city for org search."""
    beneficiary_id_df = pd.read_sql(
        f"""
        SELECT *
        FROM {_db_name}.users
        WHERE user_id = %s
        """,
        _db_conn,
        params=(beneficiary_id,),
    )

    if beneficiary_id_df.empty:
        return None, None

    beneficiary_info = beneficiary_id_df.iloc[0]

    beneficiary_location_array = [
        beneficiary_info.get("addr_ln1"),
        beneficiary_info.get("addr_ln2"),
        beneficiary_info.get("addr_ln3"),
        beneficiary_info.get("city_name"),
        beneficiary_info.get("zip_code"),
    ]

    beneficiary_location = _join_parts(beneficiary_location_array)
    beneficiary_city = beneficiary_info.get("city_name")

    return beneficiary_location, beneficiary_city


def get_req_info(request_id, beneficiary_id):
    """Look up one request and return category, description, and subject."""
    try:
        cursor = _db_conn.cursor()

        cursor.execute(
            f"""
            SELECT *
            FROM {_db_name}.requests
            WHERE req_id = %s
              AND beneficiary_id = %s
            """,
            (request_id, beneficiary_id),
        )

        row = cursor.fetchone()

        if row is None:
            raise Exception(
                f"No request found with req_id={request_id} "
                f"and beneficiary_id={beneficiary_id}"
            )

        columns = [desc[0] for desc in cursor.description]
        request_info = dict(zip(columns, row))

        cat_id = request_info.get("req_cat_id")
        if cat_id is None:
            raise Exception(f"Request {request_id} has no category assigned")

        cursor.execute(
            f"""
            SELECT *
            FROM {_db_name}.help_categories
            WHERE cat_id = %s
            """,
            (cat_id,),
        )

        row = cursor.fetchone()

        if row is None:
            raise Exception(f"No category found with cat_id={cat_id}")

        columns = [desc[0] for desc in cursor.description]
        category = dict(zip(columns, row))

        return {
            "category": category.get("cat_name"),
            "description": request_info.get("req_desc"),
            "subject": request_info.get("req_subj"),
            "req_loc": request_info.get("req_loc"),
        }

    except psycopg2.DatabaseError as e:
        raise Exception(
            f"Database error while fetching request {request_id}: {e}"
        ) from e


def get_user_info(user_ids):
    """Return representative contact information for supplied user IDs."""
    user_info = []

    for user_id in user_ids:
        if user_id is None:
            continue

        user_id_df = pd.read_sql(
            f"""
            SELECT *
            FROM {_db_name}.users
            WHERE user_id = %s
            """,
            _db_conn,
            params=(user_id,),
        )

        if user_id_df.empty:
            continue

        row = user_id_df.iloc[0]

        person_name = _join_parts(
            [row.get("first_name"), row.get("last_name")],
            sep=" ",
        )

        location = _join_parts(
            [
                row.get("addr_ln1"),
                row.get("addr_ln2"),
                row.get("addr_ln3"),
                row.get("city_name"),
                row.get("zip_code"),
            ]
        )

        user_info.append(
            {
                "PersonName": person_name,
                "Phone": row.get("primary_phone_number"),
                "Email": row.get("primary_email_address"),
                "Location": location,
            }
        )

    return user_info


def get_representatives_for_orgs(df):
    """Attach representatives to non-collaborator organizations."""
    reps_per_org = []

    for _, row in df.iterrows():
        if row.get("is_collaborator"):
            reps_per_org.append(None)
            continue

        org_id = row.get("org_id")
        if org_id is None:
            reps_per_org.append(None)
            continue

        try:
            user_id_df = pd.read_sql(
                f"""
                SELECT uo.user_id
                FROM {_db_name}.organizations AS o
                LEFT JOIN {_db_name}.user_org_map AS uo
                    ON uo.org_id = o.org_id
                WHERE o.org_id = %s
                """,
                _db_conn,
                params=(org_id,),
            )

            user_ids = user_id_df["user_id"].dropna().tolist()
            reps_per_org.append(get_user_info(user_ids))

        except psycopg2.DatabaseError as e:
            logger.warning(
                "Failed to fetch reps for org %s: %s",
                org_id,
                e,
            )
            reps_per_org.append(None)

    df["Representatives"] = reps_per_org
    return df


def get_orgs_from_db(location, category):
    """Find DB organizations by category and, when available, city."""
    if not category:
        raise Exception(
            f"get_orgs_from_db requires category (got category={category!r})"
        )

    try:
        if location:
            city = (
                location.split(",")[0].strip()
                if "," in location
                else location.strip()
            )

            df = pd.read_sql(
                f"""
                SELECT DISTINCT o.*
                FROM {_db_name}.organizations AS o
                INNER JOIN {_db_name}.org_skills AS os
                    ON o.org_id = os.org_id
                INNER JOIN {_db_name}.help_categories AS hc
                    ON os.cat_id = hc.cat_id
                WHERE hc.cat_name = %s
                  AND o.city_name = %s
                """,
                _db_conn,
                params=(category, city),
            )
        else:
            df = pd.read_sql(
                f"""
                SELECT DISTINCT o.*
                FROM {_db_name}.organizations AS o
                INNER JOIN {_db_name}.org_skills AS os
                    ON o.org_id = os.org_id
                INNER JOIN {_db_name}.help_categories AS hc
                    ON os.cat_id = hc.cat_id
                WHERE hc.cat_name = %s
                """,
                _db_conn,
                params=(category,),
            )

        df["source"] = "db"

        if not df.empty:
            df["location"] = df.apply(
                lambda r: _join_parts(
                    [
                        r.get("street"),
                        r.get("city_name"),
                        r.get("state_id"),
                        r.get("zip_code"),
                    ]
                ),
                axis=1,
            )

        return get_representatives_for_orgs(df)

    except psycopg2.DatabaseError as e:
        raise Exception(
            f"Database error while fetching orgs "
            f"for {location}/{category}: {e}"
        ) from e


def get_ai_orgs(subject, description, location, category):
    """Ask the GenAI Lambda for additional organizations."""
    try:
        response = lambda_client.invoke(
            FunctionName=GEN_AI_LAMBDA,
            InvocationType="RequestResponse",
            Payload=json.dumps(
                {
                    "subject": subject,
                    "description": description,
                    "location": location,
                    "category": category,
                }
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

        if status_code == 502 and body.get("code") == "ORG_SEARCH_UNAVAILABLE":
            logger.warning(
                "GenAI organization search unavailable; continuing with DB results"
            )
            return _empty_ai_frame()

        if status_code != 200:
            raise Exception(f"GenAI Lambda returned error: {payload}")

        org_records = body.get("organizations", [])

        if not org_records:
            return _empty_ai_frame()

        orgs = pd.DataFrame(org_records)
        orgs["source"] = "ai"
        orgs["is_collaborator"] = False

        return orgs

    except boto3.exceptions.Boto3Error as e:
        raise Exception(f"Failed to invoke GenAI Lambda: {e}") from e

    except (KeyError, TypeError, json.JSONDecodeError) as e:
        raise Exception(
            f"Unexpected response structure from GenAI Lambda: {e}"
        ) from e


def merge_organizations(db_organizations, genAI_organizations):
    """Normalize DB and AI organizations; keep address fields for distance."""

    def _normalize(df, rename_map):
        if df is None or df.empty:
            return pd.DataFrame(columns=ORG_COLUMNS + ADDRESS_COLUMNS)

        normalized = df.rename(columns=rename_map).copy()
        keep = ORG_COLUMNS + [
            c for c in ADDRESS_COLUMNS if c in normalized.columns
        ]
        # Ensure required response columns exist.
        for column in ORG_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = None
        return normalized.reindex(
            columns=list(dict.fromkeys(keep)),
            fill_value=None,
        )

    try:
        db_orgs = _normalize(db_organizations, DB_RENAME)
        ai_orgs = _normalize(genAI_organizations, AI_RENAME)
        frames = [frame for frame in (db_orgs, ai_orgs) if not frame.empty]
        if not frames:
            return pd.DataFrame(columns=ORG_COLUMNS)
        return pd.concat(frames, ignore_index=True, sort=False)

    except Exception as e:
        raise Exception(f"Failed to merge organization results: {e}") from e
