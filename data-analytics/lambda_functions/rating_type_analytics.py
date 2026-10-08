import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None



DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "mock-data-generation"

MOCK_DATA_DIR = Path(
    os.getenv("MOCK_DATA_DIR", DEFAULT_DATA_DIR)
)

USE_MOCK_DATA = os.getenv(
    "USE_MOCK_DATA",
    "true",
).strip().lower() in {"true", "1", "yes", "y"}

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

DB_SCHEMA = os.getenv(
    "DB_SCHEMA",
    "virginia_dev_saayam_rdbms",
)

BUCKET_ORDER = ("7D", "30D", "1Y", "All", "Custom")

def parse_event_body(event):
    """Parse the Lambda request body."""
    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body") from exc

    raise ValueError("Invalid request body")

def build_response(status_code, body):
    """Build a Lambda-compatible HTTP response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }

def find_csv(*filenames):
    """Return the first matching CSV file from MOCK_DATA_DIR."""
    for filename in filenames:
        path = MOCK_DATA_DIR / filename

        if path.exists():
            return path

    raise FileNotFoundError(
        f"Could not find any of: {', '.join(filenames)}"
    )


def load_mock_data():
    """Load and validate local mock CSV data."""
    organizations_path = find_csv("organizations.csv")
    states_path = find_csv("states.csv", "state.csv")
    countries_path = find_csv("countries.csv", "country.csv")

    organizations = pd.read_csv(
        organizations_path,
        encoding="utf-8-sig",
        dtype={
            "org_id": str,
            "state_id": str,
        },
    )

    states = pd.read_csv(
        states_path,
        encoding="utf-8-sig",
        dtype={
            "state_id": str,
            "country_id": str,
        },
    )

    countries = pd.read_csv(
        countries_path,
        encoding="utf-8-sig",
        dtype={
            "country_id": str,
        },
    )

    required_org_columns = {
        "org_id",
        "org_rating",
        "org_type",
        "state_id",
        "created_at",
    }

    required_state_columns = {
        "state_id",
        "country_id",
    }

    required_country_columns = {
        "country_id",
        "country_code",
    }

    missing_org = required_org_columns - set(organizations.columns)
    missing_state = required_state_columns - set(states.columns)
    missing_country = required_country_columns - set(countries.columns)

    if missing_org:
        raise ValueError(
            f"organizations.csv missing columns: {sorted(missing_org)}"
        )

    if missing_state:
        raise ValueError(
            f"states.csv missing columns: {sorted(missing_state)}"
        )

    if missing_country:
        raise ValueError(
            f"countries.csv missing columns: {sorted(missing_country)}"
        )

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="coerce",
    )

    organizations["org_rating"] = pd.to_numeric(
        organizations["org_rating"],
        errors="coerce",
    )

    organizations["org_type"] = (
        organizations["org_type"]
        .astype(str)
        .str.strip()
        .str.lower()
    )

    return organizations, states, countries

def get_database_connection():
    """Create a PostgreSQL connection for the real-data path."""
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is required when USE_MOCK_DATA=false"
        )

    required = {
        "DB_HOST": DB_HOST,
        "DB_NAME": DB_NAME,
        "DB_USER": DB_USER,
        "DB_PASSWORD": DB_PASSWORD,
    }

    missing = [
        name
        for name, value in required.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing database configuration: "
            + ", ".join(missing)
        )

    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        sslmode="require",
    )

def load_database_data():
    """Load Rating & Type source data from PostgreSQL."""
    connection = get_database_connection()

    try:
        organizations_query = f"""
            SELECT
                org_id,
                org_rating,
                org_type,
                state_id,
                created_at
            FROM {DB_SCHEMA}.organizations
        """

        states_query = f"""
            SELECT
                state_id,
                country_id
            FROM {DB_SCHEMA}.state
        """

        countries_query = f"""
            SELECT
                country_id,
                country_code,
                country_name
            FROM {DB_SCHEMA}.country
        """

        organizations = pd.read_sql_query(
            organizations_query,
            connection,
        )

        states = pd.read_sql_query(
            states_query,
            connection,
        )

        countries = pd.read_sql_query(
            countries_query,
            connection,
        )

    finally:
        connection.close()

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="coerce",
    )

    return organizations, states, countries

def load_data():
    """Load analytics data from mock CSVs or PostgreSQL."""
    if USE_MOCK_DATA:
        return load_mock_data()

    return load_database_data()

def apply_country_filter(
    organizations,
    states,
    countries,
    country="ALL",
):
    """Filter organizations by country name or country code."""
    if country is None:
        country = "ALL"

    requested_country = str(country).strip()

    if not requested_country:
        raise ValueError("country cannot be empty")

    if requested_country.upper() == "ALL":
        return organizations.copy()

    state_lookup = states[
        ["state_id", "country_id"]
    ].drop_duplicates()

    country_columns = [
        "country_id",
        "country_code",
    ]

    if "country_name" in countries.columns:
        country_columns.append("country_name")

    country_lookup = countries[
        country_columns
    ].drop_duplicates()

    merged = organizations.merge(
        state_lookup,
        on="state_id",
        how="left",
    )

    merged = merged.merge(
        country_lookup,
        on="country_id",
        how="left",
    )

    requested_lower = requested_country.lower()

    country_match = (
        merged["country_code"]
        .astype(str)
        .str.strip()
        .str.lower()
        .eq(requested_lower)
    )

    if "country_name" in merged.columns:
        country_match = country_match | (
            merged["country_name"]
            .astype(str)
            .str.strip()
            .str.lower()
            .eq(requested_lower)
        )

    return merged[country_match].copy()


def validate_date_pair(body, start_key, end_key, label):
    """Validate one optional Custom date range independently."""
    start_value = body.get(start_key)
    end_value = body.get(end_key)

    if start_value is None and end_value is None:
        return None

    if start_value is None or end_value is None:
        raise ValueError(
            f"{label} requires both {start_key} and {end_key}"
        )

    try:
        start_date = pd.Timestamp(
            datetime.strptime(start_value, "%Y-%m-%d")
        )
        end_date = pd.Timestamp(
            datetime.strptime(end_value, "%Y-%m-%d")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{label} dates must use YYYY-MM-DD format"
        ) from exc

    if start_date > end_date:
        raise ValueError(
            f"{start_key} cannot be after {end_key}"
        )

    return start_date, end_date


def current_date():
    """Return today's normalized local date."""
    return pd.Timestamp.now().normalize()

def get_fixed_window(bucket):
    """Return the inclusive date window for a fixed bucket."""
    today = current_date()

    if bucket == "7D":
        return today - pd.Timedelta(days=6), today

    if bucket == "30D":
        return today - pd.Timedelta(days=29), today

    if bucket == "1Y":
        return today - pd.Timedelta(days=364), today

    if bucket == "All":
        return None

    raise ValueError(f"Unsupported bucket: {bucket}")

def filter_by_window(organizations, date_range):
    """Filter organizations to an inclusive creation-date range."""
    valid = organizations[
        organizations["created_at"].notna()
    ].copy()

    if date_range is None:
        return valid

    start_date, end_date = date_range

    end_exclusive = end_date + pd.Timedelta(days=1)

    return valid[
        (valid["created_at"] >= start_date)
        & (valid["created_at"] < end_exclusive)
    ].copy()

def build_rating_distribution(
    organizations,
    date_range,
):
    """Count organizations by literal org_rating within a window."""
    window_data = filter_by_window(
        organizations,
        date_range,
    )

    if window_data.empty:
        return []

    valid_ratings = window_data[
        window_data["org_rating"].isin([1, 2, 3, 4, 5])
    ].copy()

    if valid_ratings.empty:
        return []

    grouped = (
        valid_ratings
        .groupby("org_rating")
        .size()
        .reset_index(name="count")
        .sort_values("org_rating")
    )

    return [
        {
            "rating": int(row.org_rating),
            "count": int(row.count),
        }
        for row in grouped.itertuples(index=False)
    ]

def period_series(frame, granularity):
    """Return period labels for organization creation dates."""
    if granularity == "day":
        return frame["created_at"].dt.strftime("%Y-%m-%d")

    if granularity == "month":
        return frame["created_at"].dt.strftime("%Y-%m")

    raise ValueError(
        f"Unsupported granularity: {granularity}"
    )

def period_end(period, granularity):
    """Return the exclusive end timestamp for one period."""
    if granularity == "day":
        return pd.Timestamp(period) + pd.Timedelta(days=1)

    if granularity == "month":
        return (
            pd.Timestamp(f"{period}-01")
            + pd.DateOffset(months=1)
        )

    raise ValueError(
        f"Unsupported granularity: {granularity}"
    )

def build_organization_mix_trend(
    organizations,
    date_range,
    granularity,
):
    """
    Build cumulative organization totals by organization type.

    Counts are absolute all-time running totals as of each displayed
    period. Periods are sparse: only periods with new organizations
    of that type are returned.
    """
    valid = organizations[
        organizations["created_at"].notna()
    ].copy()

    result = {
        "non_profit": [],
        "for_profit": [],
    }

    for org_type in ("non_profit", "for_profit"):
        type_data = valid[
            valid["org_type"] == org_type
        ].copy()

        window_data = filter_by_window(
            type_data,
            date_range,
        )

        if window_data.empty:
            continue

        window_data["period"] = period_series(
            window_data,
            granularity,
        )

        periods = sorted(
            window_data["period"].dropna().unique()
        )

        for period in periods:
            cutoff = period_end(
                period,
                granularity,
            )

            total_count = int(
                (
                    type_data["created_at"] < cutoff
                ).sum()
            )

            result[org_type].append(
                {
                    "period": str(period),
                    "count": total_count,
                }
            )

    return result

def empty_custom_bucket():
    """Return the required empty Custom response structure."""
    return {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }

def build_bucket(
    organizations,
    date_range,
    granularity,
):
    """Build both Rating & Type charts for one fixed bucket."""
    return {
        "rating_distribution": build_rating_distribution(
            organizations,
            date_range,
        ),
        "organization_mix_trend": build_organization_mix_trend(
            organizations,
            date_range,
            granularity,
        ),
    }

def build_payload(body):
    """Build the Rating & Type analytics response."""
    organizations, states, countries = load_data()

    country = body.get("country", "ALL")

    organizations = apply_country_filter(
        organizations,
        states,
        countries,
        country,
    )

    rating_custom_range = validate_date_pair(
        body,
        "rating_start_date",
        "rating_end_date",
        "Rating Distribution Custom range",
    )

    type_custom_range = validate_date_pair(
        body,
        "type_start_date",
        "type_end_date",
        "Profit vs Non-Profit Custom range",
    )

    has_custom = (
        rating_custom_range is not None
        or type_custom_range is not None
    )

    if has_custom:
        custom_bucket = empty_custom_bucket()

        if rating_custom_range is not None:
            custom_bucket["rating_distribution"] = (
                build_rating_distribution(
                    organizations,
                    rating_custom_range,
                )
            )

        if type_custom_range is not None:
            custom_bucket["organization_mix_trend"] = (
                build_organization_mix_trend(
                    organizations,
                    type_custom_range,
                    "day",
                )
            )

        return {
            "Custom": custom_bucket,
        }

    return {
        "7D": build_bucket(
            organizations,
            get_fixed_window("7D"),
            "day",
        ),
        "30D": build_bucket(
            organizations,
            get_fixed_window("30D"),
            "day",
        ),
        "1Y": build_bucket(
            organizations,
            get_fixed_window("1Y"),
            "month",
        ),
        "All": build_bucket(
            organizations,
            get_fixed_window("All"),
            "month",
        ),
        "Custom": empty_custom_bucket(),
    }

def lambda_handler(event, context):
    """AWS Lambda entry point for Rating & Type analytics."""
    try:
        body = parse_event_body(event)

        if not isinstance(body, dict):
            raise ValueError(
                "Request body must be a JSON object"
            )

        payload = build_payload(body)

        return build_response(
            200,
            payload,
        )

    except ValueError as exc:
        return build_response(
            400,
            {
                "error": str(exc),
            },
        )

    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")

        return build_response(
            500,
            {
                "error": "Required analytics data file was not found",
            },
        )

    except Exception as exc:
        print(f"ERROR: {exc}")

        return build_response(
            500,
            {
                "error": "Unable to generate Rating & Type analytics",
            },
        )

def print_sample(label, event):
    """Run and print one local Lambda sample event."""
    response = lambda_handler(event, None)

    try:
        parsed_body = json.loads(response["body"])
    except (TypeError, json.JSONDecodeError):
        parsed_body = response["body"]

    printable = {
        "statusCode": response["statusCode"],
        "body": parsed_body,
    }

    print(f"\n===== {label} =====")
    print(json.dumps(printable, indent=2))

if __name__ == "__main__":
    print_sample(
        "No body",
        {},
    )

    print_sample(
        "Country filter - USA",
        {
            "body": json.dumps(
                {
                    "country": "USA",
                }
            )
        },
    )

    print_sample(
        "Rating Custom only",
        {
            "body": json.dumps(
                {
                    "rating_start_date": "2026-01-01",
                    "rating_end_date": "2026-06-30",
                }
            )
        },
    )

    print_sample(
        "Type Custom only",
        {
            "body": json.dumps(
                {
                    "type_start_date": "2025-01-01",
                    "type_end_date": "2025-12-31",
                }
            )
        },
    )

    print_sample(
        "Both Custom ranges",
        {
            "body": json.dumps(
                {
                    "rating_start_date": "2026-01-01",
                    "rating_end_date": "2026-06-30",
                    "type_start_date": "2025-01-01",
                    "type_end_date": "2025-12-31",
                }
            )
        },
    )

    print_sample(
        "Invalid - incomplete Rating range",
        {
            "body": json.dumps(
                {
                    "rating_start_date": "2026-01-01",
                }
            )
        },
    )

    print_sample(
        "Invalid - Type start after end",
        {
            "body": json.dumps(
                {
                    "type_start_date": "2026-12-31",
                    "type_end_date": "2026-01-01",
                }
            )
        },
    )