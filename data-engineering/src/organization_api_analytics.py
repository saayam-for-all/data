import json
import os
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA_NAME = "virginia_dev_saayam_rdbms"

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
VALID_GROUP_BY = {"daily", "weekly", "monthly", "yearly"}
GROUP_BY_TRUNC = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "yearly": "year",
}


# ---------------------------------------------------------------------------
# Response / request plumbing
# ---------------------------------------------------------------------------

def get_default_response():
    return {
        "summary": {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0,
        },
        "growth_trend": [],
        "organizations_by_location": [],
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
        "rating_distribution": [],
        "organization_type_distribution": [],
    }


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def parse_event_body(event):
    """Accepts either a raw dict (local/test invocation) or an API Gateway
    style event with a JSON-encoded "body" string."""
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


# ---------------------------------------------------------------------------
# Common filters
# ---------------------------------------------------------------------------

def parse_common_filters(body):
    """Parses time_filter, start_date/end_date, group_by, region and
    organization_type from the request body. Raises ValueError on invalid
    input so the caller can return a 400 response."""
    time_filter = (body.get("time_filter") or "ALL").upper()
    group_by = (body.get("group_by") or "daily").lower()
    region = body.get("region") or "ALL"
    organization_type = body.get("organization_type") or "ALL"

    if time_filter not in VALID_TIME_FILTERS:
        raise ValueError(
            f"Invalid time_filter '{time_filter}'. Must be one of {sorted(VALID_TIME_FILTERS)}."
        )
    if group_by not in VALID_GROUP_BY:
        raise ValueError(
            f"Invalid group_by '{group_by}'. Must be one of {sorted(VALID_GROUP_BY)}."
        )

    start_date = body.get("start_date")
    end_date = body.get("end_date")

    if time_filter == "CUSTOM":
        if not start_date or not end_date:
            raise ValueError(
                "For CUSTOM time_filter, both start_date and end_date must be provided."
            )
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("start_date and end_date must be in YYYY-MM-DD format.")
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date.")

    return {
        "time_filter": time_filter,
        "start_date": start_date,
        "end_date": end_date,
        "group_by": group_by,
        "trunc_unit": GROUP_BY_TRUNC[group_by],
        "region": region,
        "organization_type": organization_type,
    }


def build_date_filter(filters, column="o.created_at"):
    tf = filters["time_filter"]
    if tf == "ALL":
        return "", []
    if tf == "7D":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '7 days'", []
    if tf == "30D":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '30 days'", []
    if tf == "1Y":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '1 year'", []
    if tf == "CUSTOM":
        return f"AND {column}::date BETWEEN %s AND %s", [filters["start_date"], filters["end_date"]]
    return "", []


def build_region_filter(filters, column="s.state_name"):
    if filters["region"] == "ALL":
        return "", []
    return f"AND {column} = %s", [filters["region"]]


def build_org_type_filter(filters, column="o.org_type"):
    if filters["organization_type"] == "ALL":
        return "", []
    return f"AND {column} = %s", [filters["organization_type"]]


def combine_filters(filters, date_column="o.created_at", region_column="s.state_name", org_type_column="o.org_type"):
    """Convenience helper: returns (sql_fragment, params) combining the date,
    region and organization_type filters."""
    date_clause, date_params = build_date_filter(filters, date_column)
    region_clause, region_params = build_region_filter(filters, region_column)
    org_type_clause, org_type_params = build_org_type_filter(filters, org_type_column)

    clause = " ".join(part for part in (date_clause, region_clause, org_type_clause) if part)
    params = date_params + region_params + org_type_params
    return clause, params


# ---------------------------------------------------------------------------
# DB connection (local PostgreSQL - no AWS Parameter Store)
# ---------------------------------------------------------------------------

def get_db_connection():
    # Matches .env.example: DATABASE_URL=postgresql://user:password@host:port/dbname
    database_url = os.environ["DATABASE_URL"]
    return psycopg2.connect(database_url)


# ---------------------------------------------------------------------------
# Fetch functions
# ---------------------------------------------------------------------------

def fetch_summary_base(cursor, filters):
    """total_organizations, total_collaborators, average_org_rating.
    total_contributors is fetched separately (see fetch_total_contributors)
    since is_contributor may not exist in the dev DB yet."""
    clause, params = combine_filters(filters)

    query = f"""
        SELECT
            COUNT(o.org_id) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator = TRUE) AS total_collaborators,
            ROUND(AVG(o.org_rating), 2) AS average_org_rating
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        WHERE 1=1
        {clause}
    """
    cursor.execute(query, params)
    row = cursor.fetchone()

    return {
        "total_organizations": int(row["total_organizations"] or 0),
        "total_collaborators": int(row["total_collaborators"] or 0),
        "average_org_rating": float(row["average_org_rating"]) if row["average_org_rating"] is not None else 0,
    }


def fetch_total_contributors(cursor, filters):
    clause, params = combine_filters(filters)

    query = f"""
        SELECT COUNT(*) AS total_contributors
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        WHERE o.is_contributor = TRUE
        {clause}
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return int(row["total_contributors"] or 0)


def fetch_growth_trend(cursor, filters):
    clause, params = combine_filters(filters)
    trunc_unit = filters["trunc_unit"]

    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), 'YYYY-MM-DD') AS period,
            COUNT(o.org_id) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator = TRUE) AS total_collaborators
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        WHERE o.created_at IS NOT NULL
        {clause}
        GROUP BY 1
        ORDER BY 1 ASC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "period": row["period"],
            "total_organizations": int(row["total_organizations"]),
            "total_collaborators": int(row["total_collaborators"]),
        }
        for row in rows
    ]


def fetch_organizations_by_location(cursor, filters):
    clause, params = combine_filters(filters)

    query = f"""
        SELECT
            s.state_id,
            s.state_name,
            COUNT(o.org_id) AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        WHERE 1=1
        {clause}
        GROUP BY s.state_id, s.state_name
        ORDER BY organization_count DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()

    total = sum(int(row["organization_count"]) for row in rows) or 1

    return [
        {
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "organization_count": int(row["organization_count"]),
            "percentage": round(int(row["organization_count"]) / total * 100, 1),
        }
        for row in rows
    ]


def fetch_organizations_by_size(cursor, filters):
    clause, params = combine_filters(filters)

    query = f"""
        SELECT
            o.org_size,
            COUNT(o.org_id) AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        WHERE 1=1
        {clause}
        GROUP BY o.org_size
        ORDER BY o.org_size;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {"org_size": row["org_size"], "organization_count": int(row["organization_count"])}
        for row in rows
    ]


def fetch_collaborator_count(cursor, filters):
    clause, params = combine_filters(filters)
    query = f"""
        SELECT COUNT(*) AS collaborator_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        WHERE o.is_collaborator = TRUE
        {clause}
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return int(row["collaborator_count"] or 0)


def fetch_contributor_count(cursor, filters):
    # Separate from collaborator count: is_contributor may not exist yet in
    # the dev DB, and we don't want that failure to also break the
    # collaborator count.
    clause, params = combine_filters(filters)
    query = f"""
        SELECT COUNT(*) AS contributor_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        WHERE o.is_contributor = TRUE
        {clause}
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return int(row["contributor_count"] or 0)


def fetch_rating_distribution(cursor, filters):
    clause, params = combine_filters(filters)

    query = f"""
        SELECT
            o.org_rating,
            COUNT(o.org_id) AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        WHERE o.org_rating IS NOT NULL
        {clause}
        GROUP BY o.org_rating
        ORDER BY o.org_rating;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {"rating": int(row["org_rating"]), "organization_count": int(row["organization_count"])}
        for row in rows
    ]


def fetch_organization_type_distribution(cursor, filters):
    # Intentionally does not apply the organization_type filter itself
    # (that would defeat the purpose of a for_profit vs non_profit
    # breakdown) but does respect the date and region filters.
    date_clause, date_params = build_date_filter(filters)
    region_clause, region_params = build_region_filter(filters)
    clause = " ".join(part for part in (date_clause, region_clause) if part)
    params = date_params + region_params
    trunc_unit = filters["trunc_unit"]

    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), 'YYYY-MM-DD') AS period,
            COUNT(*) FILTER (WHERE o.org_type = 'for_profit') AS for_profit,
            COUNT(*) FILTER (WHERE o.org_type = 'non_profit') AS non_profit,
            COUNT(o.org_id) AS total
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        WHERE o.created_at IS NOT NULL
        {clause}
        GROUP BY 1
        ORDER BY 1 ASC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "period": row["period"],
            "for_profit": int(row["for_profit"] or 0),
            "non_profit": int(row["non_profit"] or 0),
            "total": int(row["total"] or 0),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    conn = None
    cursor = None
    response_body = get_default_response()

    body = parse_event_body(event)

    try:
        filters = parse_common_filters(body)
    except ValueError as error:
        return build_response(400, {"error": str(error)})

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            summary = fetch_summary_base(cursor, filters)
        except Exception as error:
            print(f"Summary query failed: {error}")
            summary = {
                "total_organizations": 0,
                "total_collaborators": 0,
                "average_org_rating": 0,
            }

        try:
            summary["total_contributors"] = fetch_total_contributors(cursor, filters)
        except Exception as error:
            print(f"Total contributors query failed (is_contributor column may not exist yet): {error}")
            summary["total_contributors"] = 0

        response_body["summary"] = summary

        try:
            response_body["growth_trend"] = fetch_growth_trend(cursor, filters)
        except Exception as error:
            print(f"Growth trend query failed: {error}")
            response_body["growth_trend"] = []

        try:
            response_body["organizations_by_location"] = fetch_organizations_by_location(cursor, filters)
        except Exception as error:
            print(f"Organizations by location query failed: {error}")
            response_body["organizations_by_location"] = []

        try:
            response_body["organizations_by_size"] = fetch_organizations_by_size(cursor, filters)
        except Exception as error:
            print(f"Organizations by size query failed: {error}")
            response_body["organizations_by_size"] = []

        try:
            collaborator_count = fetch_collaborator_count(cursor, filters)
        except Exception as error:
            print(f"Collaborator count query failed: {error}")
            collaborator_count = 0

        try:
            contributor_count = fetch_contributor_count(cursor, filters)
        except Exception as error:
            print(f"Contributor count query failed (is_contributor column may not exist yet): {error}")
            contributor_count = 0

        total_cc = collaborator_count + contributor_count or 1
        response_body["collaborator_vs_contributor"] = [
            {
                "type": "collaborator",
                "organization_count": collaborator_count,
                "percentage": round(collaborator_count / total_cc * 100, 1),
            },
            {
                "type": "contributor",
                "organization_count": contributor_count,
                "percentage": round(contributor_count / total_cc * 100, 1),
            },
        ]

        try:
            response_body["rating_distribution"] = fetch_rating_distribution(cursor, filters)
        except Exception as error:
            print(f"Rating distribution query failed: {error}")
            response_body["rating_distribution"] = []

        try:
            response_body["organization_type_distribution"] = fetch_organization_type_distribution(cursor, filters)
        except Exception as error:
            print(f"Organization type distribution query failed: {error}")
            response_body["organization_type_distribution"] = []

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
    test_event = {
        "body": json.dumps({
            "time_filter": "ALL",
            "start_date": None,
            "end_date": None,
            "group_by": "daily",
            "region": "ALL",
            "organization_type": "ALL",
        })
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))
