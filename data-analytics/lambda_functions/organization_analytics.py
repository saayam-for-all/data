

import json

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"

SSM_PARAMETER_NAME = "/dev/saayam/db/Virginia/Analytics/user"
AWS_REGION = "us-east-1"
STATE_TABLE = f"{SCHEMA_NAME}.state"
def get_default_response():
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
            "organizations_by_location": [],
            "collaborator_distribution": [],
            "contributor_distribution": []
        },
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
    if not event:
        return {}

    if isinstance(event, str):
        try:
            return json.loads(event)
        except json.JSONDecodeError:
            return {}

    if not isinstance(event, dict):
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
    ssm = boto3.client(
        "ssm",
        region_name=AWS_REGION
    )

    response = ssm.get_parameter(
        Name=SSM_PARAMETER_NAME,
        WithDecryption=True
    )

    credentials = json.loads(
        response["Parameter"]["Value"]
    )

    return psycopg2.connect(
        host=credentials["HOST"],
        database=credentials["DATABASE NAME"],
        user=credentials["USERNAME"],
        password=credentials["PASSWORD"],
        port=credentials["PORT"],
        sslmode="require"
    )


def build_date_filter(
    time_filter,
    start_date=None,
    end_date=None
):
    sql_date_condition = ""
    sql_params = ()

    normalized_filter = str(
        time_filter or "ALL"
    ).upper()

    if (
        normalized_filter == "CUSTOM"
        and start_date
        and end_date
    ):
        sql_date_condition = (
            "o.created_at BETWEEN %s AND %s"
        )
        sql_params = (start_date, end_date)

    elif normalized_filter == "7D":
        sql_date_condition = (
            "o.created_at >= "
            "CURRENT_DATE - INTERVAL '7 days'"
        )

    elif normalized_filter == "30D":
        sql_date_condition = (
            "o.created_at >= "
            "CURRENT_DATE - INTERVAL '30 days'"
        )

    elif normalized_filter == "1Y":
        sql_date_condition = (
            "o.created_at >= "
            "CURRENT_DATE - INTERVAL '1 year'"
        )

    return sql_date_condition, sql_params
def build_organization_filters(
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None
):
    conditions = []
    params = []

    date_condition, date_params = build_date_filter(
        time_filter,
        start_date,
        end_date
    )

    if date_condition:
        conditions.append(date_condition)
        params.extend(date_params)

    if org_type:
        conditions.append("o.org_type = %s")
        params.append(org_type)

    if org_size:
        conditions.append("o.org_size = %s")
        params.append(org_size)

    if state_id is not None:
        conditions.append("o.state_id = %s")
        params.append(state_id)

    if city_name:
        conditions.append(
            "LOWER(o.city_name) = LOWER(%s)"
        )
        params.append(city_name)

    if org_rating is not None:
        conditions.append("o.org_rating = %s")
        params.append(org_rating)

    if is_collaborator is not None:
        conditions.append(
            "o.is_collaborator = %s"
        )
        params.append(is_collaborator)

    where_clause = ""

    if conditions:
        where_clause = (
            "WHERE " + " AND ".join(conditions)
        )

    return where_clause, params

def fetch_total_organizations(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None
):
    date_filter, params = build_date_filter(
        time_filter,
        start_date,
        end_date
    )

    date_filter_clause = (
        f"WHERE {date_filter}"
        if date_filter
        else ""
    )

    query = f"""
        SELECT
            COUNT(*) AS total_organizations
        FROM {ORGANIZATIONS_TABLE} o
        {date_filter_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    if (
        row
        and row["total_organizations"] is not None
    ):
        return int(row["total_organizations"])

    return 0



def fetch_organizations_by_type(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None
):
    where_clause, params = build_organization_filters(
        time_filter,
        start_date,
        end_date,
        org_type,
        org_size,
        state_id,
        city_name,
        org_rating,
        is_collaborator
    )

    query = f"""
        SELECT
            COALESCE(
                o.org_type,
                'Unknown'
            ) AS organization_type,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        GROUP BY COALESCE(
            o.org_type,
            'Unknown'
        )
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_type": row[
                "organization_type"
            ],
            "count": int(row["count"] or 0)
        }
        for row in rows
    ]

    query = f"""
        SELECT
            COALESCE(o.org_type, 'Unknown')
                AS organization_type,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {date_filter_clause}
        GROUP BY
            COALESCE(o.org_type, 'Unknown')
        ORDER BY
            count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_type": row[
                "organization_type"
            ],
            "count": int(row["count"])
        }
        for row in rows
    ]

def fetch_organizations_by_size(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None
):
    where_clause, params = build_organization_filters(
        time_filter,
        start_date,
        end_date,
        org_type,
        org_size,
        state_id,
        city_name,
        org_rating,
        is_collaborator
    )

    query = f"""
        SELECT
            COALESCE(
                o.org_size,
                'Unknown'
            ) AS organization_size,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        GROUP BY COALESCE(
            o.org_size,
            'Unknown'
        )
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_size": row["organization_size"],
            "count": int(row["count"] or 0)
        }
        for row in rows
    ]

    query = f"""
        SELECT
            COALESCE(o.size, 'Unknown')
                AS organization_size,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {date_filter_clause}
        GROUP BY
            COALESCE(o.size, 'Unknown')
        ORDER BY
            count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_size": row["organization_size"],
            "count": int(row["count"])
        }
        for row in rows
    ]

def fetch_organizations_by_location(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None
):
    date_filter, params = build_date_filter(
        time_filter,
        start_date,
        end_date
    )

    date_filter_clause = (
        f"WHERE {date_filter}"
        if date_filter
        else ""
    )

    query = f"""
        SELECT
            COALESCE(o.state_code, 'Unknown') AS state_code,
            COALESCE(o.city_name, 'Unknown') AS city_name,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {date_filter_clause}
        GROUP BY
            COALESCE(o.state_code, 'Unknown'),
            COALESCE(o.city_name, 'Unknown')
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "state_code": row["state_code"],
            "city_name": row["city_name"],
            "count": int(row["count"])
        }
        for row in rows
    ]
def fetch_collaborator_distribution(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None
):
    where_clause, params = build_organization_filters(
        time_filter,
        start_date,
        end_date,
        org_type,
        org_size,
        state_id,
        city_name,
        org_rating,
        is_collaborator
    )

    query = f"""
        SELECT
            CASE
                WHEN COALESCE(o.is_collaborator,FALSE)
                THEN 'Collaborator'
                ELSE 'Non Collaborator'
            END AS label,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        GROUP BY label
        ORDER BY label;
    """

    cursor.execute(query, params)

    rows = cursor.fetchall()

    return [
        {
            "label": row["label"],
            "count": int(row["count"] or 0)
        }
        for row in rows
    ]

def fetch_registration_trend(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None,
    group_by="daily"
):
    group_by = str(group_by).lower()

    grouping_options = {
        "daily": {
            "date_trunc": "day",
            "date_format": "YYYY-MM-DD"
        },
        "weekly": {
            "date_trunc": "week",
            "date_format": "YYYY-MM-DD"
        },
        "monthly": {
            "date_trunc": "month",
            "date_format": "YYYY-MM"
        },
        "yearly": {
            "date_trunc": "year",
            "date_format": "YYYY"
        }
    }

    if group_by not in grouping_options:
        group_by = "daily"

    date_trunc_value = grouping_options[
        group_by
    ]["date_trunc"]

    date_format = grouping_options[
        group_by
    ]["date_format"]

    where_clause, params = build_organization_filters(
        time_filter,
        start_date,
        end_date,
        org_type,
        org_size,
        state_id,
        city_name,
        org_rating,
        is_collaborator
    )

    query = f"""
        SELECT
            TO_CHAR(
                DATE_TRUNC(
                    '{date_trunc_value}',
                    o.created_at
                ),
                '{date_format}'
            ) AS period,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        AND o.created_at IS NOT NULL
        GROUP BY
            DATE_TRUNC(
                '{date_trunc_value}',
                o.created_at
            )
        ORDER BY
            DATE_TRUNC(
                '{date_trunc_value}',
                o.created_at
            ) ASC;
    """

    # When there are no filters, where_clause is empty.
    # In that case, SQL cannot begin with AND.
    if not where_clause:
        query = query.replace(
            "AND o.created_at IS NOT NULL",
            "WHERE o.created_at IS NOT NULL"
        )

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "period": row["period"],
            "count": int(row["count"] or 0)
        }
        for row in rows
    ]
    
    return [
        {
            "registration_month": str(
                row["registration_month"]
            ),
            "count": int(row["count"])
        }
        for row in rows
    ]
def fetch_overview_summary(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None
):
    where_clause, params = build_organization_filters(
        time_filter,
        start_date,
        end_date,
        org_type,
        org_size,
        state_id,
        city_name,
        org_rating,
        is_collaborator
    )

    query = f"""
        SELECT
            COUNT(*) AS total_organizations,

            COUNT(*) FILTER (
                WHERE LOWER(
                    REPLACE(
                        REPLACE(
                            COALESCE(o.org_type, ''),
                            '-',
                            ''
                        ),
                        ' ',
                        ''
                    )
                ) = 'nonprofit'
            ) AS non_profit_organizations,

            COUNT(*) FILTER (
                WHERE LOWER(
                    REPLACE(
                        REPLACE(
                            COALESCE(o.org_type, ''),
                            '-',
                            ''
                        ),
                        ' ',
                        ''
                    )
                ) = 'forprofit'
            ) AS for_profit_organizations,

            COUNT(*) FILTER (
                WHERE o.is_collaborator IS TRUE
            ) AS collaborator_organizations,

            COUNT(*) FILTER (
                WHERE COALESCE(
                    o.is_collaborator,
                    FALSE
                ) IS FALSE
            ) AS non_collaborator_organizations

        FROM {ORGANIZATIONS_TABLE} o
        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    if not row:
        return {
            "total_organizations": 0,
            "non_profit_organizations": 0,
            "for_profit_organizations": 0,
            "collaborator_organizations": 0,
            "non_collaborator_organizations": 0,
            "contributor_organizations": 0,
            "non_contributor_organizations": 0
        }

    return {
        "total_organizations": int(
            row["total_organizations"] or 0
        ),
        "non_profit_organizations": int(
            row["non_profit_organizations"] or 0
        ),
        "for_profit_organizations": int(
            row["for_profit_organizations"] or 0
        ),
        "collaborator_organizations": int(
            row["collaborator_organizations"] or 0
        ),
        "non_collaborator_organizations": int(
            row["non_collaborator_organizations"] or 0
        ),

        # is_contributor is not available yet.
        "contributor_organizations": 0,
        "non_contributor_organizations": 0
    }

def fetch_performance_summary(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None
):
    where_clause, params = build_organization_filters(
        time_filter,
        start_date,
        end_date,
        org_type,
        org_size,
        state_id,
        city_name,
        org_rating,
        is_collaborator
    )

    query = f"""
        SELECT
            COALESCE(
                ROUND(AVG(o.org_rating)::numeric, 2),
                0
            ) AS average_rating,

            COUNT(*) FILTER (
                WHERE o.org_rating IS NOT NULL
            ) AS rated_organizations,

            COUNT(*) FILTER (
                WHERE o.org_rating IS NULL
            ) AS unrated_organizations,

            COUNT(*) FILTER (
                WHERE o.org_rating = 5
            ) AS five_star_organizations

        FROM {ORGANIZATIONS_TABLE} o
        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    if not row:
        return {
            "average_rating": 0,
            "rated_organizations": 0,
            "unrated_organizations": 0,
            "five_star_organizations": 0
        }

    return {
        "average_rating": float(
            row["average_rating"] or 0
        ),
        "rated_organizations": int(
            row["rated_organizations"] or 0
        ),
        "unrated_organizations": int(
            row["unrated_organizations"] or 0
        ),
        "five_star_organizations": int(
            row["five_star_organizations"] or 0
        )
    }

def fetch_rating_distribution(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None
):
    where_clause, params = build_organization_filters(
        time_filter,
        start_date,
        end_date,
        org_type,
        org_size,
        state_id,
        city_name,
        org_rating,
        is_collaborator
    )

    query = f"""
        SELECT
            o.org_rating AS rating,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        AND o.org_rating IS NOT NULL
        GROUP BY o.org_rating
        ORDER BY o.org_rating DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "rating": row["rating"],
            "count": int(row["count"] or 0)
        }
        for row in rows
    ]

def fetch_top_rated_organizations(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None
):
    where_clause, params = build_organization_filters(
        time_filter,
        start_date,
        end_date,
        org_type,
        org_size,
        state_id,
        city_name,
        org_rating,
        is_collaborator
    )

    query = f"""
        SELECT
            o.org_name,
            o.org_rating
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        AND o.org_rating IS NOT NULL
        ORDER BY
            o.org_rating DESC,
            o.org_name ASC
        LIMIT 10;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_name": row["org_name"],
            "rating": row["org_rating"]
        }
        for row in rows
    ]
def fetch_ratings_by_organization_type(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None
):
    where_clause, params = build_organization_filters(
        time_filter,
        start_date,
        end_date,
        org_type,
        org_size,
        state_id,
        city_name,
        org_rating,
        is_collaborator
    )

    query = f"""
        SELECT
            o.org_type,
            ROUND(
                AVG(o.org_rating)::numeric,
                2
            ) AS average_rating
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        AND o.org_rating IS NOT NULL
        GROUP BY o.org_type
        ORDER BY average_rating DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_type": row["org_type"],
            "average_rating": float(
                row["average_rating"] or 0
            )
        }
        for row in rows
    ]
def fetch_ratings_by_organization_size(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None
):
    where_clause, params = build_organization_filters(
        time_filter,
        start_date,
        end_date,
        org_type,
        org_size,
        state_id,
        city_name,
        org_rating,
        is_collaborator
    )

    query = f"""
        SELECT
            o.org_size,
            ROUND(
                AVG(o.org_rating)::numeric,
                2
            ) AS average_rating
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        AND o.org_rating IS NOT NULL
        GROUP BY o.org_size
        ORDER BY average_rating DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_size": row["org_size"],
            "average_rating": float(
                row["average_rating"] or 0
            )
        }
        for row in rows
    ]
def fetch_top_collaborator_organizations(
    cursor,
    time_filter="ALL",
    start_date=None,
    end_date=None,
    org_type=None,
    org_size=None,
    state_id=None,
    city_name=None,
    org_rating=None,
    is_collaborator=None
):
    where_clause, params = build_organization_filters(
        time_filter,
        start_date,
        end_date,
        org_type,
        org_size,
        state_id,
        city_name,
        org_rating,
        is_collaborator
    )

    if where_clause:
        where_clause += " AND o.is_collaborator = TRUE"
    else:
        where_clause = "WHERE o.is_collaborator = TRUE"

    query = f"""
        SELECT
            o.org_name,
            o.org_rating
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        ORDER BY
            o.org_rating DESC NULLS LAST,
            o.org_name ASC
        LIMIT 10;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_name": row["org_name"],
            "rating": row["org_rating"]
        }
        for row in rows
    ]
def lambda_handler(event, context):
    connection = None
    cursor = None

    response_body = get_default_response()
    request_body = parse_event_body(event)

    time_filter = request_body.get(
        "time_filter",
        request_body.get("time_range", "ALL")
    )
    start_date = request_body.get("start_date")
    end_date = request_body.get("end_date")
    org_type = request_body.get("org_type")
    org_size = request_body.get("org_size")
    state_id = request_body.get("state_id")
    city_name = request_body.get("city_name")
    org_rating = request_body.get("org_rating")
    is_collaborator = request_body.get(
        "is_collaborator"
    )
    group_by = request_body.get(
        "group_by",
        "daily"
    )
    dashboard_type = request_body.get(
        "dashboard_type",
        "overview"
    ).lower()
    try:
        connection = get_db_connection()

        cursor = connection.cursor(
            cursor_factory=RealDictCursor
        )
        if dashboard_type not in [
            "overview",
            "performance"
        ]:
            return build_response(
                400,
                {
                    "error_code": "DE1002",
                    "message": (
                        "Invalid dashboard type."
                    )
                }
            )

        if dashboard_type == "performance":
            try:
                response_body[
                    "organization_performance"
                ][
                    "summary"
                ] = fetch_performance_summary(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator
                )
            except Exception as error:
                print(
                    f"Performance summary query failed: {error}"
                )

            try:
                response_body[
                    "organization_performance"
                ][
                    "rating_distribution"
                ] = fetch_rating_distribution(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator
                )

            except Exception as error:
                print(
                    f"Rating distribution query failed: {error}"
                )
                response_body[
                    "organization_performance"
                ][
                    "rating_distribution"
                ] = []

            try:
                response_body[
                    "organization_performance"
                ][
                    "top_rated_organizations"
                ] = fetch_top_rated_organizations(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator
                )

            except Exception as error:
                print(
                    f"Top rated organizations query failed: {error}"
                )
                response_body[
                    "organization_performance"
                ][
                    "top_rated_organizations"
                ] = []
            try:
                response_body[
                    "organization_performance"
                ][
                    "ratings_by_organization_type"
                ] = fetch_ratings_by_organization_type(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator
                )

            except Exception as error:
                print(
                    f"Ratings by organization type query failed: {error}"
                )
                response_body[
                    "organization_performance"
                ][
                    "ratings_by_organization_type"
                ] = []
            try:
                response_body[
                    "organization_performance"
                ][
                    "ratings_by_organization_size"
                ] = fetch_ratings_by_organization_size(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator
                )

            except Exception as error:
                print(
                    f"Ratings by organization size query failed: {error}"
                )
                response_body[
                    "organization_performance"
                ][
                    "ratings_by_organization_size"
                ] = []
            try:
                response_body[
                    "organization_performance"
                ][
                    "top_collaborator_organizations"
                ] = fetch_top_collaborator_organizations(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator
                )

            except Exception as error:
                print(
                    f"Top collaborator organizations query failed: {error}"
                )
                response_body[
                    "organization_performance"
                ][
                    "top_collaborator_organizations"
                ] = []
                response_body[
                    "organization_performance"
                ][
                    "top_contributor_organizations"
                ] = []
        if dashboard_type == "overview":
            try:
                response_body[
                    "organization_overview"
                ][
                    "summary"
                ] = fetch_overview_summary(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator
                )
            except Exception as error:
                print(
                    f"Overview summary query failed: {error}"
                )

            try:
                response_body[
                    "organization_overview"
                ][
                    "organizations_by_type"
                ] = fetch_organizations_by_type(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator
                )
            except Exception as error:
                print(
                    f"Organizations by type query failed: {error}"
                )
                response_body[
                    "organization_overview"
                ][
                    "organizations_by_type"
                ] = []

            try:
                response_body[
                    "organization_overview"
                ][
                    "organizations_by_size"
                ] = fetch_organizations_by_size(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator
                )
            except Exception as error:
                print(
                    f"Organizations by size query failed: {error}"
                )
                response_body[
                    "organization_overview"
                ][
                    "organizations_by_size"
                ] = []

            try:
                response_body[
                    "organization_overview"
                ][
                    "collaborator_distribution"
                ] = fetch_collaborator_distribution(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator
                )
            except Exception as error:
                print(
                    f"Collaborator distribution query failed: {error}"
                )
                response_body[
                    "organization_overview"
                ][
                    "collaborator_distribution"
                ] = []

            try:
                response_body[
                    "organization_overview"
                ][
                    "organizations_by_location"
                ] = fetch_organizations_by_location(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator
                )
            except Exception as error:
                print(
                    f"Organizations by location query failed: {error}"
                )
                response_body[
                    "organization_overview"
                ][
                    "organizations_by_location"
                ] = []

            try:
                response_body[
                    "organization_overview"
                ][
                    "organization_activity_trend"
                ] = fetch_registration_trend(
                    cursor,
                    time_filter,
                    start_date,
                    end_date,
                    org_type,
                    org_size,
                    state_id,
                    city_name,
                    org_rating,
                    is_collaborator,
                    group_by
                )
            except Exception as error:
                print(
                    f"Registration trend query failed: {error}"
                )
                response_body[
                    "organization_overview"
                ][
                    "organization_activity_trend"
                ] = []
            response_body[
                "organization_overview"
            ][
                "contributor_distribution"
            ] = []

        return build_response(
            200,
            response_body
        )

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()
    