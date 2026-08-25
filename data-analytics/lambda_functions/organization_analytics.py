import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Schema override so the same code runs against deployed Aurora and a local
# Postgres (CSVs may sit in a different schema, e.g. "public").
SCHEMA_NAME = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")

# NOTE: per the issue, AWS Parameter Store (SSM) must NOT be used anywhere in
# this file. Credentials always come from environment variables, both locally
# and when deployed. Whoever wires this into the AWS environment should inject
# DB_HOST / DB_NAME / DB_USER / DB_PASSWORD / DB_PORT (and DB_SSLMODE if
# needed) as Lambda environment variables through whatever mechanism the team
# uses instead of SSM (e.g. Secrets Manager -> env vars at deploy time).
DEFAULT_TOP_N = 5

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
GROUP_BY_TRUNC = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", "YYYY-MM-DD"),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}
DEFAULT_GROUP_BY = "monthly"

# Real sample data stores org_type as "Non-Profit" / "For-profit" (mixed case,
# hyphenated), while the issue's filter examples pass "non_profit" (snake
# case). Filtering normalizes both sides (lower-cased, hyphens -> underscores)
# so "non_profit" matches "Non-Profit". Response values are normalized to the
# snake_case form shown in the issue's example responses.
def normalize_org_type(value):
    if value is None:
        return None
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def normalize_org_size(value):
    if value is None:
        return None
    return str(value).strip().lower()


# ---------------------------------------------------------------------------
# Shared helpers
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
    """Always connects via environment variables. Does NOT use AWS Parameter
    Store / SSM, per the issue's explicit instruction."""
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", os.environ.get("LOCAL_DB_HOST", "localhost")),
        dbname=os.environ.get("DB_NAME", os.environ.get("LOCAL_DB_NAME", "saayam_local")),
        user=os.environ.get("DB_USER", os.environ.get("LOCAL_DB_USER", "postgres")),
        password=os.environ.get("DB_PASSWORD", os.environ.get("LOCAL_DB_PASSWORD", "postgres")),
        port=os.environ.get("DB_PORT", os.environ.get("LOCAL_DB_PORT", "5432")),
        sslmode=os.environ.get("DB_SSLMODE", "prefer"),
    )


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def parse_filters(request_body):
    time_filter = str(request_body.get("time_filter", "ALL")).upper()
    if time_filter not in VALID_TIME_FILTERS:
        time_filter = "ALL"

    group_by = str(request_body.get("group_by", DEFAULT_GROUP_BY)).lower()
    if group_by not in GROUP_BY_TRUNC:
        group_by = DEFAULT_GROUP_BY

    region = request_body.get("region")
    if region is None or str(region).strip().upper() == "ALL":
        region = None

    org_type = request_body.get("organization_type")
    if org_type is None or str(org_type).strip().upper() == "ALL":
        org_type = None

    return {
        "time_filter": time_filter,
        "start_date": request_body.get("start_date"),
        "end_date": request_body.get("end_date"),
        "group_by": group_by,
        "region": region,
        "organization_type": org_type,
        "top_n": int(request_body.get("top_n", DEFAULT_TOP_N)),
    }


def build_conditions(f):
    """Common filter conditions, referencing alias `o` (organizations) and,
    where needed, `s` (states). Region filters by state_name (case-insensitive)
    to match the issue's sample payload (e.g. "region": "California")."""
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

    if f["region"]:
        conditions.append("(LOWER(s.state_name) = LOWER(%s) OR LOWER(o.state_id) = LOWER(%s))")
        params.extend([f["region"], f["region"]])

    if f["organization_type"]:
        conditions.append(
            "LOWER(REPLACE(REPLACE(o.org_type, '-', '_'), ' ', '_')) = %s"
        )
        params.append(normalize_org_type(f["organization_type"]))

    return conditions, params


def where_clause(conditions):
    return ("WHERE " + " AND ".join(conditions)) if conditions else ""


def and_extra(conditions, extra):
    base = where_clause(conditions)
    return f"{base} AND {extra}" if conditions else f"WHERE {extra}"


# Every metric query joins states so `region` filtering works even for
# metrics that don't otherwise need location data.
BASE_FROM = f"""
    FROM {SCHEMA_NAME}.organizations o
    LEFT JOIN {SCHEMA_NAME}.states s ON o.state_id = s.state_id
"""


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------
def fetch_summary(cursor, conditions, params):
    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators,
            COUNT(*) FILTER (WHERE o.is_contributor IS TRUE) AS total_contributors,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_org_rating
        {BASE_FROM}
        {where_clause(conditions)};
    """
    cursor.execute(query, params)
    row = cursor.fetchone() or {}
    return {
        "total_organizations": int(row.get("total_organizations") or 0),
        "total_collaborators": int(row.get("total_collaborators") or 0),
        "total_contributors": int(row.get("total_contributors") or 0),
        "average_org_rating": float(row["average_org_rating"]) if row.get("average_org_rating") is not None else 0,
    }


# ---------------------------------------------------------------------------
# Tab 1: Growth & Location
# ---------------------------------------------------------------------------
def fetch_growth_trend(cursor, conditions, params, group_by):
    trunc_unit, char_fmt = GROUP_BY_TRUNC[group_by]
    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), '{char_fmt}') AS period,
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators
        {BASE_FROM}
        {where_clause(conditions)}
        GROUP BY 1
        ORDER BY 1 ASC;
    """
    cursor.execute(query, params)
    return [
        {
            "period": r["period"],
            "total_organizations": int(r["total_organizations"]),
            "total_collaborators": int(r["total_collaborators"]),
        }
        for r in cursor.fetchall()
    ]


def fetch_organizations_by_location(cursor, conditions, params):
    # Groups by state AND city so both dimensions from the acceptance
    # criteria ("Organizations by Location supports state/city data") are
    # present in one array, without inventing a second top-level key that
    # isn't in the issue's suggested response structure.
    query = f"""
        SELECT o.state_id, s.state_name, o.city_name, COUNT(*) AS organization_count
        {BASE_FROM}
        {where_clause(conditions)}
        GROUP BY o.state_id, s.state_name, o.city_name
        ORDER BY organization_count DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    total = sum(int(r["organization_count"]) for r in rows) or 1
    return [
        {
            "state_id": r["state_id"],
            "state_name": r["state_name"],
            "city_name": r["city_name"],
            "organization_count": int(r["organization_count"]),
            "percentage": round(int(r["organization_count"]) / total * 100, 1),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Tab 2: Size & Contribution
# ---------------------------------------------------------------------------
SIZE_BUCKETS = ["small", "medium", "large"]


def fetch_organizations_by_size(cursor, conditions, params):
    # Always returns all three buckets (zero-filled), same pattern as
    # rating_distribution, per the acceptance criterion "returns Small,
    # Medium, and Large distributions".
    query = f"""
        SELECT o.org_size, COUNT(*) AS organization_count
        {BASE_FROM}
        {where_clause(conditions)}
        GROUP BY o.org_size
        ORDER BY organization_count DESC;
    """
    cursor.execute(query, params)
    found = {}
    for r in cursor.fetchall():
        size = normalize_org_size(r["org_size"])
        if size in SIZE_BUCKETS:
            found[size] = int(r["organization_count"])
    return [{"org_size": size, "organization_count": found.get(size, 0)} for size in SIZE_BUCKETS]


def fetch_collaborator_vs_contributor(cursor, conditions, params):
    # Not mutually exclusive: an org can be both a collaborator and a
    # contributor, so these two counts do not have to sum to the total.
    query = f"""
        SELECT
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_count,
            COUNT(*) FILTER (WHERE o.is_contributor IS TRUE) AS contributor_count,
            COUNT(*) AS total
        {BASE_FROM}
        {where_clause(conditions)};
    """
    cursor.execute(query, params)
    row = cursor.fetchone() or {}
    total = int(row.get("total") or 0) or 1
    collab = int(row.get("collaborator_count") or 0)
    contrib = int(row.get("contributor_count") or 0)
    return [
        {"type": "collaborator", "organization_count": collab, "percentage": round(collab / total * 100, 1)},
        {"type": "contributor", "organization_count": contrib, "percentage": round(contrib / total * 100, 1)},
    ]


# ---------------------------------------------------------------------------
# Tab 3: Ratings & Type
# ---------------------------------------------------------------------------
def fetch_rating_distribution(cursor, conditions, params):
    # NULL ratings must not break this: they are simply excluded from the
    # 1-5 buckets rather than causing an error.
    query = f"""
        SELECT o.org_rating AS rating, COUNT(*) AS organization_count
        {BASE_FROM}
        {and_extra(conditions, "o.org_rating IS NOT NULL")}
        GROUP BY o.org_rating
        ORDER BY o.org_rating;
    """
    cursor.execute(query, params)
    found = {int(r["rating"]): int(r["organization_count"]) for r in cursor.fetchall()}
    return [{"rating": star, "organization_count": found.get(star, 0)} for star in range(1, 6)]


def fetch_organization_type_distribution(cursor, conditions, params, group_by):
    trunc_unit, char_fmt = GROUP_BY_TRUNC[group_by]
    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), '{char_fmt}') AS period,
            LOWER(REPLACE(REPLACE(o.org_type, '-', '_'), ' ', '_')) AS org_type_norm,
            COUNT(*) AS count
        {BASE_FROM}
        {where_clause(conditions)}
        GROUP BY 1, 2
        ORDER BY 1 ASC;
    """
    cursor.execute(query, params)
    by_period = {}
    for r in cursor.fetchall():
        period = r["period"]
        by_period.setdefault(period, {"for_profit": 0, "non_profit": 0})
        key = r["org_type_norm"]
        if key in ("for_profit", "non_profit"):
            by_period[period][key] = int(r["count"])
    return [
        {
            "period": period,
            "for_profit": counts["for_profit"],
            "non_profit": counts["non_profit"],
            "total": counts["for_profit"] + counts["non_profit"],
        }
        for period, counts in sorted(by_period.items())
    ]


# ---------------------------------------------------------------------------
# Response assembly
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


def build_organization_dashboard(cursor, filters):
    conditions, params = build_conditions(filters)
    result = get_default_response()

    def safe(key, fn):
        try:
            result[key] = fn()
        except Exception as error:
            print(f"[organizations] {key} query failed: {error}")

    safe("summary", lambda: fetch_summary(cursor, conditions, params))
    safe("growth_trend", lambda: fetch_growth_trend(cursor, conditions, params, filters["group_by"]))
    safe("organizations_by_location", lambda: fetch_organizations_by_location(cursor, conditions, params))
    safe("organizations_by_size", lambda: fetch_organizations_by_size(cursor, conditions, params))
    safe("collaborator_vs_contributor", lambda: fetch_collaborator_vs_contributor(cursor, conditions, params))
    safe("rating_distribution", lambda: fetch_rating_distribution(cursor, conditions, params))
    safe(
        "organization_type_distribution",
        lambda: fetch_organization_type_distribution(cursor, conditions, params, filters["group_by"]),
    )
    return result


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    """Single endpoint for the whole Organization Dashboard: POST /analytics/organizations.
    All three UI tabs are populated from this one response."""
    conn = cursor = None
    default_body = get_default_response()
    try:
        request_body = parse_event_body(event)
        filters = parse_filters(request_body)
        conn = get_db_connection()
        conn.autocommit = True  # one failing metric query can't abort the others
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        body = build_organization_dashboard(cursor, filters)
        return build_response(200, body)
    except Exception as error:
        print(f"DB connection / query failed: {error}")
        return build_response(500, default_body)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    for payload in (
        {"time_filter": "30D", "group_by": "daily", "region": "ALL", "organization_type": "ALL"},
        {"time_filter": "1Y", "group_by": "monthly", "region": "ALL", "organization_type": "ALL"},
        {"time_filter": "1Y", "group_by": "monthly", "region": "California", "organization_type": "ALL"},
        {"time_filter": "1Y", "group_by": "monthly", "region": "ALL", "organization_type": "non_profit"},
    ):
        print(f"===== {payload} =====")
        print(json.dumps(json.loads(lambda_handler(payload, None)["body"]), indent=2))
        print()
