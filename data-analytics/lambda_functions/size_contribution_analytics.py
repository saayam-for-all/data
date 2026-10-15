"""
Size & Contribution Analytics API

Standalone Lambda function for the Size & Contribution tab of the
Organization Analytics dashboard:

  - Organizations By Size: org counts by org_size category.
  - Collaborators vs Contributors: two independent counts
    (is_collaborator=True, is_contributor=True) against the same
    window's total org count. These are NOT a partition of each other.

Response shape changes based on which Custom date-range params are present:
  - Neither size_start_date/size_end_date nor contribution_start_date/
    contribution_end_date supplied -> full response with "7D", "30D",
    "1Y", "All", "Custom" (Custom empty).
  - Either/both of those pairs supplied -> response is ONLY {"Custom": {...}},
    with each sub-chart populated independently of the other, no fixed
    buckets at all.

This is a fresh function -- it does not reuse or modify organization_analytics.py.
"""

import json
import os
from datetime import datetime

import pandas as pd

try:
    import psycopg2  # Real Postgres path. Optional so this still runs
    # standalone with USE_MOCK_DATA=true when psycopg2 isn't installed.
except ImportError:
    psycopg2 = None

USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "true").lower() == "true"
MOCK_DATA_DIR = os.environ.get(
    "MOCK_DATA_DIR", os.path.join(os.path.dirname(__file__), "mock_data")
)

DATE_FMT = "%Y-%m-%d"


class ValidationError(Exception):
    pass


# --------------------------------------------------------------------------
# Data loading (mock CSV path)
# --------------------------------------------------------------------------

def _load_mock_data(data_dir=MOCK_DATA_DIR):
    orgs = pd.read_csv(
        os.path.join(data_dir, "organizations.csv"),
        encoding="utf-8-sig",
        dtype={"org_id": "string", "state_id": "string"},
    )
    states = pd.read_csv(
        os.path.join(data_dir, "state.csv"),
        encoding="utf-8-sig",
        dtype={"state_id": "string", "country_id": "string"},
    )
    countries = pd.read_csv(
        os.path.join(data_dir, "country.csv"),
        encoding="utf-8-sig",
        dtype={"country_id": "string"},
    )

    if orgs.empty:
        orgs["created_at"] = pd.Series(dtype="datetime64[ns]")
        orgs["is_collaborator"] = pd.Series(dtype="bool")
        orgs["is_contributor"] = pd.Series(dtype="bool")
        orgs["country_code"] = pd.Series(dtype="object")
        orgs["country_name"] = pd.Series(dtype="object")
        return orgs

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce").dt.normalize()

    orgs["is_collaborator"] = (
        orgs["is_collaborator"].astype(str).str.strip().str.lower().isin(["true", "1", "yes"])
    )
    # is_contributor may legitimately be absent from the data -- degrade to
    # all-False rather than crashing, per spec.
    if "is_contributor" in orgs.columns:
        orgs["is_contributor"] = (
            orgs["is_contributor"].astype(str).str.strip().str.lower().isin(["true", "1", "yes"])
        )
    else:
        orgs["is_contributor"] = False

    country_cols = [c for c in ["country_id", "country_code", "country_name"] if c in countries.columns]
    merged = orgs.merge(states[["state_id", "country_id"]], on="state_id", how="left").merge(
        countries[country_cols], on="country_id", how="left"
    )
    orgs["country_code"] = merged.get("country_code")
    orgs["country_name"] = merged.get("country_name")
    return orgs


def _load_data():
    if USE_MOCK_DATA or psycopg2 is None:
        return _load_mock_data()

    # Real Postgres path. Connection details come from the environment,
    # matching the existing analytics Lambdas' convention.
    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    try:
        orgs = pd.read_sql(
            """
            SELECT o.org_id, o.org_size, o.org_type, o.is_collaborator,
                   o.is_contributor, o.state_id, o.created_at,
                   c.country_code, c.country_name
            FROM organizations o
            LEFT JOIN states s ON o.state_id = s.state_id
            LEFT JOIN countries c ON s.country_id = c.country_id
            """,
            conn,
        )
    finally:
        conn.close()

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce").dt.normalize()
    orgs["is_collaborator"] = orgs["is_collaborator"].astype(bool)
    if "is_contributor" in orgs.columns:
        orgs["is_contributor"] = orgs["is_contributor"].astype(bool)
    else:
        orgs["is_contributor"] = False
    return orgs


# --------------------------------------------------------------------------
# Date validation (same approach as Growth & Location)
# --------------------------------------------------------------------------

def _parse_date(value, field_name):
    try:
        return datetime.strptime(value, DATE_FMT)
    except (ValueError, TypeError):
        raise ValidationError(
            "Invalid date format for '%s': expected YYYY-MM-DD" % field_name
        )


def _validate_range(start_value, end_value, start_name, end_name):
    """Returns (start_dt, end_dt) or (None, None) if neither supplied."""
    if start_value is None and end_value is None:
        return None, None
    if start_value is None or end_value is None:
        raise ValidationError(
            "Both '%s' and '%s' must be supplied together" % (start_name, end_name)
        )
    start_dt = _parse_date(start_value, start_name)
    end_dt = _parse_date(end_value, end_name)
    if start_dt > end_dt:
        raise ValidationError("'%s' must not be after '%s'" % (start_name, end_name))
    return start_dt, end_dt


# --------------------------------------------------------------------------
# Country / org-type filters
# --------------------------------------------------------------------------

def _normalize(value):
    if value is None:
        return ""
    return str(value).strip().lower().replace("-", "").replace("_", "").replace(" ", "")


def _apply_scope_filters(orgs, country, organization_type):
    filtered = orgs
    if country and _normalize(country) != "all":
        target = _normalize(country)
        code_match = filtered["country_code"].apply(_normalize) == target
        name_match = filtered["country_name"].apply(_normalize) == target if "country_name" in filtered.columns else False
        filtered = filtered[code_match | name_match]
    if organization_type and _normalize(organization_type) != "all":
        target = _normalize(organization_type)
        filtered = filtered[filtered["org_type"].apply(_normalize) == target]
    return filtered


# --------------------------------------------------------------------------
# Chart builders (window-scoped snapshots, not cumulative)
# --------------------------------------------------------------------------

def _apply_window(orgs, window_start, window_end):
    windowed = orgs
    if window_start is not None:
        windowed = windowed[windowed["created_at"] >= window_start]
    if window_end is not None:
        windowed = windowed[windowed["created_at"] <= window_end]
    return windowed


def _build_organizations_by_size(orgs, window_start, window_end):
    windowed = _apply_window(orgs, window_start, window_end)
    if windowed.empty:
        return []
    counts = windowed.groupby("org_size").size().sort_index()
    return [{"size": str(size), "count": int(count)} for size, count in counts.items()]


def _build_collaborator_vs_contributor(orgs, window_start, window_end):
    windowed = _apply_window(orgs, window_start, window_end)
    total = len(windowed)
    if total == 0:
        return []

    collab_count = int(windowed["is_collaborator"].sum())
    contrib_count = int(windowed["is_contributor"].sum())

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


# --------------------------------------------------------------------------
# Fixed bucket windows (same convention as Growth & Location)
# --------------------------------------------------------------------------

def _fixed_windows(reference_date):
    today = pd.Timestamp(reference_date).normalize()
    return {
        "7D": (today - pd.Timedelta(days=7), today),
        "30D": (today - pd.Timedelta(days=30), today),
        # Trailing 12 calendar months, not a fixed 365-day window.
        "1Y": (today - pd.DateOffset(months=12), today),
        "All": (None, today),
    }


# --------------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------------

def lambda_handler(event, context=None):
    try:
        event = event or {}
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"]) if event["body"] else {}
        elif isinstance(event.get("body"), dict):
            body = event["body"]
        elif "body" in event:
            body = {}
        else:
            body = event

        if not isinstance(body, dict):
            raise ValidationError("Request body must be a JSON object")

        country = body.get("country", "ALL")
        organization_type = body.get("organization_type", "ALL")

        size_start, size_end = _validate_range(
            body.get("size_start_date"), body.get("size_end_date"),
            "size_start_date", "size_end_date",
        )
        contrib_start, contrib_end = _validate_range(
            body.get("contribution_start_date"), body.get("contribution_end_date"),
            "contribution_start_date", "contribution_end_date",
        )

        orgs = _load_data()
        orgs = _apply_scope_filters(orgs, country, organization_type)

        custom_requested = size_start is not None or contrib_start is not None

        if custom_requested:
            size_chart = (
                _build_organizations_by_size(orgs, size_start, size_end)
                if size_start is not None else []
            )
            contrib_chart = (
                _build_collaborator_vs_contributor(orgs, contrib_start, contrib_end)
                if contrib_start is not None else []
            )
            response = {
                "Custom": {
                    "organizations_by_size": size_chart,
                    "collaborator_vs_contributor": contrib_chart,
                }
            }
        else:
            reference_date = datetime.now()
            fixed_windows = _fixed_windows(reference_date)
            response = {}
            for bucket, (start, end) in fixed_windows.items():
                response[bucket] = {
                    "organizations_by_size": _build_organizations_by_size(orgs, start, end),
                    "collaborator_vs_contributor": _build_collaborator_vs_contributor(orgs, start, end),
                }
            response["Custom"] = {
                "organizations_by_size": [],
                "collaborator_vs_contributor": [],
            }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps(response),
        }

    except ValidationError as e:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)}),
        }
    except Exception:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "Internal server error"}),
        }


# --------------------------------------------------------------------------
# Local test harness
# --------------------------------------------------------------------------

if __name__ == "__main__":
    def show(label, event):
        print("=" * 70)
        print(label)
        print("=" * 70)
        result = lambda_handler(event)
        print("statusCode:", result["statusCode"])
        print(json.dumps(json.loads(result["body"]), indent=2))
        print()
        return result

    show("TEST 1: No body", {})

    show("TEST 2: country=USA", {"body": json.dumps({"country": "USA"})})

    show("TEST 3: organization_type=non_profit", {"body": json.dumps({"organization_type": "non_profit"})})

    show(
        "TEST 4: Only size_start_date/size_end_date (Custom, size only)",
        {"body": json.dumps({"size_start_date": "2024-01-01", "size_end_date": "2026-09-22"})},
    )

    show(
        "TEST 5: Only contribution_start_date/contribution_end_date (Custom, contrib only)",
        {"body": json.dumps({"contribution_start_date": "2024-01-01", "contribution_end_date": "2026-09-22"})},
    )

    show(
        "TEST 6: Both Custom ranges together (Custom, both populated)",
        {"body": json.dumps({
            "size_start_date": "2024-01-01", "size_end_date": "2026-09-22",
            "contribution_start_date": "2024-06-01", "contribution_end_date": "2026-09-22",
        })},
    )

    print("=" * 70)
    print("TEST 7: Malformed input -> expect 400s")
    print("=" * 70)
    print(lambda_handler({"body": json.dumps({"size_start_date": "2026-01-01"})}))  # missing half
    print(lambda_handler({"body": json.dumps({"size_start_date": "01/01/2026", "size_end_date": "2026-06-30"})}))  # bad format
    print(lambda_handler({"body": json.dumps({"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"})}))  # start after end
    print()

    print("=" * 70)
    print("SANITY CHECKS")
    print("=" * 70)
    no_params = json.loads(lambda_handler({})["body"])
    assert set(no_params.keys()) == {"7D", "30D", "1Y", "All", "Custom"}, "expected exactly 5 top-level keys"
    print("OK: no-params response has exactly 5 top-level keys")

    custom_only = json.loads(lambda_handler({"body": json.dumps({"size_start_date": "2024-01-01", "size_end_date": "2026-09-22"})})["body"])
    assert set(custom_only.keys()) == {"Custom"}, "expected exactly 1 top-level key"
    print("OK: Custom-params response has exactly 1 top-level key")

    all_bucket = no_params["All"]
    size_total = sum(r["count"] for r in all_bucket["organizations_by_size"])
    print("organizations_by_size total (All bucket):", size_total)
    cvc = all_bucket["collaborator_vs_contributor"]
    if cvc:
        print("collaborator_vs_contributor (All bucket):", cvc)
        for row in cvc:
            assert row["count"] <= size_total, "collaborator/contributor count should not exceed total org count"
    print("OK: collaborator/contributor counts each <= total org count")

    print("\nAll sanity checks passed.")
