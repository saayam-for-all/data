import json
import os
import re
from decimal import Decimal

import pandas as pd

try:
    import boto3
except ImportError:  # pragma: no cover - supplied by the Lambda runtime layer
    boto3 = None

try:
    from aws_lambda_powertools.utilities import parameters
except ImportError:  # pragma: no cover - supplied by the Lambda runtime layer
    parameters = None

try:
    import pg8000
except ImportError:  # pragma: no cover - supplied by the Lambda runtime layer
    pg8000 = None

from distance import GeocodingDeferredError, select_beneficiary_location


GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"
_DB_PARAMETER = "/dev/saayam/db/Virginia/Analytics/user"
_DB_CONFIG = None
_LAMBDA_CLIENT = None
_GEOCODE_CACHE = None
_GEOCODE_CACHE_TABLE = None


class _DynamoCoordinateCache:
    """Use DynamoDB when available and retain a warm local fallback."""

    def __init__(self, table):
        self._table = table
        self._local = {}

    def get(self, key, default=None):
        """Return cached coordinates from memory or DynamoDB."""
        if key in self._local:
            return self._local[key]
        try:
            item = self._table.get_item(Key={"address_key": key}).get("Item")
            if not item:
                return default
            coordinates = (float(item["latitude"]), float(item["longitude"]))
        except Exception:
            return default
        self._local[key] = coordinates
        return coordinates

    def __setitem__(self, key, coordinates):
        """Cache coordinates in memory and persist them when DynamoDB is available."""
        latitude, longitude = coordinates
        normalized = (float(latitude), float(longitude))
        self._local[key] = normalized
        try:
            self._table.put_item(Item={
                "address_key": key,
                "latitude": Decimal(str(normalized[0])),
                "longitude": Decimal(str(normalized[1])),
            })
        except Exception:
            pass


def _get_db_config():
    """Load and cache the Virginia database credentials and schema name."""
    global _DB_CONFIG
    if _DB_CONFIG is None:
        if parameters is None:
            raise RuntimeError("aws-lambda-powertools is required for database access")
        _DB_CONFIG = json.loads(parameters.get_parameter(
            _DB_PARAMETER,
            decrypt=True,
            max_age=3600,
        ))
    return _DB_CONFIG


def _schema_name():
    """Return the configured schema after validating it as a SQL identifier."""
    schema = _get_db_config()["DATABASE NAME"]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError("Invalid configured database schema name")
    return schema


def _get_db_connection():
    """Open a database connection on demand rather than during module import."""
    if pg8000 is None:
        raise RuntimeError("pg8000 is required for database access")
    credentials = _get_db_config()
    return pg8000.connect(
        host=credentials["HOST"],
        user=credentials["USERNAME"],
        password=credentials["PASSWORD"],
        database=credentials["DATABASE NAME"],
        port=credentials["PORT"],
        ssl_context=True,
    )


def _get_lambda_client():
    """Create and cache the Lambda client only when GenAI lookup is requested."""
    global _LAMBDA_CLIENT
    if boto3 is None:
        raise RuntimeError("boto3 is required for GenAI organization lookup")
    if _LAMBDA_CLIENT is None:
        _LAMBDA_CLIENT = boto3.client("lambda")
    return _LAMBDA_CLIENT


def get_geocoder():
    """Return an optional provider-neutral geocoder Lambda adapter."""
    geocoder_name = os.getenv("GEOCODER_LAMBDA_NAME")
    if not geocoder_name:
        return None

    def geocode(address):
        response = _get_lambda_client().invoke(
            FunctionName=geocoder_name,
            InvocationType="RequestResponse",
            Payload=json.dumps({"address": address}),
        )
        payload = json.loads(response["Payload"].read())
        body = payload.get("body", {})
        if isinstance(body, str):
            body = json.loads(body)
        status = str(body.get("status", body.get("distance_status", ""))).casefold()
        if str(payload.get("statusCode")) in ("429", "503") or status in (
            "deferred",
            "rate_limited",
            "throttled",
        ):
            raise GeocodingDeferredError("Configured geocoder postponed the lookup")
        if payload.get("statusCode") != 200:
            raise RuntimeError("Configured geocoder returned an error")
        return body.get("coordinates", body)

    return geocode


def get_geocode_cache():
    """Return an optional persistent cache configured by GEOCODE_CACHE_TABLE."""
    global _GEOCODE_CACHE, _GEOCODE_CACHE_TABLE
    table_name = os.getenv("GEOCODE_CACHE_TABLE")
    if not table_name or boto3 is None:
        return None
    if _GEOCODE_CACHE is not None and _GEOCODE_CACHE_TABLE == table_name:
        return _GEOCODE_CACHE
    try:
        table = boto3.resource("dynamodb").Table(table_name)
        _GEOCODE_CACHE = _DynamoCoordinateCache(table)
        _GEOCODE_CACHE_TABLE = table_name
        return _GEOCODE_CACHE
    except Exception:
        return None


def _decode_record(value):
    """Decode a JSON database value into a dictionary."""
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _first_value(record, *keys):
    """Return the first non-empty value from a database record."""
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _fetch_record_with_location(cursor, table_name, lookup_keys, lookup_value, location_column):
    """Read one JSON row and return PostGIS locations as WKT when possible."""
    schema = _schema_name()
    cursor.execute(
        """SELECT udt_name FROM information_schema.columns
           WHERE table_schema = %s AND table_name = %s AND column_name = %s""",
        (schema, table_name, location_column),
    )
    column = cursor.fetchone()
    has_postgis_location = bool(column and column[0] in ("geometry", "geography"))
    key_expression = ", ".join(
        f"NULLIF(to_jsonb(record_row)->>'{key}', '')" for key in lookup_keys
    )
    location_expression = (
        f", ST_AsText(record_row.{location_column}::geometry)"
        if has_postgis_location
        else ""
    )
    query = f"""
        SELECT to_jsonb(record_row)::text{location_expression}
        FROM {schema}.{table_name} AS record_row
        WHERE COALESCE({key_expression}) = %s
        LIMIT 1
    """
    cursor.execute(query, (str(lookup_value),))
    row = cursor.fetchone()
    if not row:
        return {}
    record = _decode_record(row[0])
    if has_postgis_location and len(row) > 1 and row[1] is not None:
        record[f"{location_column}_wkt"] = row[1]
    return record


def _fetch_profile(cursor, beneficiary_id):
    """Load profile and named city/state/country values for a beneficiary."""
    schema = _schema_name()
    query = f"""
        SELECT to_jsonb(u)::text, to_jsonb(c)::text,
               to_jsonb(s)::text, to_jsonb(country)::text
        FROM {schema}.users AS u
        LEFT JOIN {schema}.cities AS c
                    ON (COALESCE(NULLIF(to_jsonb(c)->>'city_id', ''), NULLIF(to_jsonb(c)->>'id', ''))
                            = COALESCE(NULLIF(to_jsonb(u)->>'city_id', ''), NULLIF(to_jsonb(u)->>'city', ''))
                            OR lower(to_jsonb(c)->>'city_name') = lower(to_jsonb(u)->>'city'))
        LEFT JOIN {schema}.states AS s
                    ON (COALESCE(NULLIF(to_jsonb(s)->>'state_id', ''), NULLIF(to_jsonb(s)->>'id', ''))
                            = COALESCE(NULLIF(to_jsonb(c)->>'state_id', ''), NULLIF(to_jsonb(u)->>'state_id', ''))
                            OR lower(to_jsonb(s)->>'state_name') = lower(to_jsonb(u)->>'state'))
        LEFT JOIN {schema}.countries AS country
                    ON (COALESCE(NULLIF(to_jsonb(country)->>'country_id', ''), NULLIF(to_jsonb(country)->>'id', ''))
                            = COALESCE(NULLIF(to_jsonb(s)->>'country_id', ''), NULLIF(to_jsonb(u)->>'country_id', ''))
                            OR lower(to_jsonb(country)->>'country_name') = lower(to_jsonb(u)->>'country'))
        WHERE COALESCE(NULLIF(to_jsonb(u)->>'user_id', ''),
                       NULLIF(to_jsonb(u)->>'beneficiary_id', ''),
                       NULLIF(to_jsonb(u)->>'id', '')) = %s
        LIMIT 1
    """
    cursor.execute(query, (str(beneficiary_id),))
    row = cursor.fetchone()
    if not row:
        return {}, {}
    user, city, state, country = (_decode_record(value) for value in row)
    address = {
        "street": _first_value(user, "street", "street_address", "address_line_1", "address"),
        "city_name": _first_value(city, "city_name", "name") or _first_value(user, "city_name", "city"),
        "state_name": _first_value(state, "state_name", "name") or _first_value(user, "state_name", "state"),
        "zip_code": _first_value(user, "zip_code", "postal_code", "zipcode"),
        "country_name": _first_value(country, "country_name", "name") or _first_value(user, "country_name", "country"),
    }
    address = {key: value for key, value in address.items() if value is not None}
    search_context = {
        "location": address.get("city_name"),
        "subject": _first_value(user, "subject", "request_subject"),
        "description": _first_value(user, "description", "request_description"),
    }
    return address, search_context


def _fetch_category_name(cursor, request):
    """Resolve a stored request category ID to its display name when available."""
    category = _first_value(
        request,
        "category_name",
        "category",
        "req_category",
        "req_cat_name",
        "mission",
    )
    if category is not None:
        return category
    category_id = _first_value(request, "req_cat_id", "category_id", "help_category_id")
    if category_id is None:
        return None
    try:
        schema = _schema_name()
        cursor.execute(
            f"""SELECT to_jsonb(category)::text
                FROM {schema}.help_categories AS category
                WHERE COALESCE(NULLIF(to_jsonb(category)->>'cat_id', ''),
                               NULLIF(to_jsonb(category)->>'category_id', ''),
                               NULLIF(to_jsonb(category)->>'help_category_id', '')) = %s
                LIMIT 1""",
            (str(category_id),),
        )
        row = cursor.fetchone()
        if row:
            category_record = _decode_record(row[0])
            return _first_value(category_record, "cat_name", "category_name", "name")
    except Exception:
        return None
    return None


def get_request_context(request_id=None, beneficiary_id=None):
    """Resolve request, beneficiary, fallback locations, and search context."""
    if request_id is None and beneficiary_id is None:
        return {}
    connection = _get_db_connection()
    try:
        cursor = connection.cursor()
        request = {}
        if request_id is not None:
            request = _fetch_record_with_location(
                cursor,
                "requests",
                ("request_id", "req_id"),
                request_id,
                "req_loc",
            )

        resolved_beneficiary_id = beneficiary_id or _first_value(
            request,
            "beneficiary_id",
            "user_id",
            "requester_id",
            "requestor_id",
            "req_user_id",
        )
        user_location = {}
        profile_address = {}
        search_context = {}
        if resolved_beneficiary_id is not None:
            try:
                user_location = _fetch_record_with_location(
                    cursor,
                    "user_locations",
                    ("beneficiary_id", "user_id", "user_id_fk"),
                    resolved_beneficiary_id,
                    "curr_loc",
                )
            except Exception:
                user_location = {}
            try:
                profile_address, search_context = _fetch_profile(cursor, resolved_beneficiary_id)
            except Exception:
                profile_address, search_context = {}, {}

        request_location = request.get("req_loc_wkt", request.get("req_loc"))
        current_location = user_location.get("curr_loc_wkt", user_location.get("curr_loc"))
        beneficiary_location = select_beneficiary_location(
            request_location,
            current_location,
            profile_address,
        )
        search_context.update({
            "location": _first_value(request, "city_name", "city", "location") or search_context.get("location"),
            "category": _fetch_category_name(cursor, request),
            "subject": _first_value(request, "subject", "title", "req_subject") or search_context.get("subject"),
            "description": _first_value(request, "description", "req_desc") or search_context.get("description"),
        })
        return {
            "request": request,
            "beneficiary_id": resolved_beneficiary_id,
            "request_location": request_location,
            "user_location": current_location,
            "profile_address": profile_address,
            "beneficiary_location": beneficiary_location,
            "search": search_context,
        }
    finally:
        connection.close()

def get_orgs_from_db(location, category):
    """Fetch matching database organizations and their named address fields."""
    connection = _get_db_connection()
    try:
        schema = _schema_name()
        query = f"""
            SELECT organization.*, state.state_name, country.country_name
            FROM {schema}.organizations AS organization
            LEFT JOIN {schema}.states AS state
              ON organization.state_id::text = state.state_id::text
            LEFT JOIN {schema}.countries AS country
              ON state.country_id::text = country.country_id::text
            WHERE organization.mission = %s AND organization.city_name = %s
        """
        df = pd.read_sql(
            query,
            connection,
            params=(category, location),
        )
        df["db_or_ai"] = "db"
        return df
    except Exception as e:
        raise Exception(f'Error fetching from DB: {str(e)}')
    finally:
        connection.close()


def get_ai_orgs(subject, description, location):
    """Fetch organizations from the existing GenAI Lambda."""
    try:
        response = _get_lambda_client().invoke(
            FunctionName=GEN_AI_LAMBDA,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                "subject": subject,
                "description": description,
                "location": location
            })
        )
        payload = json.loads(response['Payload'].read())
        if payload.get('statusCode') != 200:
            raise Exception(f'GenAI Lambda returned error: {payload}')
        orgs = pd.DataFrame(payload['body']['organizations'])
        orgs["db_or_ai"] = "ai"
        return orgs
    except (KeyError, TypeError) as e:
        raise Exception(f'Unexpected response structure from GenAI Lambda: {str(e)}')
    except Exception as e:
        raise Exception(f'Error fetching AI orgs: {str(e)}')


def merge_organizations(db_organizations, genAI_organizations):
    """Normalize and combine sources without dropping distance/UI metadata."""
    required_columns = [
        "name",
        "location",
        "contact",
        "email",
        "web_url",
        "mission",
        "source",
        "db_or_ai",
    ]
    preserved_columns = [
        "street",
        "street_address",
        "address_line_1",
        "address",
        "formatted_address",
        "city_name",
        "city",
        "state_name",
        "state",
        "zip_code",
        "postal_code",
        "country_name",
        "country",
        "org_type",
        "organization_type",
        "Org-type",
        "is_collaborator",
        "Collaborator",
        "org_size",
        "size",
        "rating",
        "latitude",
        "longitude",
        "lat",
        "lon",
        "lng",
        "coordinates",
        "is_online",
        "online_only",
        "online",
    ]

    def normalize(frame, source):
        """Apply API field names and add stable fields to one source frame."""
        if frame is None:
            frame = pd.DataFrame()
        normalized = frame.copy()
        normalized = normalized.rename(columns={
            "org_name": "name",
            "organization_name": "name",
            "phone": "contact",
        })
        if "location" not in normalized and "city_name" in frame:
            normalized["location"] = frame["city_name"]
        if "name" not in normalized:
            normalized["name"] = None
        if "db_or_ai" not in normalized:
            normalized["db_or_ai"] = source
        for column in required_columns:
            if column not in normalized:
                normalized[column] = None
        columns = required_columns + [
            column for column in preserved_columns
            if column in normalized and column not in required_columns
        ]
        return normalized[columns]

    try:
        database_frame = normalize(db_organizations, "db")
        genai_frame = normalize(genAI_organizations, "ai")
        return pd.concat([database_frame, genai_frame], ignore_index=True, sort=False)
    except Exception as error:
        raise Exception(f"Error merging organizations: {str(error)}") from error