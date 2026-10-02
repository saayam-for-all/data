import json
import os

import psycopg2
from psycopg2 import errorcodes
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = os.environ.get("SAAYAM_SCHEMA", "virginia_dev_saayam_rdbms")
ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
STATES_TABLE = f"{SCHEMA_NAME}.states"

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
VALID_GROUP_BY = {"daily", "weekly", "monthly", "yearly"}
VALID_ORG_TYPES = {"non_profit", "for_profit"}


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
        },
        "body": json.dumps(body, default=str)
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
    # Plain env vars only -- no AWS Parameter Store / SSM per issue #228 constraints.
    return psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", 5432),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"]
    )


def normalize_org_type(value):
    if value is None:
        return "ALL"
    value = str(value).strip()
    if value.upper() == "ALL":
        return "ALL"
    return value.lower().replace("-", "_").replace(" ", "_")


def normalize_region(value):
    if value is None:
        return "ALL"
    value = str(value).strip()
    if value.upper() == "ALL":
        return "ALL"
    return value


def parse_filters(request_body):
    request_body = request_body or {}

    time_filter = str(request_body.get("time_filter") or "ALL").strip().upper()
    if time_filter not in VALID_TIME_FILTERS:
        raise ValueError(f"Invalid time_filter. Must be one of: {sorted(VALID_TIME_FILTERS)}")

    start_date = request_body.get("start_date") or None
    end_date = request_body.get("end_date") or None

    if time_filter == "CUSTOM" and (not start_date or not end_date):
        raise ValueError("start_date and end_date are required when time_filter is 'CUSTOM'")

    group_by = str(request_body.get("group_by") or "monthly").strip().lower()
    if group_by not in VALID_GROUP_BY:
        raise ValueError(f"Invalid group_by. Must be one of: {sorted(VALID_GROUP_BY)}")

    region = normalize_region(request_body.get("region", "ALL"))
    organization_type = normalize_org_type(request_body.get("organization_type", "ALL"))

    if organization_type != "ALL" and organization_type not in VALID_ORG_TYPES:
        raise ValueError(f"Invalid organization_type. Must be one of: ALL, {sorted(VALID_ORG_TYPES)}")

    return {
        "time_filter": time_filter,
        "start_date": start_date,
        "end_date": end_date,
        "group_by": group_by,
        "region": region,
        "organization_type": organization_type
    }


def build_date_filter(time_filter, start_date=None, end_date=None, column="created_at"):
    if time_filter == "CUSTOM" and start_date and end_date:
        return f"{column} BETWEEN %s AND %s", (start_date, end_date)
    if time_filter == "7D":
        return f"{column} >= CURRENT_DATE - INTERVAL '7 days'", ()
    if time_filter == "30D":
        return f"{column} >= CURRENT_DATE - INTERVAL '30 days'", ()
    if time_filter == "1Y":
        return f"{column} >= CURRENT_DATE - INTERVAL '1 year'", ()
    # ALL (or anything else) -> no date filter
    return "", ()


def get_grouping(group_by):
    mapping = {
        "daily": ("day", "YYYY-MM-DD"),
        "weekly": ("week", "YYYY-MM-DD"),
        "monthly": ("month", "YYYY-MM"),
        "yearly": ("year", "YYYY"),
    }
    if group_by not in mapping:
        raise ValueError(f"Invalid group_by. Must be one of: {sorted(VALID_GROUP_BY)}")
    return mapping[group_by]


def build_common_where(filters, alias="o"):
    """Builds the shared WHERE conditions (date range, region, organization_type)
    used across every organizations query. Returns (where_clause, params) where
    where_clause has no leading 'WHERE' -- callers prefix it themselves so the
    clause can also be combined with query-specific conditions via AND.
    """
    conditions = []
    params = []

    date_clause, date_params = build_date_filter(
        filters["time_filter"], filters["start_date"], filters["end_date"], column=f"{alias}.created_at"
    )
    if date_clause:
        conditions.append(date_clause)
        params.extend(date_params)

    if filters["region"] != "ALL":
        # Subquery (rather than a JOIN) so this helper stays self-contained and
        # never collides with a caller's own join/alias on the states table.
        conditions.append(f"{alias}.state_id IN (SELECT state_id FROM {STATES_TABLE} WHERE state_name = %s)")
        params.append(filters["region"])

    if filters["organization_type"] != "ALL":
        conditions.append(
            f"LOWER(REPLACE(REPLACE({alias}.org_type, '-', '_'), ' ', '_')) = %s"
        )
        params.append(filters["organization_type"])

    where_clause = " AND ".join(conditions)
    return where_clause, params


def is_undefined_column_error(exc):
    """True when `exc` is Postgres' 'column does not exist' error (42703) --
    used to let is_contributor degrade gracefully on DBs that lack it.
    """
    pgcode = getattr(exc, "pgcode", None)
    if pgcode == errorcodes.UNDEFINED_COLUMN:
        return True
    return "does not exist" in str(exc).lower()


def fetch_summary(cursor, filters):
    """Returns headline KPI counts for the filtered organizations set.
    total_contributors is best-effort: NULL when is_contributor doesn't exist
    on the target DB yet (see is_undefined_column_error).
    """
    where_clause, params = build_common_where(filters, alias="o")
    where_sql = f"WHERE {where_clause}" if where_clause else ""

    query_with_contributor = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator = TRUE) AS total_collaborators,
            COUNT(*) FILTER (WHERE o.is_contributor = TRUE) AS total_contributors,
            AVG(o.org_rating) AS average_org_rating
        FROM {ORGANIZATIONS_TABLE} o
        {where_sql}
    """

    try:
        cursor.execute(query_with_contributor, params)
        row = cursor.fetchone()
    except Exception as exc:
        if not is_undefined_column_error(exc):
            raise
        cursor.connection.rollback()
        query_without_contributor = f"""
            SELECT
                COUNT(*) AS total_organizations,
                COUNT(*) FILTER (WHERE o.is_collaborator = TRUE) AS total_collaborators,
                NULL AS total_contributors,
                AVG(o.org_rating) AS average_org_rating
            FROM {ORGANIZATIONS_TABLE} o
            {where_sql}
        """
        cursor.execute(query_without_contributor, params)
        row = cursor.fetchone()

    return {
        "total_organizations": row["total_organizations"],
        "total_collaborators": row["total_collaborators"],
        "total_contributors": row["total_contributors"],
        "average_org_rating": (
            round(float(row["average_org_rating"]), 2)
            if row["average_org_rating"] is not None else None
        ),
    }


def fetch_growth_trend(cursor, filters):
    """Returns cumulative running totals of organizations/collaborators per
    period, using a window SUM() over the per-period counts.
    """
    period_unit, date_format = get_grouping(filters["group_by"])
    where_clause, params = build_common_where(filters, alias="o")
    where_sql = f"WHERE {where_clause}" if where_clause else ""

    inner_query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC(%s, o.created_at), %s) AS period,
            DATE_TRUNC(%s, o.created_at) AS period_sort,
            COUNT(*) AS organizations_in_period,
            COUNT(*) FILTER (WHERE o.is_collaborator = TRUE) AS collaborators_in_period
        FROM {ORGANIZATIONS_TABLE} o
        {where_sql}
        GROUP BY period, period_sort
    """

    query = f"""
        SELECT
            period,
            SUM(organizations_in_period) OVER (ORDER BY period_sort) AS total_organizations,
            SUM(collaborators_in_period) OVER (ORDER BY period_sort) AS total_collaborators
        FROM ({inner_query}) AS periods
        ORDER BY period_sort
    """

    query_params = [period_unit, date_format, period_unit] + list(params)
    cursor.execute(query, query_params)
    rows = cursor.fetchall()

    # SUM() over a COUNT(*) comes back as numeric -> Decimal, which would be
    # serialized as a JSON string; cast to int so the response stays numeric.
    return [
        {
            "period": row["period"],
            "total_organizations": int(row["total_organizations"]),
            "total_collaborators": int(row["total_collaborators"]),
        }
        for row in rows
    ]


def fetch_organizations_by_location(cursor, filters):
    """Returns a state-level breakdown of the filtered organizations, with
    each state's share of the total filtered organization count.
    """
    where_clause, params = build_common_where(filters, alias="o")
    where_sql = f"WHERE {where_clause}" if where_clause else ""

    query = f"""
        SELECT
            s.state_id,
            s.state_name,
            COUNT(o.org_id) AS organization_count,
            ROUND(
                COUNT(o.org_id) * 100.0 / NULLIF(SUM(COUNT(o.org_id)) OVER (), 0), 2
            ) AS percentage
        FROM {ORGANIZATIONS_TABLE} o
        LEFT JOIN {STATES_TABLE} s ON s.state_id = o.state_id
        {where_sql}
        GROUP BY s.state_id, s.state_name
        ORDER BY organization_count DESC
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "organization_count": row["organization_count"],
            "percentage": float(row["percentage"]) if row["percentage"] is not None else 0.0,
        }
        for row in rows
    ]


def fetch_organizations_by_size(cursor, filters):
    """Returns a breakdown of the filtered organizations by org_size
    (Small/Medium/Large as stored in the DB).
    """
    where_clause, params = build_common_where(filters, alias="o")
    where_sql = f"WHERE {where_clause}" if where_clause else ""

    query = f"""
        SELECT
            o.org_size,
            COUNT(*) AS organization_count
        FROM {ORGANIZATIONS_TABLE} o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY organization_count DESC
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {"org_size": row["org_size"], "organization_count": row["organization_count"]}
        for row in rows
    ]


def fetch_collaborator_vs_contributor(cursor, filters):
    """Returns collaborator/contributor counts and their share of the total
    filtered organizations. The contributor entry is best-effort: it
    degrades to organization_count/percentage = None when is_contributor
    doesn't exist yet (see is_undefined_column_error).
    """
    where_clause, params = build_common_where(filters, alias="o")
    where_sql = f"WHERE {where_clause}" if where_clause else ""

    query_with_contributor = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator = TRUE) AS collaborator_count,
            COUNT(*) FILTER (WHERE o.is_contributor = TRUE) AS contributor_count
        FROM {ORGANIZATIONS_TABLE} o
        {where_sql}
    """

    try:
        cursor.execute(query_with_contributor, params)
        row = cursor.fetchone()
        contributor_count = row["contributor_count"]
    except Exception as exc:
        if not is_undefined_column_error(exc):
            raise
        cursor.connection.rollback()
        query_without_contributor = f"""
            SELECT
                COUNT(*) AS total_organizations,
                COUNT(*) FILTER (WHERE o.is_collaborator = TRUE) AS collaborator_count
            FROM {ORGANIZATIONS_TABLE} o
            {where_sql}
        """
        cursor.execute(query_without_contributor, params)
        row = cursor.fetchone()
        contributor_count = None

    total = row["total_organizations"]
    collaborator_count = row["collaborator_count"]

    collaborator_percentage = round(collaborator_count * 100.0 / total, 2) if total else 0.0
    if contributor_count is None:
        contributor_percentage = None
    else:
        contributor_percentage = round(contributor_count * 100.0 / total, 2) if total else 0.0

    return [
        {
            "type": "collaborator",
            "organization_count": collaborator_count,
            "percentage": collaborator_percentage,
        },
        {
            "type": "contributor",
            "organization_count": contributor_count,
            "percentage": contributor_percentage,
        },
    ]


def fetch_rating_distribution(cursor, filters):
    """Returns exactly 5 entries (ratings 1-5, in order), backfilling 0 for
    ratings with no organizations. Organizations with a NULL org_rating are
    excluded rather than causing an error.
    """
    where_clause, params = build_common_where(filters, alias="o")
    conditions = [where_clause] if where_clause else []
    conditions.append("o.org_rating IS NOT NULL")
    where_sql = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT o.org_rating AS rating, COUNT(*) AS organization_count
        FROM {ORGANIZATIONS_TABLE} o
        {where_sql}
        GROUP BY o.org_rating
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()
    counts_by_rating = {row["rating"]: row["organization_count"] for row in rows}

    return [
        {"rating": rating, "organization_count": counts_by_rating.get(rating, 0)}
        for rating in range(1, 6)
    ]


def fetch_organization_type_distribution(cursor, filters):
    """Returns cumulative running totals of for_profit/non_profit
    organizations per period (same window-function pattern as
    fetch_growth_trend). org_type is normalized the same way
    build_common_where does before bucketing.
    """
    period_unit, date_format = get_grouping(filters["group_by"])
    where_clause, params = build_common_where(filters, alias="o")
    where_sql = f"WHERE {where_clause}" if where_clause else ""

    normalized_org_type = "LOWER(REPLACE(REPLACE(o.org_type, '-', '_'), ' ', '_'))"

    inner_query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC(%s, o.created_at), %s) AS period,
            DATE_TRUNC(%s, o.created_at) AS period_sort,
            COUNT(*) FILTER (WHERE {normalized_org_type} = 'for_profit') AS for_profit_in_period,
            COUNT(*) FILTER (WHERE {normalized_org_type} = 'non_profit') AS non_profit_in_period
        FROM {ORGANIZATIONS_TABLE} o
        {where_sql}
        GROUP BY period, period_sort
    """

    query = f"""
        SELECT
            period,
            SUM(for_profit_in_period) OVER (ORDER BY period_sort) AS for_profit,
            SUM(non_profit_in_period) OVER (ORDER BY period_sort) AS non_profit
        FROM ({inner_query}) AS periods
        ORDER BY period_sort
    """

    query_params = [period_unit, date_format, period_unit] + list(params)
    cursor.execute(query, query_params)
    rows = cursor.fetchall()

    # SUM() over a COUNT(*) comes back as numeric -> Decimal, which would be
    # serialized as a JSON string; cast to int so the response stays numeric.
    return [
        {
            "period": row["period"],
            "for_profit": int(row["for_profit"]),
            "non_profit": int(row["non_profit"]),
            "total": int(row["for_profit"]) + int(row["non_profit"]),
        }
        for row in rows
    ]


def lambda_handler(event, context):
    request_body = parse_event_body(event)

    try:
        filters = parse_filters(request_body)
    except ValueError as exc:
        return build_response(400, {"error": str(exc)})

    try:
        conn = get_db_connection()
    except Exception as exc:
        print(f"organization_analytics: failed to connect to DB: {exc}")
        return build_response(500, {"error": "Failed to connect to the database"})

    cursor = conn.cursor(cursor_factory=RealDictCursor)

    response_body = {
        "summary": {
            "total_organizations": None,
            "total_collaborators": None,
            "total_contributors": None,
            "average_org_rating": None,
        },
        "growth_trend": [],
        "organizations_by_location": [],
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
        "rating_distribution": [],
        "organization_type_distribution": [],
    }

    try:
        try:
            response_body["summary"] = fetch_summary(cursor, filters)
        except Exception as exc:
            print(f"organization_analytics: fetch_summary failed: {exc}")
            conn.rollback()

        try:
            response_body["growth_trend"] = fetch_growth_trend(cursor, filters)
        except Exception as exc:
            print(f"organization_analytics: fetch_growth_trend failed: {exc}")
            conn.rollback()

        try:
            response_body["organizations_by_location"] = fetch_organizations_by_location(cursor, filters)
        except Exception as exc:
            print(f"organization_analytics: fetch_organizations_by_location failed: {exc}")
            conn.rollback()

        try:
            response_body["organizations_by_size"] = fetch_organizations_by_size(cursor, filters)
        except Exception as exc:
            print(f"organization_analytics: fetch_organizations_by_size failed: {exc}")
            conn.rollback()

        try:
            response_body["collaborator_vs_contributor"] = fetch_collaborator_vs_contributor(cursor, filters)
        except Exception as exc:
            print(f"organization_analytics: fetch_collaborator_vs_contributor failed: {exc}")
            conn.rollback()

        try:
            response_body["rating_distribution"] = fetch_rating_distribution(cursor, filters)
        except Exception as exc:
            print(f"organization_analytics: fetch_rating_distribution failed: {exc}")
            conn.rollback()

        try:
            response_body["organization_type_distribution"] = fetch_organization_type_distribution(cursor, filters)
        except Exception as exc:
            print(f"organization_analytics: fetch_organization_type_distribution failed: {exc}")
            conn.rollback()

        return build_response(200, response_body)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    # Local manual testing against a real PostgreSQL instance -- these are the
    # "Sample Payloads for Local PR Testing" from issue #228, in order. Load the
    # local data first (see scripts/load_local_data.py) and export PGHOST,
    # PGPORT, PGDATABASE, PGUSER and PGPASSWORD, then run:
    #     python data-analytics/lambda_functions/organization_analytics.py
    SAMPLE_PAYLOADS = [
        ("Standard Test", {
            "time_filter": "30D",
            "start_date": None,
            "end_date": None,
            "group_by": "daily",
            "region": "ALL",
            "organization_type": "ALL"
        }),
        ("Last 12 Months", {
            "time_filter": "1Y",
            "start_date": None,
            "end_date": None,
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "ALL"
        }),
        ("Filter by Region", {
            "time_filter": "1Y",
            "start_date": None,
            "end_date": None,
            "group_by": "monthly",
            "region": "California",
            "organization_type": "ALL"
        }),
        ("Filter by Organization Type", {
            "time_filter": "1Y",
            "start_date": None,
            "end_date": None,
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "non_profit"
        }),
        ("Custom Date Range", {
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "ALL"
        }),
    ]

    for index, (sample_name, sample_payload) in enumerate(SAMPLE_PAYLOADS, start=1):
        print("=" * 79)
        print(f"SAMPLE {index}: {sample_name}")
        print("=" * 79)
        print("Request:")
        print(json.dumps(sample_payload, indent=2))

        sample_response = lambda_handler({"body": json.dumps(sample_payload)}, None)

        print(f"\nResponse (statusCode {sample_response['statusCode']}):")
        print(json.dumps(json.loads(sample_response["body"]), indent=2))
        print()
