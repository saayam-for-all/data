"""Size & Contribution Analytics API for the Organization Dashboard (issue #376).

Standalone function for the Size & Contribution tab. Two charts:
  - organizations_by_size: organization counts per org_size category.
  - collaborator_vs_contributor: count(is_collaborator=True) vs
    count(is_contributor=True), computed independently (NOT a
    complement/partition -- an org can be both, or neither).

Follows the same response-shape pattern as growth_location_analytics.py
(issue #336):
  - No Custom date-range params -> full response with 7D/30D/1Y/All plus
    an empty Custom.
  - size_start_date/size_end_date and/or contribution_start_date/
    contribution_end_date present -> response is {"Custom": {...}} ONLY
    (no fixed buckets), with each sub-chart populated independently
    based on which range params were supplied. Unlike the Growth &
    Location reference, supplying BOTH custom pairs here populates BOTH
    sub-charts at once (that double-supplied-case silent-drop in the
    reference is a known bug -- intentionally not replicated here).

Reads organizations.csv / states.csv / countries.csv from a local mock
data directory (no AWS Parameter Store, no live AWS connection). Point
MOCK_DATA_DIR at wherever you keep those CSVs locally for testing; do not
commit the CSVs themselves.

This is a new function -- it does not reuse or modify organization_analytics.py.

NOTE: organization_analytics.py's actual source wasn't available when this
was written (only its test file, test_organization_analytics.py, was),
so the psycopg2 optional-import below mirrors what that test file implies
(a plain get_db_connection() -> cursor.execute/fetchall/fetchone/close
style) rather than a confirmed copy-paste of that file's real DB path.
Please double check this against organization_analytics.py's actual
import block and real-DB function before merging, and wire up the real
query if it differs.
"""

import json
import os

import pandas as pd

try:
    import psycopg2  # noqa: F401  -- only required for the real Postgres path
except ImportError:
    psycopg2 = None

# TODO: confirm with the ticket owner whether this repo's `states.csv` is the
# same file as organization_analytics.py's `state.csv` (singular, no
# country_id today) or a separate/renamed file. Same assumption as
# growth_location_analytics.py: states.csv has state_id, state_name,
# country_id.
DEFAULT_MOCK_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql"
)

BOOL_MAP = {"TRUE": True, "FALSE": False, True: True, False: False}

DATE_FORMAT = "%Y-%m-%d"


def get_mock_data_dir():
    return os.environ.get("MOCK_DATA_DIR", DEFAULT_MOCK_DATA_DIR)


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        # API Gateway's Lambda proxy integration requires `body` to be a
        # JSON-encoded string, not a raw dict.
        "body": json.dumps(body),
    }


# --------------------------------------------------------------------------
# Data loading / joining
# --------------------------------------------------------------------------

def load_data(mock_data_dir):
    orgs = pd.read_csv(os.path.join(mock_data_dir, "organizations.csv"))
    states = pd.read_csv(os.path.join(mock_data_dir, "state.csv"))
    countries = pd.read_csv(os.path.join(mock_data_dir, "country.csv"))

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce")
    orgs["is_collaborator"] = orgs["is_collaborator"].map(BOOL_MAP).fillna(False)

    # is_contributor is allowed to be entirely absent from the mock data --
    # degrade gracefully rather than KeyError later (handled again at
    # compute time in case a merge/filter drops the column).
    if "is_contributor" in orgs.columns:
        orgs["is_contributor"] = orgs["is_contributor"].map(BOOL_MAP).fillna(False)

    return orgs, states, countries


def attach_country(orgs, states, countries):
    """organizations.state_id -> states.country_id -> countries.country_code"""
    merged = orgs.merge(
        states[["state_id", "country_id"]], on="state_id", how="left"
    )
    merged = merged.merge(
        countries[["country_id", "country_code"]], on="country_id", how="left"
    )
    return merged


# --------------------------------------------------------------------------
# Static filters (country / organization_type) -- apply once, up front,
# before any window/date filtering. These are new relative to
# growth_location_analytics.py, which has no such filters.
# --------------------------------------------------------------------------

def apply_filters(df, params):
    filtered = df

    country = params.get("country")
    if country and str(country).upper() != "ALL":
        target = str(country).upper()
        mask = pd.Series(False, index=filtered.index)
        if "country_code" in filtered.columns:
            mask |= filtered["country_code"].astype(str).str.upper() == target
        if "country_name" in filtered.columns:
            mask |= filtered["country_name"].astype(str).str.upper() == target
        filtered = filtered[mask]

    def _normalize(value):
        return str(value).lower().replace("-", "").replace("_", "").replace(" ", "")

    org_type = params.get("organization_type")
    if org_type and str(org_type).upper() != "ALL":
        filtered = filtered[
            filtered["org_type"].apply(_normalize) == _normalize(org_type)
        ]

    return filtered


# --------------------------------------------------------------------------
# Date parsing / validation (identical pattern to growth_location_analytics.py)
# --------------------------------------------------------------------------

def parse_date_pair(params, start_key, end_key):
    """Returns (start_inclusive, end_exclusive) as Timestamps, or None if
    neither param was supplied. Raises ValueError (-> 400) on bad input.
    """
    start_raw = params.get(start_key)
    end_raw = params.get(end_key)

    if start_raw is None and end_raw is None:
        return None
    if start_raw is None or end_raw is None:
        raise ValueError(f"Both {start_key} and {end_key} must be provided together")

    try:
        start = pd.to_datetime(start_raw, format=DATE_FORMAT)
        end = pd.to_datetime(end_raw, format=DATE_FORMAT)
    except (ValueError, TypeError):
        raise ValueError(
            f"Invalid date format for {start_key}/{end_key}; expected YYYY-MM-DD"
        )

    if start > end:
        raise ValueError(f"{start_key} must not be after {end_key}")

    # end is inclusive of the given calendar date -> exclusive upper bound
    return start, end + pd.Timedelta(days=1)


# --------------------------------------------------------------------------
# Window helpers (same fixed-bucket anchoring as growth_location_analytics.py)
# --------------------------------------------------------------------------

def filter_window(df, start, end, col="created_at"):
    """start inclusive, end exclusive. Either may be None (unbounded)."""
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df[col] >= start
    if end is not None:
        mask &= df[col] < end
    return df[mask]


def get_fixed_windows():
    """(start_inclusive, end_exclusive) for each fixed bucket.
    All = no window at all (entire dataset). Anchored to calendar-day
    (and calendar-month, for 1Y) boundaries, same as Growth & Location:
    - 7D / 30D: today plus the previous 6 / 29 days = 7 / 30 calendar days.
    - 1Y: the current calendar month plus the previous 11 months.
    """
    today = pd.Timestamp.now().normalize()
    end_exclusive = today + pd.Timedelta(days=1)  # through end of today

    current_month_start = today.replace(day=1)
    one_year_start = current_month_start - pd.DateOffset(months=11)

    return {
        "7D": (today - pd.Timedelta(days=6), end_exclusive),
        "30D": (today - pd.Timedelta(days=29), end_exclusive),
        "1Y": (one_year_start, end_exclusive),
        "All": (None, None),
    }


# --------------------------------------------------------------------------
# Chart computations
# --------------------------------------------------------------------------

def compute_organizations_by_size(df, start, end):
    """Flat array of {"size": ..., "count": ...}, one row per org_size
    category actually present in the window -- categories aren't
    hardcoded, so this still works if a new org_size value is added later.
    """
    window_df = filter_window(df, start, end)
    if window_df.empty:
        return []

    counts = window_df.groupby("org_size").size()
    return [{"size": size, "count": int(count)} for size, count in counts.items()]


def compute_collaborator_vs_contributor(df, start, end):
    """Exactly 2 rows (Collaborator, Contributor) when the window is
    non-empty; each count/percentage computed independently against the
    window's total organization count. Not a partition -- the two counts
    are not expected to sum to the total. Degrades to a 0 Contributor
    count/percentage if is_contributor is missing from the data entirely.
    """
    window_df = filter_window(df, start, end)
    total = len(window_df)
    if total == 0:
        return []

    collab_count = int(window_df["is_collaborator"].sum())
    if "is_contributor" in window_df.columns:
        contrib_count = int(window_df["is_contributor"].sum())
    else:
        contrib_count = 0

    return [
        {
            "type": "Collaborator",
            "count": collab_count,
            "percentage": round(collab_count / total * 100, 1),
        },
        {
            "type": "Contributor",
            "count": contrib_count,
            "percentage": round(contrib_count / total * 100, 1),
        },
    ]


def build_bucket(df, start, end):
    return {
        "organizations_by_size": compute_organizations_by_size(df, start, end),
        "collaborator_vs_contributor": compute_collaborator_vs_contributor(df, start, end),
    }


# --------------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------------

def build_analytics(df, params):
    try:
        size_range = parse_date_pair(params, "size_start_date", "size_end_date")
        contribution_range = parse_date_pair(
            params, "contribution_start_date", "contribution_end_date"
        )
    except ValueError as e:
        return None, str(e)

    filtered_df = apply_filters(df, params)

    if size_range or contribution_range:
        # Custom-only response -- no fixed buckets at all. Each sub-chart
        # is populated independently of the other; both pairs supplied
        # together means both sub-charts are populated at once (no
        # priority, no dropping either one).
        custom_size = (
            compute_organizations_by_size(filtered_df, size_range[0], size_range[1])
            if size_range
            else []
        )
        custom_contribution = (
            compute_collaborator_vs_contributor(
                filtered_df, contribution_range[0], contribution_range[1]
            )
            if contribution_range
            else []
        )
        return {
            "Custom": {
                "organizations_by_size": custom_size,
                "collaborator_vs_contributor": custom_contribution,
            }
        }, None

    response = {}
    for bucket_name, (start, end) in get_fixed_windows().items():
        response[bucket_name] = build_bucket(filtered_df, start, end)

    response["Custom"] = {
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
    }

    return response, None


def lambda_handler(event, context):
    params = event
    if isinstance(event.get("body"), str):
        try:
            params = json.loads(event["body"])
        except json.JSONDecodeError:
            return build_response(400, {"error": "request body is not valid JSON"})

    try:
        orgs, states, countries = load_data(get_mock_data_dir())
        df = attach_country(orgs, states, countries)
    except Exception as e:  # noqa: BLE001
        print(f"size_contribution_analytics failed to load data: {e}")
        return build_response(500, {"error": "failed to load data"})

    response, error = build_analytics(df, params)
    if error:
        return build_response(400, {"error": error})

    return build_response(200, response)


if __name__ == "__main__":
    sample_events = {
        "no body": {},
        "malformed JSON body": {"body": "{not valid json"},
        "country filter": {"body": json.dumps({"country": "USA"})},
        "organization_type filter": {"body": json.dumps({"organization_type": "non_profit"})},
        "size range only": {
            "body": json.dumps(
                {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"}
            )
        },
        "contribution range only": {
            "body": json.dumps(
                {
                    "contribution_start_date": "2025-01-01",
                    "contribution_end_date": "2025-12-31",
                }
            )
        },
        "both ranges": {
            "body": json.dumps(
                {
                    "size_start_date": "2026-01-01",
                    "size_end_date": "2026-06-30",
                    "contribution_start_date": "2025-01-01",
                    "contribution_end_date": "2025-12-31",
                }
            )
        },
        "invalid date": {
            "body": json.dumps(
                {"size_start_date": "not-a-date", "size_end_date": "2026-06-30"}
            )
        },
        "start after end": {
            "body": json.dumps(
                {"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"}
            )
        },
        "only half a pair": {
            "body": json.dumps({"contribution_start_date": "2025-01-01"})
        },
    }

    for label, event in sample_events.items():
        print(f"\n=== {label} ===")
        print(json.dumps(lambda_handler(event, None), indent=2, default=str))
