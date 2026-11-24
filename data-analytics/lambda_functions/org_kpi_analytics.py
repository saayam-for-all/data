"""Organization KPI analytics for the Organization dashboard (#708).

Returns four KPIs per time window: total_organizations, total_collaborators,
total_contributors and avg_org_rating.
With no dates the response has 7D/30D/1Y/All and no Custom key.
If start_date and end_date are sent (YYYY-MM-DD, both inclusive), only Custom
is returned.
The country and organization_type filters apply to all four KPIs in every case.

Data comes from organizations.csv, states.csv and countries.csv in the
mock_data folder next to this file. No environment variables are needed.
"""

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

MOCK_DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "mock_data"
)
ORGANIZATIONS_FILE = "organizations.csv"
STATES_FILE = "states.csv"
COUNTRIES_FILE = "countries.csv"

FIXED_WINDOWS = ("7D", "30D", "1Y", "All")
WINDOW_PERIODS = {
    "7D": timedelta(days=7),
    "30D": timedelta(days=30),
    "1Y": timedelta(days=365),
}
CUSTOM_WINDOW = "Custom"
DATE_FORMAT = "%Y-%m-%d"
TRUE_VALUES = ("true", "t", "1", "yes")

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


class BadRequestError(ValueError):
    """Raised when the request is invalid and a 400 should be returned."""


def get_window_start(window: str, now: datetime) -> Optional[datetime]:
    """Return the start of a fixed window, or None for "All".

    Args:
        window: One of "7D", "30D", "1Y" or "All".
        now: The current time (naive UTC).

    Returns:
        now minus the window period, or None when there is no start limit.

    Raises:
        ValueError: If the window name is unknown.
    """
    if window == "All":
        return None
    if window not in WINDOW_PERIODS:
        raise ValueError(f"Unknown window: {window}")
    return now - WINDOW_PERIODS[window]


def parse_created_at(value: Optional[str]) -> Optional[datetime]:
    """Parse a created_at value into a naive UTC datetime.

    Accepts "YYYY-MM-DD HH:MM:SS" and ISO 8601 strings, with or without a
    timezone offset. Offset-aware values are converted to UTC and the tzinfo
    is dropped, so both forms compare the same way.

    Args:
        value: The raw created_at string.

    Returns:
        The parsed datetime, or None if the value is blank or unparseable.
    """
    if not value or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def parse_bool(value: Optional[str]) -> bool:
    """Return True if a CSV flag such as "True" means true."""
    return str(value or "").strip().lower() in TRUE_VALUES


def parse_rating(value: Optional[str]) -> Optional[float]:
    """Return the org rating as a float, or None when blank or invalid."""
    if value is None or not str(value).strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


def read_csv(file_name: str) -> list[dict[str, str]]:
    """Read a CSV file from the mock_data folder into a list of dicts."""
    path = os.path.join(MOCK_DATA_DIR, file_name)
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_rows() -> list[dict[str, Any]]:
    """Load the three CSVs and join them into one row per organization.

    Joins organizations.state_id -> states.state_id and
    states.country_id -> countries.country_id. Rows whose created_at cannot
    be parsed are skipped.

    Returns:
        A list of dicts with country_name, org_type, is_collaborator,
        is_contributor, org_rating and a parsed created_at.
    """
    countries = {
        row["country_id"]: row["country_name"]
        for row in read_csv(COUNTRIES_FILE)
    }
    state_to_country = {
        row["state_id"]: countries.get(row["country_id"])
        for row in read_csv(STATES_FILE)
    }

    rows = []
    for org in read_csv(ORGANIZATIONS_FILE):
        created_at = parse_created_at(org.get("created_at"))
        if created_at is None:
            continue
        rows.append({
            "country_name": state_to_country.get(org.get("state_id")),
            "org_type": (org.get("org_type") or "").strip(),
            "is_collaborator": parse_bool(org.get("is_collaborator")),
            "is_contributor": parse_bool(org.get("is_contributor")),
            "org_rating": parse_rating(org.get("org_rating")),
            "created_at": created_at,
        })
    return rows


def apply_filters(
    rows: list[dict[str, Any]],
    country: Optional[str],
    organization_type: Optional[str],
    start: Optional[datetime],
    end: Optional[datetime],
) -> list[dict[str, Any]]:
    """Keep rows that match the filters and fall inside the time window.

    Runs once before any KPI is calculated. Filter matching ignores case.

    Args:
        rows: Joined rows from load_rows().
        country: country_name to match (e.g. UNITED_STATES), or None.
        organization_type: org_type to match (e.g. non_profit), or None.
        start: Inclusive lower bound on created_at, or None for no limit.
        end: Inclusive upper bound on created_at, or None for no limit.

    Returns:
        The rows that pass every filter.
    """
    country_key = country.lower() if country else None
    type_key = organization_type.lower() if organization_type else None

    filtered = []
    for row in rows:
        if country_key and (row["country_name"] or "").lower() != country_key:
            continue
        if type_key and row["org_type"].lower() != type_key:
            continue
        if start is not None and row["created_at"] < start:
            continue
        if end is not None and row["created_at"] > end:
            continue
        filtered.append(row)
    return filtered


def count_total_organizations(rows: list[dict[str, Any]]) -> int:
    """Return the number of organizations in the filtered rows."""
    return len(rows)


def count_total_collaborators(rows: list[dict[str, Any]]) -> int:
    """Return the number of organizations where is_collaborator is True."""
    return sum(1 for row in rows if row["is_collaborator"])


def count_total_contributors(rows: list[dict[str, Any]]) -> int:
    """Return the number of organizations where is_contributor is True."""
    return sum(1 for row in rows if row["is_contributor"])


def calc_avg_org_rating(rows: list[dict[str, Any]]) -> Optional[float]:
    """Return the mean rating of rated organizations, rounded to 1 decimal.

    Unrated organizations are ignored. Returns None if no row has a rating.
    """
    ratings = [
        row["org_rating"] for row in rows if row["org_rating"] is not None
    ]
    if not ratings:
        return None
    return round(sum(ratings) / len(ratings), 1)


def build_window_result(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate the four KPIs for one window's already-filtered rows."""
    return {
        "total_organizations": count_total_organizations(rows),
        "total_collaborators": count_total_collaborators(rows),
        "total_contributors": count_total_contributors(rows),
        "avg_org_rating": calc_avg_org_rating(rows),
    }


def parse_event_body(event: Any) -> dict[str, Any]:
    """Return the request parameters from a Lambda event.

    Uses event["body"] if present, otherwise the event itself. The body may
    be a JSON string or a dict; empty or missing acts like {}.

    Raises:
        BadRequestError: If the body is not valid JSON or not an object.
    """
    if not event:
        return {}
    body = event.get("body", event) if isinstance(event, dict) else event
    if body is None or body == "":
        return {}
    if isinstance(body, (str, bytes)):
        try:
            body = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise BadRequestError("Request body is not valid JSON") from None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise BadRequestError("Request body must be a JSON object")
    return body


def clean_text(value: Any) -> Optional[str]:
    """Return a stripped string, or None if the value is missing or blank."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_date(value: Any, field: str) -> Optional[datetime]:
    """Parse a YYYY-MM-DD request date, or return None if it is absent.

    Raises:
        BadRequestError: If the value is present but not a valid date.
    """
    text = clean_text(value)
    if text is None:
        return None
    try:
        return datetime.strptime(text, DATE_FORMAT)
    except ValueError:
        raise BadRequestError(
            f"{field} must be a valid YYYY-MM-DD date"
        ) from None


def build_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Wrap a body dict in an API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": HEADERS,
        "body": json.dumps(body),
    }


def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
    """Handle a KPI request and return the four KPIs per window.

    Args:
        event: API Gateway event or a plain dict of parameters.
        context: Lambda context (unused).

    Returns:
        An API Gateway proxy response. 400 for bad input.
    """
    try:
        params = parse_event_body(event)
        country = clean_text(params.get("country"))
        organization_type = clean_text(params.get("organization_type"))
        start_date = parse_date(params.get("start_date"), "start_date")
        end_date = parse_date(params.get("end_date"), "end_date")
        if start_date and end_date and start_date > end_date:
            raise BadRequestError("start_date must not be after end_date")
    except BadRequestError as error:
        return build_response(400, {"error": str(error)})

    try:
        rows = load_rows()
    except (OSError, KeyError, csv.Error) as error:
        return build_response(500, {"error": f"Could not load data: {error}"})

    result = {}
    if start_date and end_date:
        end_of_day = end_date + timedelta(days=1) - timedelta(microseconds=1)
        window_rows = apply_filters(
            rows, country, organization_type, start_date, end_of_day
        )
        result[CUSTOM_WINDOW] = build_window_result(window_rows)
    else:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for window in FIXED_WINDOWS:
            start = get_window_start(window, now)
            window_rows = apply_filters(
                rows, country, organization_type, start, None
            )
            result[window] = build_window_result(window_rows)

    return build_response(200, result)


if __name__ == "__main__":
    print(json.dumps(json.loads(lambda_handler({}, None)["body"]), indent=2))
