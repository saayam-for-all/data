import json
import os
from datetime import datetime, date, timedelta

import pandas as pd

# psycopg2 is used for the real database path.
# Keep it optional so local mock-data testing works without PostgreSQL.
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None


# Local mock-data directory
MOCK_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "mock-data-generation"
)

ORGANIZATIONS_CSV = os.path.join(
    MOCK_DATA_DIR, "organizations.csv"
)

STATES_CSV = os.path.join(
    MOCK_DATA_DIR, "states.csv"
)

COUNTRIES_CSV = os.path.join(
    MOCK_DATA_DIR, "countries.csv"
)


def load_mock_data():
    """Load the local CSV datasets used for development and testing."""

    organizations = pd.read_csv(
        ORGANIZATIONS_CSV,
        encoding="utf-8-sig",
        dtype={
            "org_id": str,
            "state_id": str
        }
    )

    states = pd.read_csv(
        STATES_CSV,
        encoding="utf-8-sig",
        dtype={
            "state_id": str,
            "country_id": str
        }
    )

    countries = pd.read_csv(
        COUNTRIES_CSV,
        encoding="utf-8-sig",
        dtype={
            "country_id": str
        }
    )

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="coerce"
    )

    return organizations, states, countries

def apply_common_filters(
    organizations,
    states,
    countries,
    country="All",
    organization_type="All"
):
    """Apply country and organization-type filters."""

    filtered = organizations.copy()

    # Filter by organization type
    if organization_type != "All":
        filtered = filtered[
            filtered["org_type"].astype(str).str.lower()
            == str(organization_type).lower()
        ].copy()

    # Filter by country name or country code
    if country != "All":
        state_country = states.merge(
            countries[["country_id", "country_name", "country_code"]],
            on="country_id",
            how="left"
        )

        filtered = filtered.merge(
            state_country[
                ["state_id", "country_name", "country_code"]
            ],
            on="state_id",
            how="left"
        )

        requested_country = str(country).lower()

        filtered = filtered[
            (filtered["country_name"].astype(str).str.lower()
             == requested_country)
            |
            (filtered["country_code"].astype(str).str.lower()
             == requested_country)
        ].copy()

    return filtered

def filter_by_date(
    organizations,
    time_range,
    start_date=None,
    end_date=None
):
    """Filter organizations to the requested creation-date window."""

    today = pd.Timestamp.now().normalize()

    if time_range == "7D":
        cutoff = today - pd.Timedelta(days=6)
        return organizations[
            organizations["created_at"] >= cutoff
        ].copy()

    elif time_range == "30D":
        cutoff = today - pd.Timedelta(days=29)
        return organizations[
            organizations["created_at"] >= cutoff
        ].copy()

    elif time_range == "1Y":
        cutoff = today - pd.Timedelta(days=364)
        return organizations[
            organizations["created_at"] >= cutoff
        ].copy()

    elif time_range == "All":
        return organizations.copy()

    elif time_range == "Custom":
        if start_date is None or end_date is None:
            return organizations.iloc[0:0].copy()

        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date) + pd.Timedelta(days=1)

        return organizations[
            (organizations["created_at"] >= start)
            & (organizations["created_at"] < end)
        ].copy()

    else:
        raise ValueError("Invalid time range")

def calculate_organizations_by_size(organizations):
    """Count organizations by size within the selected window."""

    if organizations.empty:
        return []

    size_counts = (
        organizations
        .groupby("org_size")
        .size()
        .to_dict()
    )

    result = []

    for size in ["small", "medium", "large"]:
        if size in size_counts:
            result.append({
                "size": size,
                "count": int(size_counts[size])
            })

    return result

def calculate_collaborator_vs_contributor(organizations):
    """Calculate independent collaborator and contributor counts."""

    if organizations.empty:
        return []

    total_organizations = len(organizations)

    collaborator_count = int(
        organizations["is_collaborator"]
        .astype(str)
        .str.lower()
        .eq("true")
        .sum()
    )

    # Gracefully handle datasets where is_contributor is missing.
    if "is_contributor" in organizations.columns:
        contributor_count = int(
            organizations["is_contributor"]
            .astype(str)
            .str.lower()
            .eq("true")
            .sum()
        )
    else:
        contributor_count = 0

    collaborator_percentage = round(
        (collaborator_count / total_organizations) * 100, 1
    )

    contributor_percentage = round(
        (contributor_count / total_organizations) * 100, 1
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

def build_bucket(
    organizations,
    states,
    countries,
    time_range,
    country="All",
    organization_type="All"
):
    """Build both analytics charts for one fixed time bucket."""

    filtered = apply_common_filters(
        organizations,
        states,
        countries,
        country,
        organization_type
    )

    filtered = filter_by_date(
        filtered,
        time_range
    )

    return {
        "organizations_by_size":
            calculate_organizations_by_size(filtered),
        "collaborator_vs_contributor":
            calculate_collaborator_vs_contributor(filtered)
    }

def build_custom_bucket(
    organizations,
    states,
    countries,
    country="All",
    organization_type="All",
    size_start_date=None,
    size_end_date=None,
    contribution_start_date=None,
    contribution_end_date=None
):
    """Build Custom analytics using independent date ranges."""

    filtered = apply_common_filters(
        organizations,
        states,
        countries,
        country,
        organization_type
    )

    organizations_by_size = []
    collaborator_vs_contributor = []

    if size_start_date is not None and size_end_date is not None:
        size_filtered = filter_by_date(
            filtered,
            "Custom",
            size_start_date,
            size_end_date
        )

        organizations_by_size = calculate_organizations_by_size(
            size_filtered
        )

    if (
        contribution_start_date is not None
        and contribution_end_date is not None
    ):
        contribution_filtered = filter_by_date(
            filtered,
            "Custom",
            contribution_start_date,
            contribution_end_date
        )

        collaborator_vs_contributor = (
            calculate_collaborator_vs_contributor(
                contribution_filtered
            )
        )

    return {
        "organizations_by_size": organizations_by_size,
        "collaborator_vs_contributor": collaborator_vs_contributor
    }

def validate_date_pair(start_date, end_date, pair_name):
    """Validate a Custom date-range pair."""

    if (start_date is None) != (end_date is None):
        raise ValueError(
            f"Both {pair_name}_start_date and "
            f"{pair_name}_end_date must be provided"
        )

    if start_date is None and end_date is None:
        return

    try:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
    except Exception:
        raise ValueError("Invalid calendar date")

    if start > end:
        raise ValueError(
            f"{pair_name} start date cannot be after end date"
        )

def build_response(status_code, body):
    """Build an API Gateway-compatible response."""

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body)
    }

def lambda_handler(event, context):
    """Handle Size & Contribution Analytics API requests."""

    try:
        event = event or {}

        country = event.get("country", "All")
        organization_type = event.get("organization_type", "All")

        size_start_date = event.get("size_start_date")
        size_end_date = event.get("size_end_date")

        contribution_start_date = event.get("contribution_start_date")
        contribution_end_date = event.get("contribution_end_date")

        # Validate both Custom date pairs independently.
        validate_date_pair(
            size_start_date,
            size_end_date,
            "size"
        )

        validate_date_pair(
            contribution_start_date,
            contribution_end_date,
            "contribution"
        )

        organizations, states, countries = load_mock_data()

        size_custom = (
            size_start_date is not None
            and size_end_date is not None
        )

        contribution_custom = (
            contribution_start_date is not None
            and contribution_end_date is not None
        )

        # If either Custom range exists, return Custom only.
        if size_custom or contribution_custom:
            response_body = {
                "Custom": build_custom_bucket(
                    organizations,
                    states,
                    countries,
                    country=country,
                    organization_type=organization_type,
                    size_start_date=size_start_date,
                    size_end_date=size_end_date,
                    contribution_start_date=contribution_start_date,
                    contribution_end_date=contribution_end_date
                )
            }

            return build_response(200, response_body)

        # No Custom ranges: return all fixed buckets plus empty Custom.
        response_body = {}

        for time_range in ["7D", "30D", "1Y", "All"]:
            response_body[time_range] = build_bucket(
                organizations,
                states,
                countries,
                time_range,
                country=country,
                organization_type=organization_type
            )

        response_body["Custom"] = {
            "organizations_by_size": [],
            "collaborator_vs_contributor": []
        }

        return build_response(200, response_body)

    except ValueError as exc:
        return build_response(
            400,
            {"error": str(exc)}
        )

    except Exception as exc:
        print(f"Size & Contribution Analytics failed: {exc}")

        return build_response(
            500,
            {"error": "Internal server error"}
        )