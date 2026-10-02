"""Size & Contribution analytics for the Organization Analytics dashboard.

Two charts, both window-scoped snapshots (not cumulative):

  * organizations_by_size        - organization counts per org_size category
  * collaborator_vs_contributor  - count(is_collaborator) and count(is_contributor),
                                   read independently; an organization can be both,
                                   either, or neither, so the two rows need not sum
                                   to the window's total organization count

Response shape depends on which Custom range params are present:

  * neither size_start_date/size_end_date nor contribution_start_date/
    contribution_end_date  -> all of "7D","30D","1Y","All" plus an empty "Custom"
  * either or both supplied -> only "Custom", with each sub-chart populated from
    its own range, independently (unlike the volunteer-side reference lambda,
    which drops the second range if both are supplied - that bug is not repeated
    here: both ranges are evaluated when both are given)

country / organization_type filters apply to every shape the same way.

Data is read from organizations.csv, states.csv and countries.csv in MOCK_DATA_DIR
(mock_data/ next to this file by default) when USE_MOCK_DATA is true (the default -
this lets the file run standalone, with no DB and no psycopg2 installed, exactly
like it's exercised in the __main__ block below). Those CSVs are local-only.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone

import pandas as pd

try:
    import psycopg2
except ImportError:  # psycopg2 is only needed for the real-DB path (USE_MOCK_DATA=false)
    psycopg2 = None

logger = logging.getLogger()
logger.setLevel(logging.INFO)

USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "true").strip().lower() != "false"
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data")

SCHEMA_NAME = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")
ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
STATES_TABLE = f"{SCHEMA_NAME}.states"
COUNTRIES_TABLE = f"{SCHEMA_NAME}.countries"

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_YEAR, MAX_YEAR = 1900, 2200  # keeps dates inside the range pandas/Postgres can represent

FIXED_BUCKETS = ["7D", "30D", "1Y", "All"]
SIZE_ORDER = {"small": 0, "medium": 1, "large": 2}  # preferred display order; unknown sizes sort after

RESPONSE_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


class RequestError(ValueError):
    """The request itself is invalid (returned as a 400)."""


# --- request parsing (same approach as growth_location_analytics.py) -----------------
def parse_event_body(event):
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, str):
        if not body.strip():
            return {}
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise RequestError("Request body is not valid JSON")
    if not isinstance(body, dict):
        raise RequestError("Request body must be a JSON object")
    return body


def parse_date(name, value):
    if not isinstance(value, str) or not DATE_PATTERN.match(value):
        raise RequestError(f"Invalid {name}: {value!r}. Expected format YYYY-MM-DD")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise RequestError(f"Invalid {name}: {value!r}. Not a real calendar date")
    if not MIN_YEAR <= parsed.year <= MAX_YEAR:
        raise RequestError(f"Invalid {name}: {value!r}. Year must be between {MIN_YEAR} and {MAX_YEAR}")
    return pd.Timestamp(parsed)


def parse_range(params, start_key, end_key):
    """Return (start, end) Timestamps, or None when neither key was supplied."""
    start_raw, end_raw = params.get(start_key), params.get(end_key)
    start_given = start_raw not in (None, "")
    end_given = end_raw not in (None, "")
    if not start_given and not end_given:
        return None
    if start_given != end_given:
        raise RequestError(f"{start_key} and {end_key} must be provided together")
    start = parse_date(start_key, start_raw)
    end = parse_date(end_key, end_raw)
    if start > end:
        raise RequestError(f"{start_key} must not be after {end_key}")
    return start, end


def normalize_filter(value):
    """None/blank/"ALL" (any case) all mean "no filter"; otherwise strip and keep as-is."""
    if value is None:
        return None
    value = str(value).strip()
    return None if value == "" or value.upper() == "ALL" else value


_SEPARATORS = re.compile(r"[\s_-]+")


def normalize_enum(value):
    """Case- and separator-insensitive form of an enum-ish value, e.g. "Non-Profit",
    "non_profit" and "non profit" all normalize to "nonprofit". org_type is stored
    as the clean non_profit/for_profit enum in some data and as a messier free-text
    equivalent (e.g. "Non-Profit") in other data (such as the legacy sample CSV
    under data-analytics/sql/), so the filter needs to match either spelling."""
    return _SEPARATORS.sub("", str(value).strip().lower())


# --- fixed-bucket windows (same definitions as growth_location_analytics.py) --------
def window_start(bucket, today):
    """First day of a fixed bucket's window (it always ends today, inclusive of both
    ends); None means unbounded. "7D"/"30D" span exactly 7/30 calendar days (today
    and the 6/29 days before it) - not today's date offset by 7/30, which would be
    one day too many."""
    if bucket == "7D":
        return today - pd.Timedelta(days=6)
    if bucket == "30D":
        return today - pd.Timedelta(days=29)
    if bucket == "1Y":  # trailing 12 calendar months: this month plus the 11 before it
        return (today.to_period("M") - 11).start_time
    return None  # "All"


def in_window(days, start, end):
    mask = pd.Series(True, index=days.index)
    if start is not None:
        mask &= days >= start
    if end is not None:
        mask &= days < end + pd.Timedelta(days=1)
    return mask


# --- mock-data path (pandas over the CSVs) -------------------------------------------
def _read_csv(data_dir, filename):
    try:
        return pd.read_csv(os.path.join(data_dir, filename), dtype=str)
    except pd.errors.EmptyDataError:  # zero-byte file
        return pd.DataFrame()


def load_mock_data(data_dir):
    return (_read_csv(data_dir, "organizations.csv"),
            _read_csv(data_dir, "states.csv"),
            _read_csv(data_dir, "countries.csv"))


def _to_bool(series):
    return series.fillna("").str.strip().str.lower().isin(["true", "t", "1", "yes", "y"])


def prepare_organizations(orgs, states, countries):
    """One row per organization with its creation day, country code/name, size,
    type and collaborator/contributor flags.

    organizations.state_id -> states.country_id -> countries.country_code/name.
    is_contributor defaults to False for every row when the column is absent
    altogether, so Contributor is simply 0 rather than a crash.
    Rows without a parseable created_at can't be placed on a timeline and are dropped.
    """
    created = pd.to_datetime(orgs.get("created_at"), errors="coerce", format="mixed", utc=True)
    orgs = orgs.assign(
        created=created.dt.tz_localize(None).dt.normalize(),
        is_collaborator=_to_bool(orgs.get("is_collaborator", pd.Series(dtype=str))),
        is_contributor=_to_bool(orgs.get("is_contributor", pd.Series(dtype=str))),
        org_size=orgs.get("org_size", pd.Series(dtype=str)).str.strip(),
        org_type=orgs.get("org_type", pd.Series(dtype=str)).str.strip(),
    )
    orgs = orgs[orgs["created"].notna()]
    orgs.loc[orgs["org_size"].isin(["", None]), "org_size"] = pd.NA

    state_country = states.dropna(subset=["state_id"]).drop_duplicates("state_id")[["state_id", "country_id"]]
    country_cols = [c for c in ("country_id", "country_code", "country_name") if c in countries.columns]
    country_lookup = countries.dropna(subset=["country_id"]).drop_duplicates("country_id")[country_cols]
    orgs = orgs.merge(state_country, on="state_id", how="left").merge(country_lookup, on="country_id", how="left")

    for col in ("country_code", "country_name"):
        if col not in orgs.columns:
            orgs[col] = pd.NA
    return orgs[["created", "is_collaborator", "is_contributor", "org_size", "org_type",
                "country_code", "country_name"]]


def apply_filters(orgs, country, organization_type):
    country, organization_type = normalize_filter(country), normalize_filter(organization_type)
    if country is not None:
        needle = country.lower()
        orgs = orgs[(orgs["country_code"].fillna("").str.lower() == needle) |
                   (orgs["country_name"].fillna("").str.lower() == needle)]
    if organization_type is not None:
        needle = normalize_enum(organization_type)
        orgs = orgs[orgs["org_type"].fillna("").map(normalize_enum) == needle]
    return orgs


def organizations_by_size(window):
    """[{"size": ..., "count": ...}] for every org_size present in `window` (no zero-fill)."""
    sizes = window["org_size"].dropna()
    if sizes.empty:
        return []
    counts = sizes.value_counts()
    ordered = sorted(counts.items(), key=lambda kv: (SIZE_ORDER.get(kv[0].lower(), len(SIZE_ORDER)), kv[0].lower()))
    return [{"size": size, "count": int(count)} for size, count in ordered]


def collaborator_vs_contributor(window):
    """Exactly 2 rows (Collaborator, Contributor), each independent, or [] if the
    window holds no organizations at all."""
    total = len(window)
    if total == 0:
        return []
    collaborators = int(window["is_collaborator"].sum())
    contributors = int(window["is_contributor"].sum())
    return [
        {"type": "Collaborator", "count": collaborators, "percentage": round(collaborators / total * 100, 1)},
        {"type": "Contributor", "count": contributors, "percentage": round(contributors / total * 100, 1)},
    ]


def bucket_charts(window):
    return {"organizations_by_size": organizations_by_size(window),
            "collaborator_vs_contributor": collaborator_vs_contributor(window)}


def build_mock_response(data_dir, today, country, organization_type, size_range, contribution_range):
    orgs = apply_filters(prepare_organizations(*load_mock_data(data_dir)), country, organization_type)

    if size_range or contribution_range:
        size_window = orgs[in_window(orgs["created"], *size_range)] if size_range else orgs.iloc[0:0]
        contribution_window = (orgs[in_window(orgs["created"], *contribution_range)]
                               if contribution_range else orgs.iloc[0:0])
        return {"Custom": {
            "organizations_by_size": organizations_by_size(size_window) if size_range else [],
            "collaborator_vs_contributor": (collaborator_vs_contributor(contribution_window)
                                            if contribution_range else []),
        }}

    result = {bucket: bucket_charts(orgs[in_window(orgs["created"], window_start(bucket, today), today)]
                                    if window_start(bucket, today) is not None else orgs)
             for bucket in FIXED_BUCKETS}
    result["Custom"] = {"organizations_by_size": [], "collaborator_vs_contributor": []}
    return result


# --- real-DB path (psycopg2) ----------------------------------------------------------
# Mirrors the mock-data logic above as SQL. Exercised only when USE_MOCK_DATA=false;
# not run against a live database as part of this change (no Postgres in this repo's
# test environment) - see the PR notes.
def get_db_connection():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; set USE_MOCK_DATA=true or install psycopg2")
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        dbname=os.environ.get("DB_NAME", "saayam_local"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD"),
        port=os.environ.get("DB_PORT", "5432"),
    )


def _db_filters(country, organization_type):
    country, organization_type = normalize_filter(country), normalize_filter(organization_type)
    clauses, params = [], []
    if country is not None:
        clauses.append("(LOWER(c.country_code) = %s OR LOWER(c.country_name) = %s)")
        params += [country.lower(), country.lower()]
    if organization_type is not None:
        # same case/separator normalization as the mock path (normalize_enum), so this
        # still matches a column holding "Non-Profit"-style values, not just the clean
        # non_profit/for_profit enum spelling
        clauses.append(r"REGEXP_REPLACE(LOWER(o.org_type::text), '[\s_-]+', '', 'g') = %s")
        params.append(normalize_enum(organization_type))
    return clauses, params


def _db_window(cursor, country, organization_type, start, end):
    clauses, params = _db_filters(country, organization_type)
    if start is not None:
        clauses.append("o.created_at >= %s")
        params.append(start.date())
    if end is not None:
        clauses.append("o.created_at < %s")
        params.append((end + pd.Timedelta(days=1)).date())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    cursor.execute(f"""
        SELECT o.org_size::text AS size, COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        LEFT JOIN {STATES_TABLE} s ON o.state_id = s.state_id
        LEFT JOIN {COUNTRIES_TABLE} c ON s.country_id = c.country_id
        {where}
        AND o.org_size IS NOT NULL
        GROUP BY o.org_size
    """ if where else f"""
        SELECT o.org_size::text AS size, COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        WHERE o.org_size IS NOT NULL
        GROUP BY o.org_size
    """, params)
    ordered = sorted(cursor.fetchall(), key=lambda row: (SIZE_ORDER.get(row[0].lower(), len(SIZE_ORDER)), row[0].lower()))
    by_size = [{"size": size, "count": int(count)} for size, count in ordered]

    cursor.execute(f"""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE),
               COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)
        FROM {ORGANIZATIONS_TABLE} o
        LEFT JOIN {STATES_TABLE} s ON o.state_id = s.state_id
        LEFT JOIN {COUNTRIES_TABLE} c ON s.country_id = c.country_id
        {where}
    """, params)
    total, collaborators, contributors = cursor.fetchone()
    collab_vs_contrib = collaborator_vs_contributor_from_counts(total, collaborators, contributors)
    return {"organizations_by_size": by_size, "collaborator_vs_contributor": collab_vs_contrib}


def collaborator_vs_contributor_from_counts(total, collaborators, contributors):
    if not total:
        return []
    return [
        {"type": "Collaborator", "count": int(collaborators), "percentage": round(collaborators / total * 100, 1)},
        {"type": "Contributor", "count": int(contributors), "percentage": round(contributors / total * 100, 1)},
    ]


def build_db_response(today, country, organization_type, size_range, contribution_range):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if size_range or contribution_range:
            size_charts = (_db_window(cursor, country, organization_type, *size_range)
                           if size_range else {"organizations_by_size": [], "collaborator_vs_contributor": []})
            contribution_charts = (_db_window(cursor, country, organization_type, *contribution_range)
                                   if contribution_range else
                                   {"organizations_by_size": [], "collaborator_vs_contributor": []})
            return {"Custom": {
                "organizations_by_size": size_charts["organizations_by_size"] if size_range else [],
                "collaborator_vs_contributor": (contribution_charts["collaborator_vs_contributor"]
                                                if contribution_range else []),
            }}
        result = {bucket: _db_window(cursor, country, organization_type,
                                     window_start(bucket, today), today if window_start(bucket, today) else None)
                 for bucket in FIXED_BUCKETS}
        result["Custom"] = {"organizations_by_size": [], "collaborator_vs_contributor": []}
        return result
    finally:
        conn.close()


# --- Lambda entry point ----------------------------------------------------------------
def _today():
    return pd.Timestamp(datetime.now(timezone.utc).date())


def _reply(status_code, payload):
    return {"statusCode": status_code, "headers": RESPONSE_HEADERS, "body": json.dumps(payload)}


def lambda_handler(event, context):
    try:
        params = parse_event_body(event)
        country = params.get("country", "ALL")
        organization_type = params.get("organization_type", "ALL")
        size_range = parse_range(params, "size_start_date", "size_end_date")
        contribution_range = parse_range(params, "contribution_start_date", "contribution_end_date")
    except RequestError as exc:
        return _reply(400, {"error": str(exc)})

    try:
        if USE_MOCK_DATA:
            data_dir = os.environ.get("MOCK_DATA_DIR", DEFAULT_DATA_DIR)
            payload = build_mock_response(data_dir, _today(), country, organization_type,
                                          size_range, contribution_range)
        else:
            payload = build_db_response(_today(), country, organization_type, size_range, contribution_range)
        return _reply(200, payload)
    except Exception:
        logger.exception("size_contribution_analytics failed")
        return _reply(500, {"error": "Internal server error"})


if __name__ == "__main__":
    sample_events = [
        ("no body", {}),
        ("country filter", {"body": json.dumps({"country": "USA"})}),
        ("organization_type filter", {"body": json.dumps({"organization_type": "non_profit"})}),
        ("size range only", {"body": json.dumps({"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"})}),
        ("contribution range only", {"body": json.dumps({"contribution_start_date": "2025-01-01",
                                                          "contribution_end_date": "2025-12-31"})}),
        ("both ranges together", {"body": json.dumps({"size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
                                                       "contribution_start_date": "2025-01-01",
                                                       "contribution_end_date": "2025-12-31"})}),
    ]
    for label, sample in sample_events:
        reply = lambda_handler(sample, None)
        print(f"--- {label}: {sample.get('body', '{}')}")
        print(f"statusCode {reply['statusCode']}")
        print(json.dumps(json.loads(reply["body"]), separators=(",", ":")))
