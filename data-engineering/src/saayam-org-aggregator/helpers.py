"""Database and GenAI sources for the existing organization aggregator.

Connections are opened per invocation, not while importing the module. This
also keeps the distance calculations testable without live AWS credentials.
"""

import json


SCHEMA = "virginia_dev_saayam_rdbms"
GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"


def connect_database():
    import pg8000
    from aws_lambda_powertools.utilities import parameters

    credentials = json.loads(parameters.get_parameter(
        "/dev/saayam/db/Virginia/Analytics/user", decrypt=True, max_age=3600,
    ))
    return pg8000.connect(
        host=credentials["HOST"], user=credentials["USERNAME"],
        password=credentials["PASSWORD"], database=credentials["DATABASE NAME"],
        port=credentials["PORT"], ssl_context=True,
    )


def fetch_rows(connection, query, parameters=()):
    cursor = connection.cursor()
    try:
        cursor.execute(query, parameters)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def _location_expression(connection, table, column, alias):
    """Read a PostGIS location as WKT; leave text/JSON locations unchanged."""
    try:
        columns = fetch_rows(connection, """
            SELECT udt_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
        """, (SCHEMA, table, column))
        if columns and columns[0].get("udt_name") in {"geometry", "geography"}:
            return f"ST_AsText({alias}.{column}::geometry) AS {column}"
    except Exception:
        # Schema introspection failure should not prevent the plain-column path.
        pass
    return f"{alias}.{column}"


def _table_columns(connection, table):
    """Discover optional columns without assuming every environment is identical."""
    try:
        rows = fetch_rows(connection, """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
        """, (SCHEMA, table))
        return {row["column_name"] for row in rows if row.get("column_name")}
    except Exception:
        return set()


def get_request_context(connection, request_id, beneficiary_id=None):
    """Derive search inputs from the actual request, never the current viewer."""
    rows = fetch_rows(connection, f"""
        SELECT req_id, beneficiary_id, req_cat_id, req_subj, req_desc
        FROM {SCHEMA}.requests WHERE req_id = %s
    """, (request_id,))
    if not rows:
        return None
    request = rows[0]
    actual_id = request.get("beneficiary_id")
    if beneficiary_id is not None and str(beneficiary_id) != str(actual_id):
        return None
    category_rows = fetch_rows(connection, f"""
        SELECT cat_name FROM {SCHEMA}.help_categories WHERE cat_id = %s
    """, (request.get("req_cat_id"),)) if request.get("req_cat_id") is not None else []
    beneficiary_rows = fetch_rows(connection, f"""
        SELECT city_name FROM {SCHEMA}.users WHERE user_id = %s
    """, (actual_id,)) if actual_id is not None else []
    return {
        "beneficiary_id": actual_id,
        "category": category_rows[0].get("cat_name") if category_rows else None,
        "location": beneficiary_rows[0].get("city_name") if beneficiary_rows else None,
        "subject": request.get("req_subj"),
        "description": request.get("req_desc"),
    }


def get_orgs_from_db(connection, location, category):
    """Keep the existing mission/city search and retain all organization fields."""
    city_clause = "AND o.city_name = %s" if location else ""
    arguments = (category, location) if location else (category,)
    try:
        rows = fetch_rows(connection, f"""
            SELECT DISTINCT o.*, s.state_name, c.country_name, c.country_code
            FROM {SCHEMA}.organizations AS o
            JOIN {SCHEMA}.org_skills AS os ON os.org_id = o.org_id
            JOIN {SCHEMA}.help_categories AS hc ON hc.cat_id = os.cat_id
            LEFT JOIN {SCHEMA}.states AS s ON s.state_id = o.state_id
            LEFT JOIN {SCHEMA}.countries AS c ON c.country_id = s.country_id
            WHERE hc.cat_name = %s {city_clause}
        """, arguments)
    except Exception:
        # Older deployments searched mission directly; retain that path if
        # org_skills/category links are not available in the target schema.
        rows = fetch_rows(connection, f"""
        SELECT o.*, s.state_name, c.country_name, c.country_code
        FROM {SCHEMA}.organizations AS o
        LEFT JOIN {SCHEMA}.states AS s ON s.state_id = o.state_id
        LEFT JOIN {SCHEMA}.countries AS c ON c.country_id = s.country_id
        WHERE o.mission = %s {city_clause}
        """, arguments)
    for row in rows:
        row["name"] = row.get("org_name")
        row["contact"] = row.get("phone")
        row["location"] = row.get("city_name")
        row["size"] = row.get("org_size")
        row["rating"] = row.get("org_rating")
        row["Collaborator"] = row.get("is_collaborator")
        row["Org-type"] = row.get("org_type")
        row["db_or_ai"] = "db"
    return rows


def get_ai_orgs(subject, description, location, category=None):
    import boto3

    response = boto3.client("lambda").invoke(
        FunctionName=GEN_AI_LAMBDA, InvocationType="RequestResponse",
        Payload=json.dumps({
            "subject": subject, "description": description, "location": location,
            "category": category,
        }).encode(),
    )
    payload = json.loads(response["Payload"].read())
    if payload.get("statusCode") != 200:
        raise RuntimeError("GenAI organization source failed")
    body = payload.get("body", {})
    if isinstance(body, str):
        body = json.loads(body)
    rows = body.get("organizations", [])
    if not isinstance(rows, list):
        raise ValueError("GenAI organization response is not a list")
    result = []
    for original in rows:
        if not isinstance(original, dict):
            continue
        row = original.copy()
        row["name"] = row.get("name") or row.get("organization_name")
        row["db_or_ai"] = "ai"
        result.append(row)
    return result


def merge_organizations(db_organizations, genai_organizations):
    """Do not discard rating/collaborator or source-specific address fields."""
    return list(db_organizations) + list(genai_organizations)


def resolve_beneficiary_location(connection, request_id=None, beneficiary_id=None, geocoder=None, return_status=False):
    """Request coordinates, then beneficiary current location, then profile address.

    Never read viewer coordinates. If request_id is supplied, its beneficiary_id
    is authoritative; a mismatched caller-supplied ID is rejected.
    """
    from distance import parse_coordinates

    def finish(coordinates, status="ok"):
        return {"coordinates": coordinates, "status": status} if return_status else coordinates

    lookup_failed = False
    request_columns = _table_columns(connection, "requests")
    request_key = "req_id" if not request_columns or "req_id" in request_columns else "request_id"
    beneficiary_key = "beneficiary_id" if not request_columns or "beneficiary_id" in request_columns else "req_for_id"

    if request_id is not None:
        location_column = _location_expression(connection, "requests", "req_loc", "r")
        try:
            requests = fetch_rows(connection, f"""
                SELECT r.{request_key} AS req_id, r.{beneficiary_key} AS beneficiary_id,
                       {location_column}
                FROM {SCHEMA}.requests AS r WHERE r.{request_key} = %s
            """, (request_id,))
        except Exception:
            requests = []
            lookup_failed = True
        if not requests:
            if beneficiary_id is None:
                return finish(None, "error" if lookup_failed else "unknown_location")
            if not lookup_failed:
                return finish(None, "unknown_location")
        if requests:
            request = requests[0]
            actual_id = request.get("beneficiary_id")
            if beneficiary_id is not None and str(beneficiary_id) != str(actual_id):
                return finish(None, "unknown_location")
            beneficiary_id = actual_id
            coordinates = parse_coordinates(request.get("req_loc"))
            if coordinates is not None:
                return finish(coordinates)
    elif beneficiary_id is not None:
        # A request-details caller should send req_id. For beneficiary-only
        # callers, use that beneficiary's latest request, never the viewer's.
        location_column = _location_expression(connection, "requests", "req_loc", "r")
        try:
            requests = fetch_rows(connection, f"""
                SELECT r.{request_key} AS req_id, r.{beneficiary_key} AS beneficiary_id,
                       {location_column}
                FROM {SCHEMA}.requests AS r WHERE r.{beneficiary_key} = %s
                ORDER BY r.{('submission_date' if not request_columns or 'submission_date' in request_columns else request_key)} DESC LIMIT 1
            """, (beneficiary_id,))
        except Exception:
            requests = []
            lookup_failed = True
        if requests:
            coordinates = parse_coordinates(requests[0].get("req_loc"))
            if coordinates is not None:
                return finish(coordinates)

    if beneficiary_id is None:
        return finish(None, "error" if lookup_failed else "unknown_location")

    current_column = _location_expression(connection, "user_locations", "curr_loc", "ul")
    location_columns = _table_columns(connection, "user_locations")
    location_key = "user_id" if not location_columns or "user_id" in location_columns else "beneficiary_id"
    updated_key = "last_updated_at" if not location_columns or "last_updated_at" in location_columns else "updated_at" if "updated_at" in location_columns else None
    order_clause = f"ORDER BY ul.{updated_key} DESC " if updated_key else ""
    try:
        current = fetch_rows(connection, f"""
            SELECT {current_column} FROM {SCHEMA}.user_locations AS ul
            WHERE ul.{location_key} = %s {order_clause}LIMIT 1
        """, (beneficiary_id,))
    except Exception:
        current = []
        lookup_failed = True
    if current:
        coordinates = parse_coordinates(current[0].get("curr_loc"))
        if coordinates is not None:
            return finish(coordinates)

    user_columns = _table_columns(connection, "users")
    state_columns = _table_columns(connection, "states")
    country_columns = _table_columns(connection, "countries")
    city_columns = _table_columns(connection, "cities")
    known_user_columns = user_columns or {
        "user_id", "addr_ln1", "addr_ln2", "addr_ln3", "city_name",
        "zip_code", "state_id", "country_id",
    }
    profile_fields = [
        f"u.{column}" for column in ("addr_ln1", "addr_ln2", "addr_ln3", "zip_code")
        if column in known_user_columns
    ]
    profile_joins = []
    if "city_id" in known_user_columns and {"city_id", "city_name"}.issubset(city_columns):
        profile_fields.append("ci.city_name AS city_name")
        profile_joins.append(f"LEFT JOIN {SCHEMA}.cities AS ci ON ci.city_id = u.city_id")
    elif "city_name" in known_user_columns:
        profile_fields.append("u.city_name")
    if "state_id" in known_user_columns and (not state_columns or "state_name" in state_columns):
        profile_fields.append("s.state_name")
        profile_joins.append(f"LEFT JOIN {SCHEMA}.states AS s ON s.state_id = u.state_id")
    if "country_name" in country_columns or not country_columns:
        if "country_id" in known_user_columns:
            profile_fields.append("c.country_name")
            profile_joins.append(f"LEFT JOIN {SCHEMA}.countries AS c ON c.country_id = u.country_id")
        elif "state_id" in known_user_columns and (not state_columns or "country_id" in state_columns):
            profile_fields.append("c.country_name")
            profile_joins.append(f"LEFT JOIN {SCHEMA}.countries AS c ON c.country_id = s.country_id")
    if not profile_fields:
        return finish(None, "error" if lookup_failed else "unknown_location")
    try:
        profile = fetch_rows(connection, f"""
            SELECT {', '.join(profile_fields)}
            FROM {SCHEMA}.users AS u
            {' '.join(profile_joins)}
            WHERE u.user_id = %s
        """, (beneficiary_id,))
    except Exception:
        profile = []
        lookup_failed = True
    if not profile or geocoder is None:
        return finish(None, "error" if lookup_failed else "unknown_location")
    from distance import address_from_parts
    address = address_from_parts(profile[0], (
        "addr_ln1", "addr_ln2", "addr_ln3", "city_name", "state_name",
        "zip_code", "country_name",
    ))
    if not address:
        return finish(None, "error" if lookup_failed else "unknown_location")
    coordinates, status = geocoder.lookup(address)
    return finish(coordinates, status)
