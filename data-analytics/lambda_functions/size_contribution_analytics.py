"""Size & Contribution Analytics API for the Organization Dashboard.

Powers the Size & Contribution tab:
  - Organizations By Size
  - Collaborators vs Contributors

Supports local CSV-backed development (USE_MOCK_DATA=true + MOCK_DATA_DIR)
and an optional PostgreSQL path via psycopg2.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    import psycopg2  # type: ignore
except ImportError:  # pragma: no cover - optional for local mock runs
    psycopg2 = None


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "sql"

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
VALID_ORGANIZATION_TYPES = {"non_profit", "for_profit"}


def use_mock_data():
    """Whether to load local CSVs instead of Postgres."""
    return os.getenv("USE_MOCK_DATA", "true").lower() in {
        "1",
        "true",
        "yes",
        "y",
    }


def mock_data_dir():
    """Directory containing organizations/states/countries CSVs."""
    return Path(os.getenv("MOCK_DATA_DIR", DEFAULT_DATA_DIR))


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
            parsed = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body") from exc

        if not isinstance(parsed, dict):
            raise ValueError("Request body must be a JSON object")
        return parsed

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


def normalize_enum(value):
    """Normalize enum-like filter/data values for comparison."""
    return (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def coerce_boolean(series):
    """Convert common CSV/DB boolean representations to bool."""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)

    truthy = {"true", "1", "yes", "y", "t"}
    return (
        series.fillna(False)
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(truthy)
    )


def find_csv(*filenames):
    """Return the first matching CSV path from MOCK_DATA_DIR."""
    data_dir = mock_data_dir()
    for filename in filenames:
        path = data_dir / filename
        if path.exists():
            return path

    raise FileNotFoundError(
        f"Could not find any of: {', '.join(filenames)} in {data_dir}"
    )


def prepare_organizations(organizations):
    """Validate and normalize organization fields used by this API."""
    required = {
        "org_id",
        "org_size",
        "is_collaborator",
        "org_type",
        "state_id",
        "created_at",
    }
    missing = sorted(required - set(organizations.columns))
    if missing:
        raise ValueError(
            f"organizations data missing columns: {missing}"
        )

    prepared = organizations.copy()
    prepared["created_at"] = pd.to_datetime(
        prepared["created_at"],
        errors="coerce",
    )
    prepared["is_collaborator"] = coerce_boolean(
        prepared["is_collaborator"]
    )

    if "is_contributor" not in prepared.columns:
        prepared["is_contributor"] = False
    else:
        prepared["is_contributor"] = coerce_boolean(
            prepared["is_contributor"]
        )

    return prepared


def load_mock_data():
    """Load organization, state, and country CSVs for local testing."""
    organizations_path = find_csv("organizations.csv")
    states_path = find_csv("states.csv", "state.csv")
    countries_path = find_csv("countries.csv", "country.csv")

    organizations = pd.read_csv(organizations_path)
    states = pd.read_csv(states_path)
    countries = pd.read_csv(countries_path)

    return prepare_organizations(organizations), states, countries


def load_postgres_data():
    """Load required columns from PostgreSQL."""
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is required when USE_MOCK_DATA is false"
        )

    connection = psycopg2.connect(
        host=os.environ.get("DB_HOST"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
    )
    try:
        organizations = pd.read_sql_query(
            """
            SELECT
                org_id,
                org_size,
                is_collaborator,
                is_contributor,
                org_type,
                state_id,
                created_at
            FROM organizations
            """,
            connection,
        )
        states = pd.read_sql_query(
            "SELECT state_id, country_id FROM states",
            connection,
        )
        countries = pd.read_sql_query(
            """
            SELECT country_id, country_code, country_name
            FROM countries
            """,
            connection,
        )
    finally:
        connection.close()

    return prepare_organizations(organizations), states, countries


def load_data():
    """Load data from mock CSVs or Postgres depending on USE_MOCK_DATA."""
    if use_mock_data():
        return load_mock_data()
    return load_postgres_data()


def validate_date_pair(body, start_key, end_key, label):
    """Validate one optional Custom date range independently."""
    start_value = body.get(start_key)
    end_value = body.get(end_key)

    if start_value is None and end_value is None:
        return None

    if start_value in ("", None) and end_value in ("", None):
        return None

    if start_value in ("", None) or end_value in ("", None):
        raise ValueError(
            f"{label} requires both {start_key} and {end_key}"
        )

    try:
        start_date = pd.Timestamp(
            datetime.strptime(str(start_value), "%Y-%m-%d")
        )
        end_date = pd.Timestamp(
            datetime.strptime(str(end_value), "%Y-%m-%d")
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
        return today - pd.DateOffset(years=1), today

    if bucket == "All":
        return None

    raise ValueError(f"Unsupported bucket: {bucket}")


def filter_by_window(organizations, date_range):
    """Filter organizations to an inclusive created_at window."""
    valid = organizations[organizations["created_at"].notna()].copy()

    if date_range is None:
        return valid

    start_date, end_date = date_range
    end_exclusive = end_date + pd.Timedelta(days=1)

    return valid[
        (valid["created_at"] >= start_date)
        & (valid["created_at"] < end_exclusive)
    ].copy()


def join_location_data(organizations, states, countries):
    """Join organizations → states → countries for country filtering."""
    state_required = {"state_id", "country_id"}
    country_required = {"country_id", "country_code"}

    if not state_required.issubset(states.columns):
        raise ValueError(
            "states data must include state_id and country_id"
        )
    if not country_required.issubset(countries.columns):
        raise ValueError(
            "countries data must include country_id and country_code"
        )

    country_columns = ["country_id", "country_code"]
    if "country_name" in countries.columns:
        country_columns.append("country_name")

    merged = organizations.merge(
        states[["state_id", "country_id"]].drop_duplicates(),
        on="state_id",
        how="left",
    )
    return merged.merge(
        countries[country_columns].drop_duplicates(),
        on="country_id",
        how="left",
    )


def apply_common_filters(data, country="ALL", organization_type="ALL"):
    """Apply country and organization_type filters shared by both charts."""
    filtered = data.copy()

    country_value = str(country if country is not None else "ALL").strip()
    if country_value.upper() != "ALL":
        needle = normalize_enum(country_value)
        country_match = (
            filtered["country_code"]
            .fillna("")
            .map(normalize_enum)
            .eq(needle)
        )
        if "country_name" in filtered.columns:
            country_match |= (
                filtered["country_name"]
                .fillna("")
                .map(normalize_enum)
                .eq(needle)
            )
        filtered = filtered[country_match]

    type_value = normalize_enum(
        organization_type if organization_type is not None else "ALL"
    )
    if type_value != "all":
        if type_value not in VALID_ORGANIZATION_TYPES:
            raise ValueError(
                "organization_type must be non_profit, for_profit, or ALL"
            )
        filtered = filtered[
            filtered["org_type"].map(normalize_enum).eq(type_value)
        ]

    return filtered


def build_organizations_by_size(data):
    """Count organizations for every size value present in the window."""
    if data.empty:
        return []

    sized = data.dropna(subset=["org_size"])
    if sized.empty:
        return []

    counts = (
        sized.groupby("org_size", sort=False)
        .size()
        .reset_index(name="count")
    )

    return [
        {"size": str(row.org_size), "count": int(row.count)}
        for row in counts.itertuples(index=False)
    ]


def build_collaborator_vs_contributor(data):
    """Independent Collaborator / Contributor counts against window total."""
    if data.empty:
        return []

    total = len(data)
    collaborator_count = int(data["is_collaborator"].sum())
    contributor_count = int(data["is_contributor"].sum())

    return [
        {
            "type": "Collaborator",
            "count": collaborator_count,
            "percentage": round(collaborator_count * 100 / total, 1),
        },
        {
            "type": "Contributor",
            "count": contributor_count,
            "percentage": round(contributor_count * 100 / total, 1),
        },
    ]


def empty_charts():
    """Return both charts empty."""
    return {
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
    }


def build_charts(data):
    """Build both chart payloads for one window."""
    if data.empty:
        return empty_charts()

    return {
        "organizations_by_size": build_organizations_by_size(data),
        "collaborator_vs_contributor": build_collaborator_vs_contributor(
            data
        ),
    }


def build_payload(body):
    """
    Build the Size & Contribution response.

    - No Custom date pairs → 7D / 30D / 1Y / All / Custom (Custom empty).
    - Any Custom date pair → Custom-only object; each pair populates its
      own chart independently (both may be present and both evaluated).
    """
    size_range = validate_date_pair(
        body,
        "size_start_date",
        "size_end_date",
        "Organizations by Size Custom range",
    )
    contribution_range = validate_date_pair(
        body,
        "contribution_start_date",
        "contribution_end_date",
        "Collaborators vs Contributors Custom range",
    )

    organizations, states, countries = load_data()
    data = join_location_data(organizations, states, countries)
    data = apply_common_filters(
        data,
        country=body.get("country", "ALL"),
        organization_type=body.get("organization_type", "ALL"),
    )

    if size_range is not None or contribution_range is not None:
        custom = empty_charts()

        if size_range is not None:
            custom["organizations_by_size"] = build_organizations_by_size(
                filter_by_window(data, size_range)
            )

        if contribution_range is not None:
            custom["collaborator_vs_contributor"] = (
                build_collaborator_vs_contributor(
                    filter_by_window(data, contribution_range)
                )
            )

        return {"Custom": custom}

    response = {}
    for bucket in FIXED_BUCKETS:
        response[bucket] = build_charts(
            filter_by_window(data, get_fixed_window(bucket))
        )

    response["Custom"] = empty_charts()
    return response


def lambda_handler(event, context=None):
    """AWS Lambda entry point for Size & Contribution analytics."""
    del context
    try:
        body = parse_event_body(event)
        payload = build_payload(body)
        return build_response(200, payload)

    except ValueError as exc:
        return build_response(400, {"error": str(exc)})

    except Exception as exc:  # pragma: no cover - defensive
        print(f"ERROR: {exc}")
        return build_response(
            500,
            {"error": "Unable to generate Size & Contribution analytics"},
        )


def print_sample(label, event):
    """Run and print one local Lambda sample event."""
    response = lambda_handler(event, None)
    printable = {
        "statusCode": response["statusCode"],
        "body": json.loads(response["body"]),
    }
    print(f"\n===== {label} =====")
    print(json.dumps(printable, indent=2))


if __name__ == "__main__":
    print_sample("No body", {})

    print_sample(
        "Country filter",
        {"body": json.dumps({"country": "AFG"})},
    )

    print_sample(
        "Organization type filter",
        {"body": json.dumps({"organization_type": "non_profit"})},
    )

    print_sample(
        "Size Custom only",
        {
            "body": json.dumps(
                {
                    "size_start_date": "2025-01-01",
                    "size_end_date": "2026-06-30",
                }
            )
        },
    )

    print_sample(
        "Contribution Custom only",
        {
            "body": json.dumps(
                {
                    "contribution_start_date": "2025-01-01",
                    "contribution_end_date": "2025-12-31",
                }
            )
        },
    )

    print_sample(
        "Both Custom ranges",
        {
            "body": json.dumps(
                {
                    "country": "ALL",
                    "organization_type": "non_profit",
                    "size_start_date": "2026-01-01",
                    "size_end_date": "2026-06-30",
                    "contribution_start_date": "2025-01-01",
                    "contribution_end_date": "2025-12-31",
                }
            )
        },
    )
