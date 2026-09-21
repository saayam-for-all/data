"""Tests for growth_location_analytics.py.

Fixtures are written to a temp folder per test, so no CSVs live in the repo.
Run:  python -m pytest test_growth_location_analytics.py -v
"""

import csv
import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

import growth_location_analytics as gla

TODAY = pd.Timestamp("2026-06-15")
BUCKETS = ["7D", "30D", "1Y", "All", "Custom"]

STATES = [
    ("TX", "1", "Texas"), ("FL", "1", "Florida"), ("CA", "1", "California"),
    ("MH", "2", "Maharashtra"), ("ON", "3", "Ontario"), ("BY", "4", "Bavaria"),
    ("NSW", "5", "New South Wales"), ("QC", "3", "Quebec"),
]
COUNTRIES = [("1", "USA"), ("2", "IND"), ("3", "CAN"), ("4", "DEU"), ("5", "AUS")]


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def make_dir(tmp_path, orgs, states=STATES, countries=COUNTRIES):
    """orgs: list of (state_id, created_at, is_collaborator)."""
    rows = [(f"ORG{i:03d}", st, "City", flag, created) for i, (st, created, flag) in enumerate(orgs)]
    write_csv(tmp_path / "organizations.csv",
              ["org_id", "state_id", "city_name", "is_collaborator", "created_at"], rows)
    write_csv(tmp_path / "states.csv", ["state_id", "country_id", "state_name"],
              [(s, c, n) for s, c, n in states])
    write_csv(tmp_path / "countries.csv", ["country_id", "country_code"], countries)
    return tmp_path


def day(offset):
    """Timestamp string `offset` days before TODAY."""
    return (TODAY - timedelta(days=offset)).strftime("%Y-%m-%d 10:00:00")


@pytest.fixture
def call(tmp_path, monkeypatch):
    """call(orgs, body=None, **kw) -> (statusCode, parsed body)."""
    monkeypatch.setattr(gla, "_today", lambda: TODAY)

    def run(orgs, body=None, states=STATES, countries=COUNTRIES):
        make_dir(tmp_path, orgs, states, countries)
        monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
        event = {} if body is None else {"body": json.dumps(body)}
        reply = gla.lambda_handler(event, None)
        return reply["statusCode"], json.loads(reply["body"])

    return run


# a spread of organizations: some old, some inside every window
ORGS = [
    ("TX", "2024-03-10 09:00:00", "true"),
    ("FL", "2025-11-05 09:00:00", "false"),
    ("TX", "2025-12-20 09:00:00", "true"),
    ("MH", "2026-01-12 09:00:00", "true"),
    ("MH", "2026-01-25 09:00:00", "false"),
    ("CA", "2026-03-03 09:00:00", "false"),
    ("ON", "2026-05-20 09:00:00", "true"),
    ("BY", day(20), "true"),
    ("TX", day(3), "false"),
    ("FL", day(3), "true"),
    ("TX", day(0), "false"),
]


# --- response shape ------------------------------------------------------------------
def test_no_body_returns_exactly_the_five_buckets(call):
    status, body = call(ORGS)
    assert status == 200
    assert list(body) == BUCKETS
    for bucket in BUCKETS:
        assert set(body[bucket]) == {"growth_trend", "organizations_by_location"}
        assert set(body[bucket]["growth_trend"]) == {"total_organizations", "collaborators"}


def test_no_body_custom_is_empty_and_other_buckets_are_populated(call):
    _, body = call(ORGS)
    assert body["Custom"] == {"growth_trend": {"total_organizations": [], "collaborators": []},
                              "organizations_by_location": []}
    for bucket in ("7D", "30D", "1Y", "All"):
        assert body[bucket]["growth_trend"]["total_organizations"]
        assert body[bucket]["organizations_by_location"]


def test_bucket_without_activity_returns_empty_arrays(call):
    _, body = call([("TX", "2024-01-01 00:00:00", "true")])
    for bucket in ("7D", "30D", "1Y"):
        assert body[bucket] == {"growth_trend": {"total_organizations": [], "collaborators": []},
                                "organizations_by_location": []}
    assert body["All"]["growth_trend"]["total_organizations"] == [{"period": "2024-01", "count": 1}]


# --- Custom ranges are independent -----------------------------------------------------
def test_only_growth_range_populates_custom_growth_only(call):
    _, body = call(ORGS, {"start_date": "2026-01-01", "end_date": "2026-06-30"})
    assert body["Custom"]["growth_trend"]["total_organizations"]
    assert body["Custom"]["organizations_by_location"] == []


def test_only_location_range_populates_custom_location_only(call):
    _, body = call(ORGS, {"location_start_date": "2025-01-01", "location_end_date": "2026-06-30"})
    assert body["Custom"]["growth_trend"] == {"total_organizations": [], "collaborators": []}
    assert body["Custom"]["organizations_by_location"]


def test_both_ranges_apply_independently(call):
    _, body = call(ORGS, {"start_date": "2026-01-01", "end_date": "2026-01-31",
                          "location_start_date": "2025-11-01", "location_end_date": "2025-12-31"})
    growth = body["Custom"]["growth_trend"]
    assert [p["period"] for p in growth["total_organizations"]] == ["2026-01-12", "2026-01-25"]
    # location window (Nov-Dec 2025) has TX + FL orgs only -> one USA row of 2
    assert body["Custom"]["organizations_by_location"] == [{"country": "USA", "count": 2}]


def test_ranges_do_not_change_the_fixed_buckets(call):
    _, plain = call(ORGS)
    _, ranged = call(ORGS, {"start_date": "2026-01-01", "end_date": "2026-01-31",
                            "location_start_date": "2025-11-01", "location_end_date": "2025-12-31"})
    for bucket in ("7D", "30D", "1Y", "All"):
        assert plain[bucket] == ranged[bucket]


# --- validation -------------------------------------------------------------------------
@pytest.mark.parametrize("params", [
    {"start_date": "01/01/2026", "end_date": "2026-06-30"},
    {"start_date": "2026-01-01", "end_date": "June 30"},
    {"start_date": "2026-1-1", "end_date": "2026-06-30"},
    {"start_date": "2026-02-30", "end_date": "2026-06-30"},
    {"start_date": 20260101, "end_date": "2026-06-30"},
    {"start_date": "2026-06-30", "end_date": "2026-01-01"},
    {"location_start_date": "nope", "location_end_date": "2026-01-01"},
    {"location_start_date": "2026-06-30", "location_end_date": "2026-01-01"},
    {"start_date": "2026-01-01"},
    {"location_end_date": "2026-01-01"},
    {"start_date": "0001-01-01", "end_date": "2026-01-01"},
])
def test_invalid_dates_return_400_with_error_message(call, params):
    status, body = call(ORGS, params)
    assert status == 400
    assert list(body) == ["error"] and body["error"]


@pytest.mark.parametrize("params, message", [
    ({"start_date": "2026-01-01"}, "start_date and end_date must be provided together"),
    ({"end_date": "2026-01-01"}, "start_date and end_date must be provided together"),
    ({"location_start_date": "2026-01-01"}, "location_start_date and location_end_date must be provided together"),
])
def test_half_supplied_pair_is_rejected_with_a_clear_message(call, params, message):
    status, body = call(ORGS, params)
    assert status == 400 and body["error"] == message


def test_one_bad_pair_fails_even_when_the_other_is_valid(call):
    status, body = call(ORGS, {"start_date": "2026-01-01", "end_date": "2026-06-30",
                               "location_start_date": "2026-06-30", "location_end_date": "2026-01-01"})
    assert status == 400 and "location_start_date" in body["error"]


def test_blank_values_count_as_not_supplied(call):
    status, body = call(ORGS, {"start_date": "", "end_date": None,
                               "location_start_date": "", "location_end_date": ""})
    assert status == 200 and body["Custom"]["organizations_by_location"] == []


def test_body_can_be_dict_json_string_or_the_event_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(gla, "_today", lambda: TODAY)
    make_dir(tmp_path, ORGS)
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    params = {"start_date": "2026-01-01", "end_date": "2026-06-30"}
    replies = [gla.lambda_handler({"body": params}, None),
               gla.lambda_handler({"body": json.dumps(params)}, None),
               gla.lambda_handler(dict(params), None)]
    bodies = [json.loads(r["body"]) for r in replies]
    assert all(r["statusCode"] == 200 for r in replies)
    assert bodies[0] == bodies[1] == bodies[2]
    assert bodies[0]["Custom"]["growth_trend"]["total_organizations"]


def test_malformed_json_body_returns_400(call, tmp_path, monkeypatch):
    make_dir(tmp_path, ORGS)
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    reply = gla.lambda_handler({"body": "{not json"}, None)
    assert reply["statusCode"] == 400


# --- growth trend semantics --------------------------------------------------------------
def test_total_organizations_is_all_time_and_never_reset_per_window(call):
    _, body = call(ORGS)
    # 7D window holds only the org created today; the all-time total still counts everyone
    total_7d = body["7D"]["growth_trend"]["total_organizations"]
    assert total_7d[-1] == {"period": TODAY.strftime("%Y-%m-%d"), "count": len(ORGS)}
    # first 1Y period (2025-11) includes the 2024 org that pre-dates the window
    first = body["1Y"]["growth_trend"]["total_organizations"][0]
    assert first == {"period": "2025-11", "count": 2}


def test_all_bucket_last_total_equals_row_count(call):
    _, body = call(ORGS)
    assert body["All"]["growth_trend"]["total_organizations"][-1]["count"] == len(ORGS)


def test_total_organizations_is_non_decreasing_running_total(call):
    _, body = call(ORGS)
    for bucket in ("7D", "30D", "1Y", "All"):
        counts = [p["count"] for p in body[bucket]["growth_trend"]["total_organizations"]]
        assert counts == sorted(counts)


def test_collaborators_are_per_period_not_cumulative(call):
    _, body = call(ORGS)
    collab = {p["period"]: p["count"] for p in body["All"]["growth_trend"]["collaborators"]}
    assert collab["2026-01"] == 1       # one of the two January orgs is a collaborator
    assert collab["2025-11"] == 0       # period exists, no collaborators created in it
    assert collab["2026-03"] == 0


def test_collaborators_are_scoped_to_the_bucket_window(call):
    _, body = call(ORGS)
    # 30D holds the 2026-05-20 org, day(20), day(3) x2 and day(0); three of those are collaborators
    assert sum(p["count"] for p in body["30D"]["growth_trend"]["collaborators"]) == 3
    assert sum(p["count"] for p in body["All"]["growth_trend"]["collaborators"]) == 6


def test_both_series_share_the_same_periods(call):
    _, body = call(ORGS, {"start_date": "2025-01-01", "end_date": "2026-06-30"})
    for bucket in BUCKETS:
        trend = body[bucket]["growth_trend"]
        assert [p["period"] for p in trend["total_organizations"]] == \
               [p["period"] for p in trend["collaborators"]]


def test_periods_are_sparse_not_zero_filled(call):
    _, body = call(ORGS)
    periods = [p["period"] for p in body["1Y"]["growth_trend"]["total_organizations"]]
    assert "2026-02" not in periods and "2026-04" not in periods   # months with no new orgs
    assert periods == sorted(periods)


def test_day_buckets_for_7d_30d_custom_and_month_buckets_for_1y_all(call):
    _, body = call(ORGS, {"start_date": "2026-01-01", "end_date": "2026-01-31"})
    day_fmt, month_fmt = "%Y-%m-%d", "%Y-%m"
    for bucket, fmt in (("7D", day_fmt), ("30D", day_fmt), ("Custom", day_fmt),
                        ("1Y", month_fmt), ("All", month_fmt)):
        for point in body[bucket]["growth_trend"]["total_organizations"]:
            assert datetime.strptime(point["period"], fmt).strftime(fmt) == point["period"]


def test_window_boundaries_are_inclusive_calendar_days(call):
    orgs = [("TX", day(7), "true"), ("TX", day(8), "true"), ("TX", day(30), "false"), ("TX", day(31), "false")]
    _, body = call(orgs)
    assert [p["period"] for p in body["7D"]["growth_trend"]["total_organizations"]] == [day(7)[:10]]
    assert [p["period"] for p in body["30D"]["growth_trend"]["total_organizations"]] == \
           [day(30)[:10], day(8)[:10], day(7)[:10]]


def test_1y_is_the_trailing_12_calendar_months(call):
    # TODAY is 2026-06-15, so the window is whole months: July 2025 .. June 2026
    orgs = [("TX", "2025-06-20 09:00:00", "false"),   # same day-of-month a year ago: outside
            ("TX", "2025-06-30 23:00:00", "false"),   # last day before the window
            ("TX", "2025-07-01 00:00:00", "true")]    # first day of the window
    _, body = call(orgs)
    trend = body["1Y"]["growth_trend"]
    assert trend["total_organizations"] == [{"period": "2025-07", "count": 3}]   # all-time running total
    assert trend["collaborators"] == [{"period": "2025-07", "count": 1}]
    assert body["1Y"]["organizations_by_location"] == [{"country": "USA", "count": 1}]


def test_1y_never_has_more_than_12_monthly_periods(call):
    months = [(y, m) for y in (2024, 2025) for m in range(1, 13)] + [(2026, m) for m in range(1, 7)]
    _, body = call([("TX", f"{y}-{m:02d}-10 09:00:00", "false") for y, m in months])
    periods = [p["period"] for p in body["1Y"]["growth_trend"]["total_organizations"]]
    assert periods == [f"2025-{m:02d}" for m in range(7, 13)] + [f"2026-{m:02d}" for m in range(1, 7)]
    assert len(body["All"]["growth_trend"]["total_organizations"]) == len(months)


@pytest.mark.parametrize("today, start_1y", [
    ("2026-06-15", "2025-07-01"),
    ("2026-01-05", "2025-02-01"),     # window crosses a year boundary
    ("2026-12-31", "2026-01-01"),     # December: the window is exactly the calendar year
    ("2024-02-29", "2023-03-01"),     # leap day
])
def test_window_starts(today, start_1y):
    today = pd.Timestamp(today)
    assert gla.window_start("1Y", today) == pd.Timestamp(start_1y)
    assert gla.window_start("7D", today) == today - pd.Timedelta(days=7)
    assert gla.window_start("30D", today) == today - pd.Timedelta(days=30)
    assert gla.window_start("All", today) is None


def test_organizations_created_after_today_are_ignored_by_dated_windows(call):
    orgs = [("TX", day(1), "true"), ("TX", "2026-07-01 00:00:00", "true")]   # second is in the future
    _, body = call(orgs)
    assert body["30D"]["growth_trend"]["total_organizations"] == [{"period": day(1)[:10], "count": 1}]
    assert body["1Y"]["growth_trend"]["total_organizations"] == [{"period": "2026-06", "count": 1}]


def test_custom_growth_counts_are_all_time_totals_by_day(call):
    _, body = call(ORGS, {"start_date": "2026-01-01", "end_date": "2026-03-31"})
    assert body["Custom"]["growth_trend"]["total_organizations"] == [
        {"period": "2026-01-12", "count": 4},
        {"period": "2026-01-25", "count": 5},
        {"period": "2026-03-03", "count": 6},
    ]
    assert body["Custom"]["growth_trend"]["collaborators"] == [
        {"period": "2026-01-12", "count": 1},
        {"period": "2026-01-25", "count": 0},
        {"period": "2026-03-03", "count": 0},
    ]


# --- location semantics ---------------------------------------------------------------------
def test_locations_roll_states_up_into_countries(call):
    orgs = [("TX", day(1), "false"), ("FL", day(2), "false"), ("CA", day(3), "false"), ("MH", day(4), "false")]
    _, body = call(orgs)
    assert body["30D"]["organizations_by_location"] == [{"country": "USA", "count": 3},
                                                        {"country": "IND", "count": 1}]


def test_locations_are_capped_at_top_4_with_no_other_or_percentage(call):
    orgs = ([("TX", day(i), "false") for i in range(1, 6)] + [("MH", day(1), "false")] * 4 +
            [("ON", day(1), "false")] * 3 + [("BY", day(1), "false")] * 2 + [("NSW", day(1), "false")])
    _, body = call(orgs)
    rows = body["30D"]["organizations_by_location"]
    assert rows == [{"country": "USA", "count": 5}, {"country": "IND", "count": 4},
                    {"country": "CAN", "count": 3}, {"country": "DEU", "count": 2}]
    assert all(set(r) == {"country", "count"} for r in rows)
    assert "Other" not in json.dumps(body)


def test_fewer_than_four_countries_returns_all_of_them(call):
    _, body = call([("TX", day(1), "false"), ("MH", day(1), "false")])
    assert len(body["30D"]["organizations_by_location"]) == 2


def test_location_ties_are_ordered_by_country_code(call):
    _, body = call([("MH", day(1), "false"), ("BY", day(1), "false"), ("ON", day(1), "false")])
    assert [r["country"] for r in body["30D"]["organizations_by_location"]] == ["CAN", "DEU", "IND"]


def test_single_country_states_give_exactly_one_row(call):
    one_country = [(s, "1", n) for s, _, n in STATES]
    orgs = [("TX", day(1), "false"), ("FL", day(1), "false"), ("CA", day(2), "false"), ("QC", day(2), "false")]
    _, body = call(orgs, states=one_country, countries=[("1", "USA")])
    for bucket in ("30D", "1Y", "All"):
        assert body[bucket]["organizations_by_location"] == [{"country": "USA", "count": 4}]


def test_location_counts_are_window_scoped(call):
    _, body = call(ORGS)
    location_total = {b: sum(r["count"] for r in body[b]["organizations_by_location"])
                      for b in ("7D", "30D", "1Y", "All")}
    assert location_total == {"7D": 3, "30D": 5, "1Y": 10, "All": len(ORGS)}


def test_orgs_without_a_known_country_count_in_growth_but_not_in_locations(call):
    orgs = [("TX", day(1), "false"), (None, day(1), "false"), ("ZZ", day(1), "false")]
    _, body = call(orgs)
    assert body["30D"]["growth_trend"]["total_organizations"] == [{"period": day(1)[:10], "count": 3}]
    assert body["30D"]["organizations_by_location"] == [{"country": "USA", "count": 1}]


def test_duplicate_state_or_country_rows_do_not_duplicate_organizations(call):
    states = STATES + [("TX", "1", "Texas")]
    countries = COUNTRIES + [("1", "USA")]
    _, body = call([("TX", day(1), "false")], states=states, countries=countries)
    assert body["All"]["growth_trend"]["total_organizations"][-1]["count"] == 1
    assert body["All"]["organizations_by_location"] == [{"country": "USA", "count": 1}]


# --- empty / tiny / messy inputs ----------------------------------------------------------------
def test_header_only_organizations_file_does_not_crash(call):
    status, body = call([])
    assert status == 200 and list(body) == BUCKETS
    assert all(body[b]["growth_trend"]["total_organizations"] == [] for b in BUCKETS)
    assert all(body[b]["organizations_by_location"] == [] for b in BUCKETS)


def test_zero_byte_organizations_file_does_not_crash(call, tmp_path, monkeypatch):
    make_dir(tmp_path, ORGS)
    (tmp_path / "organizations.csv").write_text("")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(gla, "_today", lambda: TODAY)
    reply = gla.lambda_handler({}, None)
    assert reply["statusCode"] == 200
    assert json.loads(reply["body"])["All"]["growth_trend"]["total_organizations"] == []


def test_single_row_organizations_file(call):
    status, body = call([("TX", day(1), "true")],
                        {"start_date": day(5)[:10], "end_date": day(0)[:10],
                         "location_start_date": day(5)[:10], "location_end_date": day(0)[:10]})
    assert status == 200
    only = [{"period": day(1)[:10], "count": 1}]
    assert body["7D"]["growth_trend"]["total_organizations"] == only
    assert body["7D"]["growth_trend"]["collaborators"] == only
    assert body["1Y"]["growth_trend"]["total_organizations"] == [{"period": "2026-06", "count": 1}]
    assert body["Custom"]["organizations_by_location"] == [{"country": "USA", "count": 1}]


def test_rows_with_missing_or_bad_created_at_are_skipped(call):
    orgs = [("TX", day(1), "true"), ("TX", "", "true"), ("TX", "not a date", "true")]
    _, body = call(orgs)
    assert body["All"]["growth_trend"]["total_organizations"][-1]["count"] == 1
    assert body["All"]["organizations_by_location"] == [{"country": "USA", "count": 1}]


def test_mixed_timestamp_formats_and_boolean_spellings(call):
    orgs = [("TX", "2026-06-10", "True"), ("TX", "2026-06-11 08:30:00", "t"),
            ("TX", "2026-06-12T09:00:00Z", "1"), ("TX", "2026-06-13 09:00:00.123456", "no")]
    _, body = call(orgs)
    assert [p["count"] for p in body["30D"]["growth_trend"]["collaborators"]] == [1, 1, 1, 0]


def test_missing_data_file_returns_500_without_leaking_details(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))     # empty folder
    reply = gla.lambda_handler({}, None)
    assert reply["statusCode"] == 500
    assert json.loads(reply["body"]) == {"error": "Internal server error"}


def test_responses_carry_json_and_cors_headers(call, tmp_path, monkeypatch):
    make_dir(tmp_path, ORGS)
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    reply = gla.lambda_handler({}, None)
    assert reply["headers"]["Content-Type"] == "application/json"
    assert reply["headers"]["Access-Control-Allow-Origin"] == "*"
