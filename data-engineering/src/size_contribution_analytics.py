import json
import os
from datetime import datetime, timedelta

import pandas as pd

# psycopg2 is optional so the file still runs with USE_MOCK_DATA=true
try:
    import psycopg2
except ImportError:
    psycopg2 = None

SCHEMA_NAME = "virginia_dev_saayam_rdbms"

VALID_ORG_TYPES = {"non_profit", "for_profit"}
FIXED_BUCKETS = {"7D": 7, "30D": 30, "1Y": 365, "All": None}


# ---------------------------------------------------------------------------
# Response / request plumbing
# ---------------------------------------------------------------------------

def get_empty_bucket():
    return {
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
    }


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def parse_event_body(event):
    """Accepts either a raw dict (local/test invocation) or an API Gateway
    style event with a JSON-encoded "body" string."""
    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("Request body is not valid JSON.")

    if isinstance(body, dict):
        return body

    return {}


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def parse_date_range(body, start_key, end_key):
    """Returns (start, end) as datetimes, or None if neither key was sent.
    Raises ValueError on a half-supplied pair, a bad format or start > end."""
    start_date = body.get(start_key)
    end_date = body.get(end_key)

    if not start_date and not end_date:
        return None

    if not start_date or not end_date:
        raise ValueError(f"Both {start_key} and {end_key} must be provided together.")

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValueError(f"{start_key} and {end_key} must be in YYYY-MM-DD format.")

    if start > end:
        raise ValueError(f"{start_key} must not be after {end_key}.")

    return start, end


def parse_common_filters(body):
    """Parses country, organization_type and both custom date ranges from the
    request body. Raises ValueError on invalid input so the caller can return
    a 400 response."""
    country = body.get("country") or "ALL"
    organization_type = body.get("organization_type") or "ALL"

    if organization_type.upper() == "ALL":
        organization_type = "ALL"
    else:
        organization_type = organization_type.lower()
        if organization_type not in VALID_ORG_TYPES:
            raise ValueError(
                f"Invalid organization_type '{organization_type}'. Must be one of {sorted(VALID_ORG_TYPES)} or ALL."
            )

    return {
        "country": country,
        "organization_type": organization_type,
        "size_range": parse_date_range(body, "size_start_date", "size_end_date"),
        "contribution_range": parse_date_range(
            body, "contribution_start_date", "contribution_end_date"
        ),
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_from_csv():
    folder = os.environ.get("MOCK_DATA_DIR", ".")
    organizations = pd.read_csv(os.path.join(folder, "organizations.csv"))
    states = pd.read_csv(os.path.join(folder, "states.csv"))
    countries = pd.read_csv(os.path.join(folder, "countries.csv"))
    return organizations, states, countries


def load_from_postgres():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed, cannot connect to the database.")

    # Matches .env.example: DATABASE_URL=postgresql://user:password@host:port/dbname
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        frames = []
        for table in ("organizations", "state", "country"):
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {SCHEMA_NAME}.{table}")
            columns = [col[0] for col in cursor.description]
            frames.append(pd.DataFrame(cursor.fetchall(), columns=columns))
            cursor.close()
        return tuple(frames)
    finally:
        conn.close()


def load_organizations():
    """Returns one dataframe with organizations joined to state and country."""
    if os.environ.get("USE_MOCK_DATA", "true").lower() == "true":
        organizations, states, countries = load_from_csv()
    else:
        organizations, states, countries = load_from_postgres()

    states = states[[c for c in ("state_id", "country_id") if c in states.columns]]
    countries = countries[
        [c for c in ("country_id", "country_code", "country_name") if c in countries.columns]
    ]

    df = organizations.merge(states, on="state_id", how="left")
    df = df.merge(countries, on="country_id", how="left")

    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    df["created_at"] = df["created_at"].dt.tz_localize(None)
    return df


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def apply_country_and_type(df, filters):
    country = filters["country"]
    organization_type = filters["organization_type"]

    if country != "ALL":
        wanted = country.lower()
        match = pd.Series(False, index=df.index)
        for column in ("country_code", "country_name"):
            if column in df.columns:
                match = match | (df[column].astype(str).str.lower() == wanted)
        df = df[match]

    if organization_type != "ALL" and "org_type" in df.columns:
        df = df[df["org_type"].astype(str).str.lower() == organization_type]

    return df


def filter_last_days(df, days, now):
    if days is None:
        return df
    return df[df["created_at"] >= now - timedelta(days=days)]


def filter_date_range(df, start, end):
    # end date is inclusive
    return df[(df["created_at"] >= start) & (df["created_at"] < end + timedelta(days=1))]


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def to_bool(series):
    # flags can come through as True/False, 'true'/'false', 't'/'f' or 1/0
    return series.astype(str).str.strip().str.lower().isin(["true", "t", "1", "yes"])


def build_organizations_by_size(df):
    if df.empty or "org_size" not in df.columns:
        return []

    counts = df["org_size"].dropna().astype(str).value_counts()
    rows = [{"size": size, "count": int(count)} for size, count in counts.items()]
    rows.sort(key=lambda row: (-row["count"], row["size"]))
    return rows


def count_flag(df, column):
    # is_contributor may not exist yet in the dev DB, treat a missing column as 0
    if column not in df.columns:
        return 0
    return int(to_bool(df[column]).sum())


def build_collaborator_vs_contributor(df):
    total = len(df)
    if total == 0:
        return []

    collaborators = count_flag(df, "is_collaborator")
    contributors = count_flag(df, "is_contributor")

    # Each count is compared to the total org count on its own. An org can be
    # both (or neither), so these two do not have to add up to the total.
    return [
        {
            "type": "Collaborator",
            "count": collaborators,
            "percentage": round(collaborators / total * 100, 1),
        },
        {
            "type": "Contributor",
            "count": contributors,
            "percentage": round(contributors / total * 100, 1),
        },
    ]


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context=None):
    try:
        body = parse_event_body(event)
        filters = parse_common_filters(body)
    except ValueError as error:
        return build_response(400, {"error": str(error)})

    try:
        df = apply_country_and_type(load_organizations(), filters)
    except Exception as error:
        print(f"Loading organizations failed: {error}")
        return build_response(500, {"error": "Could not load organization data."})

    size_range = filters["size_range"]
    contribution_range = filters["contribution_range"]

    # Any custom range means a Custom-only response, no fixed buckets.
    if size_range or contribution_range:
        custom = get_empty_bucket()

        if size_range:
            custom["organizations_by_size"] = build_organizations_by_size(
                filter_date_range(df, *size_range)
            )

        if contribution_range:
            custom["collaborator_vs_contributor"] = build_collaborator_vs_contributor(
                filter_date_range(df, *contribution_range)
            )

        return build_response(200, {"Custom": custom})

    now = datetime.now()
    response_body = {}

    for bucket, days in FIXED_BUCKETS.items():
        window = filter_last_days(df, days, now)
        response_body[bucket] = {
            "organizations_by_size": build_organizations_by_size(window),
            "collaborator_vs_contributor": build_collaborator_vs_contributor(window),
        }

    response_body["Custom"] = get_empty_bucket()
    return build_response(200, response_body)


if __name__ == "__main__":
    test_events = [
        {},
        {"country": "USA"},
        {"organization_type": "non_profit"},
        {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"},
        {"contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"},
        {
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-06-30",
            "contribution_start_date": "2025-01-01",
            "contribution_end_date": "2025-12-31",
        },
        # these two should come back as 400 errors
        {"size_start_date": "2026-01-01"},
        {"contribution_start_date": "2026-05-01", "contribution_end_date": "2026-01-01"},
    ]

    for test_event in test_events:
        print(f"\nEvent: {test_event}")
        result = lambda_handler({"body": json.dumps(test_event)}, None)
        print(f"Status: {result['statusCode']}")
        print(json.dumps(json.loads(result["body"]), indent=2))
