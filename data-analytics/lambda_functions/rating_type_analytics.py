import json
import os
from datetime import datetime
from typing import Any

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None


VALID_ORGANIZATION_TYPES = {
    "non_profit",
    "for_profit"
}

VALID_TIME_RANGES = {
    "7D",
    "30D",
    "1Y",
    "All"
}


class RequestValidationError(ValueError):
    """Raised when the request contains invalid input."""
    pass

# Response helpers

def empty_chart_response() -> dict:
    return {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": []
        }
    }

def default_response() -> dict:
    return {
        "7D": empty_chart_response(),
        "30D": empty_chart_response(),
        "1Y": empty_chart_response(),
        "All": empty_chart_response(),
        "Custom": empty_chart_response()
    }

def build_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }

# Request parsing and validation

def parse_event(event: Any) -> dict:
    """
    Supports both:
      1. Direct Lambda invocation
      2. API Gateway event with a JSON body
    """

    if event is None:
        return {}

    if not isinstance(event, dict):
        raise RequestValidationError(
            "Request must be a JSON object."
        )

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError as exc:
            raise RequestValidationError(
                "Request body must contain valid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise RequestValidationError(
                "Request body must be a JSON object."
            )

        return parsed

    raise RequestValidationError(
        "Request body must be a JSON object."
    )


def validate_date_pair(
    start_date: Any,
    end_date: Any,
    pair_name: str
) -> None:
    """
    Validate one start/end date pair.

    Both missing:
        valid

    One missing:
        invalid

    Wrong format:
        invalid

    Start after end:
        invalid
    """

    if start_date is None and end_date is None:
        return

    if start_date is None or end_date is None:
        raise RequestValidationError(
            f"{pair_name}: both start_date and end_date "
            "must be provided."
        )

    if not isinstance(start_date, str) or not isinstance(end_date, str):
        raise RequestValidationError(
            f"{pair_name}: dates must use YYYY-MM-DD format."
        )

    try:
        start = datetime.strptime(
            start_date,
            "%Y-%m-%d"
        ).date()

        end = datetime.strptime(
            end_date,
            "%Y-%m-%d"
        ).date()

    except ValueError as exc:
        raise RequestValidationError(
            f"{pair_name}: dates must use YYYY-MM-DD format."
        ) from exc

    if start > end:
        raise RequestValidationError(
            f"{pair_name}: start date cannot be after end date."
        )

# Mock CSV loading

def load_mock_data():
    """
    Load the local CSV files using pandas.

    Expected files:
        organizations.csv
        state.csv
        country.csv
    """

    data_directory = os.getenv(
        "MOCK_DATA_DIR",
        "."
    )

    organizations_path = os.path.join(
        data_directory,
        "organizations.csv"
    )

    state_path = os.path.join(
        data_directory,
        "state.csv"
    )

    country_path = os.path.join(
        data_directory,
        "country.csv"
    )

    organizations = pd.read_csv(
        organizations_path
    )

    states = pd.read_csv(
        state_path
    )

    countries = pd.read_csv(
        country_path
    )

    return organizations, states, countries


# Data preparation

def prepare_data(
    organizations: pd.DataFrame,
    states: pd.DataFrame,
    countries: pd.DataFrame
) -> pd.DataFrame:
    """
    Join:

        organizations
            -> state
            -> country

    using:

        organizations.state_id = state.state_id
        state.country_id = country.country_id
    """

    required_org_columns = {
        "org_id",
        "org_rating",
        "org_type",
        "state_id",
        "created_at"
    }

    required_state_columns = {
        "state_id",
        "country_id"
    }

    required_country_columns = {
        "country_id",
        "country_code"
    }

    missing_org = required_org_columns - set(
        organizations.columns
    )

    missing_state = required_state_columns - set(
        states.columns
    )

    missing_country = required_country_columns - set(
        countries.columns
    )

    if missing_org:
        raise ValueError(
            f"organizations.csv is missing columns: "
            f"{sorted(missing_org)}"
        )

    if missing_state:
        raise ValueError(
            f"state.csv is missing columns: "
            f"{sorted(missing_state)}"
        )

    if missing_country:
        raise ValueError(
            f"country.csv is missing columns: "
            f"{sorted(missing_country)}"
        )

    state_lookup = states[
        ["state_id", "country_id"]
    ].drop_duplicates("state_id")

    country_columns = [
        "country_id",
        "country_code"
    ]

    if "country_name" in countries.columns:
        country_columns.append("country_name")

    country_lookup = countries[
        country_columns
    ].drop_duplicates("country_id")

    data = organizations.merge(
        state_lookup,
        on="state_id",
        how="left"
    )

    data = data.merge(
        country_lookup,
        on="country_id",
        how="left"
    )

    data["created_at"] = pd.to_datetime(
        data["created_at"],
        errors="coerce"
    )

    data["org_rating"] = pd.to_numeric(
        data["org_rating"],
        errors="coerce"
    )

    data["org_type"] = (

    data["org_type"]

    .astype(str)

    .str.strip()

    .str.lower()

    .replace({

        "non-profit": "non_profit",

        "for-profit": "for_profit"

    })

)

    return data


# Country filter

def apply_country_filter(
    data: pd.DataFrame,
    country: Any
) -> pd.DataFrame:
    """
    Country can be:
        ALL
        country code, e.g. US
        country name, e.g. United States
    """

    if country is None:
        return data

    country_value = str(country).strip()

    if not country_value:
        return data

    if country_value.upper() == "ALL":
        return data

    code_match = (
        data["country_code"]
        .fillna("")
        .astype(str)
        .str.upper()
        == country_value.upper()
    )

    if "country_name" in data.columns:
        name_match = (
            data["country_name"]
            .fillna("")
            .astype(str)
            .str.lower()
            == country_value.lower()
        )
    else:
        name_match = pd.Series(
            False,
            index=data.index
        )

    return data[
        code_match | name_match
    ]


# Date filtering

def filter_date_window(
    data: pd.DataFrame,
    start_date=None,
    end_date=None
) -> pd.DataFrame:
    """
    Apply an inclusive date range to created_at.

    Example:
        2026-01-01 through 2026-01-31
    includes the entire day of January 31.
    """

    result = data

    if start_date is not None:
        start = pd.Timestamp(start_date)

        result = result[
            result["created_at"] >= start
        ]

    if end_date is not None:
        end = (
            pd.Timestamp(end_date)
            + pd.Timedelta(days=1)
        )

        result = result[
            result["created_at"] < end
        ]

    return result


# Fixed time ranges

def get_fixed_window(
    time_range: str
):
    """
    Returns start/end dates for fixed dashboard buckets.

    All has no lower bound.
    """

    today = pd.Timestamp.today().normalize()

    if time_range == "7D":
        return (
            today - pd.Timedelta(days=7),
            today
        )

    if time_range == "30D":
        return (
            today - pd.Timedelta(days=30),
            today
        )

    if time_range == "1Y":
        return (
            today - pd.DateOffset(years=1),
            today
        )

    if time_range == "All":
        return None, today

    raise ValueError(
        f"Unsupported time range: {time_range}"
    )


# Rating Distribution

def calculate_rating_distribution(
    data: pd.DataFrame,
    start_date=None,
    end_date=None
) -> list:
    """
    Count organizations by their literal org_rating.

    Only ratings actually present are returned.
    Missing ratings are NOT zero-filled.
    """

    window = filter_date_window(
        data,
        start_date,
        end_date
    )

    window = window[
        window["org_rating"].isin(
            [1, 2, 3, 4, 5]
        )
    ]

    if window.empty:
        return []

    counts = (
        window
        .groupby("org_rating")
        .size()
        .reset_index(name="count")
        .sort_values("org_rating")
    )

    return [
        {
            "rating": int(row["org_rating"]),
            "count": int(row["count"])
        }
        for _, row in counts.iterrows()
    ]


# Organization Mix Trend

def calculate_organization_mix(
    data: pd.DataFrame,
    time_range: str,
    start_date=None,
    end_date=None
) -> dict:
    """
    Calculate cumulative organization counts by type.

    Grouping:
        7D     -> day
        30D    -> day
        1Y     -> month
        All    -> month
        Custom -> day

    Important:
        The counts are cumulative/all-time totals.

    For example, if 100 non-profits existed before the
    selected window and 3 more were created during the
    first period, that first returned period has count 103.
    """

    data = data[
        data["org_type"].isin(
            VALID_ORGANIZATION_TYPES
        )
    ].copy()

    data = data.dropna(
        subset=["created_at"]
    )

    if data.empty:
        return {
            "non_profit": [],
            "for_profit": []
        }

    if end_date is not None:
        end_boundary = (
            pd.Timestamp(end_date)
            + pd.Timedelta(days=1)
        )

        data = data[
            data["created_at"] < end_boundary
        ]

    if data.empty:
        return {
            "non_profit": [],
            "for_profit": []
        }

    # Determine period granularity.
    if time_range in {
        "7D",
        "30D",
        "Custom"
    }:
        data["period"] = (
            data["created_at"]
            .dt.floor("D")
        )

    elif time_range in {
        "1Y",
        "All"
    }:
        data["period"] = (
            data["created_at"]
            .dt.to_period("M")
        )

    else:
        raise ValueError(
            f"Unsupported time range: {time_range}"
        )

    # Number of newly created organizations in each period.
    grouped = (
        data
        .groupby(
            ["org_type", "period"]
        )
        .size()
        .reset_index(name="new_count")
        .sort_values(
            ["org_type", "period"]
        )
    )

    result = {
        "non_profit": [],
        "for_profit": []
    }

    for organization_type in [
        "non_profit",
        "for_profit"
    ]:

        type_data = grouped[
            grouped["org_type"] == organization_type
        ].copy()

        if type_data.empty:
            continue

        # Running all-time total.
        type_data["count"] = (
            type_data["new_count"]
            .cumsum()
        )

        # Only display periods inside the requested window.
        if start_date is not None:

            start = pd.Timestamp(
                start_date
            )

            if time_range in {
                "7D",
                "30D",
                "Custom"
            }:
                type_data = type_data[
                    type_data["period"] >= start
                ]

            else:
                start_month = start.to_period("M")

                type_data = type_data[
                    type_data["period"] >= start_month
                ]

        for _, row in type_data.iterrows():

            if time_range in {
                "7D",
                "30D",
                "Custom"
            }:
                period_value = (
                    row["period"]
                    .strftime("%Y-%m-%d")
                )
            else:
                period_value = str(
                    row["period"]
                )

            result[organization_type].append(
                {
                    "period": period_value,
                    "count": int(row["count"])
                }
            )

    return result


# PostgreSQL connection

def get_db_connection():
    """
    Create a PostgreSQL connection.

    The real deployment can provide these environment
    variables through the Lambda configuration:

        DB_HOST
        DB_PORT
        DB_NAME
        DB_USER
        DB_PASSWORD
    """

    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is not installed."
        )

    required = [
        "DB_HOST",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD"
    ]

    missing = [
        name
        for name in required
        if not os.getenv(name)
    ]

    if missing:
        raise RuntimeError(
            "Missing database environment variables: "
            + ", ".join(missing)
        )

    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


# PostgreSQL Rating Distribution

def db_rating_distribution(
    cursor,
    start_date=None,
    end_date=None,
    country="ALL"
) -> list:
    """
    PostgreSQL implementation of Rating Distribution.
    """

    conditions = [
        "o.org_rating BETWEEN 1 AND 5"
    ]

    parameters = []

    if start_date is not None:
        conditions.append(
            "o.created_at >= %s"
        )
        parameters.append(start_date)

    if end_date is not None:
        conditions.append(
            "o.created_at < (%s::date + INTERVAL '1 day')"
        )
        parameters.append(end_date)

    if country.upper() != "ALL":
        conditions.append(
            """
            (
                UPPER(c.country_code) = UPPER(%s)
                OR LOWER(c.country_name) = LOWER(%s)
            )
            """
        )

        parameters.extend([
            country,
            country
        ])

    where_clause = " AND ".join(
        conditions
    )

    query = f"""
        SELECT
            o.org_rating AS rating,
            COUNT(o.org_id) AS count
        FROM organizations o
        JOIN state s
            ON o.state_id = s.state_id
        JOIN country c
            ON s.country_id = c.country_id
        WHERE {where_clause}
        GROUP BY o.org_rating
        ORDER BY o.org_rating
    """

    cursor.execute(
        query,
        tuple(parameters)
    )

    rows = cursor.fetchall()

    return [
        {
            "rating": int(row[0]),
            "count": int(row[1])
        }
        for row in rows
    ]


# PostgreSQL Organization Mix

def db_organization_mix(
    cursor,
    time_range: str,
    start_date=None,
    end_date=None,
    country="ALL"
) -> dict:
    """
    PostgreSQL implementation of the cumulative
    Profit vs Non-Profit trend.
    """

    if time_range in {
        "7D",
        "30D",
        "Custom"
    }:
        truncation = "day"
        output_format = "YYYY-MM-DD"
    else:
        truncation = "month"
        output_format = "YYYY-MM"

    conditions = [
        "o.org_type IN ('non_profit', 'for_profit')"
    ]

    parameters = []


    if end_date is not None:
        conditions.append(
            "o.created_at < (%s::date + INTERVAL '1 day')"
        )
        parameters.append(end_date)

    if country.upper() != "ALL":
        conditions.append(
            """
            (
                UPPER(c.country_code) = UPPER(%s)
                OR LOWER(c.country_name) = LOWER(%s)
            )
            """
        )

        parameters.extend([
            country,
            country
        ])

    where_clause = " AND ".join(
        conditions
    )

    query = f"""
        WITH period_counts AS (
            SELECT
                DATE_TRUNC(
                    '{truncation}',
                    o.created_at
                ) AS period,
                o.org_type,
                COUNT(o.org_id) AS new_count
            FROM organizations o
            JOIN state s
                ON o.state_id = s.state_id
            JOIN country c
                ON s.country_id = c.country_id
            WHERE {where_clause}
            GROUP BY
                DATE_TRUNC(
                    '{truncation}',
                    o.created_at
                ),
                o.org_type
        ),
        running_totals AS (
            SELECT
                period,
                org_type,
                SUM(new_count) OVER (
                    PARTITION BY org_type
                    ORDER BY period
                    ROWS BETWEEN UNBOUNDED PRECEDING
                    AND CURRENT ROW
                ) AS cumulative_count
            FROM period_counts
        )
        SELECT
            TO_CHAR(
                period,
                '{output_format}'
            ) AS period,
            org_type,
            cumulative_count
        FROM running_totals
        ORDER BY period, org_type
    """

    cursor.execute(
        query,
        tuple(parameters)
    )

    rows = cursor.fetchall()

    result = {
        "non_profit": [],
        "for_profit": []
    }

    for row in rows:

        period = row[0]
        organization_type = row[1]
        count = row[2]

        # Only display periods inside the selected window.
        if start_date is not None:

            if time_range in {
                "7D",
                "30D",
                "Custom"
            }:
                if period < start_date:
                    continue

            else:
                if period < start_date[:7]:
                    continue

        if organization_type in result:
            result[organization_type].append(
                {
                    "period": period,
                    "count": int(count)
                }
            )

    return result


# Lambda handler

def lambda_handler(event, context):

    try:
        request = parse_event(event)

        country = request.get(
            "country",
            "ALL"
        )

        if country is None:
            country = "ALL"

        # Read the two independent custom ranges

        rating_start = request.get(
            "rating_start_date"
        )

        rating_end = request.get(
            "rating_end_date"
        )

        type_start = request.get(
            "type_start_date"
        )

        type_end = request.get(
            "type_end_date"
        )

        # Validate each pair independently
    
        validate_date_pair(
            rating_start,
            rating_end,
            "Rating date range"
        )

        validate_date_pair(
            type_start,
            type_end,
            "Type date range"
        )

        has_rating_custom = (
            rating_start is not None
            or rating_end is not None
        )

        has_type_custom = (
            type_start is not None
            or type_end is not None
        )

        has_custom = (
            has_rating_custom
            or has_type_custom
        )

        # MOCK DATA
    
        if os.getenv(
            "USE_MOCK_DATA",
            "false"
        ).lower() == "true":

            organizations, states, countries = (
                load_mock_data()
            )

            data = prepare_data(
                organizations,
                states,
                countries
            )

            data = apply_country_filter(
                data,
                country
            )

            # Custom-only response

            if has_custom:

                response = {
                    "Custom": empty_chart_response()
                }

                if has_rating_custom:

                    response["Custom"][
                        "rating_distribution"
                    ] = calculate_rating_distribution(
                        data,
                        rating_start,
                        rating_end
                    )

                if has_type_custom:

                    response["Custom"][
                        "organization_mix_trend"
                    ] = calculate_organization_mix(
                        data,
                        "Custom",
                        type_start,
                        type_end
                    )

                return build_response(
                    200,
                    response
                )

    
            # No Custom parameters

            response = default_response()

            for time_range in [
                "7D",
                "30D",
                "1Y",
                "All"
            ]:

                start, end = get_fixed_window(
                    time_range
                )

                # Rating is window-scoped.
                response[time_range][
                    "rating_distribution"
                ] = calculate_rating_distribution(
                    data,
                    start,
                    end
                )

                # Organization mix is cumulative.
                response[time_range][
                    "organization_mix_trend"
                ] = calculate_organization_mix(
                    data,
                    time_range,
                    start,
                    end
                )

            return build_response(
                200,
                response
            )

        # REAL POSTGRESQL DATA

        connection = get_db_connection()

        try:
            cursor = connection.cursor()

            # Custom-only response

            if has_custom:

                response = {
                    "Custom": empty_chart_response()
                }

                if has_rating_custom:

                    response["Custom"][
                        "rating_distribution"
                    ] = db_rating_distribution(
                        cursor,
                        rating_start,
                        rating_end,
                        country
                    )

                if has_type_custom:

                    response["Custom"][
                        "organization_mix_trend"
                    ] = db_organization_mix(
                        cursor,
                        "Custom",
                        type_start,
                        type_end,
                        country
                    )

                return build_response(
                    200,
                    response
                )

            # No Custom parameters

            response = default_response()

            for time_range in [
                "7D",
                "30D",
                "1Y",
                "All"
            ]:

                start, end = get_fixed_window(
                    time_range
                )

                # Rating distribution uses only the
                # selected window.
                response[time_range][
                    "rating_distribution"
                ] = db_rating_distribution(
                    cursor,
                    start,
                    end,
                    country
                )

                # Trend uses cumulative historical data.
                response[time_range][
                    "organization_mix_trend"
                ] = db_organization_mix(
                    cursor,
                    time_range,
                    start,
                    end,
                    country
                )

            return build_response(
                200,
                response
            )

        finally:
            connection.close()

    except RequestValidationError as exc:

        return build_response(
            400,
            {
                "error": str(exc)
            }
        )

    except FileNotFoundError as exc:

        return build_response(
            500,
            {
                "error": (
                    "Mock data file could not be found: "
                    f"{exc.filename}"
                )
            }
        )

    except Exception as exc:

        print(
            f"Rating & Type analytics failed: {exc}"
        )

        return build_response(
            500,
            {
                "error": "Internal server error."
            }
        )


# Local testing

if __name__ == "__main__":

    test_event = {}

    result = lambda_handler(
        test_event,
        None
    )

    print(
        json.dumps(
            result,
            indent=2
        )
    )