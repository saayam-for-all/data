import json
import os
from datetime import date, datetime, timedelta

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None


USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "false").lower() == "true"
MOCK_DATA_DIR = os.getenv("MOCK_DATA_DIR", "")

VALID_ORG_TYPES = ("non_profit", "for_profit")

REQUIRED_ORGANIZATION_COLUMNS = {
    "org_id",
    "org_rating",
    "org_type",
    "state_id",
    "created_at",
}

REQUIRED_STATE_COLUMNS = {
    "state_id",
    "country_id",
}

REQUIRED_COUNTRY_COLUMNS = {
    "country_id",
}


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event, context):
    """
    Entry point for Rating & Type analytics.

    Normal request:
        returns 7D, 30D, 1Y, All, Custom

    Request containing either Custom date pair:
        returns Custom only
    """

    try:
        params = _parse_request(event)

        country = _parse_country(params)

        rating_range = _parse_date_range(
            params=params,
            start_key="rating_start_date",
            end_key="rating_end_date",
        )

        type_range = _parse_date_range(
            params=params,
            start_key="type_start_date",
            end_key="type_end_date",
        )

        data = _load_data()
        data = _filter_by_country(data, country)

        has_custom_range = rating_range is not None or type_range is not None

        if has_custom_range:
            result = _build_custom_response(
                data=data,
                rating_range=rating_range,
                type_range=type_range,
            )
        else:
            result = _build_standard_response(data)

        return _success_response(result)

    except ValueError as exc:
        return _error_response(400, str(exc))

    except Exception as exc:
        # Log the actual exception for Lambda logs,
        # but do not expose internal details to the client.
        print(f"Unhandled Rating & Type analytics error: {exc}")

        return _error_response(
            500,
            "Internal server error",
        )


# ---------------------------------------------------------------------------
# Request parsing and validation
# ---------------------------------------------------------------------------


def _parse_request(event):
    """
    Supports:
    1. API Gateway-style event with event['body']
    2. Direct dictionaries for local testing
    """

    if event is None:
        return {}

    if not isinstance(event, dict):
        raise ValueError("Request must be a JSON object.")

    if "body" not in event:
        return event

    body = event.get("body")

    if body is None or body == "":
        return {}

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("Request body must contain valid JSON.")

        if not isinstance(parsed, dict):
            raise ValueError("Request body must be a JSON object.")

        return parsed

    raise ValueError("Request body must be a JSON object.")


def _parse_country(params):
    """
    country:
        - defaults to ALL
        - accepts country code or country name
    """

    country = params.get("country", "ALL")

    if country is None:
        return "ALL"

    if not isinstance(country, str):
        raise ValueError("country must be a string.")

    country = country.strip()

    if not country:
        raise ValueError("country cannot be empty.")

    return country


def _parse_date_range(params, start_key, end_key):
    """
    Valid states:
        neither supplied -> None
        both supplied -> (start_date, end_date)

    Invalid:
        only one supplied
        malformed YYYY-MM-DD
        start > end
    """

    start_value = params.get(start_key)
    end_value = params.get(end_key)

    has_start = start_value not in (None, "")
    has_end = end_value not in (None, "")

    if not has_start and not has_end:
        return None

    if has_start != has_end:
        raise ValueError(f"{start_key} and {end_key} must be supplied together.")

    if not isinstance(start_value, str) or not isinstance(end_value, str):
        raise ValueError(f"{start_key} and {end_key} must use YYYY-MM-DD format.")

    try:
        start_date = datetime.strptime(
            start_value,
            "%Y-%m-%d",
        ).date()

        end_date = datetime.strptime(
            end_value,
            "%Y-%m-%d",
        ).date()

    except ValueError:
        raise ValueError(f"{start_key} and {end_key} must use YYYY-MM-DD format.")

    if start_date > end_date:
        raise ValueError(f"{start_key} cannot be after {end_key}.")

    return start_date, end_date


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_data():
    """
    No module-level data cache.

    Every Lambda invocation loads fresh data so a warm Lambda cannot keep
    returning stale CSV/database contents.
    """

    if USE_MOCK_DATA:
        return _load_mock_data()

    return _load_database_data()


def _load_mock_data():
    if not MOCK_DATA_DIR:
        raise ValueError("MOCK_DATA_DIR must be set when USE_MOCK_DATA=true.")

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

    organizations = pd.read_csv(organizations_path)
    states = pd.read_csv(states_path)
    countries = pd.read_csv(countries_path)

    return _prepare_data(
        organizations=organizations,
        states=states,
        countries=countries,
    )


def _load_database_data():
    """
    Real PostgreSQL path.

    Environment-variable names are not specified in the requirement.
    These are conventional names and should be changed only if the
    repository already uses different ones.
    """

    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required when USE_MOCK_DATA is false.")

    connection = None

    try:
        connection = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
        )

        organizations = _fetch_table(
            connection,
            "organizations",
        )

        states = _fetch_table(
            connection,
            "states",
        )

        countries = _fetch_table(
            connection,
            "countries",
        )

        return _prepare_data(
            organizations=organizations,
            states=states,
            countries=countries,
        )

    finally:
        if connection is not None:
            connection.close()


def _fetch_table(connection, table_name):
    """
    Reads a known application table through psycopg2.

    table_name is controlled internally, not supplied by the request.
    """

    allowed_tables = {
        "organizations",
        "states",
        "countries",
    }

    if table_name not in allowed_tables:
        raise ValueError("Unsupported database table.")

    cursor = connection.cursor()

    try:
        cursor.execute(f"SELECT * FROM {table_name}")

        rows = cursor.fetchall()

        columns = [description[0] for description in cursor.description]

        return pd.DataFrame(
            rows,
            columns=columns,
        )

    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------


def _prepare_data(
    organizations,
    states,
    countries,
):
    """
    Validates the required schema, normalizes important fields,
    and joins:

        organizations.state_id
            -> states.country_id
            -> countries
    """

    _validate_required_columns(
        organizations,
        REQUIRED_ORGANIZATION_COLUMNS,
        "organizations",
    )

    _validate_required_columns(
        states,
        REQUIRED_STATE_COLUMNS,
        "states",
    )

    _validate_required_columns(
        countries,
        REQUIRED_COUNTRY_COLUMNS,
        "countries",
    )

    if (
        "country_code" not in countries.columns
        and "country_name" not in countries.columns
    ):
        raise ValueError("countries data must contain country_code or country_name.")

    organizations = organizations.copy()
    states = states.copy()
    countries = countries.copy()

    # Prevent accidental count multiplication if lookup files
    # contain duplicate identifiers.
    states = states.drop_duplicates(
        subset=["state_id"],
        keep="first",
    )

    countries = countries.drop_duplicates(
        subset=["country_id"],
        keep="first",
    )

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="coerce",
        utc=True,
    )

    # Convert to timezone-naive UTC timestamps for simple comparisons.
    organizations["created_at"] = organizations["created_at"].dt.tz_convert(None)

    organizations["org_rating"] = pd.to_numeric(
        organizations["org_rating"],
        errors="coerce",
    )

    organizations["org_type"] = (
        organizations["org_type"].astype("string").str.strip().str.lower()
    )

    state_columns = [
        "state_id",
        "country_id",
    ]

    country_columns = [
        "country_id",
    ]

    if "country_code" in countries.columns:
        country_columns.append("country_code")

    if "country_name" in countries.columns:
        country_columns.append("country_name")

    data = organizations.merge(
        states[state_columns],
        on="state_id",
        how="left",
    )

    data = data.merge(
        countries[country_columns],
        on="country_id",
        how="left",
    )

    return data


def _validate_required_columns(
    dataframe,
    required_columns,
    source_name,
):
    missing = required_columns - set(dataframe.columns)

    if missing:
        missing_list = ", ".join(sorted(missing))

        raise ValueError(
            f"{source_name} data is missing required columns: {missing_list}"
        )


# ---------------------------------------------------------------------------
# Country filtering
# ---------------------------------------------------------------------------


def _filter_by_country(data, country):
    """
    ALL means no country filtering.

    Otherwise match either country_code or country_name,
    case-insensitively.
    """

    if country.upper() == "ALL":
        return data.copy()

    target = country.strip().casefold()

    mask = pd.Series(
        False,
        index=data.index,
    )

    if "country_code" in data.columns:
        code_match = (
            data["country_code"]
            .astype("string")
            .str.strip()
            .str.casefold()
            .eq(target)
            .fillna(False)
        )

        mask = mask | code_match

    if "country_name" in data.columns:
        name_match = (
            data["country_name"]
            .astype("string")
            .str.strip()
            .str.casefold()
            .eq(target)
            .fillna(False)
        )

        mask = mask | name_match

    return data.loc[mask].copy()


# ---------------------------------------------------------------------------
# Standard response
# ---------------------------------------------------------------------------


def _build_standard_response(data):
    """
    Requirement:

    exactly:
        7D
        30D
        1Y
        All
        Custom

    Custom is empty when no custom parameters were supplied.
    """

    today = _utc_today()

    seven_day_start = today - timedelta(days=6)
    thirty_day_start = today - timedelta(days=29)

    # Exactly 12 calendar months including the current month.
    one_year_start = _first_day_n_months_ago(
        today,
        11,
    )

    result = {
        "7D": _build_bucket(
            data=data,
            start_date=seven_day_start,
            end_date=today,
            period_type="day",
        ),
        "30D": _build_bucket(
            data=data,
            start_date=thirty_day_start,
            end_date=today,
            period_type="day",
        ),
        "1Y": _build_bucket(
            data=data,
            start_date=one_year_start,
            end_date=today,
            period_type="month",
        ),
        "All": _build_bucket(
            data=data,
            start_date=None,
            end_date=today,
            period_type="month",
        ),
        "Custom": _empty_bucket(),
    }

    return result


def _build_bucket(
    data,
    start_date,
    end_date,
    period_type,
):
    return {
        "rating_distribution": _build_rating_distribution(
            data=data,
            start_date=start_date,
            end_date=end_date,
        ),
        "organization_mix_trend": _build_organization_mix_trend(
            data=data,
            start_date=start_date,
            end_date=end_date,
            period_type=period_type,
        ),
    }


# ---------------------------------------------------------------------------
# Custom response
# ---------------------------------------------------------------------------


def _build_custom_response(
    data,
    rating_range,
    type_range,
):
    """
    Either custom pair switches the entire response into Custom-only mode.

    Each pair affects only its own chart.
    """

    rating_distribution = []

    organization_mix_trend = {
        "non_profit": [],
        "for_profit": [],
    }

    if rating_range is not None:
        rating_start, rating_end = rating_range

        rating_distribution = _build_rating_distribution(
            data=data,
            start_date=rating_start,
            end_date=rating_end,
        )

    if type_range is not None:
        type_start, type_end = type_range

        organization_mix_trend = _build_organization_mix_trend(
            data=data,
            start_date=type_start,
            end_date=type_end,
            period_type="day",
        )

    return {
        "Custom": {
            "rating_distribution": rating_distribution,
            "organization_mix_trend": organization_mix_trend,
        }
    }


# ---------------------------------------------------------------------------
# Chart 1: Rating Distribution
# ---------------------------------------------------------------------------


def _build_rating_distribution(
    data,
    start_date,
    end_date,
):
    """
    Window-scoped categorical counts.

    Example:
        rating 3 -> 4 organizations
        rating 4 -> 9 organizations

    Ratings absent from the data are NOT zero-filled.
    """

    window = _filter_date_window(
        data=data,
        start_date=start_date,
        end_date=end_date,
    )

    if window.empty:
        return []

    valid = window[
        window["org_rating"].between(
            1,
            5,
            inclusive="both",
        )
    ].copy()

    if valid.empty:
        return []

    grouped = (
        valid.groupby(
            "org_rating",
            dropna=True,
        )
        .size()
        .reset_index(name="count")
        .sort_values("org_rating")
    )

    result = []

    for _, row in grouped.iterrows():
        result.append(
            {
                "rating": int(row["org_rating"]),
                "count": int(row["count"]),
            }
        )

    return result


# ---------------------------------------------------------------------------
# Chart 2: Profit vs Non-Profit
# ---------------------------------------------------------------------------


def _build_organization_mix_trend(
    data,
    start_date,
    end_date,
    period_type,
):
    """
    Produces two independent cumulative series:

        non_profit
        for_profit

    Important:
    Counts are absolute/all-time cumulative totals.

    Example:

        100 non-profits existed before the 7D window.
        3 new ones appear on Monday.
        2 more appear on Wednesday.

    Returned values:

        Monday    103
        Wednesday 105

    Not:

        Monday    3
        Wednesday 5
    """

    if period_type not in {"day", "month"}:
        raise ValueError("period_type must be 'day' or 'month'.")

    result = {
        "non_profit": [],
        "for_profit": [],
    }

    valid = data[
        data["org_type"].isin(VALID_ORG_TYPES) & data["created_at"].notna()
    ].copy()

    if valid.empty:
        return result

    end_exclusive = pd.Timestamp(end_date) + pd.Timedelta(days=1)

    if start_date is None:
        baseline_data = valid.iloc[0:0]

        window = valid[valid["created_at"] < end_exclusive].copy()

    else:
        start_timestamp = pd.Timestamp(start_date)

        baseline_data = valid[valid["created_at"] < start_timestamp]

        window = valid[
            (valid["created_at"] >= start_timestamp)
            & (valid["created_at"] < end_exclusive)
        ].copy()

    if window.empty:
        return result

    if period_type == "day":
        window["period"] = window["created_at"].dt.strftime("%Y-%m-%d")

    else:
        window["period"] = window["created_at"].dt.strftime("%Y-%m")

    for org_type in VALID_ORG_TYPES:
        baseline_count = int((baseline_data["org_type"] == org_type).sum())

        type_window = window[window["org_type"] == org_type]

        if type_window.empty:
            continue

        grouped = type_window.groupby("period").size().sort_index()

        running_total = baseline_count
        series = []

        for period, new_count in grouped.items():
            running_total += int(new_count)

            series.append(
                {
                    "period": str(period),
                    "count": running_total,
                }
            )

        result[org_type] = series

    return result


# ---------------------------------------------------------------------------
# Shared date filtering
# ---------------------------------------------------------------------------


def _filter_date_window(
    data,
    start_date,
    end_date,
):
    """
    Inclusive dates:

        start_date <= created_at <= end_date

    Implemented using an exclusive timestamp at the beginning
    of the following day.
    """

    valid = data[data["created_at"].notna()].copy()

    if valid.empty:
        return valid

    end_exclusive = pd.Timestamp(end_date) + pd.Timedelta(days=1)

    mask = valid["created_at"] < end_exclusive

    if start_date is not None:
        start_timestamp = pd.Timestamp(start_date)

        mask = mask & (valid["created_at"] >= start_timestamp)

    return valid.loc[mask].copy()


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _utc_today():
    """
    Kept in a helper so tests can monkeypatch the current date.
    """

    return datetime.utcnow().date()


def _first_day_n_months_ago(
    current_date,
    months_ago,
):
    """
    Returns the first day of the month N months before current_date.

    Used so 1Y represents exactly 12 calendar months:
        current month + previous 11 months.

    This avoids accidentally creating a 13-month 1Y chart.
    """

    total_months = current_date.year * 12 + current_date.month - 1 - months_ago

    year = total_months // 12
    month = total_months % 12 + 1

    return date(
        year,
        month,
        1,
    )


# ---------------------------------------------------------------------------
# Empty structures
# ---------------------------------------------------------------------------


def _empty_bucket():
    return {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }


# ---------------------------------------------------------------------------
# HTTP responses
# ---------------------------------------------------------------------------


def _success_response(data):
    return {
        "statusCode": 200,
        "body": json.dumps(data),
    }


def _error_response(
    status_code,
    message,
):
    return {
        "statusCode": status_code,
        "body": json.dumps(
            {
                "error": message,
            }
        ),
    }


# ---------------------------------------------------------------------------
# Local testing
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    sample_events = [
        {
            "name": "No body",
            "event": {},
        },
        {
            "name": "Country filter",
            "event": {
                "country": "USA",
            },
        },
        {
            "name": "Rating custom only",
            "event": {
                "rating_start_date": "2026-01-01",
                "rating_end_date": "2026-06-30",
            },
        },
        {
            "name": "Type custom only",
            "event": {
                "type_start_date": "2025-01-01",
                "type_end_date": "2025-12-31",
            },
        },
        {
            "name": "Both custom ranges",
            "event": {
                "country": "USA",
                "rating_start_date": "2026-01-01",
                "rating_end_date": "2026-06-30",
                "type_start_date": "2025-01-01",
                "type_end_date": "2025-12-31",
            },
        },
    ]

    for sample in sample_events:
        print()
        print("=" * 80)
        print(sample["name"])
        print("=" * 80)

        response = lambda_handler(
            sample["event"],
            None,
        )

        print(
            json.dumps(
                json.loads(response["body"]),
                indent=2,
            )
        )
