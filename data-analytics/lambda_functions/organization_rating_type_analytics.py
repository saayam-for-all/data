import json
import os
from datetime import datetime, timedelta

import pandas as pd

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

SCHEMA_NAME = "virginia_dev_saayam_rdbms"

USE_MOCK_DATA = (
    os.getenv("USE_MOCK_DATA", "false").lower() == "true"
)

MOCK_DATA_DIR = os.getenv(
    "MOCK_DATA_DIR",
    "data-analytics/mock-data-generation",
)


FIXED_BUCKETS = {
    "7D": {
        "days": 7,
        "group": "daily",
    },
    "30D": {
        "days": 30,
        "group": "daily",
    },
    "1Y": {
        "days": 365,
        "group": "monthly",
    },
    "All": {
        "days": None,
        "group": "monthly",
    },
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


def get_event_body(event):
    if not event:
        return {}

    if "body" in event:
        body = event.get("body")

        if isinstance(body, str):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {}

        if isinstance(body, dict):
            return body

    return event


def empty_chart_payload():
    return {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }


def validate_date_pair(
    filters,
    start_key,
    end_key,
):
    start_value = filters.get(start_key)
    end_value = filters.get(end_key)

    if bool(start_value) != bool(end_value):
        return (
            False,
            f"{start_key} and {end_key} must be provided together",
        )

    if not start_value and not end_value:
        return True, None

    try:
        start_date = datetime.strptime(
            start_value,
            "%Y-%m-%d",
        )
        end_date = datetime.strptime(
            end_value,
            "%Y-%m-%d",
        )
    except ValueError:
        return (
            False,
            f"{start_key} and {end_key} must use YYYY-MM-DD format",
        )

    if start_date > end_date:
        return (
            False,
            f"{start_key} cannot be after {end_key}",
        )

    return True, None


def validate_filters(filters):
    valid, error = validate_date_pair(
        filters,
        "rating_start_date",
        "rating_end_date",
    )

    if not valid:
        return False, error

    valid, error = validate_date_pair(
        filters,
        "type_start_date",
        "type_end_date",
    )

    if not valid:
        return False, error

    return True, None


def get_db_connection():
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is required when USE_MOCK_DATA is false"
        )

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"),
    )


def load_mock_data():
    organizations_path = os.path.join(
        MOCK_DATA_DIR,
        "organizations.csv",
    )

    states_path = os.path.join(
        MOCK_DATA_DIR,
        "states.csv",
    )

    countries_path = os.path.join(
        MOCK_DATA_DIR,
        "countries.csv",
    )

    organizations = pd.read_csv(
        organizations_path
    )

    states = pd.read_csv(
        states_path
    )

    countries = pd.read_csv(
        countries_path
    )

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="coerce",
    )

    organizations["org_rating"] = pd.to_numeric(
        organizations["org_rating"],
        errors="coerce",
    )

    data = organizations.merge(
        states[
            [
                "state_id",
                "country_id",
            ]
        ],
        on="state_id",
        how="left",
    )

    country_columns = [
        "country_id"
    ]

    if "country_code" in countries.columns:
        country_columns.append(
            "country_code"
        )

    if "country_name" in countries.columns:
        country_columns.append(
            "country_name"
        )

    data = data.merge(
        countries[country_columns],
        on="country_id",
        how="left",
    )

    return data


def apply_country_filter(
    data,
    country,
):
    if (
        not country
        or str(country).upper() == "ALL"
    ):
        return data.copy()

    value = str(country).strip().lower()

    mask = pd.Series(
        False,
        index=data.index,
    )

    if "country_code" in data.columns:
        mask = mask | (
            data["country_code"]
            .astype(str)
            .str.lower()
            == value
        )

    if "country_name" in data.columns:
        mask = mask | (
            data["country_name"]
            .astype(str)
            .str.lower()
            == value
        )

    return data[mask].copy()


def filter_date_range(
    data,
    start_date=None,
    end_date=None,
):
    result = data.copy()

    if start_date:
        start = pd.Timestamp(
            start_date
        )

        result = result[
            result["created_at"] >= start
        ]

    if end_date:
        end = (
            pd.Timestamp(end_date)
            + pd.Timedelta(days=1)
        )

        result = result[
            result["created_at"] < end
        ]

    return result


def build_rating_distribution(
    data,
):
    ratings = data[
        data["org_rating"].notna()
    ].copy()

    if ratings.empty:
        return []

    ratings["org_rating"] = (
        ratings["org_rating"]
        .astype(int)
    )

    ratings = ratings[
        ratings["org_rating"]
        .between(1, 5)
    ]

    if ratings.empty:
        return []

    grouped = (
        ratings
        .groupby("org_rating")
        .size()
        .reset_index(name="count")
        .sort_values("org_rating")
    )

    return [
        {
            "rating": int(
                row["org_rating"]
            ),
            "count": int(
                row["count"]
            ),
        }
        for _, row
        in grouped.iterrows()
    ]


def format_period(
    timestamp,
    group,
):
    if group == "daily":
        return timestamp.strftime(
            "%Y-%m-%d"
        )

    return timestamp.strftime(
        "%Y-%m"
    )


def period_series(
    data,
    group,
):
    result = data.copy()

    if group == "daily":
        result["period"] = (
            result["created_at"]
            .dt.floor("D")
        )
    else:
        result["period"] = (
            result["created_at"]
            .dt.to_period("M")
            .dt.to_timestamp()
        )

    return result


def build_mix_series_for_type(
    full_data,
    visible_data,
    org_type,
    group,
    start_date=None,
):
    typed_full = full_data[
        full_data["org_type"] == org_type
    ].copy()

    typed_visible = visible_data[
        visible_data["org_type"] == org_type
    ].copy()

    if typed_visible.empty:
        return []

    baseline = 0

    if start_date is not None:
        start_timestamp = pd.Timestamp(
            start_date
        )

        baseline = int(
            (
                typed_full["created_at"]
                < start_timestamp
            ).sum()
        )

    typed_visible = period_series(
        typed_visible,
        group,
    )

    period_counts = (
        typed_visible
        .groupby("period")
        .size()
        .reset_index(name="added")
        .sort_values("period")
    )

    running_total = baseline
    result = []

    for _, row in period_counts.iterrows():
        running_total += int(
            row["added"]
        )

        result.append(
            {
                "period": format_period(
                    row["period"],
                    group,
                ),
                "count": running_total,
            }
        )

    return result


def build_organization_mix_trend(
    full_data,
    visible_data,
    group,
    start_date=None,
):
    return {
        "non_profit":
            build_mix_series_for_type(
                full_data,
                visible_data,
                "non_profit",
                group,
                start_date,
            ),

        "for_profit":
            build_mix_series_for_type(
                full_data,
                visible_data,
                "for_profit",
                group,
                start_date,
            ),
    }


def build_fixed_bucket(
    data,
    bucket_name,
    now,
):
    config = FIXED_BUCKETS[
        bucket_name
    ]

    days = config["days"]
    group = config["group"]

    if days is None:
        start_date = None
        visible_data = data.copy()
    else:
        start_date = (
            now - timedelta(days=days)
        )

        visible_data = data[
            data["created_at"]
            >= pd.Timestamp(start_date)
        ].copy()

    return {
        "rating_distribution":
            build_rating_distribution(
                visible_data
            ),

        "organization_mix_trend":
            build_organization_mix_trend(
                data,
                visible_data,
                group,
                start_date,
            ),
    }


def build_fixed_response(
    data,
):
    now = datetime.utcnow()

    result = {}

    for bucket_name in [
        "7D",
        "30D",
        "1Y",
        "All",
    ]:
        result[bucket_name] = (
            build_fixed_bucket(
                data,
                bucket_name,
                now,
            )
        )

    result["Custom"] = (
        empty_chart_payload()
    )

    return result


def build_custom_response(
    data,
    filters,
):
    rating_start = filters.get(
        "rating_start_date"
    )
    rating_end = filters.get(
        "rating_end_date"
    )

    type_start = filters.get(
        "type_start_date"
    )
    type_end = filters.get(
        "type_end_date"
    )

    rating_distribution = []

    mix_trend = {
        "non_profit": [],
        "for_profit": [],
    }

    if rating_start and rating_end:
        rating_data = filter_date_range(
            data,
            rating_start,
            rating_end,
        )

        rating_distribution = (
            build_rating_distribution(
                rating_data
            )
        )

    if type_start and type_end:
        type_data = filter_date_range(
            data,
            type_start,
            type_end,
        )

        mix_trend = (
            build_organization_mix_trend(
                data,
                type_data,
                "daily",
                type_start,
            )
        )

    return {
        "Custom": {
            "rating_distribution":
                rating_distribution,

            "organization_mix_trend":
                mix_trend,
        }
    }


def has_custom_filters(
    filters,
):
    return any(
        [
            filters.get(
                "rating_start_date"
            ),
            filters.get(
                "rating_end_date"
            ),
            filters.get(
                "type_start_date"
            ),
            filters.get(
                "type_end_date"
            ),
        ]
    )


def build_mock_response(
    filters,
):
    data = load_mock_data()

    country = filters.get(
        "country",
        "ALL",
    )

    data = apply_country_filter(
        data,
        country,
    )

    if has_custom_filters(filters):
        return build_custom_response(
            data,
            filters,
        )

    return build_fixed_response(
        data,
    )


def build_db_filters(
    country,
):
    conditions = []
    params = []

    if (
        country
        and str(country).upper() != "ALL"
    ):
        conditions.append(
            "("
            "LOWER(c.country_code) = LOWER(%s) "
            "OR LOWER(c.country_name) = LOWER(%s)"
            ")"
        )

        params.extend(
            [
                country,
                country,
            ]
        )

    if conditions:
        return (
            "WHERE "
            + " AND ".join(conditions),
            params,
        )

    return "", params


def fetch_db_rows(
    cursor,
    country,
):
    where_clause, params = (
        build_db_filters(
            country
        )
    )

    query = f"""
        SELECT
            o.org_id,
            o.org_rating,
            o.org_type::text
                AS org_type,
            o.state_id,
            o.created_at,
            c.country_code,
            c.country_name

        FROM {SCHEMA_NAME}.organizations o

        LEFT JOIN {SCHEMA_NAME}.states s
            ON o.state_id = s.state_id

        LEFT JOIN {SCHEMA_NAME}.countries c
            ON s.country_id = c.country_id

        {where_clause}

        ORDER BY o.created_at;
    """

    cursor.execute(
        query,
        params,
    )

    rows = cursor.fetchall()

    return rows


def rows_to_dataframe(
    rows,
):
    if not rows:
        return pd.DataFrame(
            columns=[
                "org_id",
                "org_rating",
                "org_type",
                "state_id",
                "created_at",
                "country_code",
                "country_name",
            ]
        )

    data = pd.DataFrame(rows)

    data["created_at"] = (
        pd.to_datetime(
            data["created_at"],
            errors="coerce",
        )
    )

    data["org_rating"] = (
        pd.to_numeric(
            data["org_rating"],
            errors="coerce",
        )
    )

    return data


def build_database_response(
    filters,
):
    conn = None
    cursor = None

    try:
        conn = get_db_connection()

        cursor = conn.cursor(
            cursor_factory=RealDictCursor
        )

        country = filters.get(
            "country",
            "ALL",
        )

        rows = fetch_db_rows(
            cursor,
            country,
        )

        data = rows_to_dataframe(
            rows
        )

        if has_custom_filters(filters):
            return build_custom_response(
                data,
                filters,
            )

        return build_fixed_response(
            data,
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


def lambda_handler(
    event,
    context,
):
    try:
        filters = get_event_body(
            event
        )

        valid, error_message = (
            validate_filters(
                filters
            )
        )

        if not valid:
            return build_response(
                400,
                {
                    "error":
                        error_message
                },
            )

        if USE_MOCK_DATA:
            response_body = (
                build_mock_response(
                    filters
                )
            )
        else:
            response_body = (
                build_database_response(
                    filters
                )
            )

        return build_response(
            200,
            response_body,
        )

    except FileNotFoundError as error:
        print(
            "Organization rating/type "
            f"mock data error: {error}"
        )

        return build_response(
            500,
            {
                "error":
                    "Mock data file not found"
            },
        )

    except (
        psycopg2.Error
        if psycopg2 is not None
        else Exception
    ) as error:
        print(
            "Organization rating/type "
            f"database error: {error}"
        )

        return build_response(
            500,
            {
                "error":
                    "Internal Server Error"
            },
        )

    except Exception as error:
        print(
            "Organization rating/type "
            f"analytics failed: {error}"
        )

        return build_response(
            500,
            {
                "error":
                    "Internal Server Error"
            },
        )


if __name__ == "__main__":
    sample_events = [
        (
            "NO FILTERS",
            {},
        ),
        (
            "COUNTRY FILTER",
            {
                "country": "USA",
            },
        ),
        (
            "RATING CUSTOM",
            {
                "country": "ALL",
                "rating_start_date":
                    "2026-01-01",
                "rating_end_date":
                    "2026-06-30",
            },
        ),
        (
            "TYPE CUSTOM",
            {
                "country": "ALL",
                "type_start_date":
                    "2025-01-01",
                "type_end_date":
                    "2025-12-31",
            },
        ),
        (
            "BOTH CUSTOM",
            {
                "country": "ALL",
                "rating_start_date":
                    "2026-01-01",
                "rating_end_date":
                    "2026-06-30",
                "type_start_date":
                    "2025-01-01",
                "type_end_date":
                    "2025-12-31",
            },
        ),
    ]

    for name, event in sample_events:
        print(
            "\n"
            + "=" * 80
        )

        print(name)

        print(
            "Payload:"
        )

        print(
            json.dumps(
                event,
                indent=2,
            )
        )

        result = lambda_handler(
            event,
            None,
        )

        print(
            "Status:",
            result["statusCode"],
        )

        print(
            json.dumps(
                json.loads(
                    result["body"]
                ),
                indent=2,
            )
        )