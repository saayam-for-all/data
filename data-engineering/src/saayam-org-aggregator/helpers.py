import boto3
import json
import logging
from aws_lambda_powertools.utilities import parameters
import pandas as pd
import pg8000
from distance import add_distances, build_address, geocode_address, parse_coordinates


GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"
logger = logging.getLogger(__name__)
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
ADDRESS_COLUMNS = [
    "street",
    "addr_ln1",
    "addr_ln2",
    "addr_ln3",
    "city",
    "city_name",
    "state",
    "state_name",
    "state_code",
    "zip_code",
    "postal_code",
    "country",
    "country_name",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "lng",
    "address",
    "full_address",
    "online_only",
    "is_online",
]

# --- All cached at module level, initialized once on cold start ---
lambda_client = boto3.client('lambda')

_creds = json.loads(parameters.get_parameter(
    '/dev/saayam/db/Virginia/Analytics/user',
    decrypt=True,
    max_age=3600
))
_db_name = _creds['DATABASE NAME']
_db_conn = pg8000.connect(
    host=_creds['HOST'],
    user=_creds['USERNAME'],
    password=_creds['PASSWORD'],
    database=_db_name,
    port=_creds['PORT'],
    ssl_context=True
)
# -----------------------------------------------------------------


def _table_columns(table_name):
    """Return column names for a table in the configured Virginia schema."""
    try:
        rows = pd.read_sql(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            _db_conn,
            params=(_db_name, table_name),
        )
        return set(rows.get("column_name", []))
    except Exception:
        logger.exception("Could not inspect columns for %s", table_name)
        return set()


def _location_expression(table_name, column_name, alias):
    """Select PostGIS points as WKT so coordinate order stays explicit."""
    try:
        rows = pd.read_sql(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
            _db_conn,
            params=(_db_name, table_name, column_name),
        )
        if not rows.empty and rows.iloc[0]["udt_name"] in {"geometry", "geography"}:
            return f"ST_AsText({alias}.{column_name}::geometry) AS {column_name}"
    except Exception:
        logger.exception("Could not inspect %s.%s type", table_name, column_name)
    return f"{alias}.{column_name} AS {column_name}"


def _first_row(query, params=()):
    """Run a parameterized query and return its first row as a dictionary."""
    rows = pd.read_sql(query, _db_conn, params=params)
    return None if rows.empty else rows.iloc[0].to_dict()


def _lookup_location_name(table_name, id_column, name_column, value):
    """Resolve a location ID through the corresponding plural lookup table."""
    if value is None:
        return None
    columns = _table_columns(table_name)
    if not {id_column, name_column}.issubset(columns):
        return None
    row = _first_row(
        f"SELECT {name_column} FROM {_db_name}.{table_name} "
        f"WHERE {id_column} = %s",
        (value,),
    )
    return row.get(name_column) if row else None


def _lookup_location_field(table_name, id_column, field_name, value):
    """Read a related location field when that column exists in the schema."""
    if value is None or field_name not in _table_columns(table_name):
        return None
    row = _first_row(
        f"SELECT {field_name} FROM {_db_name}.{table_name} "
        f"WHERE {id_column} = %s",
        (value,),
    )
    return row.get(field_name) if row else None


def get_request_context(request_id, beneficiary_id=None):
    """Load the request and its beneficiary, optionally validating the supplied ID."""
    request_location = _location_expression("requests", "req_loc", "r")
    beneficiary_filter = " AND r.beneficiary_id = %s" if beneficiary_id is not None else ""
    params = (request_id, beneficiary_id) if beneficiary_id is not None else (request_id,)
    return _first_row(
        f"""
        SELECT r.req_id, r.beneficiary_id, r.req_subj, r.req_desc,
               r.req_cat_id, hc.cat_name AS category, {request_location}
        FROM {_db_name}.requests AS r
        LEFT JOIN {_db_name}.help_categories AS hc ON hc.cat_id = r.req_cat_id
        WHERE r.req_id = %s{beneficiary_filter}
        """,
        params,
    )


def _get_beneficiary_profile(beneficiary_id):
    """Read the beneficiary address and resolve location IDs to names."""
    profile = _first_row(
        f"SELECT * FROM {_db_name}.users WHERE user_id = %s",
        (beneficiary_id,),
    )
    if not profile:
        return {}

    if profile.get("city_id"):
        if not profile.get("city_name"):
            profile["city_name"] = _lookup_location_name(
                "cities", "city_id", "city_name", profile.get("city_id")
            )
        if not profile.get("state_id"):
            profile["state_id"] = _lookup_location_field(
                "cities", "city_id", "state_id", profile.get("city_id")
            )
    if not profile.get("state_name"):
        profile["state_name"] = _lookup_location_name(
            "states", "state_id", "state_name", profile.get("state_id")
        )
    if not profile.get("country_id"):
        profile["country_id"] = _lookup_location_field(
            "states", "state_id", "country_id", profile.get("state_id")
        )
    if not profile.get("country_name"):
        profile["country_name"] = _lookup_location_name(
            "countries", "country_id", "country_name", profile.get("country_id")
        )
    return profile


def get_beneficiary_location(beneficiary_id, request_location=None):
    """Resolve coordinates from the request, current location, then profile."""
    try:
        profile = _get_beneficiary_profile(beneficiary_id)
    except Exception:
        logger.exception("Could not read beneficiary profile address")
        profile = {}
    address = build_address(profile)
    city = profile.get("city_name")

    coordinates = parse_coordinates(request_location)
    if coordinates is not None:
        return {
            "coordinates": coordinates,
            "status": "ok",
            "address": address,
            "city": city,
        }

    try:
        location_columns = _table_columns("user_locations")
        if {"user_id", "curr_loc"}.issubset(location_columns):
            location = _location_expression("user_locations", "curr_loc", "ul")
            updated = (
                "ORDER BY ul.updated_at DESC NULLS LAST "
                if "updated_at" in location_columns
                else ""
            )
            row = _first_row(
                f"SELECT {location} FROM {_db_name}.user_locations AS ul "
                f"WHERE ul.user_id = %s AND ul.curr_loc IS NOT NULL "
                f"{updated}LIMIT 1",
                (beneficiary_id,),
            )
            coordinates = parse_coordinates(row.get("curr_loc")) if row else None
            if coordinates is not None:
                return {
                    "coordinates": coordinates,
                    "status": "ok",
                    "address": address,
                    "city": city,
                }
    except Exception:
        logger.exception("Could not read beneficiary current location")

    coordinates, status = geocode_address(address)
    return {
        "coordinates": coordinates,
        "status": status if coordinates is None else "ok",
        "address": address,
        "city": city,
    }

def get_orgs_from_db(location, category):
    try:
        org_columns = _table_columns("organizations")
        skill_columns = _table_columns("org_skills")
        category_columns = _table_columns("help_categories")
        city_columns = _table_columns("cities")
        state_columns = _table_columns("states")
        country_columns = _table_columns("countries")
        joins = []
        selections = ["o.*"]
        conditions = []
        params = []

        if {"org_id", "cat_id"}.issubset(skill_columns) and {
            "cat_id", "cat_name"
        }.issubset(category_columns) and "org_id" in org_columns:
            joins.extend([
                f"JOIN {_db_name}.org_skills AS os ON os.org_id = o.org_id",
                f"JOIN {_db_name}.help_categories AS hc ON hc.cat_id = os.cat_id",
            ])
            conditions.append("hc.cat_name = %s")
            params.append(category)
        elif "cat_id" in org_columns and {"cat_id", "cat_name"}.issubset(
            category_columns
        ):
            joins.append(
                f"JOIN {_db_name}.help_categories AS hc ON hc.cat_id = o.cat_id"
            )
            conditions.append("hc.cat_name = %s")
            params.append(category)
        else:
            conditions.append("o.mission = %s")
            params.append(category)

        if location:
            if "city_name" in org_columns or not org_columns:
                conditions.append("o.city_name = %s")
                params.append(location)
            elif "city_id" in org_columns and {"city_id", "city_name"}.issubset(
                city_columns
            ):
                joins.append(
                    f"JOIN {_db_name}.cities AS ci ON ci.city_id = o.city_id"
                )
                selections.append("ci.city_name AS city_name")
                conditions.append("ci.city_name = %s")
                params.append(location)

        if "state_id" in org_columns and "state_id" in state_columns and (
            "state_name" in state_columns or "country_id" in state_columns
        ):
            joins.append(
                f"LEFT JOIN {_db_name}.states AS st ON st.state_id = o.state_id"
            )
            if "state_name" in state_columns and "state_name" not in org_columns:
                selections.append("st.state_name AS state_name")
        if "country_id" in org_columns and {
            "country_id", "country_name"
        }.issubset(country_columns):
            joins.append(
                f"LEFT JOIN {_db_name}.countries AS co ON co.country_id = o.country_id"
            )
            if "country_name" not in org_columns:
                selections.append("co.country_name AS country_name")
        elif "state_id" in org_columns and {
            "country_id", "country_name"
        }.issubset(country_columns) and "country_id" in state_columns:
            joins.append(
                f"LEFT JOIN {_db_name}.countries AS co "
                "ON co.country_id = st.country_id"
            )
            if "country_name" not in org_columns:
                selections.append("co.country_name AS country_name")

        query = (
            f"SELECT {', '.join(selections)} FROM {_db_name}.organizations AS o "
            f"{' '.join(joins)} WHERE {' AND '.join(conditions)}"
        )
        df = pd.read_sql(query, _db_conn, params=tuple(params))
        for id_column, lookup_table, lookup_key, name_column in (
            ("state_id", "states", "state_id", "state_name"),
            ("country_id", "countries", "country_id", "country_name"),
            ("city_id", "cities", "city_id", "city_name"),
        ):
            if id_column not in df.columns or name_column in df.columns:
                continue
            names = {}
            for value in df[id_column].dropna().unique():
                names[value] = _lookup_location_name(
                    lookup_table, lookup_key, name_column, value
                )
            df[name_column] = df[id_column].map(names)
        df["db_or_ai"] = "db"
        return df
    except pg8000.DatabaseError as e:
        raise Exception(f'Database error: {str(e)}')
    except Exception as e:
        raise Exception(f'Error fetching from DB: {str(e)}')


def get_ai_orgs(subject, description, location, category=None):
    try:
        request_payload = {
            "subject": subject,
            "description": description,
            "location": location,
        }
        if category is not None:
            request_payload["category"] = category
        response = lambda_client.invoke(
            FunctionName=GEN_AI_LAMBDA,
            InvocationType='RequestResponse',
            Payload=json.dumps(request_payload)
        )
        payload = json.loads(response['Payload'].read())
        if payload.get('statusCode') != 200:
            raise Exception(f'GenAI Lambda returned error: {payload}')
        result_body = payload.get("body", {})
        if isinstance(result_body, str):
            result_body = json.loads(result_body)
        orgs = pd.DataFrame(result_body.get('organizations', []))
        orgs["db_or_ai"] = "ai"
        return orgs
    except boto3.exceptions.Boto3Error as e:
        raise Exception(f'Failed to invoke GenAI Lambda: {str(e)}')
    except (KeyError, TypeError) as e:
        raise Exception(f'Unexpected response structure from GenAI Lambda: {str(e)}')
    except Exception as e:
        raise Exception(f'Error fetching AI orgs: {str(e)}')


def merge_organizations(db_organizations, genAI_organizations):
    """Normalize source names while retaining existing address and rating data."""
    db_organizations = db_organizations.rename(columns={
        'org_name': 'name',
        'org_type': 'organization_type',
        'is_collaborator': 'collaborator',
        'org_size': 'size',
        'org_rating': 'rating',
        'city_name': 'location',
        'phone': 'contact',
    }).copy()
    genAI_organizations = genAI_organizations.rename(columns={
        'organization_name': 'name',
        'org_type': 'organization_type',
        'is_collaborator': 'collaborator',
    }).copy()

    frames = []
    for frame, source in (
        (db_organizations, "db"),
        (genAI_organizations, "ai"),
    ):
        for column in ORG_COLUMNS:
            if column not in frame:
                frame[column] = None
        if "db_or_ai" not in frame:
            frame["db_or_ai"] = source
        frames.append(frame.reindex(columns=ORG_COLUMNS + ADDRESS_COLUMNS + ["db_or_ai"]))

    columns = ORG_COLUMNS + ADDRESS_COLUMNS + ["db_or_ai"]
    populated = [frame for frame in frames if not frame.empty]
    if not populated:
        return pd.DataFrame(columns=columns)
    return pd.concat(populated, ignore_index=True, sort=False)
