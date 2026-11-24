"""Organization dashboard KPIs from CSVs in the adjacent mock_data directory.

Without custom dates, return 7D, 30D, 1Y and All. A complete custom
start_date/end_date pair returns only Custom. Dates are inclusive and UTC.
"""

import csv
import json
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

logger = logging.getLogger(__name__)
MOCK_DATA_DIR = Path(__file__).resolve().parent / "mock_data"
HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}
TRUE_VALUES = {"true", "t", "1", "yes"}
ORGANIZATION_TYPES = {"non_profit", "for_profit"}


class BadRequestError(ValueError):
    """Invalid API request."""


def is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def parse_event_body(event):
    body = event.get("body", event) if isinstance(event, dict) else event
    if is_blank(body):
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
    return " ".join(value.replace("_", " ").split()).upper()


def normalize_org_type(value):
    return "_".join(value.strip().lower().replace("-", " ").replace("_", " ").split())


def parse_filters(body):
    country = body.get("country")
    org_type = body.get("organization_type")
    if not is_blank(country) and not isinstance(country, str):
        raise BadRequestError("country must be a string")
    if not is_blank(org_type) and not isinstance(org_type, str):
        raise BadRequestError("organization_type must be a string")
    country = normalize_country(country) if not is_blank(country) else "ALL"
    org_type = normalize_org_type(org_type) if not is_blank(org_type) else "all"
    if org_type != "all" and org_type not in ORGANIZATION_TYPES:
        raise BadRequestError("organization_type must be non_profit, for_profit or ALL")
    return (None if country == "ALL" else country,
            None if org_type == "all" else org_type)


def parse_date(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        raise BadRequestError(f"{field} must be a date in YYYY-MM-DD format")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise BadRequestError(f"{field} is not a real calendar date") from None


def parse_date_pair(body):
    start, end = body.get("start_date"), body.get("end_date")
    if is_blank(start) and is_blank(end):
        return None
    if is_blank(start) or is_blank(end):
        raise BadRequestError("start_date and end_date must be sent together")
    start = parse_date(start, "start_date")
    end = parse_date(end, "end_date")
    if start > end:
        raise BadRequestError("start_date must be on or before end_date")
    return start, end


def resolve_windows(date_pair, today):
    """All windows use inclusive UTC calendar dates; 1Y covers 12 months."""
    if date_pair is not None:
        return {"Custom": date_pair}
    year, month = divmod(today.year * 12 + today.month - 1 - 11, 12)
    return {
        "7D": (today - timedelta(days=6), today),
        "30D": (today - timedelta(days=29), today),
        "1Y": (date(year, month + 1, 1), today),
        "All": (None, None),
    }


def read_csv(filename, required_columns):
    with (MOCK_DATA_DIR / filename).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = set(required_columns) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{filename} missing columns: {', '.join(sorted(missing))}")
        return list(reader)


def parse_created_at(value):
    """Treat naive timestamps as UTC and convert offset-aware values to UTC."""
    try:
        timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).date()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def load_data():
    organizations = read_csv("organizations.csv", (
        "org_id", "state_id", "org_type", "org_rating", "is_collaborator",
        "is_contributor", "created_at",
    ))
    states = read_csv("states.csv", ("state_id", "country_id"))
    countries = read_csv("countries.csv", ("country_id", "country_name", "country_code"))
    return organizations, states, countries


def apply_filters(organizations, states, countries, country, org_type):
    """Apply shared filters once and discard unreadable creation timestamps."""
    state_ids = None
    if country is not None:
        country_ids = {
            row["country_id"] for row in countries
            if country in (normalize_country(row["country_name"] or ""),
                           normalize_country(row["country_code"] or ""))
        }
        if not country_ids:
            raise BadRequestError("Unknown country")
        state_ids = {row["state_id"] for row in states if row["country_id"] in country_ids}
    result = []
    for row in organizations:
        if state_ids is not None and row["state_id"] not in state_ids:
            continue
        if org_type is not None and normalize_org_type(row["org_type"] or "") != org_type:
            continue
        created = parse_created_at(row["created_at"])
        if created is not None:
            result.append({**row, "created_date": created})
    return result


def select_window(organizations, start, end):
    if start is None:
        return organizations
    return [row for row in organizations if start <= row["created_date"] <= end]


def total_organizations(rows):
    return len(rows)


def total_collaborators(rows):
    return sum((row["is_collaborator"] or "").strip().lower() in TRUE_VALUES for row in rows)


def total_contributors(rows):
    return sum((row["is_contributor"] or "").strip().lower() in TRUE_VALUES for row in rows)


def avg_org_rating(rows):
    ratings = []
    for row in rows:
        try:
            rating = float(row["org_rating"])
        except (TypeError, ValueError):
            continue
        if math.isfinite(rating):
            ratings.append(rating)
    return round(mean(ratings), 1) if ratings else None


def calculate_kpis(rows):
    return {
        "total_organizations": total_organizations(rows),
        "total_collaborators": total_collaborators(rows),
        "total_contributors": total_contributors(rows),
        "avg_org_rating": avg_org_rating(rows),
    }


def build_response(status_code, body):
    return {"statusCode": status_code, "headers": HEADERS, "body": json.dumps(body, allow_nan=False)}


def lambda_handler(event, context):
    """Validate filters, load data, and return all four KPIs per window."""
    try:
        body = parse_event_body(event)
        country, org_type = parse_filters(body)
        date_pair = parse_date_pair(body)
        organizations = apply_filters(*load_data(), country, org_type)
        windows = resolve_windows(date_pair, datetime.now(timezone.utc).date())
        result = {key: calculate_kpis(select_window(organizations, *window))
                  for key, window in windows.items()}
        return build_response(200, result)
    except BadRequestError as exc:
        return build_response(400, {"error": str(exc)})
    except Exception:
        logger.exception("Organization KPI analytics failed")
        return build_response(500, {"error": "Internal server error"})
