"""
Size & Contribution Analytics API for the Organization Analytics dashboard's
"Size & Contribution" tab (issue #376).

Two charts, both window-scoped snapshots (only organizations created inside
the bucket's own window count - not cumulative):

  - organizations_by_size: organization count per org_size, one row per
    org_size value actually present in the window (raw enum value as-is,
    e.g. small / medium / large). No hardcoded list and no zero-filling.
  - collaborator_vs_contributor: exactly two rows, "Collaborator" and
    "Contributor". Each is computed independently from its own flag -
    count(is_collaborator = True) and count(is_contributor = True) - and its
    percentage is that count's share of the window's total organization
    count. The flags are not mutually exclusive (an organization can be
    both, or neither), so the two rows are NOT a partition and are not
    expected to sum to the total or to 100%. If is_contributor is missing
    from the data, Contributor degrades to count 0 / percentage 0.0.

Response shape:

  - Neither Custom pair supplied -> exactly "7D", "30D", "1Y", "All",
    "Custom" (Custom has both charts empty).
  - size_start_date/size_end_date and/or
    contribution_start_date/contribution_end_date supplied -> exactly
    {"Custom": {...}}; the fixed buckets are not computed. Each pair fills
    its own chart independently, so when both are supplied both charts are
    populated, each from its own range (the reference implementation's bug
    of dropping the second pair is intentionally not replicated).

Filters (applied the same way in every response shape):
  - country: country code or name, or "ALL" (default). Resolved through
    organizations.state_id -> states.country_id -> countries.
  - organization_type: "non_profit" / "for_profit" / "ALL" (default).

Data source:
  - USE_MOCK_DATA=true: organizations.csv / states.csv / countries.csv read
    with pandas from MOCK_DATA_DIR (default: a "mock_data" folder next to
    this file). The CSVs are local-only and are not committed.
  - otherwise: PostgreSQL through psycopg2 (optional import, so this file
    still runs standalone with USE_MOCK_DATA=true when psycopg2 isn't
    installed). Connection settings come from DB_HOST / DB_PORT / DB_NAME /
    DB_USER / DB_PASSWORD, schema from DB_SCHEMA.

This is a new, standalone function - not a refactor of
organization_analytics.py. Do not deploy it directly to AWS.
"""

import json
import os
from datetime import datetime

import pandas as pd

try:
    import psycopg2
except ImportError:  # Mock-data runs must work without psycopg2 installed.
    psycopg2 = None


REQUIRED_ORG_COLUMNS = ["org_id", "org_size", "is_collaborator", "org_type", "state_id", "created_at"]
OPTIONAL_ORG_COLUMNS = ["is_contributor"]
REQUIRED_STATE_COLUMNS = ["state_id", "country_id"]
REQUIRED_COUNTRY_COLUMNS = ["country_id", "country_code"]

FIXED_BUCKETS = ["7D", "30D", "1Y", "All"]
CHART_KEYS = ("organizations_by_size", "collaborator_vs_contributor")

ORG_TYPES = ["non_profit", "for_profit"]
_ORG_TYPE_ALIASES = {
    "non_profit": "non_profit",
    "nonprofit": "non_profit",
    "for_profit": "for_profit",
    "forprofit": "for_profit",
}

# Display order only - any org_size value present in the data is emitted;
# values not listed here follow, alphabetically.
SIZE_DISPLAY_ORDER = {"small": 0, "medium": 1, "large": 2}

_TRUE_VALUES = {"true", "t", "1", "yes", "y"}

DATE_FORMAT = "%Y-%m-%d"
SIZE_DATE_FIELDS = ("size_start_date", "size_end_date")
CONTRIBUTION_DATE_FIELDS = ("contribution_start_date", "contribution_end_date")
ALL_VALUE = "ALL"

# Real-DB path. Table names follow the existing queries in this repo
# (data-engineering/src/main.py joins "country" and "state"); confirm against
# the live schema before wiring this Lambda up.
DB_SCHEMA = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")
ORGANIZATIONS_TABLE = "organizations"
STATES_TABLE = "state"
COUNTRIES_TABLE = "country"


class RequestValidationError(ValueError):
    """Malformed or incomplete request input - returned to the caller as a 400."""


# ---------------------------------------------------------------------------
# Request parsing / validation
# ---------------------------------------------------------------------------

def parse_event_body(event):
    """
    Returns the request payload as a dict. Accepts a raw dict (direct / local
    invocation) or an API-Gateway-style event whose "body" is a JSON string
    or a dict. An unparseable or non-object body is rejected rather than
    silently treated as empty.
    """
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise RequestValidationError("Request must be a JSON object")

    if "body" not in event:
        return event

    body = event["body"]
    if body is None:
        return {}
    if isinstance(body, str):
        if not body.strip():
            return {}
        try:
            body = json.loads(body)
        except json.JSONDecodeError as error:
            raise RequestValidationError("Request body must be valid JSON") from error
    if not isinstance(body, dict):
        raise RequestValidationError("Request body must be a JSON object")
    return body


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def parse_date_range(payload, start_field, end_field):
    """
    Validates one Custom date pair. Returns None when neither value is
    supplied, otherwise (start, end_exclusive) as Timestamps covering the
    inclusive calendar days start..end.

    Raises RequestValidationError when only half of the pair is supplied, a
    value isn't a real YYYY-MM-DD date, or start is after end.
    """
    start_value = payload.get(start_field)
    end_value = payload.get(end_field)

    if _is_blank(start_value) and _is_blank(end_value):
        return None
    if _is_blank(start_value) or _is_blank(end_value):
        raise RequestValidationError(f"Both {start_field} and {end_field} are required together")

    parsed = []
    for field, value in ((start_field, start_value), (end_field, end_value)):
        if not isinstance(value, str):
            raise RequestValidationError(f"{field} must be a date string in YYYY-MM-DD format")
        try:
            parsed.append(datetime.strptime(value.strip(), DATE_FORMAT))
        except ValueError as error:
            raise RequestValidationError(
                f"{field} must be a valid date in YYYY-MM-DD format, got {value!r}"
            ) from error

    start, end = parsed
    if start > end:
        raise RequestValidationError(f"{start_field} must not be after {end_field}")

    return pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)


def parse_country(payload):
    """Returns the country filter string, or None for ALL (the default)."""
    country = payload.get("country")
    if country is None:
        return None
    if not isinstance(country, str) or not country.strip():
        raise RequestValidationError("country must be a non-empty string (country code, country name, or ALL)")
    country = country.strip()
    if country.upper() == ALL_VALUE:
        return None
    return country


def _normalize_org_type(value):
    if _is_blank(value) or (not isinstance(value, str) and pd.isna(value)):
        return None
    key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return _ORG_TYPE_ALIASES.get(key)


def parse_organization_type(payload):
    """Returns "non_profit" / "for_profit", or None for ALL (the default)."""
    value = payload.get("organization_type")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RequestValidationError("organization_type must be one of: non_profit, for_profit, ALL")
    if value.strip().upper() == ALL_VALUE:
        return None
    org_type = _normalize_org_type(value)
    if org_type is None:
        raise RequestValidationError(
            f"organization_type must be one of: non_profit, for_profit, ALL - got {value!r}"
        )
    return org_type


def parse_request(payload):
    """
    Validates every filter up front, so a bad value in either date pair (or
    in country / organization_type) fails the whole request - never a
    partial result.
    """
    return {
        "country": parse_country(payload),
        "organization_type": parse_organization_type(payload),
        "size_range": parse_date_range(payload, *SIZE_DATE_FIELDS),
        "contribution_range": parse_date_range(payload, *CONTRIBUTION_DATE_FIELDS),
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _use_mock_data():
    return os.environ.get("USE_MOCK_DATA", "false").strip().lower() in {"true", "1", "yes"}


def _mock_data_dir():
    return os.environ.get(
        "MOCK_DATA_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data"),
    )


def _check_columns(df, required_columns, source):
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(f"{source} is missing required column(s): {', '.join(missing)}")


def _read_csv(path, empty_columns):
    """Reads a CSV as strings; a completely empty file becomes an empty table."""
    try:
        return pd.read_csv(path, dtype=str)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=empty_columns, dtype=str)


def load_mock_tables(data_dir=None):
    """Reads organizations.csv / states.csv / countries.csv from data_dir."""
    data_dir = data_dir or _mock_data_dir()
    organizations = _read_csv(
        os.path.join(data_dir, "organizations.csv"), REQUIRED_ORG_COLUMNS + OPTIONAL_ORG_COLUMNS
    )
    states = _read_csv(os.path.join(data_dir, "states.csv"), REQUIRED_STATE_COLUMNS)
    countries = _read_csv(os.path.join(data_dir, "countries.csv"), REQUIRED_COUNTRY_COLUMNS)
    return organizations, states, countries


def _query_to_dataframe(connection, query):
    with connection.cursor() as cursor:
        cursor.execute(query)
        columns = [description[0] for description in cursor.description]
        return pd.DataFrame(cursor.fetchall(), columns=columns, dtype=object)


def load_postgres_tables():
    """Reads the same three tables from PostgreSQL."""
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; set USE_MOCK_DATA=true to use the local CSVs")

    connection = psycopg2.connect(
        host=os.environ.get("DB_HOST"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        sslmode=os.environ.get("DB_SSLMODE", "require"),
    )
    try:
        organizations = _query_to_dataframe(
            connection,
            f"SELECT org_id, org_size, is_collaborator, is_contributor, org_type, state_id, created_at "
            f"FROM {DB_SCHEMA}.{ORGANIZATIONS_TABLE}",
        )
        states = _query_to_dataframe(
            connection, f"SELECT state_id, country_id FROM {DB_SCHEMA}.{STATES_TABLE}"
        )
        countries = _query_to_dataframe(
            connection,
            f"SELECT country_id, country_code, country_name FROM {DB_SCHEMA}.{COUNTRIES_TABLE}",
        )
    finally:
        connection.close()
    return organizations, states, countries


def _parse_flag(value):
    """True for TRUE/true/t/1/yes (bool True from Postgres too); everything else False."""
    if isinstance(value, bool):
        return value
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return False
    return str(value).strip().lower() in _TRUE_VALUES


def _normalize_size(value):
    """Raw org_size value as-is (surrounding whitespace stripped); None when blank."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    value = str(value).strip()
    return value or None


def _parse_created_at(series):
    """Parses created_at (date-only or datetime, naive or tz-aware) to naive UTC."""
    try:
        parsed = pd.to_datetime(series, errors="coerce", utc=True, format="ISO8601")
    except (TypeError, ValueError):  # older pandas without format="ISO8601"
        parsed = pd.to_datetime(series, errors="coerce", utc=True)
    return parsed.dt.tz_convert(None)


def prepare_organizations(organizations, states, countries):
    """
    Validates the three tables and returns (organizations, countries) where
    organizations has:
      - org_size: raw value, or None when blank (such orgs still count toward
        the window total and collaborator_vs_contributor, but have no size
        row to land in).
      - is_collaborator / is_contributor: bool. A missing is_contributor
        column means every organization is treated as not a contributor.
      - org_type: "non_profit" / "for_profit", or None when missing/
        unrecognized (counted under organization_type=ALL only).
      - created_at: naive Timestamp. Rows whose created_at can't be parsed
        are dropped - they can't be placed in any window.
      - country_code / country_name resolved through state_id -> states.
        country_id -> countries. Orgs with no matching state/country keep
        country_code "Unknown" so they still count under country=ALL.
    """
    _check_columns(organizations, REQUIRED_ORG_COLUMNS, "organizations")
    _check_columns(states, REQUIRED_STATE_COLUMNS, "states")
    _check_columns(countries, REQUIRED_COUNTRY_COLUMNS, "countries")

    country_columns = ["country_id", "country_code"]
    if "country_name" in countries.columns:
        country_columns.append("country_name")

    states = states[REQUIRED_STATE_COLUMNS].astype(str).drop_duplicates(subset="state_id")
    countries = countries[country_columns].astype(str).drop_duplicates(subset="country_id")

    has_contributor = "is_contributor" in organizations.columns
    if not has_contributor:
        print("organizations data has no is_contributor column - Contributor counts default to 0")

    orgs = organizations[REQUIRED_ORG_COLUMNS + (["is_contributor"] if has_contributor else [])].copy()
    if not has_contributor:
        orgs["is_contributor"] = False

    orgs["state_id"] = orgs["state_id"].astype(str)
    orgs = orgs.merge(states, on="state_id", how="left").merge(countries, on="country_id", how="left")
    orgs["country_code"] = orgs["country_code"].fillna("Unknown")
    if "country_name" not in orgs.columns:
        orgs["country_name"] = None

    orgs["org_size"] = orgs["org_size"].map(_normalize_size).astype(object)
    orgs["org_type"] = orgs["org_type"].map(_normalize_org_type).astype(object)
    orgs["is_collaborator"] = orgs["is_collaborator"].map(_parse_flag).astype(bool)
    orgs["is_contributor"] = orgs["is_contributor"].map(_parse_flag).astype(bool)

    created_at = _parse_created_at(orgs["created_at"])
    for org_id in orgs.loc[created_at.isna(), "org_id"]:
        print(f"Skipping organization {org_id}: unparseable created_at")
    orgs = orgs.loc[created_at.notna()].copy()
    orgs["created_at"] = created_at.loc[created_at.notna()]

    for org_id in orgs.loc[orgs["org_size"].isna(), "org_id"]:
        print(f"Organization {org_id}: missing org_size - excluded from organizations_by_size")

    return orgs.reset_index(drop=True), countries.reset_index(drop=True)


def load_data():
    if _use_mock_data():
        tables = load_mock_tables()
    else:
        tables = load_postgres_tables()
    return prepare_organizations(*tables)


# ---------------------------------------------------------------------------
# Filters and windows
# ---------------------------------------------------------------------------

def _normalize_country(value):
    """Case-insensitive; spaces, hyphens and underscores are treated alike."""
    return str(value).strip().casefold().replace("-", "_").replace(" ", "_")


def apply_country_filter(organizations, countries, country):
    """
    Keeps only organizations in the requested country, matched on
    country_code or country_name (case-insensitive). None means ALL. A
    country that doesn't exist in the countries table is a 400, not a
    silently empty result.
    """
    if country is None:
        return organizations

    wanted = _normalize_country(country)
    known = set(countries["country_code"].map(_normalize_country))
    if "country_name" in countries.columns:
        known |= set(countries["country_name"].dropna().map(_normalize_country))
    if wanted not in known:
        raise RequestValidationError(f"Unknown country: {country!r}")

    match = organizations["country_code"].map(_normalize_country).eq(wanted)
    match |= organizations["country_name"].fillna("").map(_normalize_country).eq(wanted)
    return organizations.loc[match]


def apply_organization_type_filter(organizations, org_type):
    """Keeps only organizations of org_type. None means ALL."""
    if org_type is None:
        return organizations
    return organizations.loc[organizations["org_type"] == org_type]


def fixed_window(bucket, reference_date):
    """
    (start, end_exclusive) for a fixed bucket, ending with the whole of
    reference_date's day. 7D / 30D cover exactly 7 / 30 calendar days
    including today; 1Y covers exactly one year including today. All = no
    bounds.
    """
    today = pd.Timestamp(reference_date).normalize()
    end_exclusive = today + pd.Timedelta(days=1)
    if bucket == "7D":
        return today - pd.Timedelta(days=6), end_exclusive
    if bucket == "30D":
        return today - pd.Timedelta(days=29), end_exclusive
    if bucket == "1Y":
        return today - pd.DateOffset(years=1) + pd.Timedelta(days=1), end_exclusive
    return None, None


def _in_window(organizations, start, end_exclusive):
    mask = pd.Series(True, index=organizations.index)
    if start is not None:
        mask &= organizations["created_at"] >= start
    if end_exclusive is not None:
        mask &= organizations["created_at"] < end_exclusive
    return organizations.loc[mask]


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def empty_bucket():
    return {"organizations_by_size": [], "collaborator_vs_contributor": []}


def _size_sort_key(size):
    return (SIZE_DISPLAY_ORDER.get(str(size).lower(), len(SIZE_DISPLAY_ORDER)), str(size))


def build_organizations_by_size(organizations, start, end_exclusive):
    """
    Window-scoped organization count per org_size. Only sizes present in the
    window are returned (no zero-fill); small / medium / large first, any
    other value after them alphabetically.
    """
    sizes = _in_window(organizations, start, end_exclusive)["org_size"].dropna()
    if sizes.empty:
        return []
    counts = sizes.value_counts()
    return [
        {"size": size, "count": int(counts[size])}
        for size in sorted(counts.index, key=_size_sort_key)
    ]


def _percentage(count, total):
    return round(count * 100.0 / total, 1) if total else 0.0


def build_collaborator_vs_contributor(organizations, start, end_exclusive):
    """
    Two rows - Collaborator and Contributor - each counted independently
    from its own flag against the window's total organization count. Not a
    partition: the counts may overlap and need not sum to the total. An
    empty window returns [].
    """
    windowed = _in_window(organizations, start, end_exclusive)
    total = len(windowed)
    if total == 0:
        return []

    collaborators = int(windowed["is_collaborator"].sum())
    contributors = int(windowed["is_contributor"].sum())
    return [
        {"type": "Collaborator", "count": collaborators, "percentage": _percentage(collaborators, total)},
        {"type": "Contributor", "count": contributors, "percentage": _percentage(contributors, total)},
    ]


# ---------------------------------------------------------------------------
# Response assembly
# ---------------------------------------------------------------------------

def build_size_contribution_response(organizations, request, reference_date=None):
    """
    organizations must already be country / organization_type filtered.
    request is the output of parse_request.
    """
    size_range = request["size_range"]
    contribution_range = request["contribution_range"]

    if size_range is not None or contribution_range is not None:
        # Custom-only response. Both pairs are evaluated independently - no
        # priority, neither is dropped.
        custom = empty_bucket()
        if size_range is not None:
            custom["organizations_by_size"] = build_organizations_by_size(organizations, *size_range)
        if contribution_range is not None:
            custom["collaborator_vs_contributor"] = build_collaborator_vs_contributor(
                organizations, *contribution_range
            )
        return {"Custom": custom}

    reference_date = reference_date if reference_date is not None else pd.Timestamp.now()
    response = {}
    for bucket in FIXED_BUCKETS:
        start, end_exclusive = fixed_window(bucket, reference_date)
        response[bucket] = {
            "organizations_by_size": build_organizations_by_size(organizations, start, end_exclusive),
            "collaborator_vs_contributor": build_collaborator_vs_contributor(organizations, start, end_exclusive),
        }
    response["Custom"] = empty_bucket()
    return response


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def lambda_handler(event, context, reference_date=None):
    try:
        request = parse_request(parse_event_body(event))
    except RequestValidationError as error:
        return build_response(400, {"error": str(error)})

    try:
        organizations, countries = load_data()
    except Exception as error:  # noqa: BLE001 - any data-source failure is a 500
        print(f"Failed to load organization data: {error}")
        return build_response(500, {"error": "Failed to load organization data"})

    try:
        organizations = apply_country_filter(organizations, countries, request["country"])
    except RequestValidationError as error:
        return build_response(400, {"error": str(error)})
    organizations = apply_organization_type_filter(organizations, request["organization_type"])

    return build_response(
        200, build_size_contribution_response(organizations, request, reference_date)
    )


# ---------------------------------------------------------------------------
# Local run
# ---------------------------------------------------------------------------

def _sanity_check(name, event, result, reference_date=None):
    """Prints PASS/FAIL for the issue's local sanity checks on one response."""
    problems = []
    body = json.loads(result["body"])
    payload = parse_event_body(event)
    size_given = any(not _is_blank(payload.get(field)) for field in SIZE_DATE_FIELDS)
    contribution_given = any(not _is_blank(payload.get(field)) for field in CONTRIBUTION_DATE_FIELDS)

    if result["statusCode"] != 200:
        problems.append(f"status {result['statusCode']}")
        print(f"Sanity check [{name}]: FAIL - {'; '.join(problems)}")
        return

    expected_keys = {"Custom"} if (size_given or contribution_given) else set(FIXED_BUCKETS) | {"Custom"}
    if set(body) != expected_keys:
        problems.append(f"top-level keys {sorted(body)}")

    # Recompute each window's total independently to check the counts.
    request = parse_request(payload)
    organizations, countries = load_data()
    organizations = apply_country_filter(organizations, countries, request["country"])
    organizations = apply_organization_type_filter(organizations, request["organization_type"])
    reference = reference_date if reference_date is not None else pd.Timestamp.now()

    for bucket, charts in body.items():
        if set(charts) != set(CHART_KEYS):
            problems.append(f"{bucket} keys {sorted(charts)}")
            continue

        if bucket == "Custom":
            size_window = request["size_range"]
            contribution_window = request["contribution_range"]
            if size_window is None and charts["organizations_by_size"]:
                problems.append("Custom size chart populated without a size range")
            if contribution_window is None and charts["collaborator_vs_contributor"]:
                problems.append("Custom contribution chart populated without a contribution range")
        else:
            size_window = contribution_window = fixed_window(bucket, reference)

        if size_window is not None:
            windowed = _in_window(organizations, *size_window)
            size_total = int(windowed["org_size"].notna().sum())
            if sum(row["count"] for row in charts["organizations_by_size"]) != size_total:
                problems.append(f"{bucket} size counts don't sum to {size_total}")

        if contribution_window is not None:
            total = len(_in_window(organizations, *contribution_window))
            rows = charts["collaborator_vs_contributor"]
            if total == 0:
                if rows:
                    problems.append(f"{bucket} empty window should give []")
            else:
                if [row["type"] for row in rows] != ["Collaborator", "Contributor"]:
                    problems.append(f"{bucket} collab/contrib rows {rows}")
                if any(row["count"] > total for row in rows):
                    problems.append(f"{bucket} collab/contrib count above total {total}")

    print(f"Sanity check [{name}]: {'PASS' if not problems else 'FAIL - ' + '; '.join(problems)}")


if __name__ == "__main__":
    # Local run only: reads the CSVs in MOCK_DATA_DIR (default: ./mock_data
    # next to this file). Never deploy directly to AWS.
    os.environ.setdefault("USE_MOCK_DATA", "true")

    sample_events = [
        ("No body", {}),
        ("Country filter (USA)", {"country": "USA"}),
        ("Organization type filter (non_profit)", {"organization_type": "non_profit"}),
        ("Organization type filter (for_profit)", {"organization_type": "for_profit"}),
        ("Size Custom range only", {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"}),
        ("Contribution Custom range only", {
            "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31",
        }),
        ("Both Custom ranges together", {
            "size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
            "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31",
        }),
        ("Both Custom ranges + country + organization_type", {
            "country": "USA",
            "organization_type": "non_profit",
            "size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
            "contribution_start_date": "2025-01-01", "contribution_end_date": "2026-12-31",
        }),
        ("Custom ranges with no organizations", {
            "size_start_date": "2000-01-01", "size_end_date": "2000-01-31",
            "contribution_start_date": "2000-01-01", "contribution_end_date": "2000-01-31",
        }),
        ("API Gateway-style event (JSON string body)", {"body": json.dumps({"country": "ind"})}),
    ]
    error_events = [
        ("Missing half of size pair", {"size_start_date": "2026-01-01"}),
        ("Missing half of contribution pair", {"contribution_end_date": "2025-12-31"}),
        ("Bad size date format", {"size_start_date": "2026/01/01", "size_end_date": "2026-06-30"}),
        ("Impossible calendar date", {"contribution_start_date": "2025-02-30", "contribution_end_date": "2025-03-01"}),
        ("Size start after end", {"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"}),
        ("Contribution start after end (size pair valid)", {
            "size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
            "contribution_start_date": "2025-12-31", "contribution_end_date": "2025-01-01",
        }),
        ("Invalid organization_type", {"organization_type": "government"}),
        ("Unknown country", {"country": "Atlantis"}),
    ]

    for name, event in sample_events:
        print(f"\n===== {name} =====")
        print(f"Event: {json.dumps(event)}")
        result = lambda_handler(event, None)
        print(f"Status: {result['statusCode']}")
        print(json.dumps(json.loads(result["body"]), indent=2))
        _sanity_check(name, event, result)

    for name, event in error_events:
        print(f"\n===== {name} (expect 400) =====")
        print(f"Event: {json.dumps(event)}")
        result = lambda_handler(event, None)
        print(f"Status: {result['statusCode']}")
        print(json.dumps(json.loads(result["body"]), indent=2))
        print(f"Sanity check [{name}]: {'PASS' if result['statusCode'] == 400 else 'FAIL'}")
