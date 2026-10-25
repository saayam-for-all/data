import json
import os
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": body
    }
def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        database=os.environ.get("DB_NAME", "saayam_local"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        port=os.environ.get("DB_PORT", "5432"),
    )
def get_grouping(group_by):
    mapping = {
        "daily": ("day", "YYYY-MM-DD"),
        "weekly": ("week", "IYYY-IW"),
        "monthly": ("month", "YYYY-MM"),
        "yearly": ("year", "YYYY"),
    }
    return mapping.get(group_by, ("month", "YYYY-MM"))


def build_date_filter(time_filter, start_date=None, end_date=None):
    if time_filter == "CUSTOM" and start_date and end_date:
        return "o.created_at BETWEEN %s AND %s", (start_date, end_date)
    elif time_filter == "7D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '7 days'", ()
    elif time_filter == "30D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '30 days'", ()
    elif time_filter == "1Y":
        return "o.created_at >= CURRENT_DATE - INTERVAL '1 year'", ()
    else:
        return "", ()
def build_filter_clauses(region, organization_type):
    clauses = []
    params = []

    if region and region != "ALL":
        clauses.append("s.state_name = %s")
        params.append(region)

    if organization_type and organization_type != "ALL":
        clauses.append("o.org_type = %s")
        params.append(organization_type)

    return clauses, params


def build_where(time_filter, start_date, end_date, region, organization_type):
    date_clause, date_params = build_date_filter(time_filter, start_date, end_date)
    extra_clauses, extra_params = build_filter_clauses(region, organization_type)

    all_clauses = ([date_clause] if date_clause else []) + extra_clauses
    all_params = list(date_params) + extra_params

    where_sql = f"WHERE {' AND '.join(all_clauses)}" if all_clauses else ""
    return where_sql, all_params
def safe_round(value, digits=1):
    return round(float(value), digits) if value is not None else 0.0


def safe_pct(part, total, digits=1):
    if not total:
        return 0.0
    return safe_round((part / total) * 100, digits)

def fetch_summary(cursor, where_sql, params):
    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators,
            COUNT(*) FILTER (WHERE o.is_contributor IS TRUE) AS total_contributors,
            ROUND(AVG(o.org_rating)::numeric, 1) AS average_org_rating
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where_sql};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return {
        "total_organizations": int(row["total_organizations"]),
        "total_collaborators": int(row["total_collaborators"]),
        "total_contributors": int(row["total_contributors"]),
        "average_org_rating": safe_round(row["average_org_rating"]),
    }


def fetch_growth_trend(cursor, where_sql, params, group_by):
    period, date_format = get_grouping(group_by)
    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where_sql}
        GROUP BY 1
        ORDER BY 1;
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

def fetch_organizations_by_location(cursor, where_sql, params):
    query = f"""
        SELECT o.state_id AS state_id, s.state_name AS state_name, COUNT(*) AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where_sql}
        GROUP BY o.state_id, s.state_name
        ORDER BY organization_count DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    total = sum(int(r["organization_count"]) for r in rows)
    return [
        {
            "state_id": r["state_id"],
            "state_name": r["state_name"],
            "organization_count": int(r["organization_count"]),
            "percentage": safe_pct(int(r["organization_count"]), total),
        }
        for r in rows
    ]


def fetch_organizations_by_size(cursor, where_sql, params):
    query = f"""
        SELECT o.org_size AS org_size, COUNT(*) AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where_sql}
        GROUP BY o.org_size
        ORDER BY o.org_size;
    """
    cursor.execute(query, params)
    return [
        {"org_size": r["org_size"], "organization_count": int(r["organization_count"])}
        for r in cursor.fetchall()
    ]

def fetch_collaborator_vs_contributor(cursor, where_sql, params):
    query = f"""
        SELECT
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_count,
            COUNT(*) FILTER (WHERE o.is_contributor IS TRUE) AS contributor_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where_sql};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    collab = int(row["collaborator_count"])
    contrib = int(row["contributor_count"])
    total = collab + contrib
    return [
        {"type": "collaborator", "organization_count": collab, "percentage": safe_pct(collab, total)},
        {"type": "contributor", "organization_count": contrib, "percentage": safe_pct(contrib, total)},
    ]


def fetch_rating_distribution(cursor, where_sql, params):
    clauses = "AND" if where_sql else "WHERE"
    query = f"""
        SELECT o.org_rating AS rating, COUNT(*) AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where_sql}
        {clauses} o.org_rating IS NOT NULL
        GROUP BY o.org_rating
        ORDER BY o.org_rating;
    """
    cursor.execute(query, params)
    results_by_rating = {r["rating"]: int(r["organization_count"]) for r in cursor.fetchall()}
    return [{"rating": i, "organization_count": results_by_rating.get(i, 0)} for i in range(1, 6)]

def fetch_organization_type_distribution(cursor, where_sql, params, group_by):
    period, date_format = get_grouping(group_by)
    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
            COUNT(*) FILTER (WHERE o.org_type = 'for_profit') AS for_profit,
            COUNT(*) FILTER (WHERE o.org_type = 'non_profit') AS non_profit
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where_sql}
        GROUP BY 1
        ORDER BY 1;
    """
    cursor.execute(query, params)
    results = []
    for r in cursor.fetchall():
        fp = int(r["for_profit"])
        np = int(r["non_profit"])
        results.append({"period": r["period"], "for_profit": fp, "non_profit": np, "total": fp + np})
    return results


def build_org_dashboard_response(cursor, time_filter, start_date, end_date, group_by, region, organization_type):
    where_sql, params = build_where(time_filter, start_date, end_date, region, organization_type)

    return {
        "summary": fetch_summary(cursor, where_sql, params),
        "growth_trend": fetch_growth_trend(cursor, where_sql, params, group_by),
        "organizations_by_location": fetch_organizations_by_location(cursor, where_sql, params),
        "organizations_by_size": fetch_organizations_by_size(cursor, where_sql, params),
        "collaborator_vs_contributor": fetch_collaborator_vs_contributor(cursor, where_sql, params),
        "rating_distribution": fetch_rating_distribution(cursor, where_sql, params),
        "organization_type_distribution": fetch_organization_type_distribution(cursor, where_sql, params, group_by),
    }


def parse_event_body(event):
    if isinstance(event, dict) and "body" in event and isinstance(event["body"], str):
        try:
            return json.loads(event["body"])
        except (TypeError, ValueError):
            return {}
    return event or {}


def validate_filters(body):
    valid_time_filters = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
    time_filter = body.get("time_filter", "30D")
    if time_filter not in valid_time_filters:
        return f"Invalid time_filter '{time_filter}'. Must be one of {sorted(valid_time_filters)}."

    if time_filter == "CUSTOM":
        if not body.get("start_date") or not body.get("end_date"):
            return "CUSTOM time_filter requires both start_date and end_date."

    valid_group_by = {"daily", "weekly", "monthly", "yearly"}
    group_by = body.get("group_by", "daily")
    if group_by not in valid_group_by:
        return f"Invalid group_by '{group_by}'. Must be one of {sorted(valid_group_by)}."

    return None


def lambda_handler(event, context):
    conn = None
    cursor = None

    body = parse_event_body(event)

    validation_error = validate_filters(body)
    if validation_error:
        return build_response(400, {"error": validation_error})

    time_filter = body.get("time_filter", "30D")
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    group_by = body.get("group_by", "daily")
    region = body.get("region", "ALL")
    organization_type = body.get("organization_type", "ALL")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        response_body = build_org_dashboard_response(
            cursor, time_filter, start_date, end_date, group_by, region, organization_type
        )

        return build_response(200, response_body)

    except psycopg2.Error as e:
        print(f"organization_analytics DB error: {e}")
        return build_response(500, {"error": "Database error occurred", "details": str(e)})

    except Exception as e:
        print(f"organization_analytics failed: {e}")
        return build_response(500, {"error": str(e)})

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    result = lambda_handler({"time_filter": "ALL", "group_by": "monthly"}, None)
    print(json.dumps(result, indent=2, default=str))