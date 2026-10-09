"""Rating & Type Analytics API for the Organization Analytics dashboard."""

import json
import os
from datetime import datetime

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None


DEFAULT_DATA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "sql",
    )
)

MOCK_DATA_DIR = os.getenv("MOCK_DATA_DIR", DEFAULT_DATA_DIR)

SCHEMA_NAME = os.getenv(
    "DB_SCHEMA",
    "virginia_dev_saayam_rdbms",
)

ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
STATE_TABLE = f"{SCHEMA_NAME}.state"
COUNTRY_TABLE = f"{SCHEMA_NAME}.country"


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
    """Build a Lambda-compatible response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def use_mock_data():
    """Return True when local CSV mock data should be used."""
    value = os.getenv("USE_MOCK_DATA", "true")
    return value.strip().lower() in {
        "true",
        "1",
        "yes",
        "y",
    }


def find_csv(*filenames):
    """Return the first matching CSV in MOCK_DATA_DIR."""
    for filename in filenames:
        path = os.path.join(MOCK_DATA_DIR, filename)

        if os.path.exists(path):
            return path

    raise FileNotFoundError(
        f"Could not find any of: {', '.join(filenames)}"
    )


def normalize_org_type(value):
    """Normalize source organization types to API series names."""
    normalized = (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    mapping = {
        "non_profit": "non_profit",
        "nonprofit": "non_profit",
        "for_profit": "for_profit",
        "forprofit": "for_profit",
    }

    return mapping.get(normalized)


def prepare_data(data):
    """Normalize common organization analytics fields."""
    frame = data.copy()

    frame["created_at"] = pd.to_datetime(
        frame["created_at"],
        errors="coerce",
    )

    frame["org_rating"] = pd.to_numeric(
        frame["org_rating"],
        errors="coerce",
    )

    frame["org_type"] = frame["org_type"].apply(
        normalize_org_type
    )

    frame["country_code"] = (
        frame["country_code"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    frame["country_name"] = (
        frame["country_name"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    return frame


def load_mock_data():
    """Load organization analytics data from local CSV files."""
    organizations_path = find_csv("organizations.csv")
    states_path = find_csv("state.csv", "states.csv")
    countries_path = find_csv("country.csv", "countries.csv")

    organizations = pd.read_csv(organizations_path)
    states = pd.read_csv(states_path)
    countries = pd.read_csv(countries_path)

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
            "organizations.csv missing columns: "
            f"{sorted(missing_org)}"
        )

    if missing_state:
        raise ValueError(
            "state CSV missing columns: "
            f"{sorted(missing_state)}"
        )

    if missing_country:
        raise ValueError(
            "country CSV missing columns: "
            f"{sorted(missing_country)}"
        )

    if "country_name" not in countries.columns:
        countries["country_name"] = ""

    state_lookup = states[
        [
            "state_id",
            "country_id",
        ]
    ].drop_duplicates()

    country_lookup = countries[
        [
            "country_id",
            "country_code",
            "country_name",
        ]
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

    return prepare_data(merged)


def get_db_connection():
    """Create a PostgreSQL connection using environment variables."""
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is required when USE_MOCK_DATA is false"
        )

    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"),
    )


def load_database_data():
    """Load organization analytics data from PostgreSQL."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        query = f"""
            SELECT
                o.org_id,
                o.org_rating,
                o.org_type,
                o.state_id,
                o.created_at,
                c.country_code,
                c.country_name
            FROM {ORGANIZATIONS_TABLE} o
            LEFT JOIN {STATE_TABLE} s
                ON o.state_id = s.state_id
            LEFT JOIN {COUNTRY_TABLE} c
                ON s.country_id = c.country_id
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        columns = [
            "org_id",
            "org_rating",
            "org_type",
            "state_id",
            "created_at",
            "country_code",
            "country_name",
        ]

        data = pd.DataFrame(
            rows,
            columns=columns,
        )

        return prepare_data(data)

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()


def load_data():
    """Load data from mock CSVs or PostgreSQL."""
    if use_mock_data():
        return load_mock_data()

    return load_database_data()


def validate_country(body):
    """Validate and normalize the optional country filter."""
    country = body.get("country", "ALL")

    if country is None:
        return "ALL"

    if not isinstance(country, str):
        raise ValueError("country must be a string")

    country = country.strip()

    if not country:
        raise ValueError("country cannot be empty")

    return country


def filter_by_country(data, country):
    """Filter organizations by country name or country code."""
    if country.upper() == "ALL":
        return data.copy()

    target = country.upper()

    code_match = (
        data["country_code"]
        .astype(str)
        .str.upper()
        == target
    )

    name_match = (
        data["country_name"]
        .astype(str)
        .str.upper()
        == target
    )

    return data[
        code_match | name_match
    ].copy()


def validate_date_pair(
    body,
    start_key,
    end_key,
    label,
):
    """Validate one optional Custom date range."""
    pair_present = (
        start_key in body
        or end_key in body
    )

    if not pair_present:
        return None

    start_value = body.get(start_key)
    end_value = body.get(end_key)

    if not start_value or not end_value:
        raise ValueError(
            f"{label} requires both "
            f"{start_key} and {end_key}"
        )

    try:
        start_date = pd.Timestamp(
            datetime.strptime(
                start_value,
                "%Y-%m-%d",
            )
        )

        end_date = pd.Timestamp(
            datetime.strptime(
                end_value,
                "%Y-%m-%d",
            )
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
    """Return the inclusive window for a fixed bucket."""
    today = current_date()

    if bucket == "7D":
        return (
            today - pd.Timedelta(days=6),
            today,
        )

    if bucket == "30D":
        return (
            today - pd.Timedelta(days=29),
            today,
        )

    if bucket == "1Y":
        return (
            today - pd.Timedelta(days=364),
            today,
        )

    if bucket == "All":
        return None

    raise ValueError(
        f"Unsupported bucket: {bucket}"
    )


def filter_by_window(data, date_range):
    """Filter organizations to an inclusive date range."""
    valid = data[
        data["created_at"].notna()
    ].copy()

    if date_range is None:
        return valid

    start_date, end_date = date_range

    end_exclusive = (
        end_date
        + pd.Timedelta(days=1)
    )

    return valid[
        (valid["created_at"] >= start_date)
        & (
            valid["created_at"]
            < end_exclusive
        )
    ].copy()


def build_rating_distribution(
    data,
    date_range,
):
    """Build window-scoped counts by literal rating."""
    window_data = filter_by_window(
        data,
        date_range,
    )

    valid_ratings = window_data[
        window_data["org_rating"].between(
            1,
            5,
            inclusive="both",
        )
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
        for row in grouped.itertuples(
            index=False
        )
    ]


def period_labels(data, granularity):
    """Return period labels for trend grouping."""
    if granularity == "day":
        return (
            data["created_at"]
            .dt.strftime("%Y-%m-%d")
        )

    if granularity == "month":
        return (
            data["created_at"]
            .dt.strftime("%Y-%m")
        )

    raise ValueError(
        f"Unsupported granularity: {granularity}"
    )


def period_end(period, granularity):
    """Return exclusive end timestamp for a period."""
    if granularity == "day":
        return (
            pd.Timestamp(period)
            + pd.Timedelta(days=1)
        )

    if granularity == "month":
        return (
            pd.Timestamp(f"{period}-01")
            + pd.DateOffset(months=1)
        )

    raise ValueError(
        f"Unsupported granularity: {granularity}"
    )


def build_type_series(
    data,
    date_range,
    granularity,
    org_type,
):
    """
    Build one cumulative organization-type series.

    Periods are sparse and only appear when at least one new
    organization of this type was created during the bucket.
    """
    valid_data = data[
        data["created_at"].notna()
        & (data["org_type"] == org_type)
    ].copy()

    window_data = filter_by_window(
        valid_data,
        date_range,
    )

    if window_data.empty:
        return []

    window_data["period"] = period_labels(
        window_data,
        granularity,
    )

    periods = sorted(
        window_data["period"].unique()
    )

    results = []

    for period in periods:
        cutoff = period_end(
            period,
            granularity,
        )

        count = int(
            (
                valid_data["created_at"]
                < cutoff
            ).sum()
        )

        results.append(
            {
                "period": period,
                "count": count,
            }
        )

    return results


def build_organization_mix_trend(
    data,
    date_range,
    granularity,
):
    """Build cumulative non-profit and for-profit trend series."""
    return {
        "non_profit": build_type_series(
            data,
            date_range,
            granularity,
            "non_profit",
        ),
        "for_profit": build_type_series(
            data,
            date_range,
            granularity,
            "for_profit",
        ),
    }


def build_bucket(
    data,
    date_range,
    granularity,
):
    """Build one complete fixed time bucket."""
    return {
        "rating_distribution": (
            build_rating_distribution(
                data,
                date_range,
            )
        ),
        "organization_mix_trend": (
            build_organization_mix_trend(
                data,
                date_range,
                granularity,
            )
        ),
    }


def empty_custom_bucket():
    """Return the required empty Custom structure."""
    return {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }


def build_payload(body):
    """Build the Rating & Type analytics response."""
    country = validate_country(body)

    rating_range = validate_date_pair(
        body,
        "rating_start_date",
        "rating_end_date",
        "Rating Custom range",
    )

    type_range = validate_date_pair(
        body,
        "type_start_date",
        "type_end_date",
        "Type Custom range",
    )

    data = load_data()

    data = filter_by_country(
        data,
        country,
    )

    rating_custom_present = (
        "rating_start_date" in body
        or "rating_end_date" in body
    )

    type_custom_present = (
        "type_start_date" in body
        or "type_end_date" in body
    )

    if (
        rating_custom_present
        or type_custom_present
    ):
        custom = empty_custom_bucket()

        if rating_custom_present:
            custom["rating_distribution"] = (
                build_rating_distribution(
                    data,
                    rating_range,
                )
            )

        if type_custom_present:
            custom["organization_mix_trend"] = (
                build_organization_mix_trend(
                    data,
                    type_range,
                    "day",
                )
            )

        return {
            "Custom": custom,
        }

    return {
        "7D": build_bucket(
            data,
            get_fixed_window("7D"),
            "day",
        ),
        "30D": build_bucket(
            data,
            get_fixed_window("30D"),
            "day",
        ),
        "1Y": build_bucket(
            data,
            get_fixed_window("1Y"),
            "month",
        ),
        "All": build_bucket(
            data,
            get_fixed_window("All"),
            "month",
        ),
        "Custom": empty_custom_bucket(),
    }


def lambda_handler(event, context):
    """AWS Lambda entry point for Rating & Type analytics."""
    try:
        body = parse_event_body(event)
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

    except Exception as exc:
        print(f"ERROR: {exc}")

        return build_response(
            500,
            {
                "error": (
                    "Unable to generate "
                    "Rating & Type analytics"
                )
            },
        )


def print_sample(label, event):
    """Run and print one local Lambda sample."""
    response = lambda_handler(
        event,
        None,
    )

    printable = {
        "statusCode": response[
            "statusCode"
        ],
        "body": json.loads(
            response["body"]
        ),
    }

    print(
        f"\n===== {label} ====="
    )

    print(
        json.dumps(
            printable,
            indent=2,
        )
    )


if __name__ == "__main__":
    os.environ.setdefault(
        "USE_MOCK_DATA",
        "true",
    )

    print_sample(
        "No body",
        {},
    )

    print_sample(
        "Country filter",
        {
            "body": json.dumps(
                {
                    "country": "AFG",
                }
            )
        },
    )

    print_sample(
        "Rating Custom only",
        {
            "body": json.dumps(
                {
                    "rating_start_date": "2025-01-01",
                    "rating_end_date": "2026-01-31",
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
                    "type_end_date": "2026-01-31",
                }
            )
        },
    )

    print_sample(
        "Both Custom ranges",
        {
            "body": json.dumps(
                {
                    "rating_start_date": "2025-01-01",
                    "rating_end_date": "2026-01-31",
                    "type_start_date": "2025-01-01",
                    "type_end_date": "2026-01-31",
                }
            )
        },
    )