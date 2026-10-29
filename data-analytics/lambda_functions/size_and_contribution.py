
"""Size & Contribution analytics for the Organization dashboard.

With no custom dates, returns 7D/30D/1Y/All. When start_date and
end_date are supplied, returns Custom only, with both charts using the
same inclusive date range. CSVs are read from mock_data beside this file.
"""

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

import pandas as pd

logger = logging.getLogger(__name__)

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
SIZE_CHART = "organizations_by_size"
CONTRIBUTION_CHART = "collaborator_vs_contributor"
ORGANIZATION_TYPES = ("non_profit", "for_profit")
SIZE_ORDER = {"small": 0, "medium": 1, "large": 2}
TRUE_VALUES = ("true", "t", "1", "yes")
REQUIRED_COLUMNS = ("org_id", "org_size", "is_collaborator", "org_type", "state_id")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULT_MOCK_DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "mock_data"
)

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


class BadRequestError(ValueError):
    """Bad input in the request (400)."""


class DataSourceError(RuntimeError):
    """Missing file, column or config on our side (500)."""


# -------------------------------------------------------------
# Request parsing and filters
# -------------------------------------------------------------

def parse_event_body(event):
    """Get the filters dictionary out of the Lambda event."""
    if not event:
        return {}

    body = event.get("body", event) if isinstance(event, dict) else event

    if body is None or body == "":
        return {}

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise BadRequestError("Request body is not valid JSON") from None

    if not isinstance(body, dict):
        raise BadRequestError("Request body must be a JSON object")

    return body


def normalize_country(value):
    """Normalize country names and codes."""
    return " ".join(str(value).replace("_", " ").split()).upper()


def normalize_org_type(value):
    """Normalize organization types, including hyphens and spaces."""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def parse_filters(body):
    """Return country and organization type. None means ALL."""
    country = body.get("country") or "ALL"
    org_type = body.get("organization_type") or "ALL"

    if not isinstance(country, str) or not isinstance(org_type, str):
        raise BadRequestError("country and organization_type must be text")

    country = normalize_country(country)
    org_type = normalize_org_type(org_type)

    if org_type not in ORGANIZATION_TYPES + ("all",):
        raise BadRequestError(
            "organization_type must be non_profit, for_profit or ALL"
        )

    return (
        None if country == "ALL" else country,
        None if org_type == "all" else org_type,
    )


# -------------------------------------------------------------
# One shared Custom date range for both charts
# -------------------------------------------------------------

def parse_date(value, key):
    """Parse a YYYY-MM-DD string into a date."""
    if not isinstance(value, str) or not DATE_PATTERN.match(value):
        raise BadRequestError(f"{key} must be a date in YYYY-MM-DD format")

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise BadRequestError(
            f"{key} is not a real calendar date"
        ) from None


def parse_date_pair(body, start_key, end_key):
    """Return one shared date range, or None if both dates are blank."""
    start = body.get(start_key)
    end = body.get(end_key)

    if not start and not end:
        return None

    if not start or not end:
        raise BadRequestError(
            f"{start_key} and {end_key} must be sent together"
        )

    start = parse_date(start, start_key)
    end = parse_date(end, end_key)

    if start > end:
        raise BadRequestError(
            f"{start_key} must be on or before {end_key}"
        )

    return start, end


# -------------------------------------------------------------
# Time windows (preserved from existing implementation)
# -------------------------------------------------------------

def utc_today():
    """Return the current UTC date."""
    return datetime.now(timezone.utc).date()


def midnight(day):
    """Convert a date to midnight."""
    return datetime(day.year, day.month, day.day)


def fixed_window(bucket, today):
    """Return start and exclusive end for a fixed bucket."""
    if bucket == "All":
        return None, None

    if bucket == "1Y":
        year, month = today.year, today.month - 11
        if month < 1:
            year, month = year - 1, month + 12
        start = date(year, month, 1)
    else:
        start = today - timedelta(
            days=6 if bucket == "7D" else 29
        )

    return midnight(start), midnight(today + timedelta(days=1))


def custom_window(date_pair):
    """Make the user-supplied end date inclusive."""
    start, end = date_pair
    return midnight(start), midnight(end + timedelta(days=1))


# -------------------------------------------------------------
# Chart builders
# -------------------------------------------------------------

def size_chart(size_counts):
    """Build organization counts by size."""
    rows = sorted(
        size_counts.items(),
        key=lambda row: (
            SIZE_ORDER.get(str(row[0]).lower(), 99),
            row[0],
        ),
    )

    return [
        {"size": size, "count": int(count)}
        for size, count in rows
    ]


def contribution_chart(total, collaborators, contributors):
    """Build independent collaborator and contributor counts."""
    if total == 0:
        return []

    return [
        {
            "type": "Collaborator",
            "count": int(collaborators),
            "percentage": round(collaborators * 100 / total, 1),
        },
        {
            "type": "Contributor",
            "count": int(contributors),
            "percentage": round(contributors * 100 / total, 1),
        },
    ]


def build_body(count, date_pair, today):
    """Use the same date window for both analytics charts."""
    if date_pair is None:
        body = {}

        for bucket in FIXED_BUCKETS:
            sizes, total, collaborators, contributors = count(
                *fixed_window(bucket, today)
            )

            body[bucket] = {
                SIZE_CHART: size_chart(sizes),
                CONTRIBUTION_CHART: contribution_chart(
                    total, collaborators, contributors
                ),
            }

        return body

    sizes, total, collaborators, contributors = count(
        *custom_window(date_pair)
    )

    return {
        "Custom": {
            SIZE_CHART: size_chart(sizes),
            CONTRIBUTION_CHART: contribution_chart(
                total, collaborators, contributors
            ),
        }
    }


# -------------------------------------------------------------
# CSV loading from mock_data
# -------------------------------------------------------------

def read_mock_csv(filename):
    """Read CSVs from mock_data beside this Lambda file."""
    path = os.path.join(DEFAULT_MOCK_DATA_DIR, filename)

    if os.path.exists(path):
        return pd.read_csv(path, dtype=str)

    raise DataSourceError(
        f"{filename} not found in mock_data"
    )


def to_bool(series):
    """Convert recognized true values to boolean."""
    return (
        series.fillna("")
        .str.strip()
        .str.lower()
        .isin(TRUE_VALUES)
    )


def mock_counter(country, org_type):
    """Load CSV data and return a window-based counter."""
    orgs = read_mock_csv("organizations.csv")

    missing = [
        col
        for col in REQUIRED_COLUMNS + ("created_at",)
        if col not in orgs.columns
    ]

    if missing:
        raise DataSourceError(
            f"organizations.csv is missing column(s): {', '.join(missing)}"
        )

    orgs["created_at"] = pd.to_datetime(
        orgs["created_at"],
        errors="coerce",
    )

    orgs["is_collaborator"] = to_bool(orgs["is_collaborator"])

    if "is_contributor" in orgs.columns:
        orgs["is_contributor"] = to_bool(orgs["is_contributor"])
    else:
        orgs["is_contributor"] = False

    # Existing organization-type filter
    if org_type:
        orgs = orgs[
            orgs["org_type"].fillna("").map(normalize_org_type)
            == org_type
        ]

    # Existing country filtering through states and countries
    if country:
        states = read_mock_csv("states.csv")
        countries = read_mock_csv("countries.csv")

        match = (
            countries["country_code"]
            .fillna("")
            .map(normalize_country) == country
        )

        if "country_name" in countries.columns:
            match |= (
                countries["country_name"]
                .fillna("")
                .map(normalize_country) == country
            )

        country_ids = countries.loc[match, "country_id"]

        state_ids = states.loc[
            states["country_id"].isin(country_ids),
            "state_id",
        ]

        orgs = orgs[orgs["state_id"].isin(state_ids)]

    orgs = orgs[orgs["created_at"].notna()]

    def count(start, end):
        """Count organizations in the selected window."""
        window = orgs

        if start is not None:
            window = orgs[
                (orgs["created_at"] >= start)
                & (orgs["created_at"] < end)
            ]

        sizes = window["org_size"].dropna().value_counts().to_dict()

        return (
            sizes,
            len(window),
            int(window["is_collaborator"].sum()),
            int(window["is_contributor"].sum()),
        )

    return count


# -------------------------------------------------------------
# API Gateway response and Lambda handler
# -------------------------------------------------------------

def build_response(status_code, body):
    """Preserve the existing Lambda proxy response format."""
    return {
        "statusCode": status_code,
        "headers": HEADERS,
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    """Handle Size & Contribution analytics requests."""
    try:
        body = parse_event_body(event)
        country, org_type = parse_filters(body)

        date_pair = parse_date_pair(
            body, "start_date", "end_date"
        )

    except BadRequestError as exc:
        return build_response(400, {"error": str(exc)})

    try:
        count = mock_counter(country, org_type)

        result = build_body(
            count,
            date_pair,
            utc_today(),
        )

        return build_response(200, result)

    except DataSourceError as exc:
        logger.error("Size & Contribution analytics: %s", exc)
        return build_response(500, {"error": str(exc)})

    except Exception:
        logger.exception("Size & Contribution analytics failed")
        return build_response(
            500, {"error": "Internal server error"}
        )
