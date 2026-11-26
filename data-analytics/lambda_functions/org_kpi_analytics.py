import csv
import json
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parent / "mock_data"


def build_response(status_code, body):
    """Return an API Gateway-compatible response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, allow_nan=False),
    }


def read_csv(filename):
    """Read a CSV from the Lambda deployment directory."""
    with (DATA_DIR / filename).open(
        encoding="utf-8-sig", newline=""
    ) as file:
        return list(csv.DictReader(file))


def normalize(value):
    """Normalize country names and organization types."""
    return re.sub(
        r"[\s_-]+", "_", str(value).strip().upper()
    )


def parse_body(event):
    """Support direct invocation and API Gateway events."""
    if event is None:
        return {}

    if not isinstance(event, dict):
        raise ValueError("Request body must be a JSON object.")

    body = event.get("body", event)

    if body is None or body == "":
        return {}

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON request body.")

    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")

    return body


def parse_date(value):
    """Validate dates in YYYY-MM-DD format."""
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", value
    ):
        raise ValueError("Invalid date format. Use YYYY-MM-DD.")

    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("Invalid date format. Use YYYY-MM-DD.")


def parse_created_at(value):
    """Normalize timestamps to UTC dates."""
    try:
        timestamp = datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        )

        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(timezone.utc)

        return timestamp.date()

    except (ValueError, TypeError, AttributeError):
        return None


def validate_dates(body):
    """Validate the optional custom date pair."""
    start = body.get("start_date")
    end = body.get("end_date")

    if start is None and end is None:
        if body.get("time_range") == "Custom":
            raise ValueError(
                "Both start_date and end_date are required."
            )
        return None

    if start is None or end is None:
        raise ValueError(
            "Both start_date and end_date are required."
        )

    start = parse_date(start)
    end = parse_date(end)

    if start > end:
        raise ValueError(
            "start_date cannot be after end_date."
        )

    return start, end


def build_time_windows(custom_dates=None, today=None):
    """Define reusable time windows for all KPIs."""
    if custom_dates is not None:
        return {"Custom": custom_dates}

    if today is None:
        today = datetime.now(timezone.utc).date()

    try:
        year_start = today.replace(year=today.year - 1)
    except ValueError:
        year_start = today.replace(
            year=today.year - 1, day=28
        )

    return {
        "7D": (today - timedelta(days=7), today),
        "30D": (today - timedelta(days=30), today),
        "1Y": (year_start, today),
        "All": (None, None),
    }


def load_data():
    """Load organization records and geographic mappings."""
    organizations = read_csv("organizations.csv")
    states = read_csv("states.csv")
    countries = read_csv("countries.csv")

    state_to_country = {
        row["state_id"]: row["country_id"]
        for row in states
    }

    country_lookup = {}

    for row in countries:
        country_id = row["country_id"]

        for field in ("country_name", "country_code"):
            key = normalize(row[field])
            country_lookup[key] = country_id

    records = []

    for org in organizations:
        created_date = parse_created_at(
            org.get("created_at", "")
        )

        if created_date is None:
            continue

        record = dict(org)
        record["created_date"] = created_date
        record["country_id"] = state_to_country.get(
            org["state_id"]
        )

        records.append(record)

    return records, country_lookup


def apply_filters(records, country_lookup, body):
    """Apply shared filters before KPI calculation."""
    country = body.get("country")
    org_type = body.get("organization_type")

    country_id = None
    normalized_type = None

    if country is not None:
        if not isinstance(country, str):
            raise ValueError("Invalid country.")

        country_id = country_lookup.get(normalize(country))

        if country_id is None:
            raise ValueError("Invalid country.")

    if org_type is not None:
        if not isinstance(org_type, str):
            raise ValueError("Invalid organization_type.")

        normalized_type = normalize(org_type)

        if normalized_type not in {
            "FOR_PROFIT", "NON_PROFIT"
        }:
            raise ValueError(
                "Invalid organization_type. "
                "Must be for_profit or non_profit."
            )

    return [
        org for org in records
        if (
            country_id is None
            or org["country_id"] == country_id
        )
        and (
            normalized_type is None
            or normalize(org["org_type"]) == normalized_type
        )
    ]


def filter_by_window(records, start, end):
    """Select organizations created in the given window."""
    return [
        org for org in records
        if (start is None or org["created_date"] >= start)
        and (end is None or org["created_date"] <= end)
    ]


def is_true(value):
    """Interpret CSV boolean values."""
    return str(value).strip().lower() in {
        "true", "1", "yes", "t"
    }


def calculate_total_organizations(records):
    return len(records)


def calculate_total_collaborators(records):
    return sum(
        is_true(org.get("is_collaborator"))
        for org in records
    )


def calculate_total_contributors(records):
    return sum(
        is_true(org.get("is_contributor"))
        for org in records
    )


def calculate_avg_org_rating(records):
    ratings = []

    for org in records:
        try:
            rating = float(org.get("org_rating", ""))

            if math.isfinite(rating):
                ratings.append(rating)

        except (ValueError, TypeError):
            continue

    if not ratings:
        return None

    return round(sum(ratings) / len(ratings), 1)


def calculate_kpis(records):
    """Calculate all four dashboard KPIs."""
    return {
        "total_organizations":
            calculate_total_organizations(records),

        "total_collaborators":
            calculate_total_collaborators(records),

        "total_contributors":
            calculate_total_contributors(records),

        "avg_org_rating":
            calculate_avg_org_rating(records),
    }


def lambda_handler(event, context):
    """Entry point for the Organization Dashboard KPI API."""
    try:
        body = parse_body(event)
        custom_dates = validate_dates(body)
        windows = build_time_windows(custom_dates)

        records, country_lookup = load_data()

        filtered_records = apply_filters(
            records, country_lookup, body
        )

        response = {}

        for key, (start, end) in windows.items():
            window_records = filter_by_window(
                filtered_records, start, end
            )

            response[key] = calculate_kpis(window_records)

        return build_response(200, response)

    except ValueError as error:
        return build_response(
            400, {"error": str(error)}
        )

    except Exception:
        logger.exception("Organization KPI calculation failed")

        return build_response(
            500, {"error": "Internal server error."}
        )