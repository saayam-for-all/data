import boto3
import json
import logging

from aws_lambda_powertools.utilities import parameters
import pandas as pd
import psycopg2

from distance_utils import (
    ADDRESS_COLUMN,
    geocode_address,
    parse_point,
    STATUS_OK,
)

logger = logging.getLogger(__name__)

GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"

# Final response shape expected by the Request Details Organizations tab.
# (distance, distance_unit, distance_method and distance_status are added
# afterwards by distance_utils.add_distance.)
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

# Same columns plus the internal address used for geocoding. add_distance()
# removes ADDRESS_COLUMN, so it never appears in the API response.
_MERGE_COLUMNS = ORG_COLUMNS + [ADDRESS_COLUMN]

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
    return pd.DataFrame(columns=_MERGE_COLUMNS)


def get_beneficiary_location(beneficiary_id):
    """Return beneficiary full location and city."""
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


def _fetch_one(query, params):
    """Run a read query and return the first row, or None.

    Rolls back on a database error so one failed lookup cannot leave the
    shared connection in an aborted transaction for the next lookup.
    """
    cursor = _db_conn.cursor()
    try:
        cursor.execute(query, params)
        return cursor.fetchone()
    except psycopg2.DatabaseError as e:
        logger.warning("Location lookup failed: %s", e)
        _db_conn.rollback()
        return None
    finally:
        cursor.close()


def get_beneficiary_coordinates(request_id, beneficiary_id):
    """Return the beneficiary's (lat, lon), or None if it cannot be found.

    This is always the beneficiary / request location, never the location of
    whoever is viewing the request. Order of preference:
      1. requests.req_loc
      2. user_locations.curr_loc (for the beneficiary)
      3. the beneficiary's profile address (users + states + countries),
         geocoded
    No default location is ever substituted.
    """
    # 1. Request location (::text so geography columns come back as hex EWKB)
    row = _fetch_one(
        f"""
        SELECT req_loc::text
        FROM {_db_name}.requests
        WHERE req_id = %s AND beneficiary_id = %s
        """,
        (request_id, beneficiary_id),
    )
    point = parse_point(row[0]) if row else None
    if point:
        return point

    # 2. Beneficiary's current location
    row = _fetch_one(
        f"""
        SELECT curr_loc::text
        FROM {_db_name}.user_locations
        WHERE user_id = %s
        """,
        (beneficiary_id,),
    )
    point = parse_point(row[0]) if row else None
    if point:
        return point

    # 3. Profile address, geocoded
    row = _fetch_one(
        f"""
        SELECT u.addr_ln1, u.addr_ln2, u.addr_ln3, u.city_name,
               s.state_name, u.zip_code, c.country_name
        FROM {_db_name}.users AS u
        LEFT JOIN {_db_name}.states AS s ON u.state_id = s.state_id
        LEFT JOIN {_db_name}.countries AS c ON u.country_id = c.country_id
        WHERE u.user_id = %s
        """,
        (beneficiary_id,),
    )
    if row:
        address = _join_parts(list(row))
        lat, lon, status = geocode_address(address)
        if status == STATUS_OK:
            return lat, lon

    return None


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
    """Find DB organizations by category and, when available, city.

    Category matching uses org_skills -> help_categories rather than comparing
    the free-text organizations.mission field to a category label.

    Each row also carries its full street address (real state and country
    names, not internal IDs) in ADDRESS_COLUMN for distance calculation.
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
                SELECT DISTINCT o.*,
                       s.state_name AS addr_state_name,
                       c.country_name AS addr_country_name
                FROM {_db_name}.organizations AS o
                INNER JOIN {_db_name}.org_skills AS os
                    ON o.org_id = os.org_id
                INNER JOIN {_db_name}.help_categories AS hc
                    ON os.cat_id = hc.cat_id
                LEFT JOIN {_db_name}.states AS s
                    ON o.state_id = s.state_id
                LEFT JOIN {_db_name}.countries AS c
                    ON s.country_id = c.country_id
                WHERE hc.cat_name = %s
                  AND o.city_name = %s
                """,
                _db_conn,
                params=(category, city),
            )
        else:
            df = pd.read_sql(
                f"""
                SELECT DISTINCT o.*,
                       s.state_name AS addr_state_name,
                       c.country_name AS addr_country_name
                FROM {_db_name}.organizations AS o
                INNER JOIN {_db_name}.org_skills AS os
                    ON o.org_id = os.org_id
                INNER JOIN {_db_name}.help_categories AS hc
                    ON os.cat_id = hc.cat_id
                LEFT JOIN {_db_name}.states AS s
                    ON o.state_id = s.state_id
                LEFT JOIN {_db_name}.countries AS c
                    ON s.country_id = c.country_id
                WHERE hc.cat_name = %s
                """,
                _db_conn,
                params=(category,),
            )

        df["source"] = "db"

        df["location"] = df.apply(
            lambda r: _join_parts(
                [r.get("city_name"), r.get("state_id")]
            ),
            axis=1,
        )

        df[ADDRESS_COLUMN] = df.apply(
            lambda r: _join_parts(
                [
                    r.get("street"),
                    r.get("city_name"),
                    r.get("addr_state_name"),
                    r.get("zip_code"),
                    r.get("addr_country_name"),
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

        # The organization's own reported location is its address. If GenAI
        # did not return one, the distance for that organization is null.
        orgs[ADDRESS_COLUMN] = (
            orgs["location"] if "location" in orgs.columns else None
        )

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
            return pd.DataFrame(columns=_MERGE_COLUMNS)

        normalized = df.rename(columns=rename_map).copy()

        return normalized.reindex(columns=_MERGE_COLUMNS)

    try:
        db_orgs = _normalize(db_organizations, DB_RENAME)
        ai_orgs = _normalize(genAI_organizations, AI_RENAME)

        return pd.concat(
            [db_orgs, ai_orgs],
            ignore_index=True,
        )

    except Exception as e:
        raise Exception(
            f"Failed to merge organization results: {e}"
        ) from e