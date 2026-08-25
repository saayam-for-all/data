import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
STATES_TABLE = f"{SCHEMA_NAME}.states"

ALLOWED_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}

ALLOWED_GROUP_BY = {
    "daily",
    "weekly",
    "monthly",
    "yearly",
}

ALLOWED_ORGANIZATION_TYPES = {
    "ALL",
    "for_profit",
    "non_profit",
}

ORGANIZATION_TYPE_DB_MAP = {
    "for_profit": "For-profit",
    "non_profit": "Non-Profit",
}


GROUP_BY_MAP = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", "YYYY-MM-DD"),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
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

def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }

def get_request_filters(request_body):
    return {
        "time_filter": request_body.get("time_filter", "ALL"),
        "start_date": request_body.get("start_date"),
        "end_date": request_body.get("end_date"),
        "group_by": request_body.get("group_by", "monthly"),
        "region": request_body.get("region", "ALL"),
        "organization_type": request_body.get(
            "organization_type",
            "ALL",
        ),
    }

def validate_filters(filters):
    time_filter = filters["time_filter"]
    group_by = filters["group_by"]
    organization_type = filters["organization_type"]
    start_date = filters["start_date"]
    end_date = filters["end_date"]

    if time_filter not in ALLOWED_TIME_FILTERS:
        raise ValueError(
            "time_filter must be one of: "
            "7D, 30D, 1Y, ALL, CUSTOM"
        )

    if group_by not in ALLOWED_GROUP_BY:
        raise ValueError(
            "group_by must be one of: "
            "daily, weekly, monthly, yearly"
        )

    if organization_type not in ALLOWED_ORGANIZATION_TYPES:
        raise ValueError(
            "organization_type must be one of: "
            "ALL, for_profit, non_profit"
        )

    if time_filter == "CUSTOM":
        if not start_date or not end_date:
            raise ValueError(
                "start_date and end_date are required "
                "when time_filter is CUSTOM"
            )

        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
               "start_date and end_date must use YYYY-MM-DD format"
            )

        if start > end:
            raise ValueError(
              "start_date cannot be after end_date"
            )

def build_common_filters(filters):
    conditions = ["1=1"]
    params = []

    time_filter = filters["time_filter"]
    start_date = filters["start_date"]
    end_date = filters["end_date"]
    region = filters["region"]
    organization_type = filters["organization_type"]

    if time_filter == "7D":
        conditions.append(
            "o.created_at >= CURRENT_DATE - INTERVAL '7 days'"
        )

    elif time_filter == "30D":
        conditions.append(
            "o.created_at >= CURRENT_DATE - INTERVAL '30 days'"
        )

    elif time_filter == "1Y":
        conditions.append(
            "o.created_at >= CURRENT_DATE - INTERVAL '1 year'"
        )

    elif time_filter == "CUSTOM":
        conditions.append(
            "o.created_at::date BETWEEN %s AND %s"
        )
        params.extend([start_date, end_date]
        )

    if region != "ALL":
        conditions.append(
            "s.state_name = %s"
        )
        params.append(region)

    if organization_type != "ALL":
        conditions.append(
            "o.org_type = %s"
        )
        params.append(
            ORGANIZATION_TYPE_DB_MAP[organization_type]
        )

    where_clause = " WHERE " + " AND ".join(conditions)

    return where_clause, params

def fetch_summary(cursor, filters):
    where_clause, params = build_common_filters(filters)

    contributor_exists = has_is_contributor_column(cursor)

    contributor_sql = (
        """
        COUNT(o.org_id) FILTER (
            WHERE o.is_contributor = TRUE
        )
        """
        if contributor_exists
        else "0"
    )

    query = f"""
        SELECT
            COUNT(o.org_id) AS total_organizations,

            COUNT(o.org_id) FILTER (
                WHERE o.is_collaborator = TRUE
            ) AS total_collaborators,

            {contributor_sql} AS total_contributors,

            ROUND(
                AVG(o.org_rating)::numeric,
                1
            ) AS average_org_rating

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    return {
        "total_organizations": (
            int(row["total_organizations"])
            if row and row["total_organizations"] is not None
            else 0
        ),
        "total_collaborators": (
            int(row["total_collaborators"])
            if row and row["total_collaborators"] is not None
            else 0
        ),
        "total_contributors": (
            int(row["total_contributors"])
            if row and row["total_contributors"] is not None
            else 0
        ),
        "average_org_rating": (
            float(row["average_org_rating"])
            if row and row["average_org_rating"] is not None
            else 0.0
        ),
    }

def get_filter_start_date(filters):
    time_filter = filters["time_filter"]

    if time_filter == "7D":
        return "CURRENT_DATE - INTERVAL '7 days'"

    if time_filter == "30D":
        return "CURRENT_DATE - INTERVAL '30 days'"

    if time_filter == "1Y":
        return "CURRENT_DATE - INTERVAL '1 year'"

    if time_filter == "CUSTOM":
        return "%s"

    return None

def fetch_growth_baseline(cursor, filters):
    time_filter = filters["time_filter"]

    if time_filter == "ALL":
        return {
            "total_organizations": 0,
            "total_collaborators": 0,
        }

    start_expression = get_filter_start_date(filters)

    conditions = [
        f"o.created_at < {start_expression}"
    ]

    params = []

    if time_filter == "CUSTOM":
        params.append(filters["start_date"])

    if filters["region"] != "ALL":
        conditions.append("s.state_name = %s")
        params.append(filters["region"])

    if filters["organization_type"] != "ALL":
        conditions.append("o.org_type = %s")
        params.append(
            ORGANIZATION_TYPE_DB_MAP[
                filters["organization_type"]
            ]
        )

    where_clause = " WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            COUNT(o.org_id) AS total_organizations,

            COUNT(o.org_id) FILTER (
                WHERE o.is_collaborator = TRUE
            ) AS total_collaborators

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    return {
        "total_organizations": (
            int(row["total_organizations"])
            if row and row["total_organizations"] is not None
            else 0
        ),
        "total_collaborators": (
            int(row["total_collaborators"])
            if row and row["total_collaborators"] is not None
            else 0
        ),
    }

def fetch_growth_trend(cursor, filters):
    where_clause, params = build_common_filters(filters)

    group_by = filters["group_by"]
    period, date_format = GROUP_BY_MAP[group_by]

    baseline = fetch_growth_baseline(
        cursor,
        filters,
    )

    query = f"""
        WITH period_counts AS (
            SELECT
                DATE_TRUNC(
                    '{period}',
                    o.created_at
                ) AS period_start,

                COUNT(o.org_id) AS organizations_created,

                COUNT(o.org_id) FILTER (
                    WHERE o.is_collaborator = TRUE
                ) AS collaborators_created

            FROM {ORGANIZATIONS_TABLE} o

            LEFT JOIN {STATES_TABLE} s
                ON o.state_id = s.state_id

            {where_clause}

            GROUP BY
                DATE_TRUNC(
                    '{period}',
                    o.created_at
                )
        )

        SELECT
            TO_CHAR(
                period_start,
                '{date_format}'
            ) AS period,

            SUM(organizations_created)
                OVER (
                    ORDER BY period_start
                ) AS running_organizations,

            SUM(collaborators_created)
                OVER (
                    ORDER BY period_start
                ) AS running_collaborators

        FROM period_counts

        ORDER BY period_start;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "period": row["period"],

            "total_organizations":
                baseline["total_organizations"]
                + int(row["running_organizations"]),

            "total_collaborators":
                baseline["total_collaborators"]
                + int(row["running_collaborators"]),
        }
        for row in rows
    ]
def fetch_organizations_by_location(cursor, filters):
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            o.state_id,
            COALESCE(s.state_name, 'Unknown') AS state_name,
            COALESCE(o.city_name, 'Unknown') AS city_name,
            COUNT(o.org_id) AS organization_count

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        {where_clause}

        GROUP BY
            o.state_id,
            s.state_name,
            o.city_name

        ORDER BY
            organization_count DESC,
            state_name,
            city_name;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    total_organizations = sum(
        int(row["organization_count"])
        for row in rows
    )

    states = {}

    for row in rows:
        state_id = row["state_id"]
        state_name = row["state_name"]
        city_name = row["city_name"]
        count = int(row["organization_count"])

        if state_id not in states:
            states[state_id] = {
                "state_id": state_id,
                "state_name": state_name,
                "organization_count": 0,
                "percentage": 0.0,
                "cities": [],
            }

        states[state_id]["organization_count"] += count

        states[state_id]["cities"].append(
            {
                "city_name": city_name,
                "organization_count": count,
            }
        )

    for state in states.values():
        if total_organizations > 0:
            state["percentage"] = round(
                (
                    state["organization_count"]
                    / total_organizations
                )
                * 100,
                1,
            )

    return list(states.values())

def fetch_organizations_by_size(cursor, filters):
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            LOWER(o.org_size) AS org_size,
            COUNT(o.org_id) AS organization_count

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        {where_clause}

        AND LOWER(o.org_size) IN ('small', 'medium', 'large')

        GROUP BY
            LOWER(o.org_size);
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    size_counts = {
        "small": 0,
        "medium": 0,
        "large": 0,
    }

    for row in rows:
        org_size = row["org_size"]

        if org_size in size_counts:
            size_counts[org_size] = int(
                row["organization_count"]
            )

    return [
        {
            "org_size": "small",
            "organization_count": size_counts["small"],
        },
        {
            "org_size": "medium",
            "organization_count": size_counts["medium"],
        },
        {
            "org_size": "large",
            "organization_count": size_counts["large"],
        },
    ]

def fetch_collaborator_vs_contributor(cursor, filters):
    where_clause, params = build_common_filters(filters)

    contributor_exists = has_is_contributor_column(cursor)

    contributor_sql = (
        """
        COUNT(o.org_id) FILTER (
            WHERE o.is_contributor = TRUE
        )
        """
        if contributor_exists
        else "0"
    )

    query = f"""
        SELECT
            COUNT(o.org_id) FILTER (
                WHERE o.is_collaborator = TRUE
            ) AS collaborator_count,

            {contributor_sql} AS contributor_count

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    collaborator_count = (
        int(row["collaborator_count"])
        if row and row["collaborator_count"] is not None
        else 0
    )

    contributor_count = (
        int(row["contributor_count"])
        if row and row["contributor_count"] is not None
        else 0
    )

    total = collaborator_count + contributor_count

    collaborator_percentage = (
        round((collaborator_count / total) * 100, 1)
        if total > 0
        else 0.0
    )

    contributor_percentage = (
        round((contributor_count / total) * 100, 1)
        if total > 0
        else 0.0
    )

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
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            o.org_rating AS rating,
            COUNT(o.org_id) AS organization_count

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        {where_clause}

        AND o.org_rating BETWEEN 1 AND 5

        GROUP BY
            o.org_rating

        ORDER BY
            o.org_rating;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    rating_counts = {
        1: 0,
        2: 0,
        3: 0,
        4: 0,
        5: 0,
    }

    for row in rows:
        rating = int(row["rating"])

        if rating in rating_counts:
            rating_counts[rating] = int(
                row["organization_count"]
            )

    return [
        {
            "rating": rating,
            "organization_count": rating_counts[rating],
        }
        for rating in range(1, 6)
    ]

def fetch_org_type_baseline(cursor, filters):
    time_filter = filters["time_filter"]

    if time_filter == "ALL":
        return {
            "for_profit": 0,
            "non_profit": 0,
        }

    start_expression = get_filter_start_date(filters)

    conditions = [
        f"o.created_at < {start_expression}"
    ]

    params = []

    if time_filter == "CUSTOM":
        params.append(filters["start_date"])

    if filters["region"] != "ALL":
        conditions.append("s.state_name = %s")
        params.append(filters["region"])

    if filters["organization_type"] != "ALL":
        conditions.append("o.org_type = %s")
        params.append(
            ORGANIZATION_TYPE_DB_MAP[
                filters["organization_type"]
            ]
        )

    where_clause = " WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            COUNT(o.org_id) FILTER (
                WHERE LOWER(o.org_type) = 'for-profit'
            ) AS for_profit,

            COUNT(o.org_id) FILTER (
                WHERE LOWER(o.org_type) = 'non-profit'
            ) AS non_profit

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    return {
        "for_profit": (
            int(row["for_profit"])
            if row and row["for_profit"] is not None
            else 0
        ),
        "non_profit": (
            int(row["non_profit"])
            if row and row["non_profit"] is not None
            else 0
        ),
    }

def fetch_organization_type_distribution(cursor, filters):
    where_clause, params = build_common_filters(filters)

    group_by = filters["group_by"]
    period, date_format = GROUP_BY_MAP[group_by]

    baseline = fetch_org_type_baseline(
        cursor,
        filters,
    )

    query = f"""
        WITH period_counts AS (
            SELECT
                DATE_TRUNC(
                    '{period}',
                    o.created_at
                ) AS period_start,

                COUNT(o.org_id) FILTER (
                    WHERE LOWER(o.org_type) = 'for-profit'
                ) AS for_profit_created,

                COUNT(o.org_id) FILTER (
                    WHERE LOWER(o.org_type) = 'non-profit'
                ) AS non_profit_created

            FROM {ORGANIZATIONS_TABLE} o

            LEFT JOIN {STATES_TABLE} s
                ON o.state_id = s.state_id

            {where_clause}

            GROUP BY
                DATE_TRUNC(
                    '{period}',
                    o.created_at
                )
        )

        SELECT
            TO_CHAR(
                period_start,
                '{date_format}'
            ) AS period,

            SUM(for_profit_created)
                OVER (
                    ORDER BY period_start
                ) AS running_for_profit,

            SUM(non_profit_created)
                OVER (
                    ORDER BY period_start
                ) AS running_non_profit

        FROM period_counts

        ORDER BY period_start;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    result = []

    for row in rows:
        for_profit = (
            baseline["for_profit"]
            + int(row["running_for_profit"])
        )

        non_profit = (
            baseline["non_profit"]
            + int(row["running_non_profit"])
        )

        result.append(
            {
                "period": row["period"],
                "for_profit": for_profit,
                "non_profit": non_profit,
                "total": for_profit + non_profit,
            }
        )

    return result

def has_is_contributor_column(cursor):
    query = """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
              AND column_name = %s
        ) AS column_exists;
    """

    cursor.execute(
        query,
        (
            SCHEMA_NAME,
            "organizations",
            "is_contributor",
        ),
    )

    row = cursor.fetchone()

    return bool(row["column_exists"]) if row else False

def lambda_handler(event, context):
    conn = None
    cursor = None

    try:
        request_body = parse_event_body(event)

        filters = get_request_filters(request_body)

        validate_filters(filters)

        conn = get_db_connection()

        cursor = conn.cursor(
            cursor_factory=RealDictCursor
        )

        response_data = {
            "summary": fetch_summary(
                cursor,
                filters,
            ),
            "growth_trend": fetch_growth_trend(
                cursor,
                filters,
            ),
            "organizations_by_location": fetch_organizations_by_location(
                cursor,
                filters,
            ),
            "organizations_by_size": fetch_organizations_by_size(
                cursor,
                filters,
            ),
            "collaborator_vs_contributor": fetch_collaborator_vs_contributor(
                cursor,
                filters,
            ),
            "rating_distribution": fetch_rating_distribution(
                cursor,
                filters,
            ),
            "organization_type_distribution": fetch_organization_type_distribution(
                cursor,
                filters,
            ),
        }

        return build_response(
            200,
            response_data,
        )

    except ValueError as e:
        return build_response(
            400,
            {
                "error": str(e),
            },
        )

    except Exception as e:
        print(
            "Organization analytics error:",
            str(e),
        )

        return build_response(
            500,
            {
                "error": "Unable to fetch organization analytics"
            },
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()



def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        database=os.environ.get("PGDATABASE"),
        user=os.environ.get("PGUSER"),
        password=os.environ.get("PGPASSWORD"),
    )

