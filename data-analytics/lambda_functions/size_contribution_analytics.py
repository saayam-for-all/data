import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None


SCHEMA_NAME = os.getenv("SCHEMA_NAME", "virginia_dev_saayam_rdbms")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MOCK_DATA_DIR = os.path.abspath(
    os.path.join(BASE_DIR, "..", "mock-data-generation")
)

REQUIRED_ORGANIZATION_COLUMNS = [
    "org_id",
    "org_size",
    "is_collaborator",
    "org_type",
    "state_id",
    "created_at",
]
REQUIRED_STATE_COLUMNS = ["state_id", "country_id"]
REQUIRED_COUNTRY_COLUMNS = ["country_id", "country_code"]
REQUIRED_ORG_TYPES = {"non_profit", "for_profit"}


class DataError(Exception):
    """Raised when required server-side data is missing or invalid."""


RESPONSE_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": RESPONSE_HEADERS,
        "body": json.dumps(body, default=str),
    }


def parse_event(event):
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise ValueError("Event must be a JSON object")

    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must contain valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Request body must contain a JSON object")
        return parsed
    raise ValueError("Request body must contain a JSON object")


def parse_date(value, field_name):
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must use YYYY-MM-DD format")

    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: expected YYYY-MM-DD") from exc

    return pd.Timestamp(parsed.date())


def parse_custom_range(request, start_key, end_key):
    start_value = request.get(start_key)
    end_value = request.get(end_key)

    if start_value is None and end_value is None:
        return None

    if start_value is None or end_value is None:
        raise ValueError(f"{start_key} and {end_key} must be provided together")

    start = parse_date(start_value, start_key)
    end = parse_date(end_value, end_key)

    if start > end:
        raise ValueError(f"{start_key} cannot be after {end_key}")

    return start, end


def _read_csv(data_dir, filename, required_columns):
    path = os.path.join(data_dir, filename)

    if not os.path.isfile(path):
        raise DataError(f"Missing required mock data file: {path}")

    dataframe = pd.read_csv(path, dtype=str)

    missing = [
        column for column in required_columns if column not in dataframe.columns
    ]
    if missing:
        raise DataError(
            f"{filename} is missing required columns: {', '.join(missing)}"
        )

    return dataframe.copy()


def _normalize_boolean_series(series, column_name):
    normalized = series.fillna("").astype(str).str.strip().str.lower()

    invalid = sorted(
        set(normalized[normalized.ne("")]) - {"true", "false"}
    )

    if invalid:
        raise DataError(
            f"{column_name} contains invalid boolean values: {', '.join(invalid)}"
        )

    return normalized.eq("true")


def load_mock_data(data_dir=None):
    data_dir = data_dir or os.environ.get(
        "MOCK_DATA_DIR", DEFAULT_MOCK_DATA_DIR
    )

    organizations = _read_csv(
        data_dir,
        "organizations.csv",
        REQUIRED_ORGANIZATION_COLUMNS,
    )
    states = _read_csv(
        data_dir,
        "states.csv",
        REQUIRED_STATE_COLUMNS,
    )
    countries = _read_csv(
        data_dir,
        "countries.csv",
        REQUIRED_COUNTRY_COLUMNS,
    )

    # Older mock data may omit is_contributor. Treat missing values as False.
    if "is_contributor" not in organizations.columns:
        organizations["is_contributor"] = "FALSE"

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="raise",
    )
    organizations["state_id"] = (
        organizations["state_id"].fillna("").astype(str)
    )
    organizations["org_size"] = (
        organizations["org_size"].fillna("").astype(str).str.strip()
    )
    organizations["org_type"] = (
        organizations["org_type"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    states["state_id"] = states["state_id"].fillna("").astype(str)
    states["country_id"] = states["country_id"].fillna("").astype(str)

    countries["country_id"] = countries["country_id"].fillna("").astype(str)
    countries["country_code"] = (
        countries["country_code"].fillna("").astype(str).str.strip()
    )

    organizations["is_collaborator_bool"] = _normalize_boolean_series(
        organizations["is_collaborator"],
        "is_collaborator",
    )
    organizations["is_contributor_bool"] = _normalize_boolean_series(
        organizations["is_contributor"],
        "is_contributor",
    )

    country_columns = ["country_id", "country_code"]

    if "country_name" in countries.columns:
        countries["country_name"] = (
            countries["country_name"].fillna("").astype(str).str.strip()
        )
        country_columns.append("country_name")

    location_map = states.merge(
        countries[country_columns],
        on="country_id",
        how="left",
        validate="many_to_one",
    )

    organizations = organizations.merge(
        location_map,
        on="state_id",
        how="left",
        validate="many_to_one",
    )

    missing_country_mask = (
        organizations["country_code"].isna()
        | organizations["country_code"].astype(str).str.strip().eq("")
    )
    missing_country_count = int(missing_country_mask.sum())
    if missing_country_count:
        print(
            "WARNING: "
            f"{missing_country_count} organization(s) could not be mapped "
            "to a country; using 'Unknown'."
        )

    organizations["country_code"] = (
        organizations["country_code"]
        .fillna("Unknown")
        .astype(str)
        .str.strip()
    )

    if "country_name" not in organizations.columns:
        organizations["country_name"] = ""
    else:
        organizations["country_name"] = (
            organizations["country_name"]
            .fillna("Unknown")
            .astype(str)
            .str.strip()
        )

    organizations.loc[
        organizations["country_code"].eq(""),
        "country_code",
    ] = "Unknown"

    if "country_name" in countries.columns:
        organizations.loc[
            organizations["country_name"].eq(""),
            "country_name",
        ] = "Unknown"

    return organizations


def get_db_connection():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required when USE_MOCK_DATA is false")

    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD must be set when USE_MOCK_DATA is false")

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "host.docker.internal"),
        database=os.getenv("DB_NAME", "Saayam"),
        user=os.getenv("DB_USER", "postgres"),
        password=password,
        port=os.getenv("DB_PORT", "5432"),
    )


def load_database_data():
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        query = f"""
            SELECT
                o.org_id,
                o.org_size,
                o.is_collaborator,
                o.is_contributor,
                o.org_type,
                o.state_id,
                o.created_at,
                COALESCE(c.country_code, 'Unknown') AS country_code
            FROM {SCHEMA_NAME}.organizations AS o
            LEFT JOIN {SCHEMA_NAME}.states AS s
                ON o.state_id = s.state_id
            LEFT JOIN {SCHEMA_NAME}.countries AS c
                ON s.country_id = c.country_id
        """

        cursor.execute(query)

        rows = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        organizations = pd.DataFrame(rows, columns=columns)

        if organizations.empty:
            organizations = pd.DataFrame(
                columns=[
                    "org_id",
                    "org_size",
                    "is_collaborator",
                    "is_contributor",
                    "org_type",
                    "state_id",
                    "created_at",
                    "country_code",
                ]
            )

        if "is_contributor" not in organizations.columns:
            organizations["is_contributor"] = "FALSE"

        organizations["created_at"] = pd.to_datetime(
            organizations["created_at"],
            errors="raise",
        )
        organizations["org_size"] = (
            organizations["org_size"].fillna("").astype(str).str.strip()
        )
        organizations["org_type"] = (
            organizations["org_type"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
        )
        organizations["country_code"] = (
            organizations["country_code"]
            .fillna("Unknown")
            .astype(str)
            .str.strip()
        )
        organizations.loc[
            organizations["country_code"].eq(""),
            "country_code",
        ] = "Unknown"

        organizations["is_collaborator_bool"] = _normalize_boolean_series(
            organizations["is_collaborator"],
            "is_collaborator",
        )
        organizations["is_contributor_bool"] = _normalize_boolean_series(
            organizations["is_contributor"],
            "is_contributor",
        )
        organizations["country_name"] = ""

        return organizations

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def load_data():
    use_mock_data = (
        os.getenv("USE_MOCK_DATA", "false").strip().lower() == "true"
    )

    if use_mock_data:
        return load_mock_data()

    return load_database_data()


def get_today():
    return pd.Timestamp(date.today())


def apply_filters(organizations, request):
    filtered = organizations.copy()

    country = request.get("country", "ALL")

    if (
        country is not None
        and str(country).strip()
        and str(country).strip().upper() != "ALL"
    ):
        value = str(country).strip().casefold()

        code_match = (
            filtered["country_code"].fillna("").astype(str).str.casefold()
            == value
        )
        name_match = (
            filtered["country_name"].fillna("").astype(str).str.casefold()
            == value
        )

        filtered = filtered[code_match | name_match]

    organization_type = request.get("organization_type", "ALL")

    if (
        organization_type is not None
        and str(organization_type).strip()
        and str(organization_type).strip().upper() != "ALL"
    ):
        organization_type = str(organization_type).strip().lower()

        if organization_type not in REQUIRED_ORG_TYPES:
            raise ValueError(
                "organization_type must be non_profit, for_profit, or ALL"
            )

        filtered = filtered[
            filtered["org_type"] == organization_type
        ]

    return filtered


def fixed_ranges(organizations):
    today = get_today()

    ranges = {
        "7D": (today - timedelta(days=6), today),
        "30D": (today - timedelta(days=29), today),
    }

    current_month = today.to_period("M")
    one_year_start = (
        (current_month - 11).start_time.normalize()
    )
    ranges["1Y"] = (one_year_start, today)

    if organizations.empty:
        ranges["All"] = (today, today)
    else:
        dates = organizations["created_at"].dt.normalize()
        ranges["All"] = (dates.min(), dates.max())

    return ranges


def _window(organizations, start, end):
    if organizations.empty:
        return organizations.copy()

    dates = organizations["created_at"].dt.normalize()

    return organizations[
        (dates >= start) & (dates <= end)
    ].copy()


def organizations_by_size(organizations, start, end):
    window = _window(organizations, start, end)

    if window.empty:
        return []

    grouped = (
        window[
            window["org_size"].notna()
            & window["org_size"].astype(str).ne("")
        ]
        .groupby("org_size", sort=False)
        .size()
        .reset_index(name="count")
    )

    return [
        {
            "size": str(row.org_size),
            "count": int(row.count),
        }
        for row in grouped.itertuples(index=False)
    ]


def percentage(count, total):
    if total == 0:
        return 0.0

    value = (
        Decimal(count * 100) / Decimal(total)
    ).quantize(
        Decimal("0.1"),
        rounding=ROUND_HALF_UP,
    )

    return float(value)


def collaborator_vs_contributor(organizations, start, end):
    window = _window(organizations, start, end)

    if window.empty:
        return []

    total = len(window)

    collaborator_count = int(
        window["is_collaborator_bool"].sum()
    )

    contributor_count = (
        int(window["is_contributor_bool"].sum())
        if "is_contributor_bool" in window.columns
        else 0
    )

    return [
        {
            "type": "Collaborator",
            "count": collaborator_count,
            "percentage": percentage(collaborator_count, total),
        },
        {
            "type": "Contributor",
            "count": contributor_count,
            "percentage": percentage(contributor_count, total),
        },
    ]


def build_bucket(organizations, start, end):
    return {
        "organizations_by_size": organizations_by_size(
            organizations,
            start,
            end,
        ),
        "collaborator_vs_contributor": collaborator_vs_contributor(
            organizations,
            start,
            end,
        ),
    }


def build_response_body(
    organizations,
    size_custom,
    contribution_custom,
):
    has_custom = (
        size_custom is not None
        or contribution_custom is not None
    )

    if has_custom:
        return {
            "Custom": {
                "organizations_by_size": (
                    []
                    if size_custom is None
                    else organizations_by_size(
                        organizations,
                        size_custom[0],
                        size_custom[1],
                    )
                ),
                "collaborator_vs_contributor": (
                    []
                    if contribution_custom is None
                    else collaborator_vs_contributor(
                        organizations,
                        contribution_custom[0],
                        contribution_custom[1],
                    )
                ),
            }
        }

    ranges = fixed_ranges(organizations)
    result = {}

    for bucket in ("7D", "30D", "1Y", "All"):
        result[bucket] = build_bucket(
            organizations,
            *ranges[bucket],
        )

    result["Custom"] = {
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
    }

    return result


def lambda_handler(event, context=None):
    try:
        request = parse_event(event)

        size_custom = parse_custom_range(
            request,
            "size_start_date",
            "size_end_date",
        )
        contribution_custom = parse_custom_range(
            request,
            "contribution_start_date",
            "contribution_end_date",
        )

        organizations = apply_filters(
            load_data(),
            request,
        )

        return build_response(
            200,
            build_response_body(
                organizations,
                size_custom,
                contribution_custom,
            ),
        )

    except ValueError as exc:
        return build_response(400, {"error": str(exc)})

    except DataError as exc:
        print(f"DATA ERROR: {exc}")
        return build_response(
            500,
            {"error": "Server-side data error"},
        )

    except RuntimeError as exc:
        print(f"SERVER CONFIGURATION ERROR: {exc}")
        return build_response(
            500,
            {"error": "Server configuration error"},
        )

    except Exception as exc:
        print(f"ERROR: {exc}")
        return build_response(
            500,
            {"error": "Internal server error"},
        )


def _print_sample(label, event):
    result = lambda_handler(event)

    print(
        f"\n=== {label} (status {result['statusCode']}) ==="
    )
    print(
        json.dumps(
            json.loads(result["body"]),
            indent=2,
        )
    )


if __name__ == "__main__":
    os.environ.setdefault("USE_MOCK_DATA", "true")

    _print_sample("No body", {})
    _print_sample("Country filter", {"country": "USA"})
    _print_sample(
        "Organization type filter",
        {"organization_type": "non_profit"},
    )
    _print_sample(
        "Size custom range only",
        {
            "size_start_date": "2025-01-01",
            "size_end_date": "2025-06-30",
        },
    )
    _print_sample(
        "Contribution custom range only",
        {
            "contribution_start_date": "2025-01-01",
            "contribution_end_date": "2025-06-30",
        },
    )
    _print_sample(
        "Both custom ranges",
        {
            "size_start_date": "2025-01-01",
            "size_end_date": "2025-06-30",
            "contribution_start_date": "2025-07-01",
            "contribution_end_date": "2025-09-30",
        },
    )
