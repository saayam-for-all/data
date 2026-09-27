import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None


VALID_ORGANIZATION_TYPES = {"non_profit", "for_profit"}


class RequestValidationError(ValueError):
    pass
def parse_event(event: Any) -> dict[str, Any]:
    """Parse direct Lambda or API Gateway-style request input."""
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
            payload = json.loads(body or "{}")
        except json.JSONDecodeError as exc:
            raise RequestValidationError(
                "Request body must contain valid JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise RequestValidationError(
                "Request body must be a JSON object."
            )

        return payload

    raise RequestValidationError("Request body must be a JSON object.")


def validate_date_pair(
    payload: dict[str, Any],
    start_key: str,
    end_key: str,
) -> Optional[tuple[date, date]]:
    """Validate an optional inclusive YYYY-MM-DD date range."""
    start_value = payload.get(start_key)
    end_value = payload.get(end_key)

    if bool(start_value) != bool(end_value):
        raise RequestValidationError(
            f"{start_key} and {end_key} must be provided together."
        )

    if not start_value:
        return None

    try:
        start_date = datetime.strptime(
            str(start_value), "%Y-%m-%d"
        ).date()

        end_date = datetime.strptime(
            str(end_value), "%Y-%m-%d"
        ).date()

    except ValueError as exc:
        raise RequestValidationError(
            f"{start_key} and {end_key} must use YYYY-MM-DD format."
        ) from exc

    if start_date > end_date:
        raise RequestValidationError(
            f"{start_key} cannot be after {end_key}."
        )

    return start_date, end_date
def prepare_organizations(organizations: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize organization fields used by Rating & Type analytics."""
    required = {
        "org_id",
        "org_rating",
        "org_type",
        "state_id",
        "created_at",
    }

    missing = sorted(required.difference(organizations.columns))
    if missing:
        raise ValueError(
            f"organizations data is missing columns: {', '.join(missing)}"
        )

    prepared = organizations.copy()

    prepared["created_at"] = pd.to_datetime(
        prepared["created_at"],
        errors="coerce",
    )

    prepared = prepared.dropna(subset=["created_at"])

    prepared["org_rating"] = pd.to_numeric(
        prepared["org_rating"],
        errors="coerce",
    )

    invalid_ratings = prepared[
        prepared["org_rating"].notna()
        & ~prepared["org_rating"].isin([1, 2, 3, 4, 5])
    ]

    if not invalid_ratings.empty:
        raise ValueError("org_rating must contain integer values from 1 to 5.")

    prepared["org_rating"] = prepared["org_rating"].astype("Int64")

    prepared["org_type"] = (
    prepared["org_type"]
    .astype("string")
    .str.strip()
    .str.lower()
    .str.replace("-", "_", regex=False)
    .str.replace(" ", "_", regex=False)
)


    invalid_types = prepared[
        prepared["org_type"].notna()
        & ~prepared["org_type"].isin(VALID_ORGANIZATION_TYPES)
    ]

    if not invalid_types.empty:
        raise ValueError(
            "org_type must contain only non_profit or for_profit."
        )

    return prepared


def load_mock_data(
    mock_data_dir: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load organizations, states, and countries from local CSV files."""
    organizations = pd.read_csv(
        os.path.join(mock_data_dir, "organizations.csv")
    )
    states = pd.read_csv(
        os.path.join(mock_data_dir, "states.csv")
    )
    countries = pd.read_csv(
        os.path.join(mock_data_dir, "countries.csv")
    )

    return prepare_organizations(organizations), states, countries


def load_postgres_data(
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load the required analytics columns from PostgreSQL."""
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is required when USE_MOCK_DATA is false."
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
            SELECT org_id, org_rating, org_type, state_id, created_at
            FROM organizations
            """,
            connection,
        )

        states = pd.read_sql_query(
            """
            SELECT state_id, country_id
            FROM states
            """,
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


def join_location_data(
    organizations: pd.DataFrame,
    states: pd.DataFrame,
    countries: pd.DataFrame,
) -> pd.DataFrame:
    """Join organizations to countries through states."""
    state_required = {"state_id", "country_id"}
    country_required = {"country_id", "country_code"}

    if not state_required.issubset(states.columns):
        raise ValueError(
            "states data must include state_id and country_id."
        )

    if not country_required.issubset(countries.columns):
        raise ValueError(
            "countries data must include country_id and country_code."
        )

    country_columns = ["country_id", "country_code"]

    if "country_name" in countries.columns:
        country_columns.append("country_name")

    return organizations.merge(
        states[["state_id", "country_id"]],
        on="state_id",
        how="left",
    ).merge(
        countries[country_columns],
        on="country_id",
        how="left",
    )
def apply_country_filter(
    data: pd.DataFrame,
    country: Any = "ALL",
) -> pd.DataFrame:
    """Filter organizations by country code or country name."""
    country_value = str(country or "ALL").strip()

    if country_value.upper() == "ALL":
        return data.copy()

    code_match = (
        data["country_code"]
        .fillna("")
        .astype(str)
        .str.casefold()
        .eq(country_value.casefold())
    )

    if "country_name" in data.columns:
        name_match = (
            data["country_name"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.casefold()
            .eq(country_value.casefold())
        )
        code_match |= name_match

    return data[code_match].copy()


def filter_by_date_range(
    data: pd.DataFrame,
    start_date: Optional[date],
    end_date: Optional[date],
) -> pd.DataFrame:
    """Return organizations created within an inclusive date range."""
    if start_date is None or end_date is None:
        return data.copy()

    created_dates = data["created_at"].dt.date

    return data[
        created_dates.between(start_date, end_date)
    ].copy()


def build_rating_distribution(
    data: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Count organizations for each rating actually present."""
    if data.empty:
        return []

    valid = data.dropna(subset=["org_rating"])

    if valid.empty:
        return []

    counts = (
        valid.groupby("org_rating", sort=True)
        .size()
    )

    return [
        {
            "rating": int(rating),
            "count": int(count),
        }
        for rating, count in counts.items()
    ]
def build_organization_mix_trend(
    data: pd.DataFrame,
    window_data: pd.DataFrame,
    monthly: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Build cumulative organization counts by type over time."""
    result = {
        "non_profit": [],
        "for_profit": [],
    }

    if window_data.empty:
        return result

    selected = window_data.copy()

    period_format = "%Y-%m" if monthly else "%Y-%m-%d"
    selected["period"] = selected["created_at"].dt.strftime(period_format)

    for org_type in ("non_profit", "for_profit"):
        type_selected = selected[
            selected["org_type"] == org_type
        ]

        if type_selected.empty:
            continue

        all_type_dates = (
            data.loc[data["org_type"] == org_type, "created_at"]
            .sort_values()
        )

        for period, rows in type_selected.groupby("period", sort=True):
            del rows

            if monthly:
                period_start = pd.Timestamp(
                    f"{period}-01"
                )
                period_end = period_start + pd.DateOffset(months=1)
            else:
                period_start = pd.Timestamp(period)
                period_end = period_start + pd.Timedelta(days=1)

            if all_type_dates.dt.tz is not None:
                if period_end.tzinfo is None:
                    period_end = period_end.tz_localize("UTC")
            elif period_end.tzinfo is not None:
                period_end = period_end.tz_localize(None)

            cumulative_count = int(
                (all_type_dates < period_end).sum()
            )

            result[org_type].append(
                {
                    "period": period,
                    "count": cumulative_count,
                }
            )

    return result
def empty_charts() -> dict[str, Any]:
    """Return the empty response structure for both Rating & Type charts."""
    return {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }


def build_charts(
    data: pd.DataFrame,
    window_data: pd.DataFrame,
    monthly: bool = False,
) -> dict[str, Any]:
    """Build both charts for one fixed time bucket."""
    return {
        "rating_distribution": build_rating_distribution(window_data),
        "organization_mix_trend": build_organization_mix_trend(
            data,
            window_data,
            monthly=monthly,
        ),
    }


def build_response(
    payload: dict[str, Any],
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Build fixed-bucket or Custom-only Rating & Type analytics."""

    rating_range = validate_date_pair(
        payload,
        "rating_start_date",
        "rating_end_date",
    )

    type_range = validate_date_pair(
        payload,
        "type_start_date",
        "type_end_date",
    )

    use_mock_data = (
        os.environ.get("USE_MOCK_DATA", "true").lower() == "true"
    )

    if use_mock_data:
        mock_data_dir = os.environ.get("MOCK_DATA_DIR")

        if not mock_data_dir:
            raise RuntimeError(
                "MOCK_DATA_DIR must be set when USE_MOCK_DATA is true."
            )

        organizations, states, countries = load_mock_data(
            mock_data_dir
        )
    else:
        organizations, states, countries = load_postgres_data()

    data = join_location_data(
        organizations,
        states,
        countries,
    )

    data = apply_country_filter(
        data,
        payload.get("country", "ALL"),
    )

    # If either Custom pair is supplied, return Custom only.
    if rating_range or type_range:
        custom = empty_charts()

        if rating_range:
            rating_data = filter_by_date_range(
                data,
                *rating_range,
            )

            custom["rating_distribution"] = (
                build_rating_distribution(rating_data)
            )

        if type_range:
            type_data = filter_by_date_range(
                data,
                *type_range,
            )

            custom["organization_mix_trend"] = (
                build_organization_mix_trend(
                    data,
                    type_data,
                    monthly=False,
                )
            )

        return {"Custom": custom}

    current_date = today or datetime.now().date()

    bucket_ranges = {
        "7D": (
            current_date - timedelta(days=6),
            current_date,
        ),
        "30D": (
            current_date - timedelta(days=29),
            current_date,
        ),
        "1Y": (
            current_date - timedelta(days=364),
            current_date,
        ),
        "All": (
            None,
            None,
        ),
    }

    result = {}

    for bucket, (start_date, end_date) in bucket_ranges.items():
        window_data = filter_by_date_range(
            data,
            start_date,
            end_date,
        )

        result[bucket] = build_charts(
            data,
            window_data,
            monthly=bucket in ("1Y", "All"),
        )

    result["Custom"] = empty_charts()

    return result
def lambda_handler(
    event: Any,
    context: Any = None,
) -> dict[str, Any]:
    """AWS Lambda entry point for Rating & Type analytics."""
    del context

    try:
        payload = parse_event(event)
        result = build_response(payload)

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
            },
            "body": json.dumps(result),
        }

    except RequestValidationError as exc:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
            },
            "body": json.dumps({"error": str(exc)}),
        }

    except (
        FileNotFoundError,
        KeyError,
        ValueError,
        RuntimeError,
    ) as exc:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
            },
            "body": json.dumps({"error": str(exc)}),
        }


if __name__ == "__main__":
    sample_events = {
        "No filters": {},

        "Country filter": {
            "country": "USA",
        },

        "Rating Custom": {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
        },

        "Type Custom": {
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        },

        "Both Custom ranges": {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        },
    }

    for label, sample_event in sample_events.items():
        print(f"\n=== {label} ===")
        print(
            json.dumps(
                lambda_handler(sample_event),
                indent=2,
            )
        )
