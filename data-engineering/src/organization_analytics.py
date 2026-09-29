"""Organization analytics endpoint and query helpers for local PostgreSQL testing."""

from collections import Counter, defaultdict
from datetime import date
import os
from typing import Any

from flask import Blueprint, jsonify, request

try:
    import psycopg2
except ImportError:
    psycopg2 = None


organization_analytics = Blueprint("organization_analytics", __name__)

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
VALID_GROUPINGS = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", 'IYYY-"W"IW'),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}
VALID_ORG_TYPES = {"ALL", "for_profit", "non_profit"}


def default_response() -> dict[str, Any]:
    return {
        "summary": {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0.0,
        },
        "growth_trend": [],
        "organizations_by_location": [],
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
        "rating_distribution": [],
        "organization_type_distribution": [],
    }


def parse_filters(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    time_filter = str(payload.get("time_filter", "ALL")).upper()
    group_by = str(payload.get("group_by", "monthly")).lower()
    region = payload.get("region", "ALL") or "ALL"
    organization_type = payload.get("organization_type", "ALL") or "ALL"
    organization_type = str(organization_type).lower() if organization_type != "ALL" else "ALL"

    if time_filter not in VALID_TIME_FILTERS:
        raise ValueError("time_filter must be one of: 7D, 30D, 1Y, ALL, CUSTOM")
    if group_by not in VALID_GROUPINGS:
        raise ValueError("group_by must be one of: daily, weekly, monthly, yearly")
    if organization_type not in VALID_ORG_TYPES:
        raise ValueError("organization_type must be ALL, for_profit, or non_profit")

    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    if time_filter == "CUSTOM":
        if not start_date or not end_date:
            raise ValueError("start_date and end_date are required for CUSTOM")
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except (TypeError, ValueError) as error:
            raise ValueError("start_date and end_date must use YYYY-MM-DD") from error
        if start > end:
            raise ValueError("start_date must be on or before end_date")

    return {
        "time_filter": time_filter,
        "group_by": group_by,
        "region": region,
        "organization_type": organization_type,
        "start_date": start_date,
        "end_date": end_date,
    }


def build_organization_query(filters: dict[str, Any], include_contributor: bool = True) -> tuple[str, tuple[Any, ...]]:
    where = ["o.created_at IS NOT NULL"]
    params: list[Any] = []
    time_filter = filters["time_filter"]

    if time_filter == "7D":
        where.append("o.created_at >= CURRENT_DATE - INTERVAL '7 days'")
    elif time_filter == "30D":
        where.append("o.created_at >= CURRENT_DATE - INTERVAL '30 days'")
    elif time_filter == "1Y":
        where.append("o.created_at >= CURRENT_DATE - INTERVAL '1 year'")
    elif time_filter == "CUSTOM":
        where.append("o.created_at::date BETWEEN %s AND %s")
        params.extend((filters["start_date"], filters["end_date"]))

    if filters["region"] != "ALL":
        where.append("(s.state_name = %s OR o.state_id = %s OR o.city_name = %s)")
        params.extend((filters["region"], filters["region"], filters["region"]))
    if filters["organization_type"] != "ALL":
        where.append("LOWER(REPLACE(o.org_type, '-', '_')) = %s")
        params.append(filters["organization_type"])

    contributor_expression = "o.is_contributor" if include_contributor else "FALSE"
    query = f"""
        SELECT o.org_id, o.city_name, o.state_id, s.state_name, o.org_size,
               o.org_rating, o.is_collaborator, {contributor_expression} AS is_contributor,
               o.org_type, o.created_at
        FROM virginia_dev_saayam_rdbms.organizations AS o
        LEFT JOIN virginia_dev_saayam_rdbms.states AS s ON s.state_id = o.state_id
        WHERE {' AND '.join(where)}
        ORDER BY o.created_at, o.org_id
    """
    return query, tuple(params)


def fetch_organization_rows(cursor: Any, filters: dict[str, Any]) -> list[Any]:
    query, params = build_organization_query(filters)
    try:
        cursor.execute(query, params)
    except Exception as error:
        if "is_contributor" not in str(error).lower():
            raise
        query, params = build_organization_query(filters, include_contributor=False)
        cursor.execute(query, params)
    return cursor.fetchall()


def row_value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, dict) else row[index]


def normalize_type(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return "non_profit" if normalized == "non_profit" else "for_profit"


def period_value(created_at: Any, group_by: str) -> str:
    timestamp = created_at.date() if hasattr(created_at, "date") else created_at
    if group_by == "yearly":
        return f"{timestamp.year:04d}"
    if group_by == "monthly":
        return f"{timestamp.year:04d}-{timestamp.month:02d}"
    if group_by == "weekly":
        iso = timestamp.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"
    return timestamp.isoformat()


def build_analytics(rows: list[Any], group_by: str = "monthly") -> dict[str, Any]:
    response = default_response()
    total = len(rows)
    if not total:
        return response

    ratings = [row_value(row, "org_rating", 5) for row in rows if row_value(row, "org_rating", 5) is not None]
    response["summary"] = {
        "total_organizations": total,
        "total_collaborators": sum(bool(row_value(row, "is_collaborator", 6)) for row in rows),
        "total_contributors": sum(bool(row_value(row, "is_contributor", 7)) for row in rows),
        "average_org_rating": round(sum(ratings) / len(ratings), 2) if ratings else 0.0,
    }

    trends: dict[str, dict[str, int]] = defaultdict(lambda: {"total_organizations": 0, "total_collaborators": 0})
    locations: Counter[tuple[Any, Any]] = Counter()
    sizes: Counter[str] = Counter()
    ratings_count: Counter[int] = Counter()
    types: dict[str, dict[str, int]] = defaultdict(lambda: {"for_profit": 0, "non_profit": 0})
    for row in rows:
        period = period_value(row_value(row, "created_at", 9), group_by)
        trends[period]["total_organizations"] += 1
        trends[period]["total_collaborators"] += bool(row_value(row, "is_collaborator", 6))
        locations[(row_value(row, "state_id", 2), row_value(row, "state_name", 3))] += 1
        sizes[str(row_value(row, "org_size", 4) or "unknown").lower()] += 1
        rating = row_value(row, "org_rating", 5)
        if rating is not None and 1 <= int(rating) <= 5:
            ratings_count[int(rating)] += 1
        types[period][normalize_type(row_value(row, "org_type", 8))] += 1

    response["growth_trend"] = [{"period": period, **values} for period, values in sorted(trends.items())]
    response["organizations_by_location"] = [
        {"state_id": state_id, "state_name": state_name or state_id, "organization_count": count, "percentage": round(count / total * 100, 2)}
        for (state_id, state_name), count in locations.most_common()
    ]
    response["organizations_by_size"] = [
        {"org_size": size, "organization_count": sizes.get(size, 0)} for size in ("small", "medium", "large")
    ]
    collaborator_count = response["summary"]["total_collaborators"]
    contributor_count = response["summary"]["total_contributors"]
    response["collaborator_vs_contributor"] = [
        {"type": "collaborator", "organization_count": collaborator_count, "percentage": round(collaborator_count / total * 100, 2)},
        {"type": "contributor", "organization_count": contributor_count, "percentage": round(contributor_count / total * 100, 2)},
    ]
    response["rating_distribution"] = [{"rating": rating, "organization_count": ratings_count.get(rating, 0)} for rating in range(1, 6)]
    response["organization_type_distribution"] = [
        {"period": period, **values, "total": values["for_profit"] + values["non_profit"]}
        for period, values in sorted(types.items())
    ]
    return response


def get_db_connection() -> Any:
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required for PostgreSQL organization analytics")
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "saayam"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


@organization_analytics.post("/analytics/organizations")
def get_organization_analytics():
    try:
        filters = parse_filters(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        rows = fetch_organization_rows(cursor, filters)
        return jsonify(build_analytics(rows, filters["group_by"])), 200
    except Exception as error:
        print(f"Organization analytics query failed: {error}")
        return jsonify(default_response()), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()