import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Schema is overridable so the SAME code runs against deployed Aurora and a
# local Postgres where CSVs may sit in a different schema (e.g. "public").
SCHEMA_NAME = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")

# Local mode: connect to a local Postgres instead of SSM/Aurora.
# Accepts LOCAL_DB or LOCAL_TEST so it fits either local convention.
LOCAL_DB = (
    os.environ.get("LOCAL_DB", "").lower() == "true"
    or os.environ.get("LOCAL_TEST", "").lower() == "true"
)

# SSM parameter holding the analytics DB creds as one JSON blob (kpi pattern).
SSM_PARAM_NAME = os.environ.get("SSM_PARAM_NAME", "/dev/saayam/db/Virginia/Analytics/user")

DEFAULT_TOP_N = 10

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
VALID_DASHBOARDS = {"overview", "performance"}
GROUP_BY_TRUNC = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", "YYYY-MM-DD"),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}
DEFAULT_GROUP_BY = "daily"


# ---------------------------------------------------------------------------
# Shared helpers (same shape as kpi_api_analytics.py)
# ---------------------------------------------------------------------------
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
    """Accept a direct dict payload (local tests) or an API Gateway event
    whose JSON payload is a string in event['body']."""
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
    if LOCAL_DB:
        return psycopg2.connect(
            host=os.environ.get("LOCAL_DB_HOST", "localhost"),
            database=os.environ.get("LOCAL_DB_NAME", "saayam_local"),
            user=os.environ.get("LOCAL_DB_USER", "postgres"),
            password=os.environ.get("LOCAL_DB_PASSWORD", "postgres"),
            port=os.environ.get("LOCAL_DB_PORT", "5432"),
        )

    import boto3  # lazy import so local runs don't require boto3
    ssm = boto3.client("ssm", region_name="us-east-1")
    response = ssm.get_parameter(Name=SSM_PARAM_NAME, WithDecryption=True)
    creds = json.loads(response["Parameter"]["Value"])
    return psycopg2.connect(
        host=creds["HOST"],
        database=creds["DATABASE NAME"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require",
    )


# ---------------------------------------------------------------------------
# Request parsing + filters (shared by every metric)
# ---------------------------------------------------------------------------
def parse_filters(request_body):
    time_filter = str(request_body.get("time_filter", "ALL")).upper()
    if time_filter not in VALID_TIME_FILTERS:
        time_filter = "ALL"

    group_by = str(request_body.get("group_by", DEFAULT_GROUP_BY)).lower()
    if group_by not in GROUP_BY_TRUNC:
        group_by = DEFAULT_GROUP_BY

    return {
        "time_filter": time_filter,
        "start_date": request_body.get("start_date"),
        "end_date": request_body.get("end_date"),
        "org_type": request_body.get("org_type"),
        "org_size": request_body.get("org_size"),
        "state_id": request_body.get("state_id"),
        "city_name": request_body.get("city_name"),
        "org_rating": request_body.get("org_rating"),
        "is_collaborator": request_body.get("is_collaborator"),
        "is_contributor": request_body.get("is_contributor"),
        "group_by": group_by,
        "top_n": int(request_body.get("top_n", DEFAULT_TOP_N)),
    }


def build_conditions(f):
    """Return (conditions, params). All conditions reference alias `o`."""
    conditions, params = [], []

    tf = f["time_filter"]
    if tf == "7D":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '7 days'")
    elif tf == "30D":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '30 days'")
    elif tf == "1Y":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '1 year'")
    elif tf == "CUSTOM" and f["start_date"] and f["end_date"]:
        conditions.append("o.created_at BETWEEN %s AND %s")
        params.extend([f["start_date"], f["end_date"]])

    if f["org_type"]:
        conditions.append("o.org_type = %s")
        params.append(f["org_type"])
    if f["org_size"]:
        conditions.append("o.org_size = %s")
        params.append(f["org_size"])
    if f["state_id"]:
        conditions.append("o.state_id = %s")
        params.append(f["state_id"])
    if f["city_name"]:
        conditions.append("o.city_name = %s")
        params.append(f["city_name"])
    if f["org_rating"] is not None:
        conditions.append("o.org_rating = %s")
        params.append(f["org_rating"])
    if f["is_collaborator"] is not None:
        conditions.append("o.is_collaborator = %s")
        params.append(bool(f["is_collaborator"]))
    if f["is_contributor"] is not None:
        conditions.append("o.is_contributor = %s")
        params.append(bool(f["is_contributor"]))

    return conditions, params


def where_clause(conditions):
    return ("WHERE " + " AND ".join(conditions)) if conditions else ""


def and_extra(conditions, extra):
    """Append an extra always-true-style condition (e.g. NOT NULL) to a WHERE."""
    base = where_clause(conditions)
    return f"{base} AND {extra}" if conditions else f"WHERE {extra}"


# ---------------------------------------------------------------------------
# OVERVIEW dashboard
# ---------------------------------------------------------------------------
def fetch_overview_summary(cursor, conditions, params):
    # Core counts only. Contributor counts are fetched separately so that a
    # missing is_contributor column (not yet in the current DB, per #228) blanks
    # only the two contributor fields rather than zeroing the whole summary.
    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'non_profit')            AS non_profit_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'for_profit')            AS for_profit_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE)            AS collaborator_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS DISTINCT FROM TRUE) AS non_collaborator_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_clause(conditions)};
    """
    cursor.execute(query, params)
    row = cursor.fetchone() or {}
    summary = {k: int(v or 0) for k, v in row.items()}
    summary["contributor_organizations"] = 0
    summary["non_contributor_organizations"] = 0
    return summary


def fetch_contributor_counts(cursor, conditions, params):
    query = f"""
        SELECT
            COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)            AS contributor_organizations,
            COUNT(*) FILTER (WHERE o.is_contributor IS DISTINCT FROM TRUE)  AS non_contributor_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_clause(conditions)};
    """
    cursor.execute(query, params)
    row = cursor.fetchone() or {}
    return {k: int(v or 0) for k, v in row.items()}


def fetch_registration_trend(cursor, conditions, params, group_by):
    trunc_unit, char_fmt = GROUP_BY_TRUNC[group_by]
    query = f"""
        SELECT TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), '{char_fmt}') AS period,
               COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause(conditions)}
        GROUP BY 1
        ORDER BY 1 ASC;
    """
    cursor.execute(query, params)
    return [{"period": r["period"], "count": int(r["count"])} for r in cursor.fetchall()]


def fetch_group_count(cursor, column, conditions, params):
    query = f"""
        SELECT o.{column}::text AS label, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause(conditions)}
        GROUP BY o.{column}
        ORDER BY count DESC;
    """
    cursor.execute(query, params)
    return [{column: r["label"], "count": int(r["count"])} for r in cursor.fetchall()]


def fetch_organizations_by_state(cursor, conditions, params):
    query = f"""
        SELECT o.state_id, s.state_name, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where_clause(conditions)}
        GROUP BY o.state_id, s.state_name
        ORDER BY count DESC;
    """
    cursor.execute(query, params)
    return [
        {"state_id": r["state_id"], "state_name": r["state_name"], "count": int(r["count"])}
        for r in cursor.fetchall()
    ]


def fetch_organizations_by_city(cursor, conditions, params):
    query = f"""
        SELECT o.city_name, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause(conditions)}
        GROUP BY o.city_name
        ORDER BY count DESC;
    """
    cursor.execute(query, params)
    return [{"city_name": r["city_name"], "count": int(r["count"])} for r in cursor.fetchall()]


def fetch_boolean_distribution(cursor, column, true_label, false_label, conditions, params):
    query = f"""
        SELECT
            COUNT(*) FILTER (WHERE o.{column} IS TRUE)            AS yes,
            COUNT(*) FILTER (WHERE o.{column} IS DISTINCT FROM TRUE) AS no
        FROM {SCHEMA_NAME}.organizations o
        {where_clause(conditions)};
    """
    cursor.execute(query, params)
    row = cursor.fetchone() or {}
    return [
        {"label": true_label, "count": int(row.get("yes") or 0)},
        {"label": false_label, "count": int(row.get("no") or 0)},
    ]


def get_default_overview_response():
    return {
        "organization_overview": {
            "summary": {
                "total_organizations": 0,
                "non_profit_organizations": 0,
                "for_profit_organizations": 0,
                "collaborator_organizations": 0,
                "non_collaborator_organizations": 0,
                "contributor_organizations": 0,
                "non_contributor_organizations": 0,
            },
            "organization_activity_trend": [],
            "organizations_by_type": [],
            "organizations_by_size": [],
            "organizations_by_location": [],
            "organizations_by_city": [],
            "collaborator_distribution": [],
            "contributor_distribution": [],
        }
    }


def build_overview(cursor, filters):
    conditions, params = build_conditions(filters)
    result = get_default_overview_response()["organization_overview"]

    def safe(key, fn):
        try:
            result[key] = fn()
        except Exception as error:
            print(f"[overview] {key} query failed: {error}")

    safe("summary", lambda: fetch_overview_summary(cursor, conditions, params))

    # Contributor counts are merged in separately; if the column isn't in the DB
    # yet, only these two summary fields stay 0 (everything else is unaffected).
    try:
        result["summary"].update(fetch_contributor_counts(cursor, conditions, params))
    except Exception as error:
        print(f"[overview] contributor counts unavailable (is_contributor column missing?): {error}")

    safe("organization_activity_trend",
         lambda: fetch_registration_trend(cursor, conditions, params, filters["group_by"]))
    safe("organizations_by_type", lambda: fetch_group_count(cursor, "org_type", conditions, params))
    safe("organizations_by_size", lambda: fetch_group_count(cursor, "org_size", conditions, params))
    safe("organizations_by_location", lambda: fetch_organizations_by_state(cursor, conditions, params))
    safe("organizations_by_city", lambda: fetch_organizations_by_city(cursor, conditions, params))
    safe("collaborator_distribution",
         lambda: fetch_boolean_distribution(cursor, "is_collaborator", "collaborator", "non_collaborator", conditions, params))
    safe("contributor_distribution",
         lambda: fetch_boolean_distribution(cursor, "is_contributor", "contributor", "non_contributor", conditions, params))
    return {"organization_overview": result}


# ---------------------------------------------------------------------------
# PERFORMANCE dashboard
# ---------------------------------------------------------------------------
def fetch_performance_summary(cursor, conditions, params):
    query = f"""
        SELECT
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating IS NULL)     AS unrated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating = 5)         AS five_star_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_clause(conditions)};
    """
    cursor.execute(query, params)
    row = cursor.fetchone() or {}
    return {
        "average_rating": float(row["average_rating"]) if row.get("average_rating") is not None else 0,
        "rated_organizations": int(row.get("rated_organizations") or 0),
        "unrated_organizations": int(row.get("unrated_organizations") or 0),
        "five_star_organizations": int(row.get("five_star_organizations") or 0),
    }


def fetch_rating_distribution(cursor, conditions, params):
    query = f"""
        SELECT o.org_rating AS rating, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {and_extra(conditions, "o.org_rating IS NOT NULL")}
        GROUP BY o.org_rating
        ORDER BY o.org_rating;
    """
    cursor.execute(query, params)
    found = {int(r["rating"]): int(r["count"]) for r in cursor.fetchall()}
    return [{"rating": star, "count": found.get(star, 0)} for star in range(1, 6)]


def fetch_top_rated(cursor, conditions, params, top_n):
    query = f"""
        SELECT o.org_id, o.org_name, o.org_rating
        FROM {SCHEMA_NAME}.organizations o
        {and_extra(conditions, "o.org_rating IS NOT NULL")}
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT %s;
    """
    cursor.execute(query, params + [top_n])
    return [
        {"org_id": r["org_id"], "org_name": r["org_name"], "org_rating": int(r["org_rating"])}
        for r in cursor.fetchall()
    ]


def fetch_top_flagged(cursor, column, conditions, params, top_n):
    """Top organizations where a boolean flag is TRUE, ranked by rating.
    Used for both top collaborators and top contributors. 'Top' is defined
    as highest-rated among flagged orgs (there is no interaction-count column)."""
    query = f"""
        SELECT o.org_id, o.org_name, o.org_rating
        FROM {SCHEMA_NAME}.organizations o
        {and_extra(conditions, f"o.{column} IS TRUE")}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT %s;
    """
    cursor.execute(query, params + [top_n])
    return [
        {
            "org_id": r["org_id"],
            "org_name": r["org_name"],
            "org_rating": int(r["org_rating"]) if r["org_rating"] is not None else None,
        }
        for r in cursor.fetchall()
    ]


def fetch_ratings_by_group(cursor, column, conditions, params):
    query = f"""
        SELECT o.{column}::text AS label,
               ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
               COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause(conditions)}
        GROUP BY o.{column}
        ORDER BY average_rating DESC NULLS LAST;
    """
    cursor.execute(query, params)
    return [
        {
            column: r["label"],
            "average_rating": float(r["average_rating"]) if r["average_rating"] is not None else 0,
            "rated_count": int(r["rated_count"]),
        }
        for r in cursor.fetchall()
    ]


def get_default_performance_response():
    return {
        "organization_performance": {
            "summary": {
                "average_rating": 0,
                "rated_organizations": 0,
                "unrated_organizations": 0,
                "five_star_organizations": 0,
            },
            "rating_distribution": [],
            "top_rated_organizations": [],
            "top_collaborator_organizations": [],
            "top_contributor_organizations": [],
            "ratings_by_organization_type": [],
            "ratings_by_organization_size": [],
        }
    }


def build_performance(cursor, filters):
    conditions, params = build_conditions(filters)
    top_n = filters["top_n"]
    result = get_default_performance_response()["organization_performance"]

    def safe(key, fn):
        try:
            result[key] = fn()
        except Exception as error:
            print(f"[performance] {key} query failed: {error}")

    safe("summary", lambda: fetch_performance_summary(cursor, conditions, params))
    safe("rating_distribution", lambda: fetch_rating_distribution(cursor, conditions, params))
    safe("top_rated_organizations", lambda: fetch_top_rated(cursor, conditions, params, top_n))
    safe("top_collaborator_organizations",
         lambda: fetch_top_flagged(cursor, "is_collaborator", conditions, params, top_n))
    safe("top_contributor_organizations",
         lambda: fetch_top_flagged(cursor, "is_contributor", conditions, params, top_n))
    safe("ratings_by_organization_type", lambda: fetch_ratings_by_group(cursor, "org_type", conditions, params))
    safe("ratings_by_organization_size", lambda: fetch_ratings_by_group(cursor, "org_size", conditions, params))
    return {"organization_performance": result}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def _run(dashboard_type, request_body):
    conn = cursor = None
    default_body = (
        get_default_performance_response()
        if dashboard_type == "performance"
        else get_default_overview_response()
    )
    try:
        filters = parse_filters(request_body)
        conn = get_db_connection()
        # Read-only analytics: autocommit means one failing metric query (e.g. a
        # not-yet-added column) doesn't abort the transaction for the others.
        conn.autocommit = True
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        body = (
            build_performance(cursor, filters)
            if dashboard_type == "performance"
            else build_overview(cursor, filters)
        )
        return build_response(200, body)
    except Exception as error:
        print(f"DB connection / query failed: {error}")
        return build_response(500, default_body)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def lambda_handler(event, context):
    """Single entry point, routes on `dashboard_type` (overview|performance).
    Matches the issue's 'one endpoint with a dashboard type' option."""
    body = parse_event_body(event)
    dashboard_type = str(body.get("dashboard_type", "overview")).lower()
    if dashboard_type not in VALID_DASHBOARDS:
        dashboard_type = "overview"
    return _run(dashboard_type, body)


# Thin wrappers for the two-endpoint deployment style:
#   POST /analytics/organizations/overview     -> overview_handler
#   POST /analytics/organizations/performance  -> performance_handler
def overview_handler(event, context):
    return _run("overview", parse_event_body(event))


def performance_handler(event, context):
    return _run("performance", parse_event_body(event))


if __name__ == "__main__":
    for payload in (
        {"dashboard_type": "overview", "time_filter": "ALL"},
        {"dashboard_type": "performance", "time_filter": "ALL"},
    ):
        print(f"===== {payload['dashboard_type'].upper()} (ALL) =====")
        print(json.dumps(json.loads(lambda_handler(payload, None)["body"]), indent=2))
        print()