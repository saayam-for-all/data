"""Organization Dashboard KPIs API.

Returns four KPI values for the Organization Dashboard:

    total_organizations  number of organizations created in the window
    total_collaborators  how many of those are flagged as collaborators
    total_contributors   how many of those are flagged as contributors
    avg_org_rating       average rating of those organizations, rounded to one
                         decimal; organizations without a rating are ignored

The function reads three CSV files (organizations, states, countries) from a
``mock_data`` folder next to this file, with no environment variables, matching
the Lambda zip layout. The response matches the other analytics APIs: a
``statusCode``, CORS ``headers`` and a JSON string ``body``.

The code is organized so it can grow: the time windows are worked out in one
place, the filters are applied once before any KPI is calculated, and each KPI
is a small named step so new KPIs can be added without touching the others.
"""

import csv
import json
import os
from datetime import datetime, timedelta, timezone

MOCK_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data")

FIXED_WINDOWS = ("7D", "30D", "1Y", "All")


def _read_csv(name):
    path = os.path.join(MOCK_DATA_DIR, name)
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_organizations():
    """Load organizations joined to their country via state.

    Each returned organization carries the resolved ``country_name`` and
    ``country_code`` so the country filter can be applied without re-joining.
    """
    organizations = _read_csv("organizations.csv")
    states = {s["state_id"]: s for s in _read_csv("states.csv")}
    countries = {c["country_id"]: c for c in _read_csv("countries.csv")}

    for org in organizations:
        state = states.get(org.get("state_id"))
        country = countries.get(state["country_id"]) if state else None
        org["country_name"] = country["country_name"] if country else None
        org["country_code"] = country["country_code"] if country else None
    return organizations


def parse_created_at(value):
    """Return a timezone-aware UTC datetime, or None if it cannot be read.

    Accepts values with or without a timezone offset; a value with an offset
    gives the same result as the equivalent value without one.
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    normalized = text.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M%z", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _is_date_only(value):
    """True when the value is a plain date with no time component."""
    text = str(value).strip()
    if not text:
        return False
    return " " not in text and "T" not in text


def _to_bool(value):
    return str(value).strip().lower() == "true"


def _to_rating(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def window_bounds(window, now=None, start_date=None, end_date=None):
    """Return (start, end) UTC datetimes for a window, or (None, end) for All.

    ``start`` is None for "All", meaning no lower bound. ``end`` is the upper
    bound (inclusive by date) for every window.
    """
    now = now or datetime.now(timezone.utc)
    if window == "All":
        return None, now
    if window == "7D":
        return now - timedelta(days=7), now
    if window == "30D":
        return now - timedelta(days=30), now
    if window == "1Y":
        return now - timedelta(days=365), now
    if window == "Custom":
        start = parse_created_at(start_date) if start_date else None
        end = parse_created_at(end_date) if end_date else now
        # A date-only end_date (no time component) covers the whole end day, so
        # organizations created later that day are included rather than dropped.
        if end is not None and end_date and _is_date_only(end_date):
            end = end + timedelta(days=1) - timedelta(microseconds=1)
        return start, end
    raise ValueError("Unknown window: %s" % window)


def in_window(created_at, start, end):
    if created_at is None:
        return False
    if start is not None and created_at < start:
        return False
    if end is not None and created_at > end:
        return False
    return True


def apply_filters(organizations, country=None, organization_type=None):
    """Return organizations matching the country and organization_type filters.

    Country matching is case-insensitive and tolerates spaces vs underscores,
    and accepts either the country name or the country code.
    """
    result = organizations

    if country:
        wanted = str(country).strip().lower().replace(" ", "_")
        result = [
            o for o in result
            if (o.get("country_name") or "").lower() == wanted
            or (o.get("country_code") or "").lower() == wanted
        ]

    if organization_type:
        wanted_type = str(organization_type).strip().lower()
        result = [o for o in result if (o.get("org_type") or "").strip().lower() == wanted_type]

    return result


def kpi_total_organizations(orgs):
    return len(orgs)


def kpi_total_collaborators(orgs):
    return sum(1 for o in orgs if _to_bool(o.get("is_collaborator")))


def kpi_total_contributors(orgs):
    return sum(1 for o in orgs if _to_bool(o.get("is_contributor")))


def kpi_avg_org_rating(orgs):
    ratings = [r for r in (_to_rating(o.get("org_rating")) for o in orgs) if r is not None]
    if not ratings:
        return None
    return round(sum(ratings) / len(ratings), 1)


def compute_kpis(orgs_in_window):
    return {
        "total_organizations": kpi_total_organizations(orgs_in_window),
        "total_collaborators": kpi_total_collaborators(orgs_in_window),
        "total_contributors": kpi_total_contributors(orgs_in_window),
        "avg_org_rating": kpi_avg_org_rating(orgs_in_window),
    }


def kpis_for_window(filtered_orgs, window, now, start_date=None, end_date=None):
    start, end = window_bounds(window, now=now, start_date=start_date, end_date=end_date)
    in_range = [o for o in filtered_orgs if in_window(o.get("_created_at"), start, end)]
    return compute_kpis(in_range)


def parse_request(event):
    """Return the request payload as a dict.

    The body may arrive as a JSON string (API Gateway) or as an object. An
    empty body behaves like ``{}``. Top-level event fields are used as a
    fallback when there is no body.
    """
    if event is None:
        return {}
    body = event.get("body", None) if isinstance(event, dict) else None
    if body is None:
        return event if isinstance(event, dict) else {}
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        if body.strip() == "":
            return {}
        try:
            parsed = json.loads(body)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event, context=None):
    payload = parse_request(event)

    country = payload.get("country")
    organization_type = payload.get("organization_type")
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")

    try:
        organizations = load_organizations()
    except (OSError, csv.Error) as exc:
        return build_response(500, {"error": "Could not load data: %s" % exc})

    # Parse each organization's created_at once, up front.
    for org in organizations:
        org["_created_at"] = parse_created_at(org.get("created_at"))

    # Filters are applied once, before any KPI is calculated.
    filtered = apply_filters(organizations, country=country, organization_type=organization_type)

    now = datetime.now(timezone.utc)

    # A date pair returns only Custom; otherwise the four fixed windows.
    if start_date and end_date:
        result = {"Custom": kpis_for_window(filtered, "Custom", now, start_date, end_date)}
    else:
        result = {w: kpis_for_window(filtered, w, now) for w in FIXED_WINDOWS}

    return build_response(200, result)


if __name__ == "__main__":
    print(json.dumps(json.loads(lambda_handler({}, None)["body"]), indent=2))
