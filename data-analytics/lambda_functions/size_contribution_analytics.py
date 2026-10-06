import json
import os
from datetime import datetime, timedelta

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None


USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "true").lower() == "true"
MOCK_DATA_DIR = os.getenv("MOCK_DATA_DIR", ".")


def _error_response(message):
    return {
        "statusCode": 400,
        "body": json.dumps({"error": message})
    }


def _success_response(data):
    return {
        "statusCode": 200,
        "body": json.dumps(data)
    }


def _parse_body(event):
    body = event.get("body")

    if body is None or body == "":
        return {}

    if isinstance(body, dict):
        return body

    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("Request body must be valid JSON.")


def _validate_date_pair(data, start_key, end_key):
    start = data.get(start_key)
    end = data.get(end_key)

    # Neither supplied: valid, no custom range requested.
    if start is None and end is None:
        return None, None

    # Only one supplied: invalid.
    if start is None or end is None:
        raise ValueError(
            f"Both {start_key} and {end_key} must be provided together."
        )

    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValueError(
            f"{start_key} and {end_key} must use YYYY-MM-DD format."
        )

    if start_date > end_date:
        raise ValueError(
            f"{start_key} cannot be after {end_key}."
        )

    return start_date, end_date


def _load_mock_data():
    organizations_path = os.path.join(
        MOCK_DATA_DIR, "organizations.csv"
    )
    states_path = os.path.join(
        MOCK_DATA_DIR, "state.csv"
    )
    countries_path = os.path.join(
        MOCK_DATA_DIR, "country.csv"
    )

    organizations = pd.read_csv(organizations_path)
    states = pd.read_csv(states_path)
    countries = pd.read_csv(countries_path)

    return organizations, states, countries


def _load_data():
    if USE_MOCK_DATA:
        return _load_mock_data()

    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is required when USE_MOCK_DATA is false."
        )

    connection = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )

    query = """
        SELECT
            o.org_id,
            o.org_size,
            o.is_collaborator,
            o.is_contributor,
            o.org_type,
            o.state_id,
            o.created_at,
            s.country_id,
            c.country_code,
            c.country_name
        FROM organizations o
        LEFT JOIN states s
            ON o.state_id = s.state_id
        LEFT JOIN countries c
            ON s.country_id = c.country_id
    """

    df = pd.read_sql_query(query, connection)
    connection.close()

    return df


def _prepare_mock_data(organizations, states, countries):
    """
    Join:
        organizations.state_id
        -> states.country_id
        -> countries.country_id

    The result has country_code/country_name available
    for filtering.
    """

    merged = organizations.merge(
        states[["state_id", "country_id"]],
        on="state_id",
        how="left"
    )

    country_columns = [
        column
        for column in ["country_id", "country_code", "country_name"]
        if column in countries.columns
    ]

    merged = merged.merge(
        countries[country_columns],
        on="country_id",
        how="left"
    )

    return merged


def _prepare_data():
    data = _load_data()

    # Mock path returns three DataFrames.
    if USE_MOCK_DATA:
        organizations, states, countries = data
        return _prepare_mock_data(
            organizations,
            states,
            countries
        )

    # Real DB path already returns one DataFrame.
    return data


def _normalize_value(value):
    if value is None:
        return ""

    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _apply_common_filters(df, country, organization_type):
    filtered = df.copy()

    # Country filter
    if country and _normalize_value(country) != "all":
        country_value = _normalize_value(country)

        country_code = filtered["country_code"].apply(
            _normalize_value
        )

        country_name = filtered["country_name"].apply(
            _normalize_value
        )

        filtered = filtered[
            (country_code == country_value)
            | (country_name == country_value)
        ]

    # Organization type filter
    if organization_type and _normalize_value(organization_type) != "all":
        type_value = _normalize_value(organization_type)

        org_type = filtered["org_type"].apply(
            _normalize_value
        )

        filtered = filtered[org_type == type_value]

    return filtered


def _prepare_created_at(df):
    result = df.copy()

    if "created_at" not in result.columns:
        result["created_at"] = pd.NaT

    result["created_at"] = pd.to_datetime(
        result["created_at"],
        errors="coerce"
    )

    return result


def _filter_date_range(df, start_date, end_date):
    if start_date is None or end_date is None:
        return df

    dates = df["created_at"].dt.date

    return df[
        (dates >= start_date)
        & (dates <= end_date)
    ]


def _organizations_by_size(df):
    if df.empty or "org_size" not in df.columns:
        return []

    size_series = df["org_size"].dropna()

    if size_series.empty:
        return []

    counts = size_series.value_counts()

    return [
        {
            "size": str(size),
            "count": int(count)
        }
        for size, count in counts.items()
    ]


def _collaborator_vs_contributor(df):
    total = len(df)

    if total == 0:
        return [
            {
                "type": "Collaborator",
                "count": 0,
                "percentage": 0.0
            },
            {
                "type": "Contributor",
                "count": 0,
                "percentage": 0.0
            }
        ]

    if "is_collaborator" in df.columns:
        collaborator_count = int(
            (df["is_collaborator"] == True).sum()
        )
    else:
        collaborator_count = 0

    if "is_contributor" in df.columns:
        contributor_count = int(
            (df["is_contributor"] == True).sum()
        )
    else:
        contributor_count = 0

    collaborator_percentage = round(
        (collaborator_count / total) * 100,
        1
    )

    contributor_percentage = round(
        (contributor_count / total) * 100,
        1
    )

    return [
        {
            "type": "Collaborator",
            "count": collaborator_count,
            "percentage": collaborator_percentage
        },
        {
            "type": "Contributor",
            "count": contributor_count,
            "percentage": contributor_percentage
        }
    ]


def _build_bucket(df):
    return {
        "organizations_by_size": _organizations_by_size(df),
        "collaborator_vs_contributor": _collaborator_vs_contributor(df)
    }


def _get_fixed_ranges():
    today = datetime.now().date()

    return {
        "7D": (
            today - timedelta(days=6),
            today
        ),
        "30D": (
            today - timedelta(days=29),
            today
        ),
        "1Y": (
            today - timedelta(days=364),
            today
        ),
        "All": (
            None,
            None
        )
    }


def lambda_handler(event, context):
    try:
        body = _parse_body(event)

        country = body.get("country", "ALL")
        organization_type = body.get(
            "organization_type",
            "ALL"
        )

        size_start, size_end = _validate_date_pair(
            body,
            "size_start_date",
            "size_end_date"
        )

        contribution_start, contribution_end = _validate_date_pair(
            body,
            "contribution_start_date",
            "contribution_end_date"
        )

        size_custom = size_start is not None
        contribution_custom = contribution_start is not None

        df = _prepare_data()
        df = _prepare_created_at(df)

        # Apply country/type filters once.
        df = _apply_common_filters(
            df,
            country,
            organization_type
        )

        # ---------------------------------------------------------
        # CUSTOM RESPONSE
        # ---------------------------------------------------------
        if size_custom or contribution_custom:
            response = {
                "Custom": {
                    "organizations_by_size": [],
                    "collaborator_vs_contributor": []
                }
            }

            if size_custom:
                size_df = _filter_date_range(
                    df,
                    size_start,
                    size_end
                )

                response["Custom"]["organizations_by_size"] = (
                    _organizations_by_size(size_df)
                )

            if contribution_custom:
                contribution_df = _filter_date_range(
                    df,
                    contribution_start,
                    contribution_end
                )

                response["Custom"]["collaborator_vs_contributor"] = (
                    _collaborator_vs_contributor(contribution_df)
                )

            return _success_response(response)

        # ---------------------------------------------------------
        # FIXED BUCKET RESPONSE
        # ---------------------------------------------------------
        response = {}

        for bucket, (start_date, end_date) in _get_fixed_ranges().items():
            bucket_df = _filter_date_range(
                df,
                start_date,
                end_date
            )

            response[bucket] = _build_bucket(bucket_df)

        response["Custom"] = {
            "organizations_by_size": [],
            "collaborator_vs_contributor": []
        }

        return _success_response(response)

    except ValueError as exc:
        return _error_response(str(exc))

    except FileNotFoundError as exc:
        return _error_response(
            f"Mock data file not found: {exc.filename}"
        )

    except Exception as exc:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": f"Internal server error: {str(exc)}"
            })
        }


if __name__ == "__main__":
    sample_events = [
        {
            "name": "No filters",
            "event": {
                "body": {}
            }
        },
        {
            "name": "Country filter",
            "event": {
                "body": {
                    "country": "USA"
                }
            }
        },
        {
            "name": "Organization type filter",
            "event": {
                "body": {
                    "organization_type": "non_profit"
                }
            }
        },
        {
            "name": "Size custom range",
            "event": {
                "body": {
                    "size_start_date": "2026-01-01",
                    "size_end_date": "2026-06-30"
                }
            }
        },
        {
            "name": "Contribution custom range",
            "event": {
                "body": {
                    "contribution_start_date": "2025-01-01",
                    "contribution_end_date": "2025-12-31"
                }
            }
        },
        {
            "name": "Both custom ranges",
            "event": {
                "body": {
                    "size_start_date": "2026-01-01",
                    "size_end_date": "2026-06-30",
                    "contribution_start_date": "2025-01-01",
                    "contribution_end_date": "2025-12-31"
                }
            }
        }
    ]

    for sample in sample_events:
        print("\n" + "=" * 70)
        print(sample["name"])
        print("=" * 70)

        result = lambda_handler(sample["event"], None)

        print(
            json.dumps(
                json.loads(result["body"]),
                indent=2
            )
        )