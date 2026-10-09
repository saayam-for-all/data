"""Rating & Type Analytics API for Saayam's Organization Dashboard (issue #380).

Same pattern as growth_location_analytics.py (#336, merged): same response
envelope, same fixed-bucket/Custom split logic, same local-test style.

Two charts:
  - rating_distribution      - window-scoped categorical breakdown by
                                org_rating (1-5). No zero-filling: only
                                ratings actually present in the window show
                                up.
  - organization_mix_trend   - genuine time series, grouped by bucket exactly
                                like growth_trend. Two series, non_profit and
                                for_profit, each an absolute/cumulative
                                all-time running total (not window-reset),
                                with sparse periods (omitted when there's no
                                new org of that type in that period).

country filters both charts the same way in every response shape, via
organizations.state_id -> states.country_id -> countries.country_code.
There is no organization_type filter on this tab (Chart 2 already is the
type breakdown).
"""

import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta

import pandas as pd

try:
    import psycopg2  # noqa: F401  (optional: only needed for the real DB path)
except ImportError:
    psycopg2 = None

# csvs are only used for local testing, they are not part of the PR
DATA_DIR = os.environ.get(
    "MOCK_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mock-data-generation"),
)

RANGES = ["7D", "30D", "1Y", "All", "Custom"]
DAILY_RANGES = ("7D", "30D", "Custom")
ORG_TYPES = ("non_profit", "for_profit")


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": body,
    }


def parse_event_body(event):
    if not event:
        return {}
    if "body" not in event:
        return event
    body = event["body"]
    if body is None or body == "":
        return {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("request body is not valid JSON")
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return body


def read_custom_range(params, start_key, end_key):
    # returns None when neither date is sent, (start, end_exclusive) otherwise
    start = params.get(start_key)
    end = params.get(end_key)
    if not start and not end:
        return None
    if not start or not end:
        raise ValueError(f"{start_key} and {end_key} have to be sent together")
    try:
        first = datetime.strptime(start, "%Y-%m-%d")
        last = datetime.strptime(end, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValueError(f"{start_key} and {end_key} must be in YYYY-MM-DD format")
    if first > last:
        raise ValueError(f"{start_key} cannot be after {end_key}")
    # end date is inclusive, so the cutoff is the start of the next day
    return pd.Timestamp(first), pd.Timestamp(last) + timedelta(days=1)


def fixed_range(name, today):
    tomorrow = today + timedelta(days=1)
    if name == "7D":
        return tomorrow - timedelta(days=7), tomorrow
    if name == "30D":
        return tomorrow - timedelta(days=30), tomorrow
    if name == "1Y":
        return tomorrow - timedelta(days=365), tomorrow
    return None, None


def normalize_org_type(series):
    """Map whatever casing/punctuation org_type actually uses in the data
    ("Non-Profit", "For-profit", "non_profit", ...) onto the two canonical
    keys the response contract requires: non_profit / for_profit.

    The issue spec says the enum is non_profit/for_profit, but the real
    organizations.csv already in this repo (and the one generated for
    #301) uses "Non-Profit"/"For-profit" - this normalizes either source
    without caring which one is on disk.
    """
    return series.astype(str).str.strip().str.lower().str.replace("-", "_", regex=False)


def _has_country_name():
    # countries.csv in this repo sometimes carries country_name, sometimes
    # not - probe the header once rather than hardcoding a schema that
    # might not match what's actually on disk.
    try:
        header = pd.read_csv(os.path.join(DATA_DIR, "countries.csv"), nrows=0)
        return "country_name" in header.columns
    except Exception:
        return False


def load_data():
    orgs = pd.read_csv(
        os.path.join(DATA_DIR, "organizations.csv"),
        usecols=["org_id", "org_rating", "org_type", "state_id", "created_at"],
        dtype={"state_id": str},
        keep_default_na=False,
        na_values=[""],
    )
    states = pd.read_csv(
        os.path.join(DATA_DIR, "states.csv"),
        usecols=["state_id", "country_id"],
        dtype={"state_id": str},
        keep_default_na=False,
        na_values=[""],
    )
    country_cols = ["country_id", "country_code", "country_name"] if _has_country_name() else ["country_id", "country_code"]
    countries = pd.read_csv(
        os.path.join(DATA_DIR, "countries.csv"),
        usecols=country_cols,
        keep_default_na=False,
        na_values=[""],
    )

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce")
    orgs = orgs.dropna(subset=["created_at"])
    orgs["org_rating"] = pd.to_numeric(orgs["org_rating"], errors="coerce")
    orgs = orgs.dropna(subset=["org_rating"])
    orgs["org_rating"] = orgs["org_rating"].astype(int)
    orgs["org_type_norm"] = normalize_org_type(orgs["org_type"])
    return orgs, states, countries


def apply_country_filter(orgs, states, countries, country):
    if not country or str(country).upper() == "ALL":
        return orgs

    state_country = states[["state_id", "country_id"]].drop_duplicates("state_id")
    joined = orgs.merge(state_country, on="state_id", how="inner")
    joined = joined.merge(countries, on="country_id", how="inner")

    needle = str(country).strip().lower()
    code_match = joined["country_code"].astype(str).str.lower() == needle
    if "country_name" in joined.columns:
        name_match = joined["country_name"].astype(str).str.lower() == needle
        mask = code_match | name_match
    else:
        mask = code_match
    drop_cols = ["country_id", "country_code"] + (["country_name"] if "country_name" in joined.columns else [])
    return joined[mask].drop(columns=drop_cols)


def in_window(df, start, end):
    if start is not None:
        df = df[df["created_at"] >= start]
    if end is not None:
        df = df[df["created_at"] < end]
    return df


def rating_distribution(orgs, start, end):
    windowed = in_window(orgs, start, end)
    if windowed.empty:
        return []
    counts = windowed["org_rating"].value_counts().sort_index()
    return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]


def organization_mix_trend(orgs, start, end, daily):
    fmt = "%Y-%m-%d" if daily else "%Y-%m"
    result = {org_type: [] for org_type in ORG_TYPES}

    windowed = in_window(orgs, start, end)
    if windowed.empty:
        return result

    for org_type in ORG_TYPES:
        type_full = orgs[orgs["org_type_norm"] == org_type]
        type_windowed = windowed[windowed["org_type_norm"] == org_type]
        if type_full.empty or type_windowed.empty:
            continue
        # running total comes from the whole (country-filtered) dataset,
        # not just this window - matches growth_trend's total_organizations
        running = type_full["created_at"].dt.strftime(fmt).value_counts().sort_index().cumsum()
        periods = sorted(type_windowed["created_at"].dt.strftime(fmt).unique())
        result[org_type] = [{"period": p, "count": int(running[p])} for p in periods]
    return result


def lambda_handler(event, context):
    try:
        params = parse_event_body(event)
        rating_range = read_custom_range(params, "rating_start_date", "rating_end_date")
        type_range = read_custom_range(params, "type_start_date", "type_end_date")
        country = params.get("country", "ALL")
    except ValueError as e:
        return build_response(400, {"error": str(e)})

    try:
        orgs, states, countries = load_data()
        orgs = apply_country_filter(orgs, states, countries, country)

        today = pd.Timestamp.now().normalize()

        if rating_range or type_range:
            custom = {
                "rating_distribution": [],
                "organization_mix_trend": {org_type: [] for org_type in ORG_TYPES},
            }
            if rating_range:
                custom["rating_distribution"] = rating_distribution(orgs, *rating_range)
            if type_range:
                custom["organization_mix_trend"] = organization_mix_trend(orgs, *type_range, daily=True)
            return build_response(200, {"Custom": custom})

        result = {}
        for name in RANGES:
            if name == "Custom":
                result[name] = {
                    "rating_distribution": [],
                    "organization_mix_trend": {org_type: [] for org_type in ORG_TYPES},
                }
                continue
            start, end = fixed_range(name, today)
            result[name] = {
                "rating_distribution": rating_distribution(orgs, start, end),
                "organization_mix_trend": organization_mix_trend(orgs, start, end, daily=name in DAILY_RANGES),
            }
        return build_response(200, result)

    except Exception as e:
        print(f"rating/type analytics failed: {e}")
        return build_response(500, {"error": "could not build rating and type analytics"})


# ---------------------------------------------------------------------------
# Local test harness - not part of the API, only runs via `python
# rating_type_analytics.py`. No CSVs are committed with the PR; this reads
# whatever is in MOCK_DATA_DIR (defaults to data-analytics/mock-data-generation,
# e.g. the CSVs already generated for #301) plus a couple of hand-made
# throwaway datasets for edge cases.
# ---------------------------------------------------------------------------

def show(label, event):
    print(f"--- {label} ---")
    res = lambda_handler(event, None)
    print("status:", res["statusCode"])
    print(json.dumps(res["body"], indent=2))
    print()
    return res


def make_sample_dir(org_rows):
    tmp = tempfile.mkdtemp()
    orgs = pd.DataFrame(org_rows, columns=["org_id", "org_rating", "org_type", "state_id", "created_at"])
    orgs.to_csv(os.path.join(tmp, "organizations.csv"), index=False)
    pd.DataFrame({
        "state_id": ["TX", "FL", "MH", "ON"],
        "country_id": [1, 1, 2, 3],
    }).to_csv(os.path.join(tmp, "states.csv"), index=False)
    pd.DataFrame({
        "country_id": [1, 2, 3],
        "country_code": ["USA", "IND", "CAN"],
    }).to_csv(os.path.join(tmp, "countries.csv"), index=False)
    return tmp


if __name__ == "__main__":
    real_dir = DATA_DIR

    print("===== against the mock csvs in MOCK_DATA_DIR =====\n")
    everything = show("no body", {})
    show("country filter", {"body": json.dumps({"country": "USA"})})
    show("rating range only", {"body": json.dumps({"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"})})
    show("type range only", {"body": json.dumps({"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"})})
    show("both ranges", {"body": json.dumps({
        "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
        "type_start_date": "2025-01-01", "type_end_date": "2025-12-31",
    })})
    show("bad date format", {"body": json.dumps({"rating_start_date": "01/01/2026", "rating_end_date": "2026-06-30"})})
    show("start after end", {"body": json.dumps({"type_start_date": "2026-06-30", "type_end_date": "2026-01-01"})})
    show("only one date of a pair", {"body": json.dumps({"rating_start_date": "2026-01-01"})})

    print("===== sanity checks on the real mock data =====")
    body = everything["body"]
    assert list(body) == RANGES, "no-Custom-params response must have exactly the 5 bucket keys"
    for name in RANGES:
        bucket = body[name]
        assert set(bucket) == {"rating_distribution", "organization_mix_trend"}
        assert set(bucket["organization_mix_trend"]) == set(ORG_TYPES)
        for row in bucket["rating_distribution"]:
            assert set(row) == {"rating", "count"}
            assert 1 <= row["rating"] <= 5
    for org_type in ORG_TYPES:
        counts = [p["count"] for p in body["All"]["organization_mix_trend"][org_type]]
        assert counts == sorted(counts), f"{org_type} running total should never go down"
    rating_only = show("rating range only (recheck shape)", {"body": json.dumps({"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"})})
    assert list(rating_only["body"]) == ["Custom"], "Custom-only response must have exactly 1 top-level key"
    assert rating_only["body"]["Custom"]["organization_mix_trend"] == {"non_profit": [], "for_profit": []}
    print("all checks passed\n")

    print("===== small hand-made dataset (recent dates, mixed types/ratings) =====\n")
    today = pd.Timestamp.now().normalize()
    day = lambda n: (today - timedelta(days=n) + timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
    sample = [
        ["O1", 5, "non_profit", "TX", day(400)],
        ["O2", 4, "for_profit", "FL", day(200)],
        ["O3", 3, "Non-Profit", "MH", day(20)],
        ["O4", 5, "For-profit", "ON", day(5)],
        ["O5", 2, "non_profit", "TX", day(2)],
        ["O6", 4, "for_profit", "FL", day(0)],
    ]
    DATA_DIR = make_sample_dir(sample)
    small = show("no body", {})
    sb = small["body"]
    # both types' running totals reach their full-dataset count by the
    # window's last period, since every org in this sample is within 400
    # days and the 7D window's last period is "today"
    assert sb["7D"]["organization_mix_trend"]["non_profit"][-1]["count"] == 3
    assert sb["7D"]["organization_mix_trend"]["for_profit"][-1]["count"] == 3
    assert sb["Custom"]["rating_distribution"] == []
    print("mixed-casing org_type normalization + small dataset checks passed\n")
    shutil.rmtree(DATA_DIR)

    print("===== empty and single row files =====\n")
    DATA_DIR = make_sample_dir([])
    show("empty organizations.csv", {})
    shutil.rmtree(DATA_DIR)
    DATA_DIR = make_sample_dir([["O1", 5, "non_profit", "TX", day(1)]])
    show("one row", {})
    shutil.rmtree(DATA_DIR)
    DATA_DIR = real_dir