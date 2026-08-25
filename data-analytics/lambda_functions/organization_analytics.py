import json
import os
from datetime import datetime

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor


load_dotenv("data-analytics/.env")

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
STATES_TABLE = f"{SCHEMA_NAME}.states"


VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}

VALID_GROUP_BY = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", "YYYY-MM-DD"),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}


def get_db_connection():
    """
    Local PostgreSQL connection only.
    No AWS Parameter Store is used.
    """
    return psycopg2.connect(
        host=os.getenv("host"),
        database=os.getenv("dbname"),
        user=os.getenv("user"),
        password=os.getenv("password"),
        port=os.getenv("port", "5432"),
    )


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
        "body": json.dumps(body, default=str),
    }


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


def validate_request(payload):
    time_filter = str(
        payload.get("time_filter", "30D")
    ).upper()

    group_by = str(
        payload.get("group_by", "daily")
    ).lower()

    organization_type = str(
        payload.get("organization_type", "ALL")
    ).lower()

    start_date = payload.get("start_date")
    end_date = payload.get("end_date")

    if time_filter not in VALID_TIME_FILTERS:
        return (
            "Invalid time_filter. "
            "Use 7D, 30D, 1Y, ALL, or CUSTOM."
        )

    if group_by not in VALID_GROUP_BY:
        return (
            "Invalid group_by. "
            "Use daily, weekly, monthly, or yearly."
        )

    if organization_type not in {
        "all",
        "for_profit",
        "non_profit",
    }:
        return (
            "Invalid organization_type. "
            "Use ALL, for_profit, or non_profit."
        )

    if time_filter == "CUSTOM":
        if not start_date or not end_date:
            return (
                "For CUSTOM time_filter, both start_date "
                "and end_date are required."
            )

        try:
            parsed_start = datetime.strptime(
                start_date,
                "%Y-%m-%d",
            )

            parsed_end = datetime.strptime(
                end_date,
                "%Y-%m-%d",
            )

            if parsed_start > parsed_end:
                return "start_date cannot be after end_date."

        except ValueError:
            return "Dates must use YYYY-MM-DD format."

    return None


def normalize_org_type_sql(alias="o"):
    return f"""
        LOWER(
            REPLACE(
                REPLACE(
                    COALESCE({alias}.org_type, ''),
                    '-',
                    '_'
                ),
                ' ',
                '_'
            )
        )
    """


def build_common_filters(
    time_filter,
    region="ALL",
    organization_type="ALL",
    start_date=None,
    end_date=None,
    alias="o",
):
    conditions = []
    params = []

    time_filter = str(time_filter).upper()
    organization_type = str(
        organization_type
    ).lower()

    if time_filter == "7D":
        conditions.append(
            f"{alias}.created_at >= "
            "CURRENT_DATE - INTERVAL '7 days'"
        )

    elif time_filter == "30D":
        conditions.append(
            f"{alias}.created_at >= "
            "CURRENT_DATE - INTERVAL '30 days'"
        )

    elif time_filter == "1Y":
        conditions.append(
            f"{alias}.created_at >= "
            "CURRENT_DATE - INTERVAL '1 year'"
        )

    elif time_filter == "CUSTOM":
        conditions.append(
            f"{alias}.created_at::date BETWEEN %s AND %s"
        )

        params.extend(
            [
                start_date,
                end_date,
            ]
        )

    if region and str(region).upper() != "ALL":
        conditions.append(
            """
            (
                UPPER(COALESCE(s.state_name, '')) = UPPER(%s)
                OR UPPER(COALESCE(o.state_id, '')) = UPPER(%s)
            )
            """
        )

        params.extend(
            [
                region,
                region,
            ]
        )

    if organization_type != "all":
        conditions.append(
            f"{normalize_org_type_sql(alias)} = %s"
        )

        params.append(
            organization_type
        )

    where_clause = ""

    if conditions:
        where_clause = (
            " AND "
            + " AND ".join(conditions)
        )

    return where_clause, params


def fetch_summary(
    cursor,
    time_filter,
    region,
    organization_type,
    start_date=None,
    end_date=None,
):
    where_clause, params = build_common_filters(
        time_filter,
        region,
        organization_type,
        start_date,
        end_date,
    )

    query = f"""
        SELECT
            COUNT(o.org_id) AS total_organizations,

            COUNT(*) FILTER (
                WHERE COALESCE(
                    o.is_collaborator,
                    FALSE
                ) = TRUE
            ) AS total_collaborators,

            COUNT(*) FILTER (
                WHERE COALESCE(
                    o.is_contributor,
                    FALSE
                ) = TRUE
            ) AS total_contributors,

            ROUND(
                AVG(o.org_rating)::numeric,
                1
            ) AS average_org_rating

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        WHERE 1=1
        {where_clause};
    """

    cursor.execute(
        query,
        params,
    )

    row = cursor.fetchone()

    if not row:
        return {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0,
        }

    return {
        "total_organizations": int(
            row["total_organizations"] or 0
        ),
        "total_collaborators": int(
            row["total_collaborators"] or 0
        ),
        "total_contributors": int(
            row["total_contributors"] or 0
        ),
        "average_org_rating": float(
            row["average_org_rating"] or 0
        ),
    }


def fetch_growth_trend(
    cursor,
    time_filter,
    group_by,
    region,
    organization_type,
    start_date=None,
    end_date=None,
):
    period, date_format = VALID_GROUP_BY[
        group_by
    ]

    where_clause, params = build_common_filters(
        time_filter,
        region,
        organization_type,
        start_date,
        end_date,
    )

    query = f"""
        WITH period_counts AS (
            SELECT
                DATE_TRUNC(
                    '{period}',
                    o.created_at
                ) AS period_date,

                COUNT(
                    o.org_id
                ) AS new_organizations,

                COUNT(*) FILTER (
                    WHERE COALESCE(
                        o.is_collaborator,
                        FALSE
                    ) = TRUE
                ) AS new_collaborators

            FROM {ORGANIZATIONS_TABLE} o

            LEFT JOIN {STATES_TABLE} s
                ON o.state_id = s.state_id

            WHERE o.created_at IS NOT NULL
            {where_clause}

            GROUP BY 1
        )

        SELECT
            TO_CHAR(
                period_date,
                '{date_format}'
            ) AS period,

            SUM(
                new_organizations
            ) OVER (
                ORDER BY period_date
            ) AS total_organizations,

            SUM(
                new_collaborators
            ) OVER (
                ORDER BY period_date
            ) AS total_collaborators

        FROM period_counts

        ORDER BY period_date;
    """

    cursor.execute(
        query,
        params,
    )

    rows = cursor.fetchall()

    return [
        {
            "period": row["period"],
            "total_organizations": int(
                row["total_organizations"] or 0
            ),
            "total_collaborators": int(
                row["total_collaborators"] or 0
            ),
        }
        for row in rows
    ]


def fetch_organizations_by_location(
    cursor,
    time_filter,
    region,
    organization_type,
    start_date=None,
    end_date=None,
):
    where_clause, params = build_common_filters(
        time_filter,
        region,
        organization_type,
        start_date,
        end_date,
    )

    query = f"""
        WITH location_counts AS (
            SELECT
                COALESCE(
                    o.state_id,
                    'Unknown'
                ) AS state_id,

                COALESCE(
                    s.state_name,
                    'Unknown'
                ) AS state_name,

                COALESCE(
                    o.city_name,
                    'Unknown'
                ) AS city_name,

                COUNT(
                    o.org_id
                ) AS organization_count

            FROM {ORGANIZATIONS_TABLE} o

            LEFT JOIN {STATES_TABLE} s
                ON o.state_id = s.state_id

            WHERE 1=1
            {where_clause}

            GROUP BY
                COALESCE(
                    o.state_id,
                    'Unknown'
                ),
                COALESCE(
                    s.state_name,
                    'Unknown'
                ),
                COALESCE(
                    o.city_name,
                    'Unknown'
                )
        ),

        totals AS (
            SELECT
                SUM(
                    organization_count
                ) AS total_count
            FROM location_counts
        )

        SELECT
            lc.state_id,
            lc.state_name,
            lc.city_name,
            lc.organization_count,

            CASE
                WHEN totals.total_count > 0
                THEN ROUND(
                    (
                        lc.organization_count::numeric
                        / totals.total_count
                    ) * 100,
                    1
                )
                ELSE 0
            END AS percentage

        FROM location_counts lc

        CROSS JOIN totals

        ORDER BY
            lc.organization_count DESC,
            lc.state_name,
            lc.city_name;
    """

    cursor.execute(
        query,
        params,
    )

    rows = cursor.fetchall()

    return [
        {
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "city_name": row["city_name"],
            "organization_count": int(
                row["organization_count"] or 0
            ),
            "percentage": float(
                row["percentage"] or 0
            ),
        }
        for row in rows
    ]


def fetch_organizations_by_size(
    cursor,
    time_filter,
    region,
    organization_type,
    start_date=None,
    end_date=None,
):
    where_clause, params = build_common_filters(
        time_filter,
        region,
        organization_type,
        start_date,
        end_date,
    )

    query = f"""
        SELECT
            LOWER(
                o.org_size
            ) AS org_size,

            COUNT(
                o.org_id
            ) AS organization_count

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        WHERE
            LOWER(
                COALESCE(
                    o.org_size,
                    ''
                )
            ) IN (
                'small',
                'medium',
                'large'
            )

        {where_clause}

        GROUP BY
            LOWER(
                o.org_size
            );
    """

    cursor.execute(
        query,
        params,
    )

    rows = cursor.fetchall()

    result_map = {
        "small": 0,
        "medium": 0,
        "large": 0,
    }

    for row in rows:
        result_map[
            row["org_size"]
        ] = int(
            row["organization_count"] or 0
        )

    return [
        {
            "org_size": "small",
            "organization_count": result_map[
                "small"
            ],
        },
        {
            "org_size": "medium",
            "organization_count": result_map[
                "medium"
            ],
        },
        {
            "org_size": "large",
            "organization_count": result_map[
                "large"
            ],
        },
    ]


def fetch_collaborator_vs_contributor(
    cursor,
    time_filter,
    region,
    organization_type,
    start_date=None,
    end_date=None,
):
    where_clause, params = build_common_filters(
        time_filter,
        region,
        organization_type,
        start_date,
        end_date,
    )

    query = f"""
        SELECT
            COUNT(
                o.org_id
            ) AS total_organizations,

            COUNT(*) FILTER (
                WHERE COALESCE(
                    o.is_collaborator,
                    FALSE
                ) = TRUE
            ) AS collaborator_count,

            COUNT(*) FILTER (
                WHERE COALESCE(
                    o.is_contributor,
                    FALSE
                ) = TRUE
            ) AS contributor_count

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        WHERE 1=1
        {where_clause};
    """

    cursor.execute(
        query,
        params,
    )

    row = cursor.fetchone()

    total_organizations = int(
        row["total_organizations"] or 0
    )

    collaborator_count = int(
        row["collaborator_count"] or 0
    )

    contributor_count = int(
        row["contributor_count"] or 0
    )

    if total_organizations == 0:
        collaborator_percentage = 0
        contributor_percentage = 0

    else:
        collaborator_percentage = round(
            (
                collaborator_count
                / total_organizations
            )
            * 100,
            1,
        )

        contributor_percentage = round(
            (
                contributor_count
                / total_organizations
            )
            * 100,
            1,
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


def fetch_rating_distribution(
    cursor,
    time_filter,
    region,
    organization_type,
    start_date=None,
    end_date=None,
):
    where_clause, params = build_common_filters(
        time_filter,
        region,
        organization_type,
        start_date,
        end_date,
    )

    query = f"""
        SELECT
            o.org_rating AS rating,

            COUNT(
                o.org_id
            ) AS organization_count

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        WHERE
            o.org_rating IS NOT NULL

            AND o.org_rating BETWEEN 1 AND 5

        {where_clause}

        GROUP BY
            o.org_rating

        ORDER BY
            o.org_rating;
    """

    cursor.execute(
        query,
        params,
    )

    rows = cursor.fetchall()

    result_map = {
        1: 0,
        2: 0,
        3: 0,
        4: 0,
        5: 0,
    }

    for row in rows:
        rating = int(
            row["rating"]
        )

        if rating in result_map:
            result_map[
                rating
            ] = int(
                row["organization_count"]
                or 0
            )

    return [
        {
            "rating": rating,
            "organization_count": result_map[
                rating
            ],
        }
        for rating in range(
            1,
            6,
        )
    ]


def fetch_organization_type_distribution(
    cursor,
    time_filter,
    group_by,
    region,
    organization_type,
    start_date=None,
    end_date=None,
):
    period, date_format = VALID_GROUP_BY[
        group_by
    ]

    where_clause, params = build_common_filters(
        time_filter,
        region,
        organization_type,
        start_date,
        end_date,
    )

    normalized_type = normalize_org_type_sql(
        "o"
    )

    query = f"""
        SELECT
            TO_CHAR(
                DATE_TRUNC(
                    '{period}',
                    o.created_at
                ),
                '{date_format}'
            ) AS period,

            COUNT(*) FILTER (
                WHERE
                    {normalized_type}
                    = 'for_profit'
            ) AS for_profit,

            COUNT(*) FILTER (
                WHERE
                    {normalized_type}
                    = 'non_profit'
            ) AS non_profit

        FROM {ORGANIZATIONS_TABLE} o

        LEFT JOIN {STATES_TABLE} s
            ON o.state_id = s.state_id

        WHERE
            o.created_at IS NOT NULL

        {where_clause}

        GROUP BY 1

        ORDER BY 1 ASC;
    """

    cursor.execute(
        query,
        params,
    )

    rows = cursor.fetchall()

    result = []

    for row in rows:
        for_profit = int(
            row["for_profit"] or 0
        )

        non_profit = int(
            row["non_profit"] or 0
        )

        result.append(
            {
                "period": row["period"],
                "for_profit": for_profit,
                "non_profit": non_profit,
                "total": (
                    for_profit
                    + non_profit
                ),
            }
        )

    return result


def lambda_handler(
    event,
    context,
):
    response_body = get_default_response()

    conn = None
    cursor = None

    try:
        payload = parse_event_body(
            event
        )

        validation_error = validate_request(
            payload
        )

        if validation_error:
            return build_response(
                400,
                {
                    "error": validation_error,
                    **response_body,
                },
            )

        time_filter = str(
            payload.get(
                "time_filter",
                "30D",
            )
        ).upper()

        group_by = str(
            payload.get(
                "group_by",
                "daily",
            )
        ).lower()

        region = payload.get(
            "region",
            "ALL",
        )

        organization_type = str(
            payload.get(
                "organization_type",
                "ALL",
            )
        ).lower()

        start_date = payload.get(
            "start_date"
        )

        end_date = payload.get(
            "end_date"
        )

        conn = get_db_connection()

        cursor = conn.cursor(
            cursor_factory=RealDictCursor
        )

        response_body[
            "summary"
        ] = fetch_summary(
            cursor,
            time_filter,
            region,
            organization_type,
            start_date,
            end_date,
        )

        response_body[
            "growth_trend"
        ] = fetch_growth_trend(
            cursor,
            time_filter,
            group_by,
            region,
            organization_type,
            start_date,
            end_date,
        )

        response_body[
            "organizations_by_location"
        ] = fetch_organizations_by_location(
            cursor,
            time_filter,
            region,
            organization_type,
            start_date,
            end_date,
        )

        response_body[
            "organizations_by_size"
        ] = fetch_organizations_by_size(
            cursor,
            time_filter,
            region,
            organization_type,
            start_date,
            end_date,
        )

        response_body[
            "collaborator_vs_contributor"
        ] = fetch_collaborator_vs_contributor(
            cursor,
            time_filter,
            region,
            organization_type,
            start_date,
            end_date,
        )

        response_body[
            "rating_distribution"
        ] = fetch_rating_distribution(
            cursor,
            time_filter,
            region,
            organization_type,
            start_date,
            end_date,
        )

        response_body[
            "organization_type_distribution"
        ] = fetch_organization_type_distribution(
            cursor,
            time_filter,
            group_by,
            region,
            organization_type,
            start_date,
            end_date,
        )

        return build_response(
            200,
            response_body,
        )

    except Exception as exc:
        print(
            "Organization Analytics API error:",
            str(exc),
        )

        return build_response(
            500,
            {
                "error": (
                    "Organization analytics "
                    "query failed."
                ),
                **response_body,
            },
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


if __name__ == "__main__":
    test_cases = [
        {
            "name": "Standard 30D",
            "payload": {
                "time_filter": "30D",
                "start_date": None,
                "end_date": None,
                "group_by": "daily",
                "region": "ALL",
                "organization_type": "ALL",
            },
        },
        {
            "name": "Last 12 Months",
            "payload": {
                "time_filter": "1Y",
                "start_date": None,
                "end_date": None,
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "ALL",
            },
        },
        {
            "name": "California",
            "payload": {
                "time_filter": "1Y",
                "start_date": None,
                "end_date": None,
                "group_by": "monthly",
                "region": "California",
                "organization_type": "ALL",
            },
        },
        {
            "name": "Non-Profit",
            "payload": {
                "time_filter": "1Y",
                "start_date": None,
                "end_date": None,
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "non_profit",
            },
        },
        {
            "name": "Custom Range",
            "payload": {
                "time_filter": "CUSTOM",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "ALL",
            },
        },
    ]

    for test_case in test_cases:
        print("\n" + "=" * 70)
        print(test_case["name"])
        print("=" * 70)

        result = lambda_handler(
            test_case["payload"],
            None,
        )

        print("Status:", result["statusCode"])

        body = json.loads(result["body"])

        print(
            json.dumps(
                body,
                indent=2,
            )
        )