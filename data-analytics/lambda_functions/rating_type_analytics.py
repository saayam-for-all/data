"""
Rating & Type Analytics API for the Organization Analytics dashboard's
"Rating & Type" tab (issue #380).

Two charts:

  - rating_distribution: organization counts grouped by org_rating (the
    literal integer 1-5 stored on the organization), window-scoped. One row
    per rating actually present in the window - no zero-filling.
  - organization_mix_trend: Profit vs Non-Profit stacked bar. Two series,
    non_profit and for_profit, each a list of {"period", "count"} where
    count is the absolute, all-time running total of that type as of the
    end of the period. Only periods in which at least one organization of
    that type was created (inside the window) are listed - sparse, not
    zero-filled.

Response shape:

  - Neither Custom pair supplied -> exactly "7D", "30D", "1Y", "All",
    "Custom" (Custom has both charts empty).
  - rating_start_date/rating_end_date and/or type_start_date/type_end_date
    supplied -> exactly {"Custom": {...}}. Each pair independently fills
    its own chart; the other chart stays empty.

Filters: country (country code or name, or "ALL" - the default) applies to
both charts via organizations.state_id -> states.country_id ->
countries.country_code. There is no organization_type or time_filter field.

Data source:
  - USE_MOCK_DATA=true: organizations.csv / states.csv / countries.csv read
    with pandas from MOCK_DATA_DIR (default: a "mock_data" folder next to
    this file). The CSVs are local-only and are not committed.
  - otherwise: PostgreSQL through psycopg2 (optional import, so this file
    still runs standalone with USE_MOCK_DATA=true when psycopg2 isn't
    installed). Connection settings come from DB_HOST / DB_PORT / DB_NAME /
    DB_USER / DB_PASSWORD, schema from DB_SCHEMA.

This is a new, standalone function. Do not deploy it directly to AWS.
"""

import json
import os
from datetime import datetime

import pandas as pd

try:
    import psycopg2
except ImportError:  # Mock-data runs must work without psycopg2 installed.
    psycopg2 = None


REQUIRED_ORG_COLUMNS = ["org_id", "org_rating", "org_type", "state_id", "created_at"]
REQUIRED_STATE_COLUMNS = ["state_id", "country_id"]
REQUIRED_COUNTRY_COLUMNS = ["country_id", "country_code"]

FIXED_BUCKETS = ["7D", "30D", "1Y", "All"]

# 7D / 30D / Custom group by day (YYYY-MM-DD); 1Y / All group by month (YYYY-MM).
BUCKET_GRANULARITY = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
    "Custom": "day",
}

ORG_TYPES = ["non_profit", "for_profit"]
_ORG_TYPE_ALIASES = {
    "non_profit": "non_profit",
    "nonprofit": "non_profit",
    "for_profit": "for_profit",
    "forprofit": "for_profit",
}

VALID_RATINGS = {1, 2, 3, 4, 5}

DATE_FORMAT = "%Y-%m-%d"
RATING_DATE_FIELDS = ("rating_start_date", "rating_end_date")
TYPE_DATE_FIELDS = ("type_start_date", "type_end_date")
ALL_COUNTRIES = "ALL"

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
    if country.upper() == ALL_COUNTRIES:
        return None
    return country


def parse_request(payload):
    """
    Validates every filter up front, so a bad value in either date pair (or
    the country field) fails the whole request - never a partial result.
    """
    return {
        "country": parse_country(payload),
        "rating_range": parse_date_range(payload, *RATING_DATE_FIELDS),
        "type_range": parse_date_range(payload, *TYPE_DATE_FIELDS),
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


def load_mock_tables(data_dir=None):
    """Reads organizations.csv / states.csv / countries.csv from data_dir."""
    data_dir = data_dir or _mock_data_dir()
    organizations = pd.read_csv(os.path.join(data_dir, "organizations.csv"), dtype=str)
    states = pd.read_csv(os.path.join(data_dir, "states.csv"), dtype=str)
    countries = pd.read_csv(os.path.join(data_dir, "countries.csv"), dtype=str)
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
            f"SELECT org_id, org_rating, org_type, state_id, created_at "
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


def _normalize_org_type(value):
    if _is_blank(value) or (not isinstance(value, str) and pd.isna(value)):
        return None
    key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return _ORG_TYPE_ALIASES.get(key)


def _parse_rating(value):
    """org_rating is a literal integer 1-5 - no rounding of fractional values."""
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number) or float(number) != int(number) or int(number) not in VALID_RATINGS:
        return None
    return int(number)


def _parse_created_at(series):
    """Parses created_at (date-only or datetime, naive or tz-aware) to naive UTC."""
    try:
        parsed = pd.to_datetime(series, errors="coerce", utc=True, format="ISO8601")
    except (TypeError, ValueError):  # older pandas without format="ISO8601"
        parsed = pd.to_datetime(series, errors="coerce", utc=True)
    return parsed.dt.tz_convert(None)


def prepare_organizations(organizations, states, countries):
    """
    Validates the three tables and returns one organizations DataFrame with:
      - org_rating: int 1-5, or None when missing/invalid (excluded from
        rating_distribution only).
      - org_type: "non_profit" / "for_profit", or None when missing/
        unrecognized (excluded from organization_mix_trend only).
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

    orgs = organizations[REQUIRED_ORG_COLUMNS].copy()
    orgs["state_id"] = orgs["state_id"].astype(str)
    orgs = orgs.merge(states, on="state_id", how="left").merge(countries, on="country_id", how="left")
    orgs["country_code"] = orgs["country_code"].fillna("Unknown")
    if "country_name" not in orgs.columns:
        orgs["country_name"] = None

    orgs["org_rating"] = orgs["org_rating"].map(_parse_rating).astype(object)
    orgs["org_type"] = orgs["org_type"].map(_normalize_org_type).astype(object)

    created_at = _parse_created_at(orgs["created_at"])
    for org_id in orgs.loc[created_at.isna(), "org_id"]:
        print(f"Skipping organization {org_id}: unparseable created_at")
    orgs = orgs.loc[created_at.notna()].copy()
    orgs["created_at"] = created_at.loc[created_at.notna()]

    for org_id in orgs.loc[orgs["org_rating"].isna(), "org_id"]:
        print(f"Organization {org_id}: missing/invalid org_rating - excluded from rating_distribution")
    for org_id in orgs.loc[orgs["org_type"].isna(), "org_id"]:
        print(f"Organization {org_id}: missing/unrecognized org_type - excluded from organization_mix_trend")

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
    country_code or country_name (case-insensitive; "United States of
    America" matches "UNITED_STATES_OF_AMERICA"). None means ALL. A country
    that doesn't exist in the countries table is a 400, not a silently
    empty result.
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

def empty_mix_trend():
    return {org_type: [] for org_type in ORG_TYPES}


def empty_bucket():
    return {"rating_distribution": [], "organization_mix_trend": empty_mix_trend()}


def build_rating_distribution(organizations, start, end_exclusive):
    """
    Window-scoped count per org_rating, ascending by rating. Only ratings
    present in the window are returned (no zero-fill).
    """
    windowed = _in_window(organizations, start, end_exclusive)
    ratings = windowed["org_rating"].dropna()
    if ratings.empty:
        return []
    counts = ratings.astype(int).value_counts().sort_index()
    return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]


def _period_key(created_at, granularity):
    return created_at.dt.strftime("%Y-%m-%d" if granularity == "day" else "%Y-%m")


def _period_end_exclusive(period, granularity):
    freq = "D" if granularity == "day" else "M"
    return (pd.Period(period, freq=freq) + 1).start_time


def build_organization_mix_trend(organizations, start, end_exclusive, granularity):
    """
    For each org type, the periods (inside the window) in which at least one
    organization of that type was created, each with the absolute all-time
    running total of that type as of the end of the period - same semantics
    as Growth & Location's growth_trend.total_organizations. Running totals
    count every organization of the type (country filter applied) created
    up to that point, including ones before the window starts, so each
    series is non-decreasing. Periods are sparse per type.
    """
    trend = empty_mix_trend()
    for org_type in ORG_TYPES:
        of_type = organizations.loc[organizations["org_type"] == org_type]
        windowed = _in_window(of_type, start, end_exclusive)
        if windowed.empty:
            continue

        all_created = of_type["created_at"].sort_values().to_numpy()
        for period in sorted(_period_key(windowed["created_at"], granularity).unique()):
            cutoff = _period_end_exclusive(period, granularity).to_datetime64()
            running_total = int(all_created.searchsorted(cutoff, side="left"))
            trend[org_type].append({"period": period, "count": running_total})
    return trend


# ---------------------------------------------------------------------------
# Response assembly
# ---------------------------------------------------------------------------

def build_rating_type_response(organizations, request, reference_date=None):
    """
    organizations must already be country-filtered. request is the output
    of parse_request.
    """
    rating_range = request["rating_range"]
    type_range = request["type_range"]

    if rating_range is not None or type_range is not None:
        custom = empty_bucket()
        if rating_range is not None:
            custom["rating_distribution"] = build_rating_distribution(organizations, *rating_range)
        if type_range is not None:
            custom["organization_mix_trend"] = build_organization_mix_trend(
                organizations, *type_range, BUCKET_GRANULARITY["Custom"]
            )
        return {"Custom": custom}

    reference_date = reference_date if reference_date is not None else pd.Timestamp.now()
    response = {}
    for bucket in FIXED_BUCKETS:
        start, end_exclusive = fixed_window(bucket, reference_date)
        response[bucket] = {
            "rating_distribution": build_rating_distribution(organizations, start, end_exclusive),
            "organization_mix_trend": build_organization_mix_trend(
                organizations, start, end_exclusive, BUCKET_GRANULARITY[bucket]
            ),
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

    return build_response(200, build_rating_type_response(organizations, request, reference_date))


# ---------------------------------------------------------------------------
# Local run
# ---------------------------------------------------------------------------

def _sanity_check(name, event, result):
    """Prints PASS/FAIL for the issue's local sanity checks on one response."""
    problems = []
    body = json.loads(result["body"])
    payload = parse_event_body(event)
    has_custom = any(not _is_blank(payload.get(field)) for field in RATING_DATE_FIELDS + TYPE_DATE_FIELDS)

    if result["statusCode"] != 200:
        problems.append(f"status {result['statusCode']}")
    else:
        expected_keys = {"Custom"} if has_custom else set(FIXED_BUCKETS) | {"Custom"}
        if set(body) != expected_keys:
            problems.append(f"top-level keys {sorted(body)}")
        for bucket, charts in body.items():
            if set(charts) != {"rating_distribution", "organization_mix_trend"}:
                problems.append(f"{bucket} keys {sorted(charts)}")
                continue
            if set(charts["organization_mix_trend"]) != set(ORG_TYPES):
                problems.append(f"{bucket} mix series {sorted(charts['organization_mix_trend'])}")
            for org_type, series in charts["organization_mix_trend"].items():
                counts = [point["count"] for point in series]
                if counts != sorted(counts):
                    problems.append(f"{bucket}.{org_type} not non-decreasing")

    print(f"Sanity check [{name}]: {'PASS' if not problems else 'FAIL - ' + '; '.join(problems)}")


if __name__ == "__main__":
    # Local run only: reads the CSVs in MOCK_DATA_DIR (default: ./mock_data
    # next to this file). Never deploy directly to AWS.
    os.environ.setdefault("USE_MOCK_DATA", "true")

    sample_events = [
        ("No body", {}),
        ("Country filter (USA)", {"country": "USA"}),
        ("Rating Custom range only", {"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"}),
        ("Type Custom range only", {"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"}),
        ("Both Custom ranges + country", {
            "country": "USA",
            "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
            "type_start_date": "2025-01-01", "type_end_date": "2026-12-31",
        }),
        ("Custom range with no organizations", {
            "rating_start_date": "2000-01-01", "rating_end_date": "2000-01-31",
            "type_start_date": "2000-01-01", "type_end_date": "2000-01-31",
        }),
        ("API Gateway-style event (JSON string body)", {"body": json.dumps({"country": "ind"})}),
    ]
    error_events = [
        ("Missing half of rating pair", {"rating_start_date": "2026-01-01"}),
        ("Bad type date format", {"type_start_date": "2025/01/01", "type_end_date": "2025-12-31"}),
        ("Impossible calendar date", {"rating_start_date": "2026-02-30", "rating_end_date": "2026-03-01"}),
        ("Start after end", {"type_start_date": "2025-12-31", "type_end_date": "2025-01-01"}),
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
