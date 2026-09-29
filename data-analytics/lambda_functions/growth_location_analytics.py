import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta

import pandas as pd

# csvs are only used for local testing, they are not part of the PR
DATA_DIR = os.environ.get(
    "MOCK_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mock-data-generation"),
)

RANGES = ["7D", "30D", "1Y", "All", "Custom"]
DAILY_RANGES = ("7D", "30D", "Custom")


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": body
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


def load_data():
    orgs = pd.read_csv(
        os.path.join(DATA_DIR, "organizations.csv"),
        usecols=["org_id", "state_id", "city_name", "is_collaborator", "created_at"],
        dtype={"state_id": str},
        keep_default_na=False,
        na_values=[""],
    )
    states = pd.read_csv(
        os.path.join(DATA_DIR, "states.csv"),
        usecols=["state_id", "state_name", "country_id"],
        dtype={"state_id": str},
        keep_default_na=False,
        na_values=[""],
    )
    countries = pd.read_csv(
        os.path.join(DATA_DIR, "countries.csv"),
        usecols=["country_id", "country_code"],
        keep_default_na=False,
        na_values=[""],
    )

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce")
    orgs = orgs.dropna(subset=["created_at"])
    orgs["is_collaborator"] = orgs["is_collaborator"].astype(str).str.lower() == "true"
    return orgs, states, countries


def in_window(df, start, end):
    if start is not None:
        df = df[df["created_at"] >= start]
    if end is not None:
        df = df[df["created_at"] < end]
    return df


def growth_trend(orgs, start, end, daily):
    empty = {"total_organizations": [], "collaborators": []}
    fmt = "%Y-%m-%d" if daily else "%Y-%m"

    windowed = in_window(orgs, start, end)
    if windowed.empty:
        return empty

    # running total comes from the whole dataset, not just this window
    running = orgs["created_at"].dt.strftime(fmt).value_counts().sort_index().cumsum()

    period = windowed["created_at"].dt.strftime(fmt)
    collabs = windowed.groupby(period)["is_collaborator"].sum()

    periods = sorted(collabs.index)
    return {
        "total_organizations": [{"period": p, "count": int(running[p])} for p in periods],
        "collaborators": [{"period": p, "count": int(collabs[p])} for p in periods],
    }


def orgs_by_location(orgs, states, countries, start, end):
    windowed = in_window(orgs, start, end)
    if windowed.empty:
        return []

    state_country = states[["state_id", "country_id"]].drop_duplicates("state_id")
    joined = windowed.merge(state_country, on="state_id", how="inner")
    joined = joined.merge(countries[["country_id", "country_code"]], on="country_id", how="inner")

    counts = joined["country_code"].value_counts()
    # biggest first, ties go alphabetical so the order is the same every run
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:4]
    return [{"country": code, "count": int(n)} for code, n in top]


def lambda_handler(event, context):
    try:
        params = parse_event_body(event)
        growth_range = read_custom_range(params, "start_date", "end_date")
        location_range = read_custom_range(params, "location_start_date", "location_end_date")
    except ValueError as e:
        return build_response(400, {"error": str(e)})

    try:
        orgs, states, countries = load_data()

        today = pd.Timestamp.now().normalize()
        result = {}
        for name in RANGES:
            if name == "Custom":
                result[name] = {
                    "growth_trend": {"total_organizations": [], "collaborators": []},
                    "organizations_by_location": [],
                }
                if growth_range:
                    result[name]["growth_trend"] = growth_trend(orgs, *growth_range, daily=True)
                if location_range:
                    result[name]["organizations_by_location"] = orgs_by_location(
                        orgs, states, countries, *location_range
                    )
            else:
                start, end = fixed_range(name, today)
                result[name] = {
                    "growth_trend": growth_trend(orgs, start, end, name in DAILY_RANGES),
                    "organizations_by_location": orgs_by_location(orgs, states, countries, start, end),
                }
        return build_response(200, result)

    except Exception as e:
        print(f"growth/location analytics failed: {e}")
        return build_response(500, {"error": "could not build growth and location analytics"})


def show(label, event):
    print(f"--- {label} ---")
    res = lambda_handler(event, None)
    print("status:", res["statusCode"])
    print(json.dumps(res["body"], indent=2))
    print()
    return res


def make_sample_dir(rows):
    # tiny throwaway dataset so recent dates and several countries can be tested
    tmp = tempfile.mkdtemp()
    orgs = pd.DataFrame(rows, columns=["org_id", "city_name", "state_id", "is_collaborator", "created_at"])
    orgs.to_csv(os.path.join(tmp, "organizations.csv"), index=False)
    pd.DataFrame({
        "state_id": ["TX", "FL", "MH", "ON", "BC", "NSW", "BAV"],
        "state_name": ["Texas", "Florida", "Maharashtra", "Ontario", "British Columbia", "New South Wales", "Bavaria"],
        "country_id": [1, 1, 2, 3, 3, 4, 5],
    }).to_csv(os.path.join(tmp, "states.csv"), index=False)
    pd.DataFrame({
        "country_id": [1, 2, 3, 4, 5],
        "country_code": ["USA", "IND", "CAN", "AUS", "DEU"],
    }).to_csv(os.path.join(tmp, "countries.csv"), index=False)
    return tmp


if __name__ == "__main__":
    real_dir = DATA_DIR

    print("===== against the mock csvs in the repo =====\n")
    everything = show("no body", {})
    show("growth range only", {"body": json.dumps({"start_date": "2026-05-01", "end_date": "2026-05-10"})})
    show("location range only", {"body": json.dumps({"location_start_date": "2026-01-01", "location_end_date": "2026-06-30"})})
    show("both ranges", {"body": json.dumps({
        "start_date": "2026-01-01", "end_date": "2026-01-15",
        "location_start_date": "2025-06-01", "location_end_date": "2025-12-31",
    })})
    show("bad date format", {"body": json.dumps({"start_date": "01/01/2026", "end_date": "2026-06-30"})})
    show("start after end", {"body": json.dumps({"location_start_date": "2026-06-30", "location_end_date": "2026-01-01"})})
    show("only one date of a pair", {"body": json.dumps({"start_date": "2026-01-01"})})

    print("===== sanity checks on the real mock data =====")
    orgs, _, _ = load_data()
    body = everything["body"]
    last_all = body["All"]["growth_trend"]["total_organizations"][-1]["count"]
    assert last_all == len(orgs), "last All total should equal the row count"
    assert sum(p["count"] for p in body["All"]["growth_trend"]["collaborators"]) == int(orgs["is_collaborator"].sum())
    totals = [p["count"] for p in body["All"]["growth_trend"]["total_organizations"]]
    assert totals == sorted(totals), "running total should never go down"
    assert all(len(p["period"]) == 7 for p in body["1Y"]["growth_trend"]["total_organizations"])
    assert all(len(p["period"]) == 10 for p in body["30D"]["growth_trend"]["total_organizations"])
    for name in RANGES:
        locs = body[name]["organizations_by_location"]
        assert len(locs) <= 4
        assert all(set(row) == {"country", "count"} for row in locs)
        assert set(body[name]) == {"growth_trend", "organizations_by_location"}
    assert list(body) == RANGES
    print("all checks passed\n")

    print("===== small hand-made dataset (recent dates, 5 countries) =====\n")
    today = pd.Timestamp.now().normalize()
    day = lambda n: (today - timedelta(days=n) + timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
    sample = [
        ["O1", "Austin", "TX", True, day(400)],
        ["O2", "Miami", "FL", False, day(200)],
        ["O3", "Pune", "MH", True, day(20)],
        ["O4", "Toronto", "ON", False, day(5)],
        ["O5", "Vancouver", "BC", True, day(5)],
        ["O6", "Sydney", "NSW", False, day(2)],
        ["O7", "Munich", "BAV", True, day(0)],
        ["O8", "Dallas", "TX", False, day(0)],
    ]
    DATA_DIR = make_sample_dir(sample)
    small = show("no body", {})
    sb = small["body"]
    assert len(sb["7D"]["organizations_by_location"]) == 4
    assert all(row["country"] != "Other" for row in sb["All"]["organizations_by_location"])
    assert sb["7D"]["growth_trend"]["total_organizations"][-1]["count"] == 8
    assert sb["Custom"]["growth_trend"]["total_organizations"] == []
    print("small dataset checks passed\n")
    shutil.rmtree(DATA_DIR)

    print("===== empty and single row files =====\n")
    DATA_DIR = make_sample_dir([])
    show("empty organizations.csv", {})
    shutil.rmtree(DATA_DIR)
    DATA_DIR = make_sample_dir([["O1", "Austin", "TX", True, day(1)]])
    show("one row", {})
    shutil.rmtree(DATA_DIR)
    DATA_DIR = real_dir
