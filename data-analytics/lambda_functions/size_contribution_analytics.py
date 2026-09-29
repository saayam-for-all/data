"""Size & Contribution analytics for the Organization dashboard (#376).

Returns two charts: organizations_by_size and collaborator_vs_contributor.
With no custom dates the response has 7D/30D/1Y/All plus an empty Custom.
If size_* or contribution_* dates are sent, only Custom is returned.

Set USE_MOCK_DATA=true and MOCK_DATA_DIR to run against local CSVs,
otherwise it reads from Postgres using the DB_* env vars.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import pandas as pd

try:
    import psycopg2
except ImportError:  # not needed for mock data
    psycopg2 = None

logger = logging.getLogger(__name__)

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
SIZE_CHART = "organizations_by_size"
CONTRIBUTION_CHART = "collaborator_vs_contributor"
ORGANIZATION_TYPES = ("non_profit", "for_profit")
SIZE_ORDER = {"small": 0, "medium": 1, "large": 2}  # display order only
TRUE_VALUES = ("true", "t", "1", "yes")
REQUIRED_COLUMNS = ("org_id", "org_size", "is_collaborator", "org_type", "state_id")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_MOCK_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data")

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


def parse_event_body(event):
    """Get the filters dict out of the Lambda event."""
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
    """Uppercase and treat '_' as a space, e.g. 'united_states' -> 'UNITED STATES'."""
    return " ".join(str(value).replace("_", " ").split()).upper()


def parse_filters(body):
    """Returns (country, org_type). None means ALL."""
    country = body.get("country") or "ALL"
    org_type = body.get("organization_type") or "ALL"
    if not isinstance(country, str) or not isinstance(org_type, str):
        raise BadRequestError("country and organization_type must be text")
    country = normalize_country(country)
    org_type = org_type.strip().lower()
    if org_type not in ORGANIZATION_TYPES + ("all",):
        raise BadRequestError("organization_type must be non_profit, for_profit or ALL")
    return (
        None if country == "ALL" else country,
        None if org_type == "all" else org_type,
    )


def parse_date(value, key):
    """Parse a YYYY-MM-DD string into a date."""
    if not isinstance(value, str) or not DATE_PATTERN.match(value):
        raise BadRequestError(f"{key} must be a date in YYYY-MM-DD format")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise BadRequestError(f"{key} is not a real calendar date") from None


def parse_date_pair(body, start_key, end_key):
    """Returns (start, end), or None if the pair wasn't sent."""
    start, end = body.get(start_key), body.get(end_key)
    if not start and not end:
        return None
    if not start or not end:
        raise BadRequestError(f"{start_key} and {end_key} must be sent together")
    start, end = parse_date(start, start_key), parse_date(end, end_key)
    if start > end:
        raise BadRequestError(f"{start_key} must be on or before {end_key}")
    return start, end


def utc_today():
    """created_at is stored in UTC, so use the UTC date."""
    return datetime.now(timezone.utc).date()


def midnight(day):
    """date -> datetime at 00:00."""
    return datetime(day.year, day.month, day.day)


def fixed_window(bucket, today):
    """(start, end) for a fixed bucket. End is exclusive, i.e. start of tomorrow."""
    if bucket == "All":
        return None, None
    if bucket == "1Y":
        try:
            start = today.replace(year=today.year - 1)
        except ValueError:  # today is Feb 29
            start = today.replace(year=today.year - 1, day=28)
    else:
        start = today - timedelta(days=7 if bucket == "7D" else 30)
    return midnight(start), midnight(today + timedelta(days=1))


def custom_window(date_pair):
    """End date is inclusive, so go up to midnight of the next day."""
    start, end = date_pair
    return midnight(start), midnight(end + timedelta(days=1))


def size_chart(size_counts):
    """Only sizes that show up in the data, sorted small/medium/large."""
    rows = sorted(size_counts.items(), key=lambda row: (SIZE_ORDER.get(row[0], 99), row[0]))
    return [{"size": size, "count": int(count)} for size, count in rows]


def contribution_chart(total, collaborators, contributors):
    """Separate flags, so the two percentages don't have to add up to 100."""
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


def empty_charts():
    """A bucket with both charts empty."""
    return {SIZE_CHART: [], CONTRIBUTION_CHART: []}


def build_body(count, size_pair, contribution_pair, today):
    """count(start, end) returns (sizes, total, collaborators, contributors)."""
    if size_pair is None and contribution_pair is None:
        body = {}
        for bucket in FIXED_BUCKETS:
            sizes, total, collaborators, contributors = count(*fixed_window(bucket, today))
            body[bucket] = {
                SIZE_CHART: size_chart(sizes),
                CONTRIBUTION_CHART: contribution_chart(total, collaborators, contributors),
            }
        body["Custom"] = empty_charts()
        return body

    # custom dates sent: only return Custom, each chart uses its own range
    custom = empty_charts()
    if size_pair is not None:
        sizes, _, _, _ = count(*custom_window(size_pair))
        custom[SIZE_CHART] = size_chart(sizes)
    if contribution_pair is not None:
        _, total, collaborators, contributors = count(*custom_window(contribution_pair))
        custom[CONTRIBUTION_CHART] = contribution_chart(total, collaborators, contributors)
    return {"Custom": custom}


def read_mock_csv(filename):
    """Read a CSV from MOCK_DATA_DIR as plain text."""
    path = os.path.join(os.getenv("MOCK_DATA_DIR") or DEFAULT_MOCK_DATA_DIR, filename)
    if not os.path.exists(path):
        raise DataSourceError(f"{filename} not found in MOCK_DATA_DIR")
    return pd.read_csv(path, dtype=str)


def to_bool(series):
    """Anything other than true/t/1/yes counts as False."""
    return series.fillna("").str.strip().str.lower().isin(TRUE_VALUES)


def mock_counter(country, org_type):
    """Load the CSVs once and return a count(start, end) function."""
    orgs = read_mock_csv("organizations.csv")
    missing = [col for col in REQUIRED_COLUMNS + ("created_at",) if col not in orgs.columns]
    if missing:
        raise DataSourceError(f"organizations.csv is missing column(s): {', '.join(missing)}")

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce", format="ISO8601")
    orgs["is_collaborator"] = to_bool(orgs["is_collaborator"])
    # is_contributor isn't in every dataset yet, count it as 0 if missing
    if "is_contributor" in orgs.columns:
        orgs["is_contributor"] = to_bool(orgs["is_contributor"])
    else:
        orgs["is_contributor"] = False

    if org_type:
        orgs = orgs[orgs["org_type"] == org_type]
    if country:
        # org -> state -> country
        states = read_mock_csv("states.csv")
        countries = read_mock_csv("countries.csv")
        match = countries["country_code"].fillna("").map(normalize_country) == country
        if "country_name" in countries.columns:
            match |= countries["country_name"].fillna("").map(normalize_country) == country
        country_ids = countries.loc[match, "country_id"]
        state_ids = states.loc[states["country_id"].isin(country_ids), "state_id"]
        orgs = orgs[orgs["state_id"].isin(state_ids)]
    orgs = orgs[orgs["created_at"].notna()]

    def count(start, end):
        window = orgs
        if start is not None:
            window = orgs[(orgs["created_at"] >= start) & (orgs["created_at"] < end)]
        sizes = window["org_size"].dropna().value_counts().to_dict()
        return (
            sizes,
            len(window),
            int(window["is_collaborator"].sum()),
            int(window["is_contributor"].sum()),
        )

    return count


def get_db_connection():
    """Connect using the DB_* env vars."""
    if psycopg2 is None:
        raise DataSourceError("psycopg2 is not installed; set USE_MOCK_DATA=true to use local CSVs")
    required = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise DataSourceError(f"Missing environment variable(s): {', '.join(missing)}")
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def db_counter(cursor, country, org_type):
    """Same idea as mock_counter, but the counting happens in SQL."""
    schema = os.getenv("ORG_ANALYTICS_SCHEMA", "virginia_dev_saayam_rdbms")

    # Virginia's organizations table doesn't have is_contributor yet
    cursor.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = %s"
        " AND table_name = 'organizations' AND column_name = 'is_contributor'",
        (schema,),
    )
    has_contributor = cursor.fetchone() is not None
    contributor_sql = "COUNT(*) FILTER (WHERE o.is_contributor)" if has_contributor else "0"

    from_sql = f"FROM {schema}.organizations o"
    conditions, params = ["o.created_at IS NOT NULL"], []
    if country:
        from_sql += (
            f" JOIN {schema}.state s ON s.state_id = o.state_id"
            f" JOIN {schema}.country c ON c.country_id = s.country_id"
        )
        # same normalization as normalize_country()
        code = "UPPER(BTRIM(REGEXP_REPLACE(c.country_code, '[_[:space:]]+', ' ', 'g')))"
        name = "UPPER(BTRIM(REGEXP_REPLACE(c.country_name, '[_[:space:]]+', ' ', 'g')))"
        conditions.append(f"({code} = %s OR {name} = %s)")
        params += [country, country]
    if org_type:
        conditions.append("o.org_type = %s")
        params.append(org_type)

    def count(start, end):
        where, values = list(conditions), list(params)
        if start is not None:
            where.append("o.created_at >= %s AND o.created_at < %s")
            values += [start, end]
        where_sql = " AND ".join(where)
        cursor.execute(
            f"SELECT o.org_size::text, COUNT(*) {from_sql} WHERE {where_sql}"
            " AND o.org_size IS NOT NULL GROUP BY o.org_size",
            values,
        )
        sizes = dict(cursor.fetchall())
        cursor.execute(
            f"SELECT COUNT(*), COUNT(*) FILTER (WHERE o.is_collaborator), {contributor_sql}"
            f" {from_sql} WHERE {where_sql}",
            values,
        )
        total, collaborators, contributors = cursor.fetchone()
        return sizes, total, collaborators, contributors

    return count


def build_response(status_code, body):
    """Same response format as the other analytics lambdas."""
    return {"statusCode": status_code, "headers": HEADERS, "body": json.dumps(body)}


def lambda_handler(event, context):
    """Lambda entry point."""
    try:
        body = parse_event_body(event)
        country, org_type = parse_filters(body)
        size_pair = parse_date_pair(body, "size_start_date", "size_end_date")
        contribution_pair = parse_date_pair(
            body, "contribution_start_date", "contribution_end_date"
        )
    except BadRequestError as exc:
        return build_response(400, {"error": str(exc)})

    connection = None
    try:
        if os.getenv("USE_MOCK_DATA", "false").strip().lower() == "true":
            count = mock_counter(country, org_type)
            result = build_body(count, size_pair, contribution_pair, utc_today())
        else:
            connection = get_db_connection()
            with connection.cursor() as cursor:
                count = db_counter(cursor, country, org_type)
                result = build_body(count, size_pair, contribution_pair, utc_today())
        return build_response(200, result)
    except DataSourceError as exc:
        logger.error("Size & Contribution analytics: %s", exc)
        return build_response(500, {"error": str(exc)})
    except Exception:
        logger.exception("Size & Contribution analytics failed")
        return build_response(500, {"error": "Internal server error"})
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    # USE_MOCK_DATA=true MOCK_DATA_DIR=/path/to/csvs python size_contribution_analytics.py
    os.environ.setdefault("USE_MOCK_DATA", "true")

    size_range = {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"}
    contribution_range = {
        "contribution_start_date": "2025-01-01",
        "contribution_end_date": "2025-12-31",
    }
    samples = [
        ("No body", None),
        ("Country filter", {"country": "USA"}),
        ("Organization type filter", {"organization_type": "non_profit"}),
        ("Size Custom range only", size_range),
        ("Contribution Custom range only", contribution_range),
        ("Both Custom ranges together", {**size_range, **contribution_range}),
        ("Invalid: only half of a pair", {"size_start_date": "2026-01-01"}),
    ]

    print(f"Run date (UTC): {utc_today()}")
    for name, sample in samples:
        event = {} if sample is None else {"body": json.dumps(sample)}
        response = lambda_handler(event, None)
        print(f"\n=== {name} ===")
        print(f"Event: {json.dumps(event)}")
        print(f"statusCode: {response['statusCode']}")
        print(json.dumps(json.loads(response["body"]), indent=2))
