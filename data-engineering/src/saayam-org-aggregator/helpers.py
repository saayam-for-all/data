import json
import logging
import math
import re

import boto3
import pandas as pd
import psycopg2
from aws_lambda_powertools.utilities import parameters

logger = logging.getLogger(__name__)

GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"

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

DB_RENAME = {
    "org_name": "name",
    "org_type": "organization_type",
    "is_collaborator": "collaborator",
    "org_rating": "rating",
    "org_size": "size",
    "phone": "contact",
}

AI_RENAME = {
    "organization_name": "name",
    "org_type": "organization_type",
    "is_collaborator": "collaborator",
}


lambda_client = None
_db_conn = None
_db_name = None

_coordinate_cache = {}
_table_columns_cache = {}
_location_name_cache = {}


def _get_lambda_client():
    global lambda_client

    if lambda_client is None:
        lambda_client = boto3.client("lambda")

    return lambda_client


def _get_db():
    global _db_conn
    global _db_name

    if _db_conn is not None:
        return _db_conn, _db_name

    creds = json.loads(
        parameters.get_parameter(
            "/dev/saayam/db/Virginia/Analytics/user",
            decrypt=True,
            max_age=3600,
        )
    )

    _db_name = creds["DATABASE NAME"]

    _db_conn = psycopg2.connect(
        host=creds["HOST"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        database=_db_name,
        port=creds["PORT"],
        sslmode="require",
    )

    return _db_conn, _db_name


def _join_parts(parts, sep=", "):
    cleaned = []

    for value in parts:
        if value is None:
            continue

        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass

        value = str(value).strip()

        if value:
            cleaned.append(value)

    return sep.join(cleaned) if cleaned else None


def _empty_ai_frame():
    return pd.DataFrame(columns=ORG_COLUMNS + ["_distance_address"])


def _get_table_columns(table_name):
    if table_name in _table_columns_cache:
        return _table_columns_cache[table_name]

    conn, db_name = _get_db()

    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            """,
            (db_name, table_name),
        )

        columns = {row[0] for row in cursor.fetchall()}
        _table_columns_cache[table_name] = columns

        return columns

    finally:
        cursor.close()


def _first_existing_column(table_name, candidates):
    columns = _get_table_columns(table_name)

    for candidate in candidates:
        if candidate in columns:
            return candidate

    return None


def _lookup_location_name(
    table_name,
    record_id,
    id_candidates,
    name_candidates,
):
    if record_id is None:
        return None

    cache_key = (table_name, record_id)

    if cache_key in _location_name_cache:
        return _location_name_cache[cache_key]

    id_column = _first_existing_column(
        table_name,
        id_candidates,
    )

    name_column = _first_existing_column(
        table_name,
        name_candidates,
    )

    if not id_column or not name_column:
        return None

    conn, db_name = _get_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            f"""
            SELECT {name_column}
            FROM {db_name}.{table_name}
            WHERE {id_column} = %s
            LIMIT 1
            """,
            (record_id,),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        value = row[0]
        _location_name_cache[cache_key] = value

        return value

    finally:
        cursor.close()


def parse_coordinates(value):
    if value is None:
        return None

    if isinstance(value, dict):
        latitude = value.get(
            "latitude",
            value.get("lat"),
        )

        longitude = value.get(
            "longitude",
            value.get(
                "lng",
                value.get("lon"),
            ),
        )

        if latitude is not None and longitude is not None:
            try:
                return float(latitude), float(longitude)
            except (TypeError, ValueError):
                return None

    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            latitude = float(value[0])
            longitude = float(value[1])

            if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                return latitude, longitude

        except (TypeError, ValueError):
            return None

    text = str(value).strip()

    latitude_match = re.search(
        r"(?:latitude|lat)\s*[:=]\s*(-?\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )

    longitude_match = re.search(
        r"(?:longitude|lng|lon)\s*[:=]\s*(-?\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )

    if latitude_match and longitude_match:
        return (
            float(latitude_match.group(1)),
            float(longitude_match.group(1)),
        )

    simple_match = re.match(
        r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$",
        text,
    )

    if simple_match:
        latitude = float(simple_match.group(1))
        longitude = float(simple_match.group(2))

        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return latitude, longitude

    return None


def calculate_distance_miles(
    latitude1,
    longitude1,
    latitude2,
    longitude2,
):
    earth_radius_miles = 3958.7613

    lat1 = math.radians(latitude1)
    lon1 = math.radians(longitude1)
    lat2 = math.radians(latitude2)
    lon2 = math.radians(longitude2)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return earth_radius_miles * c


def geocode_address(address, geocoder=None):
    """
    Convert an address into (latitude, longitude).

    No provider is hard-coded because the approved provider has not
    been selected yet.

    During local tests, pass a mock geocoder callable.
    """

    if not address:
        return None, "unknown_location"

    direct_coordinates = parse_coordinates(address)

    if direct_coordinates:
        return direct_coordinates, "ok"

    normalized_address = " ".join(str(address).strip().lower().split())

    if normalized_address in _coordinate_cache:
        return _coordinate_cache[normalized_address], "ok"

    if geocoder is None:
        return None, "deferred"

    try:
        result = geocoder(address)

        if result is None:
            return None, "not_found"

        coordinates = parse_coordinates(result)

        if coordinates is None:
            return None, "not_found"

        _coordinate_cache[normalized_address] = coordinates

        return coordinates, "ok"

    except Exception as exc:
        logger.warning(
            "Geocoding failed for address %s: %s",
            address,
            exc,
        )

        return None, "error"


def _get_user_row(beneficiary_id):
    conn, db_name = _get_db()

    df = pd.read_sql(
        f"""
        SELECT *
        FROM {db_name}.users
        WHERE user_id = %s
        """,
        conn,
        params=(beneficiary_id,),
    )

    if df.empty:
        return None

    return df.iloc[0]


def _resolve_user_city(user):
    city = user.get("city_name") or user.get("city")

    if city:
        return city

    city_id = user.get("city_id")

    return _lookup_location_name(
        "cities",
        city_id,
        ["city_id", "id"],
        ["city_name", "name"],
    )


def _resolve_user_state(user):
    state = user.get("state_name") or user.get("state")

    if state:
        return state

    state_id = user.get("state_id")

    return _lookup_location_name(
        "states",
        state_id,
        ["state_id", "id"],
        ["state_name", "name"],
    )


def _resolve_user_country(user):
    country = user.get("country_name") or user.get("country")

    if country:
        return country

    country_id = user.get("country_id")

    return _lookup_location_name(
        "countries",
        country_id,
        ["country_id", "id"],
        ["country_name", "name"],
    )


def get_beneficiary_location(beneficiary_id):
    """
    Return beneficiary profile address and beneficiary city.

    This remains useful for DB organization search and GenAI input.
    """

    user = _get_user_row(beneficiary_id)

    if user is None:
        return None, None

    city = _resolve_user_city(user)
    state = _resolve_user_state(user)
    country = _resolve_user_country(user)

    address = _join_parts(
        [
            user.get("addr_ln1"),
            user.get("addr_ln2"),
            user.get("addr_ln3"),
            city,
            state,
            user.get("zip_code"),
            country,
        ]
    )

    return address, city


def get_user_location_coordinates(
    beneficiary_id,
    geocoder=None,
):
    """
    Check user_locations.curr_loc using beneficiary_id/user_id.
    """

    conn, db_name = _get_db()

    identifier_column = _first_existing_column(
        "user_locations",
        ["beneficiary_id", "user_id"],
    )

    if not identifier_column:
        return None, "unknown_location"

    if "curr_loc" not in _get_table_columns("user_locations"):
        return None, "unknown_location"

    df = pd.read_sql(
        f"""
        SELECT curr_loc
        FROM {db_name}.user_locations
        WHERE {identifier_column} = %s
        LIMIT 1
        """,
        conn,
        params=(beneficiary_id,),
    )

    if df.empty:
        return None, "unknown_location"

    current_location = df.iloc[0].get("curr_loc")

    if not current_location:
        return None, "unknown_location"

    coordinates = parse_coordinates(current_location)

    if coordinates:
        return coordinates, "ok"

    return geocode_address(
        current_location,
        geocoder=geocoder,
    )


def get_beneficiary_coordinates(
    request_location,
    beneficiary_id,
    geocoder=None,
):
    """
    Required fallback order:

    1. requests.req_loc
    2. user_locations.curr_loc
    3. beneficiary profile address
    """

    if request_location:
        coordinates = parse_coordinates(request_location)

        if coordinates:
            return coordinates, "ok"

        coordinates, status = geocode_address(
            request_location,
            geocoder=geocoder,
        )

        if coordinates:
            return coordinates, "ok"

    user_coordinates, user_status = get_user_location_coordinates(
        beneficiary_id,
        geocoder=geocoder,
    )

    if user_coordinates:
        return user_coordinates, "ok"

    profile_address, _ = get_beneficiary_location(beneficiary_id)

    if not profile_address:
        return None, "unknown_location"

    coordinates, profile_status = geocode_address(
        profile_address,
        geocoder=geocoder,
    )

    if coordinates:
        return coordinates, "ok"

    if profile_status in {
        "not_found",
        "deferred",
        "error",
    }:
        return None, profile_status

    if user_status in {
        "not_found",
        "deferred",
        "error",
    }:
        return None, user_status

    return None, "unknown_location"


def get_req_info(request_id, beneficiary_id):
    try:
        conn, db_name = _get_db()
        cursor = conn.cursor()

        cursor.execute(
            f"""
            SELECT *
            FROM {db_name}.requests
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

        columns = [description[0] for description in cursor.description]

        request_info = dict(zip(columns, row))

        category_id = request_info.get("req_cat_id")

        if category_id is None:
            raise Exception(f"Request {request_id} has no category assigned")

        cursor.execute(
            f"""
            SELECT *
            FROM {db_name}.help_categories
            WHERE cat_id = %s
            """,
            (category_id,),
        )

        category_row = cursor.fetchone()

        if category_row is None:
            raise Exception(f"No category found with cat_id={category_id}")

        columns = [description[0] for description in cursor.description]

        category = dict(zip(columns, category_row))

        return {
            "category": category.get("cat_name"),
            "description": request_info.get("req_desc"),
            "subject": request_info.get("req_subj"),
            "req_loc": request_info.get("req_loc"),
        }

    except psycopg2.DatabaseError as exc:
        raise Exception(
            f"Database error while fetching request {request_id}: {exc}"
        ) from exc

    finally:
        try:
            cursor.close()
        except Exception:
            pass


def get_user_info(user_ids):
    conn, db_name = _get_db()

    user_info = []

    for user_id in user_ids:
        if user_id is None:
            continue

        df = pd.read_sql(
            f"""
            SELECT *
            FROM {db_name}.users
            WHERE user_id = %s
            """,
            conn,
            params=(user_id,),
        )

        if df.empty:
            continue

        row = df.iloc[0]

        person_name = _join_parts(
            [
                row.get("first_name"),
                row.get("last_name"),
            ],
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
    conn, db_name = _get_db()

    representatives = []

    for _, row in df.iterrows():
        if row.get("is_collaborator"):
            representatives.append(None)
            continue

        org_id = row.get("org_id")

        if org_id is None:
            representatives.append(None)
            continue

        try:
            user_id_df = pd.read_sql(
                f"""
                SELECT uo.user_id
                FROM {db_name}.organizations AS o
                LEFT JOIN {db_name}.user_org_map AS uo
                    ON uo.org_id = o.org_id
                WHERE o.org_id = %s
                """,
                conn,
                params=(org_id,),
            )

            user_ids = user_id_df["user_id"].dropna().tolist()

            representatives.append(get_user_info(user_ids))

        except psycopg2.DatabaseError as exc:
            logger.warning(
                "Failed to fetch representatives for org %s: %s",
                org_id,
                exc,
            )

            representatives.append(None)

    df["Representatives"] = representatives

    return df


def _resolve_org_city(row):
    city = row.get("city_name") or row.get("city")

    if city:
        return city

    return _lookup_location_name(
        "cities",
        row.get("city_id"),
        ["city_id", "id"],
        ["city_name", "name"],
    )


def _resolve_org_state(row):
    state = row.get("state_name") or row.get("state")

    if state:
        return state

    return _lookup_location_name(
        "states",
        row.get("state_id"),
        ["state_id", "id"],
        ["state_name", "name"],
    )


def _resolve_org_country(row):
    country = row.get("country_name") or row.get("country")

    if country:
        return country

    return _lookup_location_name(
        "countries",
        row.get("country_id"),
        ["country_id", "id"],
        ["country_name", "name"],
    )


def _build_database_org_address(row):
    city = _resolve_org_city(row)
    state = _resolve_org_state(row)
    country = _resolve_org_country(row)

    street = row.get("street") or row.get("addr_ln1") or row.get("address")

    return _join_parts(
        [
            street,
            row.get("addr_ln2"),
            row.get("addr_ln3"),
            city,
            state,
            row.get("zip_code"),
            country,
        ]
    )


def _build_database_org_location(row):
    city = _resolve_org_city(row)
    state = _resolve_org_state(row)
    country = _resolve_org_country(row)

    return _join_parts(
        [
            city,
            state,
            row.get("zip_code"),
            country,
        ]
    )


def get_orgs_from_db(location, category):
    if not category:
        raise Exception("get_orgs_from_db requires category")

    conn, db_name = _get_db()

    try:
        if location:
            city = location.split(",")[0].strip()

            df = pd.read_sql(
                f"""
                SELECT DISTINCT o.*
                FROM {db_name}.organizations AS o
                INNER JOIN {db_name}.org_skills AS os
                    ON o.org_id = os.org_id
                INNER JOIN {db_name}.help_categories AS hc
                    ON os.cat_id = hc.cat_id
                WHERE hc.cat_name = %s
                  AND o.city_name = %s
                """,
                conn,
                params=(category, city),
            )

        else:
            df = pd.read_sql(
                f"""
                SELECT DISTINCT o.*
                FROM {db_name}.organizations AS o
                INNER JOIN {db_name}.org_skills AS os
                    ON o.org_id = os.org_id
                INNER JOIN {db_name}.help_categories AS hc
                    ON os.cat_id = hc.cat_id
                WHERE hc.cat_name = %s
                """,
                conn,
                params=(category,),
            )

        df["source"] = "db"

        if not df.empty:
            df["_distance_address"] = df.apply(
                _build_database_org_address,
                axis=1,
            )

            df["location"] = df.apply(
                _build_database_org_location,
                axis=1,
            )

        return get_representatives_for_orgs(df)

    except psycopg2.DatabaseError as exc:
        raise Exception(
            f"Database error while fetching organizations "
            f"for {location}/{category}: {exc}"
        ) from exc


def get_ai_orgs(
    subject,
    description,
    location,
    category,
):
    try:
        client = _get_lambda_client()

        response = client.invoke(
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

        if status_code != 200:
            logger.warning(
                "GenAI organization search failed: %s",
                payload,
            )

            return _empty_ai_frame()

        organization_records = body.get(
            "organizations",
            [],
        )

        if not organization_records:
            return _empty_ai_frame()

        organizations = pd.DataFrame(organization_records)

        organizations["source"] = "ai"
        organizations["is_collaborator"] = False

        organizations["_distance_address"] = organizations.apply(
            lambda row: (
                row.get("address")
                or row.get("location")
                or row.get("organization_location")
            ),
            axis=1,
        )

        return organizations

    except Exception as exc:
        logger.warning(
            "GenAI organization search unavailable: %s",
            exc,
        )

        return _empty_ai_frame()


def merge_organizations(
    db_organizations,
    genai_organizations,
):
    internal_columns = ORG_COLUMNS + ["_distance_address"]

    def normalize(df, rename_map):
        if df is None or df.empty:
            return pd.DataFrame(columns=internal_columns)

        normalized = df.rename(columns=rename_map).copy()

        if "_distance_address" not in normalized:
            normalized["_distance_address"] = normalized.get("location")

        return normalized.reindex(columns=internal_columns)

    db_orgs = normalize(
        db_organizations,
        DB_RENAME,
    )

    ai_orgs = normalize(
        genai_organizations,
        AI_RENAME,
    )

    return pd.concat(
        [
            db_orgs,
            ai_orgs,
        ],
        ignore_index=True,
    )


def add_distance_information(
    organizations,
    beneficiary_coordinates,
    beneficiary_status="unknown_location",
    geocoder=None,
):
    result = organizations.copy()

    distances = []
    statuses = []

    for _, organization in result.iterrows():
        distance = None
        status = "unknown_location"

        address = organization.get("_distance_address")

        if address is not None and not pd.isna(address):
            location_text = str(address).strip().lower()
        else:
            location_text = ""

        if location_text in {
            "online",
            "online only",
            "online-only",
            "virtual",
            "remote",
        }:
            status = "online"

        elif beneficiary_coordinates is None:
            if beneficiary_status in {
                "unknown_location",
                "not_found",
                "deferred",
                "error",
            }:
                status = beneficiary_status
            else:
                status = "unknown_location"

        elif not location_text:
            status = "unknown_location"

        else:
            (
                organization_coordinates,
                organization_status,
            ) = geocode_address(
                address,
                geocoder=geocoder,
            )

            if organization_coordinates:
                try:
                    beneficiary_latitude = beneficiary_coordinates[0]

                    beneficiary_longitude = beneficiary_coordinates[1]

                    organization_latitude = organization_coordinates[0]

                    organization_longitude = organization_coordinates[1]

                    distance = calculate_distance_miles(
                        beneficiary_latitude,
                        beneficiary_longitude,
                        organization_latitude,
                        organization_longitude,
                    )

                    distance = round(distance, 1)
                    status = "ok"

                except Exception as exc:
                    logger.warning(
                        "Distance calculation failed: %s",
                        exc,
                    )

                    distance = None
                    status = "error"

            else:
                status = organization_status

        distances.append(distance)
        statuses.append(status)

    result["distance"] = distances
    result["distance_unit"] = "miles"
    result["distance_method"] = "straight_line"
    result["distance_status"] = statuses

    if "_distance_address" in result.columns:
        result = result.drop(columns=["_distance_address"])

    return result


def sort_organizations_by_distance(
    organizations,
):
    if (
        organizations is None
        or organizations.empty
        or "distance" not in organizations.columns
    ):
        return organizations

    return organizations.sort_values(
        by="distance",
        ascending=True,
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)
