"""Size and contribution analytics for the organization dashboard.

The Lambda supports local CSV-backed development and a PostgreSQL-backed
runtime. Local CSV files are intentionally kept outside version control and
located through ``MOCK_DATA_DIR``.
"""

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

try:
    import psycopg2
except ImportError:  # Local mock-data use must work without psycopg2.
    psycopg2 = None


FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
VALID_ORGANIZATION_TYPES = {"non_profit", "for_profit"}


class RequestValidationError(ValueError):
    """Raised when an analytics request contains invalid filters or dates."""


def _normalize_enum(value: Any) -> str:
    """Normalize enum-like values for comparison without changing output."""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _coerce_boolean(series: pd.Series) -> pd.Series:
    """Convert common CSV/database Boolean representations to bool values."""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)

    truthy = {"true", "1", "yes", "y", "t"}
    return series.fillna(False).map(lambda value: _normalize_enum(value) in truthy)


def _parse_event(event: Any) -> dict[str, Any]:
    """Return a request dictionary from direct or API Gateway-style input."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise RequestValidationError("Request must be a JSON object.")

    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError as exc:
            raise RequestValidationError("Request body must contain valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise RequestValidationError("Request body must be a JSON object.")
        return parsed
    raise RequestValidationError("Request body must be a JSON object.")


def _validate_date_pair(
    payload: dict[str, Any], start_key: str, end_key: str
) -> Optional[tuple[date, date]]:
    """Validate one optional, inclusive YYYY-MM-DD date pair."""
    start_value = payload.get(start_key)
    end_value = payload.get(end_key)

    if bool(start_value) != bool(end_value):
        raise RequestValidationError(
            f"{start_key} and {end_key} must be provided together."
        )
    if not start_value:
        return None

    try:
        start_date = datetime.strptime(str(start_value), "%Y-%m-%d").date()
        end_date = datetime.strptime(str(end_value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise RequestValidationError(
            f"{start_key} and {end_key} must use YYYY-MM-DD format."
        ) from exc

    if start_date > end_date:
        raise RequestValidationError(f"{start_key} cannot be after {end_key}.")
    return start_date, end_date


def _prepare_organizations(organizations: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize organization fields used by the analytics."""
    required = {
        "org_id",
        "org_size",
        "is_collaborator",
        "org_type",
        "state_id",
        "created_at",
    }
    missing = sorted(required.difference(organizations.columns))
    if missing:
        raise ValueError(f"organizations data is missing columns: {', '.join(missing)}")

    prepared = organizations.copy()
    prepared["created_at"] = pd.to_datetime(prepared["created_at"], errors="coerce")
    prepared = prepared.dropna(subset=["created_at"])
    prepared["is_collaborator"] = _coerce_boolean(prepared["is_collaborator"])

    if "is_contributor" not in prepared.columns:
        prepared["is_contributor"] = False
    else:
        prepared["is_contributor"] = _coerce_boolean(prepared["is_contributor"])

    return prepared


def load_mock_data(mock_data_dir: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load the three local CSV tables required by this API."""
    organizations = pd.read_csv(os.path.join(mock_data_dir, "organizations.csv"))
    states = pd.read_csv(os.path.join(mock_data_dir, "states.csv"))
    countries = pd.read_csv(os.path.join(mock_data_dir, "countries.csv"))
    return _prepare_organizations(organizations), states, countries


def load_postgres_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load required columns from PostgreSQL using environment configuration."""
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required when USE_MOCK_DATA is false.")

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
            SELECT org_id, org_size, is_collaborator, is_contributor,
                   org_type, state_id, created_at
            FROM organizations
            """,
            connection,
        )
        states = pd.read_sql_query(
            "SELECT state_id, country_id FROM states", connection
        )
        countries = pd.read_sql_query(
            "SELECT country_id, country_code, country_name FROM countries",
            connection,
        )
    finally:
        connection.close()

    return _prepare_organizations(organizations), states, countries


def join_location_data(
    organizations: pd.DataFrame,
    states: pd.DataFrame,
    countries: pd.DataFrame,
) -> pd.DataFrame:
    """Join organizations to their country through the states table."""
    state_required = {"state_id", "country_id"}
    country_required = {"country_id", "country_code"}
    if not state_required.issubset(states.columns):
        raise ValueError("states data must include state_id and country_id.")
    if not country_required.issubset(countries.columns):
        raise ValueError("countries data must include country_id and country_code.")

    country_columns = ["country_id", "country_code"]
    if "country_name" in countries.columns:
        country_columns.append("country_name")

    return organizations.merge(
        states[["state_id", "country_id"]], on="state_id", how="left"
    ).merge(countries[country_columns], on="country_id", how="left")


def apply_common_filters(
    data: pd.DataFrame, country: Any = "ALL", organization_type: Any = "ALL"
) -> pd.DataFrame:
    """Apply country and organization-type filters to both charts."""
    filtered = data.copy()

    country_value = str(country or "ALL").strip()
    if country_value.upper() != "ALL":
        country_match = filtered["country_code"].fillna("").astype(str).str.casefold().eq(
            country_value.casefold()
        )
        if "country_name" in filtered.columns:
            normalized_country = _normalize_enum(country_value)
            country_match |= (
                filtered["country_name"]
                .fillna("")
                .map(_normalize_enum)
                .eq(normalized_country)
            )
        filtered = filtered[country_match]

    type_value = _normalize_enum(organization_type or "ALL")
    if type_value != "all":
        if type_value not in VALID_ORGANIZATION_TYPES:
            raise RequestValidationError(
                "organization_type must be non_profit, for_profit, or ALL."
            )
        filtered = filtered[filtered["org_type"].map(_normalize_enum).eq(type_value)]

    return filtered


def filter_by_date_range(
    data: pd.DataFrame, start_date: Optional[date], end_date: Optional[date]
) -> pd.DataFrame:
    """Return rows created within an inclusive date window."""
    if start_date is None or end_date is None:
        return data.copy()
    created_dates = data["created_at"].dt.date
    return data[created_dates.between(start_date, end_date)]


def build_organizations_by_size(data: pd.DataFrame) -> list[dict[str, Any]]:
    """Count organizations for every size value present in the window."""
    if data.empty:
        return []

    counts = data.dropna(subset=["org_size"]).groupby("org_size", sort=True).size()
    return [
        {"size": str(size), "count": int(count)}
        for size, count in counts.items()
    ]


def build_collaborator_vs_contributor(data: pd.DataFrame) -> list[dict[str, Any]]:
    """Calculate independent collaborator and contributor counts and shares."""
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


def _empty_charts() -> dict[str, list[dict[str, Any]]]:
    return {"organizations_by_size": [], "collaborator_vs_contributor": []}


def _build_charts(data: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    if data.empty:
        return _empty_charts()
    return {
        "organizations_by_size": build_organizations_by_size(data),
        "collaborator_vs_contributor": build_collaborator_vs_contributor(data),
    }


def build_response(payload: dict[str, Any], today: Optional[date] = None) -> dict[str, Any]:
    """Build either the fixed-bucket response or Custom-only response."""
    size_range = _validate_date_pair(payload, "size_start_date", "size_end_date")
    contribution_range = _validate_date_pair(
        payload, "contribution_start_date", "contribution_end_date"
    )

    use_mock_data = os.environ.get("USE_MOCK_DATA", "true").lower() == "true"
    if use_mock_data:
        mock_data_dir = os.environ.get("MOCK_DATA_DIR")
        if not mock_data_dir:
            raise RuntimeError("MOCK_DATA_DIR must be set when USE_MOCK_DATA is true.")
        organizations, states, countries = load_mock_data(mock_data_dir)
    else:
        organizations, states, countries = load_postgres_data()

    data = join_location_data(organizations, states, countries)
    data = apply_common_filters(
        data,
        country=payload.get("country", "ALL"),
        organization_type=payload.get("organization_type", "ALL"),
    )

    if size_range or contribution_range:
        custom = _empty_charts()
        if size_range:
            custom["organizations_by_size"] = build_organizations_by_size(
                filter_by_date_range(data, *size_range)
            )
        if contribution_range:
            custom["collaborator_vs_contributor"] = (
                build_collaborator_vs_contributor(
                    filter_by_date_range(data, *contribution_range)
                )
            )
        return {"Custom": custom}

    current_date = today or datetime.now().date()
    bucket_ranges = {
        "7D": (current_date - timedelta(days=7), current_date),
        "30D": (current_date - timedelta(days=30), current_date),
        "1Y": (current_date - timedelta(days=365), current_date),
        "All": (None, None),
    }

    response = {
        bucket: _build_charts(filter_by_date_range(data, start, end))
        for bucket, (start, end) in bucket_ranges.items()
    }
    response["Custom"] = _empty_charts()
    return response


def lambda_handler(event: Any, context: Any = None) -> dict[str, Any]:
    """AWS Lambda entry point for Size & Contribution analytics."""
    del context
    try:
        payload = _parse_event(event)
        response = build_response(payload)
        return {"statusCode": 200, "body": json.dumps(response)}
    except RequestValidationError as exc:
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        return {"statusCode": 500, "body": json.dumps({"error": str(exc)})}


if __name__ == "__main__":
    sample_events = {
        "No filters": {},
        "Country": {"country": "USA"},
        "Organization type": {"organization_type": "non_profit"},
        "Size Custom": {
            "size_start_date": "2025-01-01",
            "size_end_date": "2026-12-31",
        },
        "Contribution Custom": {
            "contribution_start_date": "2025-01-01",
            "contribution_end_date": "2026-12-31",
        },
        "Both Custom ranges": {
            "size_start_date": "2025-01-01",
            "size_end_date": "2026-12-31",
            "contribution_start_date": "2025-01-01",
            "contribution_end_date": "2026-12-31",
        },
    }
    for label, sample_event in sample_events.items():
        print(f"\n=== {label} ===")
        print(json.dumps(lambda_handler(sample_event), indent=2))
