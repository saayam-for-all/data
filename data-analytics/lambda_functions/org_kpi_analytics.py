"""Organization Dashboard KPI API (issue #708).

The Lambda zip places organizations.csv, states.csv, and countries.csv in a
mock_data directory beside this file. The CSV reader keeps the four dashboard
KPIs independent of a database connection or deployment environment variables.
"""

import csv
import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "mock_data"
WINDOWS = ("7D", "30D", "1Y", "All")
TRUE_VALUES = frozenset(("true", "t", "1", "yes"))
ORG_TYPES = frozenset(("non_profit", "for_profit"))
HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


class BadRequest(ValueError):
    """The client supplied an invalid filter or date range."""


class DataError(RuntimeError):
    """The packaged CSV data is missing or malformed."""


def response(status, payload):
    """Use the response envelope shared by the other analytics Lambdas."""
    return {"statusCode": status, "headers": HEADERS, "body": json.dumps(payload)}


def parse_body(event):
    """Accept a direct body object or API Gateway's JSON string body."""
    body = event.get("body", event) if isinstance(event, dict) else event
    if body is None or body == "":
        return {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise BadRequest("Request body is not valid JSON") from None
    if not isinstance(body, dict):
        raise BadRequest("Request body must be a JSON object")
    return body


def is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def parse_date(value, name):
    """Dates in requests must be actual calendar days in YYYY-MM-DD form."""
    if not isinstance(value, str) or len(value.strip()) != 10:
        raise BadRequest(f"{name} must be a date in YYYY-MM-DD format")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise BadRequest(f"{name} must be a valid date in YYYY-MM-DD format") from None


def custom_date_pair(body):
    """Return an inclusive date pair, or None for the four fixed windows."""
    start, end = body.get("start_date"), body.get("end_date")
    if is_blank(start) and is_blank(end):
        return None
    if is_blank(start) or is_blank(end):
        raise BadRequest("start_date and end_date must be sent together")
    start, end = parse_date(start, "start_date"), parse_date(end, "end_date")
    if start > end:
        raise BadRequest("start_date must be on or before end_date")
    return start, end


def normalize_country(value):
    """Country codes and underscore-separated names use one comparison form."""
    return " ".join(value.replace("_", " ").strip().upper().split())


def normalize_org_type(value):
    return "_".join(value.strip().lower().replace("-", " ").split())


def parse_filters(body):
    """Parse filter values once; None means no filter."""
    country = body.get("country")
    org_type = body.get("organization_type")
    if country is not None and not isinstance(country, str):
        raise BadRequest("country must be a string")
    if org_type is not None and not isinstance(org_type, str):
        raise BadRequest("organization_type must be a string")
    country = normalize_country(country or "ALL")
    org_type = normalize_org_type(org_type or "ALL")
    if org_type != "all" and org_type not in ORG_TYPES:
        raise BadRequest("organization_type must be non_profit, for_profit or ALL")
    return (None if country in ("ALL", "ALL COUNTRIES") else country,
            None if org_type == "all" else org_type)


def read_csv(name, required):
    path = DATA_DIR / name
    try:
        with path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            missing = set(required) - set(reader.fieldnames or ())
            if missing:
                raise DataError(f"{name} is missing columns: {', '.join(sorted(missing))}")
            return list(reader)
    except OSError as exc:
        raise DataError(f"Could not read {name} in mock_data") from exc


def load_data():
    """Read each file once; geographic lookups never multiply organization rows."""
    orgs = read_csv("organizations.csv", (
        "org_id", "state_id", "org_type", "is_collaborator",
        "is_contributor", "org_rating", "created_at",
    ))
    states = read_csv("states.csv", ("state_id", "country_id"))
    countries = read_csv("countries.csv", (
        "country_id", "country_name", "country_code",
    ))
    return orgs, states, countries


def created_day(value):
    """Interpret naive timestamps as UTC and normalize offset timestamps to UTC."""
    try:
        timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(timezone.utc)
        return timestamp.date()
    except (AttributeError, ValueError, TypeError):
        return None


def apply_filters(orgs, states, countries, country, org_type):
    """Resolve the country and filter organizations before calculating any KPI."""
    country_id = None
    if country is not None:
        matches = {
            row["country_id"] for row in countries
            if country in (normalize_country(row["country_name"]),
                           normalize_country(row["country_code"]))
        }
        if not matches:
            raise BadRequest("Unknown country")
        country_id = matches

    state_to_country = {row["state_id"]: row["country_id"] for row in states}
    filtered = []
    for row in orgs:
        if org_type and normalize_org_type(row["org_type"]) != org_type:
            continue
        if country_id and state_to_country.get(row["state_id"]) not in country_id:
            continue
        day = created_day(row["created_at"])
        if day is not None:
            filtered.append((row, day))
    return filtered


def window_bounds(name, today, custom=None):
    """Return inclusive dates; All has no date boundaries."""
    if name == "Custom":
        return custom
    if name == "7D":
        return today - timedelta(days=6), today
    if name == "30D":
        return today - timedelta(days=29), today
    if name == "1Y":
        # Current month plus the eleven preceding calendar months.
        month_index = today.year * 12 + today.month - 11
        year, month_zero = divmod(month_index - 1, 12)
        return date(year, month_zero + 1, 1), today
    if name == "All":
        return None, None
    raise ValueError(f"Unknown window: {name}")


def rows_in_window(rows, start, end):
    if start is None:
        return [row for row, _day in rows]
    return [row for row, day in rows if start <= day <= end]


def is_true(value):
    return str(value).strip().lower() in TRUE_VALUES


def total_organizations(rows):
    return len(rows)


def total_collaborators(rows):
    return sum(is_true(row["is_collaborator"]) for row in rows)


def total_contributors(rows):
    return sum(is_true(row["is_contributor"]) for row in rows)


def avg_org_rating(rows):
    ratings = []
    for row in rows:
        try:
            rating = float(row["org_rating"])
        except (TypeError, ValueError):
            continue
        if math.isfinite(rating):
            ratings.append(rating)
    return round(sum(ratings) / len(ratings), 1) if ratings else None


def calculate_kpis(rows):
    return {
        "total_organizations": total_organizations(rows),
        "total_collaborators": total_collaborators(rows),
        "total_contributors": total_contributors(rows),
        "avg_org_rating": avg_org_rating(rows),
    }


def lambda_handler(event, context):
    try:
        body = parse_body(event)
        country, org_type = parse_filters(body)
        custom = custom_date_pair(body)
        orgs, states, countries = load_data()
        filtered = apply_filters(orgs, states, countries, country, org_type)
        today = datetime.now(timezone.utc).date()
        names = ("Custom",) if custom else WINDOWS
        result = {}
        for name in names:
            start, end = window_bounds(name, today, custom)
            result[name] = calculate_kpis(rows_in_window(filtered, start, end))
        return response(200, result)
    except BadRequest as exc:
        return response(400, {"error": str(exc)})
    except DataError as exc:
        logger.error("Organization KPI source error: %s", exc)
        return response(500, {"error": str(exc)})
    except Exception:
        logger.exception("Organization KPI analytics failed")
        return response(500, {"error": "Internal server error"})
