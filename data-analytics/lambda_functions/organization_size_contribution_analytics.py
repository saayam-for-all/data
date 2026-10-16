

import json
import os
from datetime import date, datetime, time, timedelta

import pandas as pd

try:
    import psycopg2
except ImportError:  # the mock-data path must run without psycopg2 installed
    psycopg2 = None


USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "false").strip().lower() == "true"
MOCK_DATA_DIR = os.environ.get("MOCK_DATA_DIR", os.path.join(os.path.dirname(__file__), "mock_data"))
DB_SCHEMA = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")

FIXED_BUCKETS = {
    "7D": timedelta(days=7),
    "30D": timedelta(days=30),
    "1Y": timedelta(days=365),
    "All": None,
}

VALID_ORG_TYPES = {"non_profit", "for_profit"}
DATE_FORMAT = "%Y-%m-%d"

REQUIRED_COLUMNS = ["org_id", "org_size", "is_collaborator", "created_at"]


class ValidationError(Exception):
    """Raised for malformed or incomplete request input — returned as HTTP 400."""


# Request parsing and validation

def _parse_event(event):
    """
    Accept either a direct invocation payload or an API Gateway event whose
    filters arrive as a JSON string in "body".
    """
    if not event:
        return {}
    if not isinstance(event, dict):
        raise ValidationError("Request must be a JSON object")

    body = event.get("body", event)
    if body is None:
        return {}
    if isinstance(body, str):
        if not body.strip():
            return {}
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValidationError("Request body is not valid JSON")
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object")
    return body


def _parse_date(value, field):
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a date string in YYYY-MM-DD format")
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT).date()
    except ValueError:
        raise ValidationError(f"{field} must be a valid date in YYYY-MM-DD format, got '{value}'")


def _parse_date_pair(filters, start_key, end_key):
    """
    Return (start, end) as datetimes covering whole days, or None when neither
    half of the pair was sent. Sending only one half is an error.
    """
    start_raw = filters.get(start_key)
    end_raw = filters.get(end_key)

    has_start = start_raw not in (None, "")
    has_end = end_raw not in (None, "")

    if not has_start and not has_end:
        return None
    if has_start != has_end:
        missing = end_key if has_start else start_key
        raise ValidationError(f"{start_key} and {end_key} must be provided together; {missing} is missing")

    start = _parse_date(start_raw, start_key)
    end = _parse_date(end_raw, end_key)
    if start > end:
        raise ValidationError(f"{start_key} ({start}) must be on or before {end_key} ({end})")

    return datetime.combine(start, time.min), datetime.combine(end, time.max)


def parse_filters(event):
    """Validate the request and return a normalized filter dict."""
    filters = _parse_event(event)

    country = filters.get("country", "ALL")
    if country in (None, ""):
        country = "ALL"
    if not isinstance(country, str):
        raise ValidationError("country must be a string (country name, country code, or ALL)")
    country = country.strip()

    org_type = filters.get("organization_type", "ALL")
    if org_type in (None, ""):
        org_type = "ALL"
    if not isinstance(org_type, str):
        raise ValidationError("organization_type must be one of non_profit, for_profit, ALL")
    org_type = org_type.strip()
    if org_type.upper() == "ALL":
        org_type = "ALL"
    elif org_type.lower() in VALID_ORG_TYPES:
        org_type = org_type.lower()
    else:
        raise ValidationError(f"organization_type must be one of non_profit, for_profit, ALL, got '{org_type}'")

    return {
        "country": country,
        "organization_type": org_type,
        "size_range": _parse_date_pair(filters, "size_start_date", "size_end_date"),
        "contribution_range": _parse_date_pair(filters, "contribution_start_date", "contribution_end_date"),
    }


# Data loading

def _to_bool(value):
    """Normalize the many ways a boolean arrives from CSV or the DB driver."""
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().lower() in ("true", "t", "1", "yes", "y")


def _normalize(df):
    """Coerce column types so both data paths hand identical frames onward."""
    if df.empty:
        cols = REQUIRED_COLUMNS + ["is_contributor"]
        return pd.DataFrame(columns=cols).astype({"created_at": "datetime64[ns]"})

    df = df.copy()
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df = df.dropna(subset=["created_at"])
    df["is_collaborator"] = df["is_collaborator"].map(_to_bool)
    if "is_contributor" in df.columns:
        df["is_contributor"] = df["is_contributor"].map(_to_bool)
    return df


def load_mock_organizations(country, org_type, data_dir=None):
    """Read the three CSVs with pandas and apply the country/type filters."""
    data_dir = data_dir or MOCK_DATA_DIR
    orgs = pd.read_csv(os.path.join(data_dir, "organizations.csv"), dtype={"state_id": str})

    missing = [c for c in REQUIRED_COLUMNS if c not in orgs.columns]
    if missing:
        raise RuntimeError(f"organizations.csv is missing required columns: {', '.join(missing)}")

    if org_type != "ALL":
        if "org_type" not in orgs.columns:
            raise RuntimeError("organizations.csv has no org_type column to filter on")
        orgs = orgs[orgs["org_type"].astype(str).str.lower() == org_type]

    if country.upper() != "ALL":
        states = pd.read_csv(os.path.join(data_dir, "states.csv"), dtype={"state_id": str})
        countries = pd.read_csv(os.path.join(data_dir, "countries.csv"))

        wanted = country.upper()
        match = countries[
            (countries["country_code"].astype(str).str.upper() == wanted)
            | (countries["country_name"].astype(str).str.upper() == wanted)
        ]
        state_ids = states.loc[states["country_id"].isin(match["country_id"]), "state_id"]
        orgs = orgs[orgs["state_id"].isin(state_ids)]

    return _normalize(orgs)


def _get_db_connection():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; set USE_MOCK_DATA=true to run against local CSVs")
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=10,
    )


def load_db_organizations(country, org_type):
    """
    Read organizations from PostgreSQL with the country/type filters applied
    in SQL. All user input is passed as bound parameters.
    """
    conditions = []
    params = []

    if org_type != "ALL":
        conditions.append("o.org_type::text = %s")
        params.append(org_type)

    if country.upper() != "ALL":
        conditions.append("(UPPER(c.country_code) = UPPER(%s) OR UPPER(c.country_name) = UPPER(%s))")
        params.extend([country, country])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"""
        SELECT o.org_id,
               o.org_size::text AS org_size,
               o.is_collaborator,
               o.is_contributor,
               o.created_at
        FROM {DB_SCHEMA}.organizations o
        LEFT JOIN {DB_SCHEMA}.states s    ON s.state_id = o.state_id
        LEFT JOIN {DB_SCHEMA}.countries c ON c.country_id = s.country_id
        {where}
    """

    conn = _get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
    finally:
        conn.close()

    return _normalize(pd.DataFrame(rows, columns=columns))


def load_organizations(country, org_type):
    if USE_MOCK_DATA:
        return load_mock_organizations(country, org_type)
    return load_db_organizations(country, org_type)


# Aggregation

def _now():
    """Kept as a function so tests can pin the reference time."""
    return datetime.now()


def _in_window(df, start, end):
    mask = df["created_at"] <= end
    if start is not None:
        mask &= df["created_at"] >= start
    return df[mask]


def organizations_by_size(df):
    """
    One row per org_size value present in the window, most common first.
    The size list is read from the data rather than hardcoded.
    """
    sizes = df["org_size"].dropna().astype(str)
    sizes = sizes[sizes.str.strip() != ""]
    if sizes.empty:
        return []

    counts = sizes.value_counts()
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"size": size, "count": int(count)} for size, count in ordered]


def _pct(part, total):
    return round(part / total * 100, 1) if total else 0.0


def collaborator_vs_contributor(df):
    """
    Two independent counts over the same window. An organization can be a
    collaborator, a contributor, both, or neither, so the rows are not a
    partition and need not sum to the total or to 100%.
    """
    total = len(df)
    if total == 0:
        return []

    collaborators = int(df["is_collaborator"].sum())
    contributors = int(df["is_contributor"].sum()) if "is_contributor" in df.columns else 0

    return [
        {"type": "Collaborator", "count": collaborators, "percentage": _pct(collaborators, total)},
        {"type": "Contributor", "count": contributors, "percentage": _pct(contributors, total)},
    ]


def build_fixed_buckets(df, now):
    result = {}
    for label, span in FIXED_BUCKETS.items():
        start = now - span if span is not None else None
        window = _in_window(df, start, now)
        result[label] = {
            "organizations_by_size": organizations_by_size(window),
            "collaborator_vs_contributor": collaborator_vs_contributor(window),
        }
    result["Custom"] = {"organizations_by_size": [], "collaborator_vs_contributor": []}
    return result


def build_custom(df, size_range, contribution_range):
    """
    Each range drives only its own chart. Both may be present at once and
    both are evaluated — neither takes priority over the other.
    """
    custom = {"organizations_by_size": [], "collaborator_vs_contributor": []}
    if size_range is not None:
        custom["organizations_by_size"] = organizations_by_size(_in_window(df, *size_range))
    if contribution_range is not None:
        custom["collaborator_vs_contributor"] = collaborator_vs_contributor(
            _in_window(df, *contribution_range)
        )
    return {"Custom": custom}


# Handler

def _response(status, payload):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(payload),
    }


def get_size_contribution_analytics(filters, df):
    if filters["size_range"] is None and filters["contribution_range"] is None:
        return build_fixed_buckets(df, _now())
    return build_custom(df, filters["size_range"], filters["contribution_range"])


def lambda_handler(event, context=None):
    try:
        filters = parse_filters(event)
    except ValidationError as exc:
        return _response(400, {"error": str(exc)})

    try:
        df = load_organizations(filters["country"], filters["organization_type"])
        return _response(200, get_size_contribution_analytics(filters, df))
    except Exception as exc:  # database/file failures must not leak a stack trace
        print(f"size_contribution_analytics failed: {exc!r}")
        return _response(500, {"error": "Failed to compute size and contribution analytics"})


# Local run

if __name__ == "__main__":
    os.environ["USE_MOCK_DATA"] = "true"
    USE_MOCK_DATA = True

    sample_events = [
        ("No body", {}),
        ("Country filter (USA)", {"country": "USA"}),
        ("Country filter by name (India)", {"country": "India"}),
        ("Org-type filter (non_profit)", {"organization_type": "non_profit"}),
        ("Size Custom range only",
         {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"}),
        ("Contribution Custom range only",
         {"contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"}),
        ("Both Custom ranges together",
         {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
          "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"}),
        ("Both Custom ranges + country + type",
         {"country": "USA", "organization_type": "for_profit",
          "size_start_date": "2025-01-01", "size_end_date": "2025-12-31",
          "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"}),
        ("API Gateway style body string", {"body": json.dumps({"country": "IND"})}),
        ("Error: only half of size pair", {"size_start_date": "2026-01-01"}),
        ("Error: bad date format", {"contribution_start_date": "2025/01/01",
                                    "contribution_end_date": "2025-12-31"}),
        ("Error: start after end", {"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"}),
        ("Error: invalid organization_type", {"organization_type": "government"}),
    ]

    print(f"MOCK_DATA_DIR = {MOCK_DATA_DIR}")
    print(f"Reference time (now) = {_now():%Y-%m-%d %H:%M:%S}\n")

    for label, event in sample_events:
        response = lambda_handler(event)
        body = json.loads(response["body"])
        print("=" * 72)
        print(f"{label}")
        print(f"event:  {json.dumps(event)}")
        print(f"status: {response['statusCode']}   top-level keys: {list(body.keys())}")
        print(json.dumps(body, indent=2))