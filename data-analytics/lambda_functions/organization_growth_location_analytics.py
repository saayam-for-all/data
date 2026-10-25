"""
Growth & Location analytics for the Organization Analytics dashboard (issue #336).

One call returns every time bucket ("7D", "30D", "1Y", "All", "Custom") so the
frontend can switch either chart's range without another request. Each bucket:

    {
      "growth_trend": [{"period", "total_organizations", "collaborators"}, ...],
      "organizations_by_location": [{"country", "count"}, ...]   # max 4, no "Other"
    }

Event parameters (only used for the "Custom" key; the two charts are independent):
    growth_start_date / growth_end_date      YYYY-MM-DD
    location_start_date / location_end_date  YYYY-MM-DD

Semantics
  * total_organizations: absolute all-time running total of organizations created
    up to the end of each period (never reset per bucket / window).
  * collaborators: organizations with is_collaborator created within that period.
  * 7D / 30D / Custom group by day; 1Y / All group by calendar month.
  * organizations_by_location: organizations created in the window, by country.

Data comes from organizations, states and countries. Locally, pass CSV paths via
load_csv_data(); the Lambda path reads from the Analytics database.
"""
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
TOP_LOCATIONS = 4
RANGE_KEYS = ["7D", "30D", "1Y", "All", "Custom"]


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": body,
    }


# ---------- data loading ----------

def _parse_ts(value):
    return datetime.fromisoformat(str(value).strip()).date()


def _truthy(value):
    return str(value).strip().lower() in ("true", "t", "1", "yes")


def load_csv_data(organizations_path, states_path, countries_path):
    """Return org rows as [{'created': date, 'is_collaborator': bool, 'country': str|None}]."""
    with open(countries_path, newline="") as f:
        country_code = {r["country_id"]: r["country_code"] for r in csv.DictReader(f)}
    with open(states_path, newline="") as f:
        state_country = {r["state_id"]: country_code.get(r["country_id"]) for r in csv.DictReader(f)}
    orgs = []
    with open(organizations_path, newline="") as f:
        for r in csv.DictReader(f):
            if not r.get("created_at"):
                continue
            orgs.append({
                "created": _parse_ts(r["created_at"]),
                "is_collaborator": _truthy(r["is_collaborator"]),
                "country": state_country.get(r["state_id"]),
            })
    return orgs


def load_db_data(cursor):
    cursor.execute(f"""
        SELECT o.created_at, o.is_collaborator, c.country_code
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.states s ON o.state_id = s.state_id
        LEFT JOIN {SCHEMA_NAME}.countries c ON s.country_id = c.country_id
        WHERE o.created_at IS NOT NULL
    """)
    return [
        {
            "created": r["created_at"].date() if isinstance(r["created_at"], datetime) else r["created_at"],
            "is_collaborator": bool(r["is_collaborator"]),
            "country": r["country_code"],
        }
        for r in cursor.fetchall()
    ]


def get_db_connection():
    import boto3
    import psycopg2

    ssm = boto3.client("ssm", region_name="us-east-1")
    creds = json.loads(ssm.get_parameter(
        Name="/dev/saayam/db/Virginia/Analytics/user", WithDecryption=True
    )["Parameter"]["Value"])
    return psycopg2.connect(
        host=creds["HOST"], database=creds["DATABASE NAME"], user=creds["USERNAME"],
        password=creds["PASSWORD"], port=creds["PORT"], sslmode="require",
    )


# ---------- windows & bucketing ----------

def _parse_date(value, name):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a YYYY-MM-DD date")


def resolve_window(time_range, orgs, today, start=None, end=None):
    """Return (start_date, end_date, granularity) with inclusive bounds."""
    if time_range == "7D":
        return today - timedelta(days=6), today, "day"
    if time_range == "30D":
        return today - timedelta(days=29), today, "day"
    if time_range == "1Y":
        first = date(today.year, today.month, 1)
        m = first.month - 11
        y = first.year + (m - 1) // 12
        return date(y, (m - 1) % 12 + 1, 1), today, "month"
    if time_range == "All":
        earliest = min((o["created"] for o in orgs), default=today)
        return date(earliest.year, earliest.month, 1), today, "month"
    if time_range == "Custom":
        if start > end:
            raise ValueError("start date must not be after end date")
        return start, end, "day"
    raise ValueError(f"Invalid time range: {time_range}")


def _periods(start, end, granularity):
    """Yield (label, period_start, period_end) covering [start, end]."""
    if granularity == "day":
        d = start
        while d <= end:
            yield d.isoformat(), d, d
            d += timedelta(days=1)
    else:
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            p_start = date(y, m, 1)
            ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
            yield f"{y:04d}-{m:02d}", p_start, date(ny, nm, 1) - timedelta(days=1)
            y, m = ny, nm


def growth_trend(orgs, start, end, granularity):
    created_sorted = sorted(o["created"] for o in orgs)
    result = []
    for label, p_start, p_end in _periods(start, end, granularity):
        # Window edges clamp the first/last period; totals still count all time.
        lo, hi = max(p_start, start), min(p_end, end)
        total = sum(1 for c in created_sorted if c <= hi)
        collabs = sum(1 for o in orgs if o["is_collaborator"] and lo <= o["created"] <= hi)
        result.append({"period": label, "total_organizations": total, "collaborators": collabs})
    return result


def organizations_by_location(orgs, start, end):
    counts = Counter(
        o["country"] for o in orgs
        if o["country"] and start <= o["created"] <= end
    )
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_LOCATIONS]
    return [{"country": c, "count": n} for c, n in ranked]


def build_analytics(orgs, today=None, event=None):
    today = today or date.today()
    event = event or {}
    body = {}
    for key in RANGE_KEYS:
        if key == "Custom":
            g_start = _parse_date(event["growth_start_date"], "growth_start_date") if event.get("growth_start_date") else None
            g_end = _parse_date(event["growth_end_date"], "growth_end_date") if event.get("growth_end_date") else None
            l_start = _parse_date(event["location_start_date"], "location_start_date") if event.get("location_start_date") else None
            l_end = _parse_date(event["location_end_date"], "location_end_date") if event.get("location_end_date") else None
            entry = {"growth_trend": [], "organizations_by_location": []}
            if g_start and g_end:
                s, e, gran = resolve_window("Custom", orgs, today, g_start, g_end)
                entry["growth_trend"] = growth_trend(orgs, s, e, gran)
            if l_start and l_end:
                s, e, _ = resolve_window("Custom", orgs, today, l_start, l_end)
                entry["organizations_by_location"] = organizations_by_location(orgs, s, e)
            body[key] = entry
            continue
        s, e, gran = resolve_window(key, orgs, today)
        body[key] = {
            "growth_trend": growth_trend(orgs, s, e, gran),
            "organizations_by_location": organizations_by_location(orgs, s, e),
        }
    return body


def lambda_handler(event, context):
    conn = cursor = None
    try:
        from psycopg2.extras import RealDictCursor
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        orgs = load_db_data(cursor)
        return build_response(200, build_analytics(orgs, event=event))
    except ValueError as e:
        return build_response(400, {"error": str(e)})
    except Exception as e:
        print(f"Growth & location analytics failed: {e}")
        return build_response(500, {"error": "Internal error"})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
