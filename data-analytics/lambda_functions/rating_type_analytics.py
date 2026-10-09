import json
import os
from datetime import datetime

import pandas as pd

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

MOCK_DATA_DIR = os.getenv(
    "MOCK_DATA_DIR",
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "mock-data-generation",
    ),
)

ORGANIZATIONS_CSV = os.path.join(
    MOCK_DATA_DIR,
    "organizations.csv",
)

STATES_CSV = os.path.join(
    MOCK_DATA_DIR,
    "states.csv",
)

COUNTRIES_CSV = os.path.join(
    MOCK_DATA_DIR,
    "countries.csv",
)


# ---------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------

def load_mock_data():
    """
    Load organizations, states, and countries from local CSV files.
    """

    organizations = pd.read_csv(
        ORGANIZATIONS_CSV,
        dtype={
            "org_id": str,
            "state_id": str,
        },
    )

    states = pd.read_csv(
        STATES_CSV,
        dtype={
            "state_id": str,
            "country_id": str,
        },
    )

    countries = pd.read_csv(
        COUNTRIES_CSV,
        dtype={
            "country_id": str,
        },
    )

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="coerce",
    )

    organizations["org_rating"] = pd.to_numeric(
        organizations["org_rating"],
        errors="coerce",
    )

    return organizations, states, countries


def load_database_data():
    """
    Load organizations, states, and countries from PostgreSQL.

    psycopg2 is optional so local CSV testing works without it.
    """

    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is not installed. "
            "Use mock data locally or install the database dependency."
        )

    connection = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )

    try:
        with connection.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

            cursor.execute(
                """
                SELECT
                    org_id,
                    org_rating,
                    org_type,
                    state_id,
                    created_at
                FROM organizations
                """
            )
            organizations = pd.DataFrame(cursor.fetchall())

            cursor.execute(
                """
                SELECT
                    state_id,
                    country_id
                FROM states
                """
            )
            states = pd.DataFrame(cursor.fetchall())

            try:
                cursor.execute(
                    """
                    SELECT
                        country_id,
                        country_code,
                        country_name
                    FROM countries
                    """
                )
                countries = pd.DataFrame(cursor.fetchall())

            except Exception:
                connection.rollback()

                cursor.execute(
                    """
                    SELECT
                        country_id,
                        country_code
                    FROM countries
                    """
                )
                countries = pd.DataFrame(cursor.fetchall())

    finally:
        connection.close()

    if "org_id" in organizations.columns:
        organizations["org_id"] = (
            organizations["org_id"].astype(str)
        )

    if "state_id" in organizations.columns:
        organizations["state_id"] = (
            organizations["state_id"].astype(str)
        )

    if "state_id" in states.columns:
        states["state_id"] = states["state_id"].astype(str)

    if "country_id" in states.columns:
        states["country_id"] = (
            states["country_id"].astype(str)
        )

    if "country_id" in countries.columns:
        countries["country_id"] = (
            countries["country_id"].astype(str)
        )

    if "created_at" in organizations.columns:
        organizations["created_at"] = pd.to_datetime(
            organizations["created_at"],
            errors="coerce",
        )

    if "org_rating" in organizations.columns:
        organizations["org_rating"] = pd.to_numeric(
            organizations["org_rating"],
            errors="coerce",
        )

    return organizations, states, countries


def load_data():
    """
    Use mock CSV data locally by default.
    Set USE_MOCK_DATA=false to use PostgreSQL.
    """

    use_mock_data = (
        os.getenv("USE_MOCK_DATA", "true")
        .strip()
        .lower()
        == "true"
    )

    if use_mock_data:
        return load_mock_data()

    return load_database_data()


# ---------------------------------------------------------------------
# Country Filtering
# ---------------------------------------------------------------------

def apply_country_filter(
    organizations,
    states,
    countries,
    country,
):
    """
    Filter organizations by country name or country code.

    organizations.state_id
        -> states.country_id
        -> countries.country_id
    """

    if (
        country is None
        or str(country).strip() == ""
        or str(country).strip().lower() == "all"
    ):
        return organizations.copy()

    country_value = str(country).strip().lower()

    country_columns = ["country_id"]

    if "country_code" in countries.columns:
        country_columns.append("country_code")

    if "country_name" in countries.columns:
        country_columns.append("country_name")

    country_lookup = countries[
        country_columns
    ].copy()

    merged = organizations.merge(
        states[["state_id", "country_id"]],
        on="state_id",
        how="left",
    )

    merged = merged.merge(
        country_lookup,
        on="country_id",
        how="left",
    )

    country_match = pd.Series(
        False,
        index=merged.index,
    )

    if "country_code" in merged.columns:
        country_match = (
            country_match
            | (
                merged["country_code"]
                .astype(str)
                .str.strip()
                .str.lower()
                == country_value
            )
        )

    if "country_name" in merged.columns:
        country_match = (
            country_match
            | (
                merged["country_name"]
                .astype(str)
                .str.strip()
                .str.lower()
                == country_value
            )
        )

    filtered = merged[country_match].copy()

    original_columns = organizations.columns.tolist()

    return filtered[original_columns].copy()


# ---------------------------------------------------------------------
# Date Filtering
# ---------------------------------------------------------------------

def filter_by_date(
    organizations,
    time_range,
    start_date=None,
    end_date=None,
):
    """
    Filter organizations by the requested time window.

    7D     -> today and previous 6 days
    30D    -> today and previous 29 days
    1Y     -> today and previous 364 days
    All    -> no date restriction
    Custom -> inclusive custom date range
    """

    if organizations.empty:
        return organizations.copy()

    filtered = organizations.copy()

    today = pd.Timestamp.now().normalize()

    if time_range == "7D":
        range_start = today - pd.Timedelta(days=6)

        return filtered[
            filtered["created_at"] >= range_start
        ].copy()

    if time_range == "30D":
        range_start = today - pd.Timedelta(days=29)

        return filtered[
            filtered["created_at"] >= range_start
        ].copy()

    if time_range == "1Y":
        range_start = today - pd.Timedelta(days=364)

        return filtered[
            filtered["created_at"] >= range_start
        ].copy()

    if time_range == "All":
        return filtered.copy()

    if time_range == "Custom":
        range_start = pd.Timestamp(start_date)

        # Add one day so end_date is inclusive.
        range_end = (
            pd.Timestamp(end_date)
            + pd.Timedelta(days=1)
        )

        return filtered[
            (filtered["created_at"] >= range_start)
            & (filtered["created_at"] < range_end)
        ].copy()

    return filtered.copy()


# ---------------------------------------------------------------------
# Rating Distribution
# ---------------------------------------------------------------------

def calculate_rating_distribution(
    organizations,
    time_range,
    start_date=None,
    end_date=None,
):
    """
    Count organizations grouped by literal org_rating values 1-5.

    Ratings that do not occur are omitted.
    No zero-fill is performed.
    """

    filtered = filter_by_date(
        organizations,
        time_range,
        start_date,
        end_date,
    )

    if filtered.empty:
        return []

    filtered = filtered.copy()

    filtered["org_rating"] = pd.to_numeric(
        filtered["org_rating"],
        errors="coerce",
    )

    # Only literal ratings 1 through 5.
    filtered = filtered[
        filtered["org_rating"].isin([1, 2, 3, 4, 5])
    ]

    if filtered.empty:
        return []

    rating_counts = (
        filtered.groupby("org_rating")
        .size()
        .sort_index()
    )

    result = []

    for rating, count in rating_counts.items():
        result.append(
            {
                "rating": int(rating),
                "count": int(count),
            }
        )

    return result


# ---------------------------------------------------------------------
# Organization Mix Trend
# ---------------------------------------------------------------------

def normalize_org_type(series):
    """
    Normalize organization types.

    Examples:
        Non-Profit -> non_profit
        For-profit -> for_profit
    """
    return (
        series
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace("-", "_", regex=False)
        .str.replace(" ", "_", regex=False)
    )


def calculate_organization_mix_trend(
    organizations,
    time_range,
    start_date=None,
    end_date=None,
):
    """
    Return cumulative absolute organization counts by organization type.

    Supported organization types:
        non_profit
        for_profit

    Period grouping:
        7D     -> day
        30D    -> day
        Custom -> day
        1Y     -> month
        All    -> month

    Periods are sparse. A period appears only when at least one
    qualifying organization was created during that period.

    Counts are absolute cumulative totals across the entire
    country-filtered dataset up to the end of each emitted period.
    """

    filtered = filter_by_date(
        organizations,
        time_range,
        start_date,
        end_date,
    )

    if filtered.empty:
        return {
            "non_profit": [],
            "for_profit": [],
        }

    filtered = filtered.copy()

    filtered["org_type"] = normalize_org_type(
        filtered["org_type"]
    )

    # Only the two required organization types contribute
    # to the mix trend.
    filtered = filtered[
        filtered["org_type"].isin(
            ["non_profit", "for_profit"]
        )
    ].copy()

    if filtered.empty:
        return {
            "non_profit": [],
            "for_profit": [],
        }

    if time_range in ["7D", "30D", "Custom"]:
        period_format = "%Y-%m-%d"
    else:
        period_format = "%Y-%m"

    filtered["period"] = (
        filtered["created_at"]
        .dt.strftime(period_format)
    )

    # Determine which periods actually contain newly-created
    # organizations. This preserves sparse-period behavior.
    period_counts = (
        filtered.groupby("period")
        .size()
        .sort_index()
    )

    if period_counts.empty:
        return {
            "non_profit": [],
            "for_profit": [],
        }

    # Use the entire country-filtered dataset for cumulative totals,
    # not only the selected date window.
    all_data = organizations.copy()

    all_data["org_type"] = normalize_org_type(
        all_data["org_type"]
    )

    all_data = all_data[
        all_data["org_type"].isin(
            ["non_profit", "for_profit"]
        )
    ].copy()

    non_profit = []
    for_profit = []

    for period in period_counts.index:

        if period_format == "%Y-%m-%d":
            period_end = (
                pd.Timestamp(period)
                + pd.Timedelta(days=1)
            )
        else:
            period_end = (
                pd.Timestamp(period)
                + pd.DateOffset(months=1)
            )

        cumulative_non_profit = int(
            (
                (
                    all_data["created_at"]
                    < period_end
                )
                & (
                    all_data["org_type"]
                    == "non_profit"
                )
            ).sum()
        )

        cumulative_for_profit = int(
            (
                (
                    all_data["created_at"]
                    < period_end
                )
                & (
                    all_data["org_type"]
                    == "for_profit"
                )
            ).sum()
        )

        non_profit.append(
            {
                "period": period,
                "count": cumulative_non_profit,
            }
        )

        for_profit.append(
            {
                "period": period,
                "count": cumulative_for_profit,
            }
        )

    return {
        "non_profit": non_profit,
        "for_profit": for_profit,
    }


# ---------------------------------------------------------------------
# Bucket Builders
# ---------------------------------------------------------------------

def build_bucket(
    organizations,
    states,
    countries,
    country,
    time_range,
):
    """
    Build both charts for a fixed time bucket.
    """

    country_organizations = apply_country_filter(
        organizations,
        states,
        countries,
        country,
    )

    rating_distribution = (
        calculate_rating_distribution(
            country_organizations,
            time_range,
        )
    )

    organization_mix_trend = (
        calculate_organization_mix_trend(
            country_organizations,
            time_range,
        )
    )

    return {
        "rating_distribution": rating_distribution,
        "organization_mix_trend": organization_mix_trend,
    }


def build_custom_bucket(
    organizations,
    states,
    countries,
    country,
    rating_start_date=None,
    rating_end_date=None,
    type_start_date=None,
    type_end_date=None,
):
    """
    Build the Custom response.

    Rating and organization-type custom ranges are independent.
    """

    country_organizations = apply_country_filter(
        organizations,
        states,
        countries,
        country,
    )

    rating_distribution = []

    organization_mix_trend = {
        "non_profit": [],
        "for_profit": [],
    }

    if rating_start_date and rating_end_date:
        rating_distribution = (
            calculate_rating_distribution(
                country_organizations,
                "Custom",
                rating_start_date,
                rating_end_date,
            )
        )

    if type_start_date and type_end_date:
        organization_mix_trend = (
            calculate_organization_mix_trend(
                country_organizations,
                "Custom",
                type_start_date,
                type_end_date,
            )
        )

    return {
        "rating_distribution": rating_distribution,
        "organization_mix_trend": organization_mix_trend,
    }


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------

def validate_date_pair(
    start_date,
    end_date,
    label,
):
    """
    Validate an independent custom date pair.
    """

    if not start_date and not end_date:
        return None

    if not start_date or not end_date:
        return (
            f"Both {label}_start_date and "
            f"{label}_end_date are required."
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

    except (TypeError, ValueError):
        return (
            f"{label}_start_date and "
            f"{label}_end_date must use YYYY-MM-DD format."
        )

    if parsed_start > parsed_end:
        return (
            f"{label}_start_date cannot be after "
            f"{label}_end_date."
        )

    return None


# ---------------------------------------------------------------------
# Event / Response Helpers
# ---------------------------------------------------------------------

def parse_event(event):
    """
    Support direct local events and API Gateway body events.
    """

    if event is None:
        return {}

    if not isinstance(event, dict):
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        if body.strip() == "":
            return {}

        return json.loads(body)

    return {}


def build_response(
    status_code,
    body,
):
    """
    Build an API Gateway-compatible response.
    """

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


# ---------------------------------------------------------------------
# Lambda Handler
# ---------------------------------------------------------------------

def lambda_handler(event, context):
    """
    Organization Rating & Type Analytics Lambda.
    """

    try:
        request = parse_event(event)

        country = request.get("country", "ALL")

        rating_start_date = request.get(
            "rating_start_date"
        )

        rating_end_date = request.get(
            "rating_end_date"
        )

        type_start_date = request.get(
            "type_start_date"
        )

        type_end_date = request.get(
            "type_end_date"
        )

        # Validate rating dates independently.
        rating_error = validate_date_pair(
            rating_start_date,
            rating_end_date,
            "rating",
        )

        if rating_error:
            return build_response(
                400,
                {
                    "error": rating_error,
                },
            )

        # Validate organization-type dates independently.
        type_error = validate_date_pair(
            type_start_date,
            type_end_date,
            "type",
        )

        if type_error:
            return build_response(
                400,
                {
                    "error": type_error,
                },
            )

        organizations, states, countries = load_data()

        rating_custom_requested = bool(
            rating_start_date or rating_end_date
        )

        type_custom_requested = bool(
            type_start_date or type_end_date
        )

        custom_requested = (
            rating_custom_requested
            or type_custom_requested
        )

        # -------------------------------------------------------------
        # Custom mode
        # -------------------------------------------------------------
        # If either custom pair is supplied, return ONLY Custom.
        # Each chart uses its own independent custom range.
        # -------------------------------------------------------------

        if custom_requested:

            response_data = {
                "Custom": build_custom_bucket(
                    organizations,
                    states,
                    countries,
                    country,
                    rating_start_date,
                    rating_end_date,
                    type_start_date,
                    type_end_date,
                )
            }

            return build_response(
                200,
                response_data,
            )

        # -------------------------------------------------------------
        # Fixed mode
        # -------------------------------------------------------------
        # No custom pair:
        # return 7D, 30D, 1Y, All, and empty Custom.
        # -------------------------------------------------------------

        response_data = {}

        for time_range in [
            "7D",
            "30D",
            "1Y",
            "All",
        ]:
            response_data[time_range] = build_bucket(
                organizations,
                states,
                countries,
                country,
                time_range,
            )

        response_data["Custom"] = {
            "rating_distribution": [],
            "organization_mix_trend": {
                "non_profit": [],
                "for_profit": [],
            },
        }

        return build_response(
            200,
            response_data,
        )

    except json.JSONDecodeError:
        return build_response(
            400,
            {
                "error": "Request body must contain valid JSON."
            },
        )

    except Exception as exc:
        return build_response(
            500,
            {
                "error": str(exc)
            },
        )


# ---------------------------------------------------------------------
# Local Testing
# ---------------------------------------------------------------------

if __name__ == "__main__":

    sample_events = {
        "no_body": {},

        "country": {
            "country": "USA"
        },

        "rating_custom_only": {
            "rating_start_date": "2025-01-01",
            "rating_end_date": "2025-12-31",
        },

        "type_custom_only": {
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        },

        "both_custom": {
            "rating_start_date": "2024-01-01",
            "rating_end_date": "2024-12-31",
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        },
    }

    for test_name, sample_event in sample_events.items():

        print()
        print("=" * 70)
        print(f"TEST: {test_name}")
        print("=" * 70)

        result = lambda_handler(
            sample_event,
            None,
        )

        print(
            json.dumps(
                result,
                indent=2,
            )
        )