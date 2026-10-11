import boto3
import json
import logging
import math

from aws_lambda_powertools.utilities import parameters
import pandas as pd
import psycopg2

import geo

logger = logging.getLogger(__name__)

GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"

DISTANCE_COLUMNS = [
    "distance",
    "distance_unit",
    "distance_method",
    "distance_status",
]

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
] + DISTANCE_COLUMNS

# Maps raw DB column names -> final response shape.
DB_RENAME = {
    "org_name": "name",
    "org_type": "organization_type",
    "is_collaborator": "collaborator",
    "org_rating": "rating",
    "org_size": "size",
    "web_url": "web_url",
    "phone": "contact",
}

# Maps raw GenAI payload column names -> final response shape.
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

# Coordinate cache shared by every warm invocation of this container, backed
# by the geocode_cache table when it exists (see migrations/).
_geocode_cache = geo.GeocodeCache(conn=_db_conn, schema=_db_name)

# id -> display name lookups for cities / states / countries.
_name_cache = {}
# -------------------------------------------------------------


def _is_blank(value):
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and not value.strip()


def _join_parts(parts, sep=", "):
    """Join values with `sep`, skipping None, NaN, and empty strings."""
    cleaned = [str(p).strip() for p in parts if not _is_blank(p)]
    return sep.join(cleaned) if cleaned else None


def _first(row, columns):
    """First non-blank value among `columns` in a row/dict."""
    for col in columns:
        value = row.get(col)
        if not _is_blank(value):
            return value
    return None


def _empty_ai_frame():
    """Return an empty AI DataFrame with the final response columns."""
    return pd.DataFrame(columns=ORG_COLUMNS)


def new_geocoder():
    """One Geocoder per invocation (own call budget, shared cache)."""
    return geo.Geocoder(provider=geo.get_provider(), cache=_geocode_cache)


# ---------------------------------------------------------------------------
# Name lookups (cities / states / countries) so addresses never contain IDs
# ---------------------------------------------------------------------------

_LOOKUPS = {
    "city": ("cities", "city_id", ("city_name", "name")),
    "state": ("states", "state_id", ("state_name", "name", "state_code")),
    "country": ("countries", "country_id", ("country_name", "name")),
}


def _lookup_name(kind, id_value):
    """Resolve a city/state/country id to its name; None if unavailable.

    If the lookup fails and the stored value is clearly not a numeric id
    (e.g. 'CA'), that value is used as-is.
    """
    if _is_blank(id_value):
        return None

    table, id_col, name_cols = _LOOKUPS[kind]
    key = (kind, str(id_value))
    if key in _name_cache:
        return _name_cache[key]

    name = None
    try:
        cursor = _db_conn.cursor()
        cursor.execute(
            f"SELECT * FROM {_db_name}.{table} WHERE {id_col} = %s",
            (id_value,),
        )
        row = cursor.fetchone()
        if row is not None:
            columns = [desc[0] for desc in cursor.description]
            name = _first(dict(zip(columns, row)), name_cols)
    except psycopg2.Error as e:
        _db_conn.rollback()
        logger.warning("%s lookup failed for %s: %s", table, id_value, e)

    if name is None and not str(id_value).strip().isdigit():
        name = str(id_value).strip()

    _name_cache[key] = name
    return name


def _place_names(row):
    """Return (city, state, country) names for a users/organizations row."""
    city = _first(row, ["city_name"]) or _lookup_name("city", row.get("city_id"))
    state = _first(row, ["state_name"]) or _lookup_name(
        "state", row.get("state_id")
    )
    country = _first(row, ["country_name"]) or _lookup_name(
        "country", row.get("country_id")
    )
    return city, state, country


# ---------------------------------------------------------------------------
# Beneficiary location
# ---------------------------------------------------------------------------

def get_beneficiary_location(beneficiary_id):
    """Return beneficiary full location and city (used for org search)."""
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


def _get_user_location_coordinates(beneficiary_id):
    """Most recent parseable user_locations.curr_loc for the beneficiary."""
    try:
        df = pd.read_sql(
            f"""
            SELECT *
            FROM {_db_name}.user_locations
            WHERE user_id = %s
            """,
            _db_conn,
            params=(beneficiary_id,),
        )
    except Exception as e:
        _db_conn.rollback()
        logger.warning("user_locations lookup failed: %s", e)
        return None

    if df.empty or "curr_loc" not in df.columns:
        return None

    for ts_col in ("last_update_date", "last_updated", "updated_at",
                   "created_at", "creation_date"):
        if ts_col in df.columns:
            df = df.sort_values(ts_col, ascending=False, na_position="last")
            break

    for value in df["curr_loc"]:
        coords = geo.parse_coordinates(value)
        if coords:
            return coords
    return None


def build_beneficiary_profile_address(beneficiary_id):
    """users + cities + states + countries -> full address string."""
    try:
        df = pd.read_sql(
            f"SELECT * FROM {_db_name}.users WHERE user_id = %s",
            _db_conn,
            params=(beneficiary_id,),
        )
    except Exception as e:
        _db_conn.rollback()
        logger.warning("users lookup failed: %s", e)
        return None

    if df.empty:
        return None

    row = df.iloc[0]
    city, state, country = _place_names(row)
    if _is_blank(city) and _is_blank(row.get("zip_code")):
        return None  # street/state alone is not a usable location

    return _join_parts(
        [
            row.get("addr_ln1"),
            row.get("addr_ln2"),
            row.get("addr_ln3"),
            city,
            _join_parts([state, row.get("zip_code")], sep=" "),
            country,
        ]
    )


def get_beneficiary_coordinates(beneficiary_id, req_loc, geocoder):
    """Resolve where the beneficiary/request is.

    Order: requests.req_loc -> user_locations.curr_loc -> geocoded profile
    address. Never uses the viewer's location and never falls back to a
    default such as 'United States'.

    Returns (coords_or_None, status, source).
    """
    coords = geo.parse_coordinates(req_loc)
    if coords:
        return coords, geo.STATUS_OK, "request"

    coords = _get_user_location_coordinates(beneficiary_id)
    if coords:
        return coords, geo.STATUS_OK, "user_locations"

    address = build_beneficiary_profile_address(beneficiary_id)
    if not address:
        return None, geo.STATUS_UNKNOWN_LOCATION, None

    result = geocoder.geocode(address)
    if result.coordinates:
        return result.coordinates, geo.STATUS_OK, "profile_address"

    # not_found from the profile address means we don't know where they are.
    status = (
        geo.STATUS_UNKNOWN_LOCATION
        if result.status == geo.STATUS_NOT_FOUND
        else result.status
    )
    return None, status, "profile_address"


# ---------------------------------------------------------------------------
# Organization addresses
# ---------------------------------------------------------------------------

_LAT_COLS = ["latitude", "lat", "org_lat", "org_latitude"]
_LON_COLS = ["longitude", "lng", "lon", "org_lng", "org_long", "org_longitude"]
_ONLINE_FLAG_COLS = ["is_online", "online_only", "is_online_only", "is_virtual"]


def _row_coordinates(row):
    lat, lon = _first(row, _LAT_COLS), _first(row, _LON_COLS)
    if lat is not None and lon is not None:
        coords = geo.valid_coordinates(lat, lon)
        if coords:
            return coords
    return geo.parse_coordinates(
        _first(row, ["coordinates", "geo_location", "org_loc", "location_coords"])
    )


def _is_online_org(row):
    for col in _ONLINE_FLAG_COLS:
        value = row.get(col)
        if value is True or str(value).strip().lower() in ("true", "1", "yes"):
            return True
    return False


def build_db_org_address(row):
    """Full street/city/state/zip/country address for a DB organization."""
    city, state, country = _place_names(row)
    zip_code = _first(row, ["zip_code", "zip", "postal_code"])
    if _is_blank(city) and _is_blank(zip_code):
        return None
    return _join_parts(
        [
            _first(row, ["street", "street_address", "address", "addr_ln1"]),
            row.get("addr_ln2"),
            row.get("addr_ln3"),
            city,
            _join_parts([state, zip_code], sep=" "),
            country,
        ]
    )


def build_ai_org_address(row):
    """Best address GenAI returned for an organization (None if none)."""
    city = _first(row, ["city", "city_name"])
    zip_code = _first(row, ["zip_code", "zip", "postal_code"])
    street = _first(row, ["street", "street_address", "address_line1"])
    structured = None
    if not _is_blank(city) or not _is_blank(zip_code):
        structured = _join_parts(
            [
                street,
                city,
                _join_parts([_first(row, ["state", "state_name"]), zip_code],
                            sep=" "),
                _first(row, ["country", "country_name"]),
            ]
        )
    return _first(row, ["address", "full_address", "headquarters"]) \
        or structured or row.get("location")


def attach_distances(df, beneficiary_coords, beneficiary_status, geocoder,
                     address_builder):
    """Add distance fields to every row of an organization DataFrame.

    Never raises: any failure marks the affected rows `error` and the
    organization is still returned.
    """
    if df is None or df.empty:
        if df is not None:
            for col in DISTANCE_COLUMNS:
                df[col] = pd.Series(dtype=object)
        return df

    results = []
    try:
        rows = [row for _, row in df.iterrows()]
        addresses = []
        for row in rows:
            try:
                addresses.append(address_builder(row))
            except Exception as e:
                logger.warning("Address build failed: %s", e)
                addresses.append(None)

        if beneficiary_coords:
            geocoder.prefetch(a for a in addresses if a)

        for row, address in zip(rows, addresses):
            results.append(
                _distance_for_org(
                    row, address, beneficiary_coords, beneficiary_status,
                    geocoder,
                )
            )
    except Exception as e:
        logger.exception("Distance calculation failed: %s", e)
        results = [geo.distance_fields(status=geo.STATUS_ERROR)] * len(df)

    df = df.copy()
    for col in DISTANCE_COLUMNS:
        df[col] = pd.Series([r[col] for r in results], index=df.index,
                            dtype=object)
    return df


def _distance_for_org(row, address, beneficiary_coords, beneficiary_status,
                      geocoder):
    try:
        if _is_online_org(row) or (
            address and geo.is_online_location(address)
        ):
            return geo.distance_fields(status=geo.STATUS_ONLINE)

        if not beneficiary_coords:
            return geo.distance_fields(status=beneficiary_status)

        org_coords = _row_coordinates(row)
        if not org_coords:
            if not address or geo.is_too_vague(address):
                return geo.distance_fields(status=geo.STATUS_UNKNOWN_LOCATION)
            result = geocoder.geocode(address)
            if not result.coordinates:
                return geo.distance_fields(status=result.status)
            org_coords = result.coordinates

        return geo.distance_fields(
            geo.calculate_distance(beneficiary_coords, org_coords),
            geo.STATUS_OK,
        )
    except Exception as e:
        logger.warning("Distance failed for %r: %s", row.get("org_name")
                       or row.get("organization_name"), e)
        return geo.distance_fields(status=geo.STATUS_ERROR)


def _distance_sort_key(org):
    d = org.get("distance")
    unknown = d is None or (isinstance(d, float) and math.isnan(d))
    return (unknown, 0 if unknown else d)


def sort_by_distance(organizations):
    """Nearest first, unknown (null) distances last. Stable."""
    return sorted(organizations, key=_distance_sort_key)


def to_json_safe(records):
    """Replace NaN/NaT with None and numpy scalars with Python values."""
    def clean(value):
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if hasattr(value, "item") and not isinstance(value, (str, bytes)):
            try:
                value = value.item()
            except (ValueError, AttributeError):
                pass
        if _is_blank(value) and not isinstance(value, str):
            return None
        return value

    return [clean(r) for r in records]


# ---------------------------------------------------------------------------
# Existing request / organization lookups
# ---------------------------------------------------------------------------

def get_req_info(request_id, beneficiary_id):
    """Look up one request: category, description, subject and req_loc."""
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
        _db_conn.rollback()
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
            _db_conn.rollback()
            logger.warning(
                "Failed to fetch reps for org %s: %s",
                org_id,
                e,
            )
            reps_per_org.append(None)

    df["Representatives"] = reps_per_org
    return df


def get_orgs_from_db(location, category):
    """Find DB organizations by category and, when available, city.

    Category matching uses org_skills -> help_categories rather than comparing
    the free-text organizations.mission field to a category label.
    """
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

        # Display location uses the state name, not the internal state_id.
        df["location"] = df.apply(
            lambda r: _join_parts(
                [
                    r.get("city_name"),
                    _first(r, ["state_name"])
                    or _lookup_name("state", r.get("state_id")),
                ]
            ),
            axis=1,
        )

        return get_representatives_for_orgs(df)

    except psycopg2.DatabaseError as e:
        _db_conn.rollback()
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

        # Graceful degradation: keep DB results if GenAI is unavailable.
        if status_code == 502 and body.get("code") == "ORG_SEARCH_UNAVAILABLE":
            logger.warning(
                "GenAI organization search unavailable; continuing with DB results"
            )
            return _empty_ai_frame()

        if status_code != 200:
            raise Exception(f"GenAI Lambda returned error: {payload}")

        org_records = body.get("organizations", [])

        # Empty AI results are valid and should not fail the merge.
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
    """Normalize DB and AI organizations and combine them safely."""

    def _normalize(df, rename_map):
        if df is None or df.empty:
            return pd.DataFrame(columns=ORG_COLUMNS)

        normalized = df.rename(columns=rename_map).copy()

        return normalized.reindex(columns=ORG_COLUMNS)

    try:
        db_orgs = _normalize(db_organizations, DB_RENAME)
        ai_orgs = _normalize(genAI_organizations, AI_RENAME)

        frames = [f for f in (db_orgs, ai_orgs) if not f.empty]
        if not frames:
            return pd.DataFrame(columns=ORG_COLUMNS)

        return pd.concat(frames, ignore_index=True)

    except Exception as e:
        raise Exception(
            f"Failed to merge organization results: {e}"
        ) from e
