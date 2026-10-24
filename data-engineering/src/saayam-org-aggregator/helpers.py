import boto3
import json
import logging

from aws_lambda_powertools.utilities import parameters
import pandas as pd
import psycopg2

from distance import (
    GEO_ADDRESS,
    GEO_CITY,
    GEO_STATE,
    LocationCandidate,
    is_blank,
)

logger = logging.getLogger(__name__)

GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"

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

# Internal geocoding inputs carried through the merge; distance.add_distances
# strips them before the response is returned.
GEO_COLUMNS = [GEO_ADDRESS, GEO_CITY, GEO_STATE]

# Address-like keys GenAI may return, most specific first.
AI_ADDRESS_KEYS = ("address", "full_address", "street_address", "location")

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
    return pd.DataFrame(columns=ORG_COLUMNS + GEO_COLUMNS)


def _rollback():
    """Clear an aborted transaction so later queries on the shared connection work."""
    try:
        _db_conn.rollback()
    except Exception:  # noqa: BLE001
        pass


def _query_one(sql, params):
    """Run a query and return the first row as a dict, or None. Never raises."""
    try:
        cursor = _db_conn.cursor()
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))
    except Exception as e:  # noqa: BLE001 - distance lookups must not break the API
        logger.warning("distance lookup query failed: %s", e)
        _rollback()
        return None


def _readable(value):
    """'UNITED_STATES' -> 'UNITED STATES'; blanks -> None."""
    return None if is_blank(value) else str(value).replace("_", " ").strip()


def get_beneficiary_location_candidates(request_id, beneficiary_id):
    """Ordered beneficiary/request location sources for distance (issue #433).

    1. requests.req_loc coordinates
    2. user_locations.curr_loc for the beneficiary
    3. beneficiary profile address (users + cities/states/countries), geocoded
    4. requests.req_loc as free text (e.g. 'Suffolk, VA'), geocoded

    Uses the beneficiary only - never the volunteer/admin viewing the request,
    and never a default location such as 'United States'.
    """
    candidates = []

    request_row = _query_one(
        f"""
        SELECT CAST(req_loc AS TEXT) AS req_loc
        FROM {_db_name}.requests
        WHERE req_id = %s
        """,
        (request_id,),
    )
    req_loc = request_row.get("req_loc") if request_row else None
    candidates.append(LocationCandidate("requests.req_loc", coordinates=req_loc))

    location_row = _query_one(
        f"""
        SELECT CAST(curr_loc AS TEXT) AS curr_loc
        FROM {_db_name}.user_locations
        WHERE user_id = %s
        """,
        (beneficiary_id,),
    )
    if location_row:
        candidates.append(
            LocationCandidate(
                "user_locations.curr_loc",
                coordinates=location_row.get("curr_loc"),
            )
        )

    profile = _query_one(
        f"""
        SELECT u.addr_ln1, u.addr_ln2, u.addr_ln3, u.city_name, u.zip_code,
               u.state_id, s.state_name, c.country_name
        FROM {_db_name}.users AS u
        LEFT JOIN {_db_name}.states AS s
            ON s.state_id = u.state_id
        LEFT JOIN {_db_name}.countries AS c
            ON c.country_id = u.country_id
        WHERE u.user_id = %s
        """,
        (beneficiary_id,),
    )
    if profile:
        address = _join_parts(
            [
                profile.get("addr_ln1"),
                profile.get("addr_ln2"),
                profile.get("addr_ln3"),
                profile.get("city_name"),
                _readable(profile.get("state_name")) or profile.get("state_id"),
                profile.get("zip_code"),
                _readable(profile.get("country_name")),
            ]
        )
        candidates.append(
            LocationCandidate(
                "users.profile_address",
                address=address,
                city=profile.get("city_name"),
                state=profile.get("state_id"),
            )
        )

    if not is_blank(req_loc):
        candidates.append(LocationCandidate("requests.req_loc_text", address=req_loc))

    return candidates


def load_city_coordinates():
    """Rows from cities (+ state code/name) for the city_table geocoder."""
    try:
        df = pd.read_sql(
            f"""
            SELECT ci.city_name, ci.state_id, ci.lattitude, ci.longitude,
                   s.state_code, s.state_name
            FROM {_db_name}.cities AS ci
            LEFT JOIN {_db_name}.states AS s
                ON s.state_id = ci.state_id
            """,
            _db_conn,
        )
        return df.to_dict(orient="records")
    except Exception as e:  # noqa: BLE001
        logger.warning("could not load cities for geocoding: %s", e)
        _rollback()
        return []


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
                       s.state_name AS geo_state_name,
                       c.country_name AS geo_country_name
                FROM {_db_name}.organizations AS o
                INNER JOIN {_db_name}.org_skills AS os
                    ON o.org_id = os.org_id
                INNER JOIN {_db_name}.help_categories AS hc
                    ON os.cat_id = hc.cat_id
                LEFT JOIN {_db_name}.states AS s
                    ON s.state_id = o.state_id
                LEFT JOIN {_db_name}.countries AS c
                    ON c.country_id = s.country_id
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
                       s.state_name AS geo_state_name,
                       c.country_name AS geo_country_name
                FROM {_db_name}.organizations AS o
                INNER JOIN {_db_name}.org_skills AS os
                    ON o.org_id = os.org_id
                INNER JOIN {_db_name}.help_categories AS hc
                    ON os.cat_id = hc.cat_id
                LEFT JOIN {_db_name}.states AS s
                    ON s.state_id = o.state_id
                LEFT JOIN {_db_name}.countries AS c
                    ON c.country_id = s.country_id
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

        add_db_geo_columns(df)

        return get_representatives_for_orgs(df)

    except psycopg2.DatabaseError as e:
        raise Exception(
            f"Database error while fetching orgs "
            f"for {location}/{category}: {e}"
        ) from e


def add_db_geo_columns(df):
    """Full address (real names, not IDs) used to geocode DB organizations."""
    if df.empty:
        for column in GEO_COLUMNS:
            df[column] = None
        return df

    df[GEO_ADDRESS] = df.apply(
        lambda r: _join_parts(
            [
                r.get("street"),
                r.get("city_name"),
                _readable(r.get("geo_state_name")) or r.get("state_id"),
                r.get("zip_code"),
                _readable(r.get("geo_country_name")),
            ]
        ),
        axis=1,
    )
    df[GEO_CITY] = df.get("city_name")
    df[GEO_STATE] = df.get("state_id")
    return df


def add_ai_geo_columns(df):
    """Use the real address/location GenAI returned; None when it has none."""
    def _address(row):
        for key in AI_ADDRESS_KEYS:
            value = row.get(key)
            if not is_blank(value):
                return str(value).strip()
        return None

    df[GEO_ADDRESS] = df.apply(_address, axis=1) if not df.empty else None
    df[GEO_CITY] = None
    df[GEO_STATE] = None
    return df


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

        return add_ai_geo_columns(orgs)

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
            return pd.DataFrame(columns=ORG_COLUMNS + GEO_COLUMNS)

        normalized = df.rename(columns=rename_map).copy()

        # GEO_COLUMNS are internal and removed again after distance calculation.
        return normalized.reindex(columns=ORG_COLUMNS + GEO_COLUMNS)

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
