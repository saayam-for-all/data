import json
import os
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
STATE_TABLE = f"{SCHEMA_NAME}.state"

VALID_DASHBOARD_TYPES = {"overview", "performance"}
VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}

# group_by -> (DATE_TRUNC unit, TO_CHAR display format)
GROUP_BY_TRUNC = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", "IYYY-IW"),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}

TOP_N = 10


def get_default_response(dashboard_type):
    """
    Returns the empty/zeroed response shape for the requested dashboard, used
    as the fallback body on a failed DB connection so the frontend always
    gets a well-formed response.
    """
    if dashboard_type == "performance":
        return {
            "organization_performance": {
                "summary": {
                    "average_rating": 0,
                    "rated_organizations": 0,
                    "unrated_organizations": 0,
                    "five_star_organizations": 0
                },
                "rating_distribution": [],
                "top_rated_organizations": [],
                "top_collaborator_organizations": [],
                "top_contributor_organizations": [],
                "ratings_by_organization_type": [],
                "ratings_by_organization_size": []
            }
        }

    return {
        "organization_overview": {
            "summary": {
                "total_organizations": 0,
                "non_profit_organizations": 0,
                "for_profit_organizations": 0,
                "collaborator_organizations": 0,
                "non_collaborator_organizations": 0,
                "contributor_organizations": 0,
                "non_contributor_organizations": 0
            },
            "organization_activity_trend": [],
            "organizations_by_type": [],
            "organizations_by_size": [],
            "organizations_by_location": {
                "by_state": [],
                "by_city": []
            },
            "collaborator_distribution": [],
            "contributor_distribution": []
        }
    }


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=str)
    }


def parse_event_body(event):
    """
    Normalizes the incoming Lambda event - handles both a raw dict (local/
    direct invocation) and an API-Gateway-style event with a JSON string (or
    dict) "body" key.
    """
    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body

    return {}


def get_db_connection():
    """
    Returns a psycopg2 connection to the Virginia RDS PostgreSQL database.

    Local testing path: set LOCAL_DB=true and supply connection details via
    environment variables (e.g. a .env file that is NOT committed). No
    production credentials are ever hardcoded here.

    Production/dev path (default): credentials are pulled from AWS SSM
    Parameter Store, as before.
    """
    if os.environ.get("LOCAL_DB", "false").lower() == "true":
        return psycopg2.connect(
            host=os.environ.get("LOCAL_DB_HOST", "localhost"),
            port=int(os.environ.get("LOCAL_DB_PORT", "5432")),
            database=os.environ.get("LOCAL_DB_NAME", "saayam"),
            user=os.environ.get("LOCAL_DB_USER", "postgres"),
            password=os.environ.get("LOCAL_DB_PASSWORD", ""),
        )

    ssm = boto3.client("ssm", region_name="us-east-1")

    response = ssm.get_parameter(
        Name="/dev/saayam/db/Virginia/Analytics/user",
        WithDecryption=True
    )

    creds = json.loads(response["Parameter"]["Value"])
    db_name = creds["DATABASE NAME"]
    return psycopg2.connect(
        host=creds["HOST"],
        database=db_name,
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )


def build_date_filter(time_filter, start_date=None, end_date=None, column="o.created_at"):
    """
    Builds the SQL date-filter condition (against the organizations table's
    created_at column, by default) and its query parameters for the given
    time_filter. Meant to be spliced directly into a WHERE/AND clause. Never
    interpolates start_date/end_date directly into the SQL string - they are
    always passed back as bind params.

    Returns a tuple (sql_condition, params):
        - sql_condition is "1=1" (a no-op filter) when no filter should be
          applied (time_filter "ALL", an unrecognized value, or an incomplete
          "CUSTOM" range), so callers can always splice it in unconditionally.
        - params is a list of values to bind to any %s placeholders.
    """
    time_filter = (time_filter or "ALL").upper()

    if time_filter == "7D":
        return f"{column} >= CURRENT_DATE - INTERVAL '7 days'", []

    if time_filter == "30D":
        return f"{column} >= CURRENT_DATE - INTERVAL '30 days'", []

    if time_filter == "1Y":
        return f"{column} >= CURRENT_DATE - INTERVAL '1 year'", []

    if time_filter == "CUSTOM":
        if start_date and end_date:
            return f"{column} BETWEEN %s AND %s", [start_date, end_date]
        print("CUSTOM time_filter requested without both start_date and end_date; no date filter applied")
        return "1=1", []

    # "ALL" (default) or any unrecognized value -> no filter
    return "1=1", []


def build_common_filters(filters):
    """
    Builds the shared WHERE conditions for the common filter payload
    (org_type, org_size, state_id, city_name, org_rating, is_collaborator,
    is_contributor). Returns (conditions, params); every value is passed back
    as a bind param, never interpolated into the SQL string.

    Note: is_contributor is part of the requested filter set, but is not yet
    present on the live virginia_dev_saayam_rdbms.organizations schema (see
    ddl_organizations.sql). Any query that references it is wrapped in a
    try/except by its caller, so it degrades to an empty/zeroed result
    instead of failing the whole request once the column exists.
    """
    conditions = []
    params = []

    org_type = filters.get("org_type")
    if org_type:
        conditions.append("o.org_type = %s")
        params.append(org_type)

    org_size = filters.get("org_size")
    if org_size:
        conditions.append("o.org_size = %s")
        params.append(org_size)

    state_id = filters.get("state_id")
    if state_id:
        conditions.append("o.state_id = %s")
        params.append(state_id)

    city_name = filters.get("city_name")
    if city_name:
        conditions.append("o.city_name = %s")
        params.append(city_name)

    org_rating = filters.get("org_rating")
    if org_rating is not None:
        conditions.append("o.org_rating = %s")
        params.append(org_rating)

    is_collaborator = filters.get("is_collaborator")
    if is_collaborator is not None:
        conditions.append("o.is_collaborator = %s")
        params.append(is_collaborator)

    is_contributor = filters.get("is_contributor")
    if is_contributor is not None:
        conditions.append("o.is_contributor = %s")
        params.append(is_contributor)

    return conditions, params


def build_where_clause(date_condition, date_params, common_conditions, common_params):
    conditions = [date_condition] + common_conditions
    params = list(date_params) + list(common_params)
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    return where_clause, params


# ---------------------------------------------------------------------------
# Dashboard 1: Organization Overview
# ---------------------------------------------------------------------------

def fetch_overview_summary(cursor, where_clause, params):
    try:
        query = f"""
            SELECT
                COUNT(*) AS total_organizations,
                COUNT(*) FILTER (WHERE o.org_type = 'non_profit') AS non_profit_organizations,
                COUNT(*) FILTER (WHERE o.org_type = 'for_profit') AS for_profit_organizations,
                COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_organizations,
                COUNT(*) FILTER (WHERE o.is_collaborator IS NOT TRUE) AS non_collaborator_organizations,
                COUNT(*) FILTER (WHERE o.is_contributor IS TRUE) AS contributor_organizations,
                COUNT(*) FILTER (WHERE o.is_contributor IS NOT TRUE) AS non_contributor_organizations
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause};
        """
        cursor.execute(query, params)
        row = cursor.fetchone()

        return {
            "total_organizations": int(row["total_organizations"]),
            "non_profit_organizations": int(row["non_profit_organizations"]),
            "for_profit_organizations": int(row["for_profit_organizations"]),
            "collaborator_organizations": int(row["collaborator_organizations"]),
            "non_collaborator_organizations": int(row["non_collaborator_organizations"]),
            "contributor_organizations": int(row["contributor_organizations"]),
            "non_contributor_organizations": int(row["non_contributor_organizations"])
        }
    except Exception as e:
        print("Error in fetch_overview_summary:", str(e))
        return {
            "total_organizations": 0,
            "non_profit_organizations": 0,
            "for_profit_organizations": 0,
            "collaborator_organizations": 0,
            "non_collaborator_organizations": 0,
            "contributor_organizations": 0,
            "non_contributor_organizations": 0
        }


def fetch_organization_activity_trend(cursor, where_clause, params, group_by):
    try:
        trunc_unit, date_format = GROUP_BY_TRUNC.get(group_by, GROUP_BY_TRUNC["daily"])

        query = f"""
            SELECT TO_CHAR(DATE_TRUNC(%s, o.created_at), %s) AS period,
                COUNT(*) AS count
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
              AND o.created_at IS NOT NULL
            GROUP BY 1
            ORDER BY 1 ASC;
        """
        cursor.execute(query, [trunc_unit, date_format] + list(params))
        rows = cursor.fetchall()

        return [{"period": row["period"], "count": int(row["count"])} for row in rows]
    except Exception as e:
        print("Error in fetch_organization_activity_trend:", str(e))
        return []


def fetch_organizations_by_type(cursor, where_clause, params):
    try:
        query = f"""
            SELECT COALESCE(o.org_type::text, 'unknown') AS org_type, COUNT(*) AS count
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
            GROUP BY 1
            ORDER BY count DESC;
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [{"org_type": row["org_type"], "count": int(row["count"])} for row in rows]
    except Exception as e:
        print("Error in fetch_organizations_by_type:", str(e))
        return []


def fetch_organizations_by_size(cursor, where_clause, params):
    try:
        query = f"""
            SELECT COALESCE(o.org_size::text, 'unknown') AS org_size, COUNT(*) AS count
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
            GROUP BY 1
            ORDER BY count DESC;
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [{"org_size": row["org_size"], "count": int(row["count"])} for row in rows]
    except Exception as e:
        print("Error in fetch_organizations_by_size:", str(e))
        return []


def fetch_organizations_by_state(cursor, where_clause, params):
    try:
        query = f"""
            SELECT COALESCE(s.state_name, 'Unknown') AS state, COUNT(*) AS count
            FROM {ORGANIZATIONS_TABLE} o
            LEFT JOIN {STATE_TABLE} s ON o.state_id = s.state_id
            WHERE {where_clause}
            GROUP BY COALESCE(s.state_name, 'Unknown')
            ORDER BY count DESC;
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [{"state": row["state"], "count": int(row["count"])} for row in rows]
    except Exception as e:
        print("Error in fetch_organizations_by_state:", str(e))
        return []


def fetch_organizations_by_city(cursor, where_clause, params):
    try:
        query = f"""
            SELECT COALESCE(o.city_name, 'Unknown') AS city, COUNT(*) AS count
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
            GROUP BY COALESCE(o.city_name, 'Unknown')
            ORDER BY count DESC;
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [{"city": row["city"], "count": int(row["count"])} for row in rows]
    except Exception as e:
        print("Error in fetch_organizations_by_city:", str(e))
        return []


def fetch_collaborator_distribution(cursor, where_clause, params):
    try:
        query = f"""
            SELECT
                CASE WHEN o.is_collaborator IS TRUE THEN 'collaborator' ELSE 'non_collaborator' END AS category,
                COUNT(*) AS count
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
            GROUP BY 1;
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [{"category": row["category"], "count": int(row["count"])} for row in rows]
    except Exception as e:
        print("Error in fetch_collaborator_distribution:", str(e))
        return []


def fetch_contributor_distribution(cursor, where_clause, params):
    # NOTE: is_contributor is not yet present on the live organizations
    # schema (ddl_organizations.sql only defines is_collaborator). This will
    # raise and safely fall back to [] until the column is added.
    try:
        query = f"""
            SELECT
                CASE WHEN o.is_contributor IS TRUE THEN 'contributor' ELSE 'non_contributor' END AS category,
                COUNT(*) AS count
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
            GROUP BY 1;
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [{"category": row["category"], "count": int(row["count"])} for row in rows]
    except Exception as e:
        print("Error in fetch_contributor_distribution:", str(e))
        return []


def build_organization_overview(cursor, where_clause, params, group_by):
    return {
        "organization_overview": {
            "summary": fetch_overview_summary(cursor, where_clause, params),
            "organization_activity_trend": fetch_organization_activity_trend(cursor, where_clause, params, group_by),
            "organizations_by_type": fetch_organizations_by_type(cursor, where_clause, params),
            "organizations_by_size": fetch_organizations_by_size(cursor, where_clause, params),
            "organizations_by_location": {
                "by_state": fetch_organizations_by_state(cursor, where_clause, params),
                "by_city": fetch_organizations_by_city(cursor, where_clause, params)
            },
            "collaborator_distribution": fetch_collaborator_distribution(cursor, where_clause, params),
            "contributor_distribution": fetch_contributor_distribution(cursor, where_clause, params)
        }
    }


# ---------------------------------------------------------------------------
# Dashboard 2: Organization Performance
# ---------------------------------------------------------------------------

def fetch_performance_summary(cursor, where_clause, params):
    try:
        query = f"""
            SELECT
                ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
                COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations,
                COUNT(*) FILTER (WHERE o.org_rating IS NULL) AS unrated_organizations,
                COUNT(*) FILTER (WHERE o.org_rating = 5) AS five_star_organizations
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause};
        """
        cursor.execute(query, params)
        row = cursor.fetchone()

        return {
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
            "rated_organizations": int(row["rated_organizations"]),
            "unrated_organizations": int(row["unrated_organizations"]),
            "five_star_organizations": int(row["five_star_organizations"])
        }
    except Exception as e:
        print("Error in fetch_performance_summary:", str(e))
        return {
            "average_rating": 0,
            "rated_organizations": 0,
            "unrated_organizations": 0,
            "five_star_organizations": 0
        }


def fetch_rating_distribution(cursor, where_clause, params):
    try:
        query = f"""
            SELECT o.org_rating AS rating, COUNT(*) AS count
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
              AND o.org_rating IS NOT NULL
            GROUP BY o.org_rating
            ORDER BY o.org_rating ASC;
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [{"rating": int(row["rating"]), "count": int(row["count"])} for row in rows]
    except Exception as e:
        print("Error in fetch_rating_distribution:", str(e))
        return []


def fetch_top_rated_organizations(cursor, where_clause, params, limit=TOP_N):
    try:
        query = f"""
            SELECT o.org_id, o.org_name, o.org_rating, o.org_type::text AS org_type, o.org_size::text AS org_size
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
              AND o.org_rating IS NOT NULL
            ORDER BY o.org_rating DESC, o.org_name ASC
            LIMIT %s;
        """
        cursor.execute(query, list(params) + [limit])
        rows = cursor.fetchall()

        return [
            {
                "org_id": row["org_id"],
                "org_name": row["org_name"],
                "org_rating": int(row["org_rating"]),
                "org_type": row["org_type"],
                "org_size": row["org_size"]
            }
            for row in rows
        ]
    except Exception as e:
        print("Error in fetch_top_rated_organizations:", str(e))
        return []


def fetch_top_collaborator_organizations(cursor, where_clause, params, limit=TOP_N):
    try:
        query = f"""
            SELECT o.org_id, o.org_name, o.org_rating
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
              AND o.is_collaborator IS TRUE
            ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
            LIMIT %s;
        """
        cursor.execute(query, list(params) + [limit])
        rows = cursor.fetchall()

        return [
            {
                "org_id": row["org_id"],
                "org_name": row["org_name"],
                "org_rating": int(row["org_rating"]) if row["org_rating"] is not None else None
            }
            for row in rows
        ]
    except Exception as e:
        print("Error in fetch_top_collaborator_organizations:", str(e))
        return []


def fetch_top_contributor_organizations(cursor, where_clause, params, limit=TOP_N):
    # NOTE: is_contributor is not yet present on the live organizations
    # schema (see the note on fetch_contributor_distribution above). This
    # will raise and safely fall back to [] until the column is added.
    try:
        query = f"""
            SELECT o.org_id, o.org_name, o.org_rating
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
              AND o.is_contributor IS TRUE
            ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
            LIMIT %s;
        """
        cursor.execute(query, list(params) + [limit])
        rows = cursor.fetchall()

        return [
            {
                "org_id": row["org_id"],
                "org_name": row["org_name"],
                "org_rating": int(row["org_rating"]) if row["org_rating"] is not None else None
            }
            for row in rows
        ]
    except Exception as e:
        print("Error in fetch_top_contributor_organizations:", str(e))
        return []


def fetch_ratings_by_organization_type(cursor, where_clause, params):
    try:
        query = f"""
            SELECT
                COALESCE(o.org_type::text, 'unknown') AS org_type,
                ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
                COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
            GROUP BY 1
            ORDER BY 1;
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {
                "org_type": row["org_type"],
                "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
                "rated_organizations": int(row["rated_organizations"])
            }
            for row in rows
        ]
    except Exception as e:
        print("Error in fetch_ratings_by_organization_type:", str(e))
        return []


def fetch_ratings_by_organization_size(cursor, where_clause, params):
    try:
        query = f"""
            SELECT
                COALESCE(o.org_size::text, 'unknown') AS org_size,
                ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
                COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations
            FROM {ORGANIZATIONS_TABLE} o
            WHERE {where_clause}
            GROUP BY 1
            ORDER BY 1;
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {
                "org_size": row["org_size"],
                "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
                "rated_organizations": int(row["rated_organizations"])
            }
            for row in rows
        ]
    except Exception as e:
        print("Error in fetch_ratings_by_organization_size:", str(e))
        return []


def build_organization_performance(cursor, where_clause, params):
    return {
        "organization_performance": {
            "summary": fetch_performance_summary(cursor, where_clause, params),
            "rating_distribution": fetch_rating_distribution(cursor, where_clause, params),
            "top_rated_organizations": fetch_top_rated_organizations(cursor, where_clause, params),
            "top_collaborator_organizations": fetch_top_collaborator_organizations(cursor, where_clause, params),
            "top_contributor_organizations": fetch_top_contributor_organizations(cursor, where_clause, params),
            "ratings_by_organization_type": fetch_ratings_by_organization_type(cursor, where_clause, params),
            "ratings_by_organization_size": fetch_ratings_by_organization_size(cursor, where_clause, params)
        }
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    conn = None
    cursor = None

    request_body = parse_event_body(event)

    dashboard_type = str(request_body.get("dashboard_type", "overview")).lower()
    if dashboard_type not in VALID_DASHBOARD_TYPES:
        dashboard_type = "overview"

    time_filter = request_body.get("time_filter", "30D")
    start_date = request_body.get("start_date")
    end_date = request_body.get("end_date")
    group_by = request_body.get("group_by", "daily")
    if group_by not in GROUP_BY_TRUNC:
        group_by = "daily"

    response_body = get_default_response(dashboard_type)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        date_condition, date_params = build_date_filter(time_filter, start_date, end_date)
        common_conditions, common_params = build_common_filters(request_body)
        where_clause, params = build_where_clause(date_condition, date_params, common_conditions, common_params)

        if dashboard_type == "performance":
            response_body = build_organization_performance(cursor, where_clause, params)
        else:
            response_body = build_organization_overview(cursor, where_clause, params, group_by)

        return build_response(200, response_body)

    except Exception as error:
        print(f"DB connection failed: {error}")
        return build_response(500, response_body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    # Local run: set LOCAL_DB=true (plus LOCAL_DB_HOST/PORT/NAME/USER/PASSWORD
    # env vars pointing at a local Postgres loaded with the real schema) before
    # running `python organization_analytics.py`.
    test_events = [
        {"dashboard_type": "overview", "time_filter": "ALL", "group_by": "monthly"},
        {"dashboard_type": "overview", "time_filter": "30D", "group_by": "daily"},
        {"dashboard_type": "overview", "time_filter": "1Y", "group_by": "monthly", "org_type": "non_profit"},
        {"dashboard_type": "overview", "time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-12-31", "group_by": "weekly"},
        {"dashboard_type": "performance", "time_filter": "ALL"},
        {"dashboard_type": "performance", "time_filter": "ALL", "org_size": "large"},
        {"dashboard_type": "performance", "time_filter": "ALL", "is_collaborator": True},
    ]

    for test_event in test_events:
        print(f"--- Testing payload: {test_event} ---")
        result = lambda_handler(test_event, None)
        print(json.dumps(result, indent=2))
