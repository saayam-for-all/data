"""Tests for the Growth & Location Analytics API (issue #336).

These run entirely offline: the handler reads CSVs rather than a database, so
there is nothing to mock out. Tests that touch a time window must use the
`frozen_today` fixture - the fixed buckets are relative to the current date, so
without it the suite would start failing on its own as real time passes.

Synthetic fixtures cover the multi-country cases. The tracked seed data contains
exactly one distinct country, so top-N, tie-break and window-scoping behaviour
cannot be exercised against it.

Run with:
    python -m pytest data-analytics/tests -q
"""
import json
import re
from datetime import date, timedelta

import pandas as pd
import pytest

import growth_location_analytics as growth_module


FROZEN_TODAY = date(2026, 9, 22)

DAY_LABEL = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_LABEL = re.compile(r"^\d{4}-\d{2}$")

# Row counts and boundary values taken from the tracked data-analytics/sql CSVs.
REAL_ORG_COUNT = 40
REAL_ALL_PERIOD_COUNT = 20


@pytest.fixture
def mod():
    return growth_module


@pytest.fixture
def frozen_today(monkeypatch):
    """Pin 'today' so window-relative buckets stay deterministic."""
    monkeypatch.setattr(growth_module, "_today", lambda: FROZEN_TODAY)
    return FROZEN_TODAY


@pytest.fixture
def real_data(monkeypatch):
    """Use the tracked data-analytics/sql CSVs."""
    monkeypatch.delenv("MOCK_DATA_DIR", raising=False)


@pytest.fixture
def write_csvs(tmp_path, monkeypatch):
    """Write synthetic CSVs into a temp dir and point MOCK_DATA_DIR at it."""

    def _write(organizations, states=None, countries=None, state_name="state.csv",
               country_name="country.csv", write_lookup=True):
        pd.DataFrame(organizations).to_csv(tmp_path / "organizations.csv", index=False)

        if write_lookup:
            if states is None:
                states = [{"state_id": "TX", "country_id": 1, "state_name": "Texas"}]
            if countries is None:
                countries = [{"country_id": 1, "country_code": "USA"}]
            pd.DataFrame(states).to_csv(tmp_path / state_name, index=False)
            pd.DataFrame(countries).to_csv(tmp_path / country_name, index=False)

        monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
        return tmp_path

    return _write


def org(org_id, created_at, is_collaborator=False, state_id="TX"):
    """One organizations.csv row."""
    return {
        "org_id": org_id,
        "created_at": created_at,
        "is_collaborator": is_collaborator,
        "state_id": state_id,
    }


def call(mod, event=None, expected_status=200):
    """Invoke the handler and return the parsed body."""
    response = mod.lambda_handler(event, None)
    assert response["statusCode"] == expected_status, response["body"]
    return json.loads(response["body"])


# --------------------------------------------------------------------------
# Response contract
# --------------------------------------------------------------------------


def test_response_has_exactly_five_buckets(mod, real_data, frozen_today):
    body = call(mod, {})
    assert set(body) == {"7D", "30D", "1Y", "All", "Custom"}


def test_each_bucket_has_exactly_two_keys(mod, real_data, frozen_today):
    body = call(mod, {})
    for bucket, payload in body.items():
        assert set(payload) == {"growth_trend", "organizations_by_location"}, bucket


def test_growth_trend_has_exactly_two_series(mod, real_data, frozen_today):
    body = call(mod, {})
    for bucket, payload in body.items():
        assert set(payload["growth_trend"]) == {"total_organizations", "collaborators"}, bucket


def test_series_entries_have_only_period_and_count(mod, real_data, frozen_today):
    body = call(mod, {})
    for payload in body.values():
        for series in payload["growth_trend"].values():
            for entry in series:
                assert set(entry) == {"period", "count"}
                assert isinstance(entry["period"], str)
                assert isinstance(entry["count"], int)


def test_location_entries_have_no_other_row_or_percentage(mod, real_data, frozen_today):
    body = call(mod, {})
    for payload in body.values():
        for entry in payload["organizations_by_location"]:
            assert set(entry) == {"country", "count"}
            assert entry["country"] != "Other"
            assert "percentage" not in entry


def test_body_is_a_json_string(mod, real_data, frozen_today):
    response = mod.lambda_handler({}, None)
    assert response["statusCode"] == 200
    assert isinstance(response["body"], str)
    assert isinstance(json.loads(response["body"]), dict)


# --------------------------------------------------------------------------
# Bucketing granularity
# --------------------------------------------------------------------------


def test_seven_and_thirty_day_periods_are_day_labels(mod, write_csvs, frozen_today):
    write_csvs([org("A", f"{FROZEN_TODAY - timedelta(days=2)} 10:00:00")])
    body = call(mod, {})
    for bucket in ("7D", "30D"):
        periods = [e["period"] for e in body[bucket]["growth_trend"]["total_organizations"]]
        assert periods and all(DAY_LABEL.match(p) for p in periods), bucket


def test_one_year_and_all_periods_are_month_labels(mod, real_data, frozen_today):
    body = call(mod, {})
    for bucket in ("1Y", "All"):
        periods = [e["period"] for e in body[bucket]["growth_trend"]["total_organizations"]]
        assert periods and all(MONTH_LABEL.match(p) for p in periods), bucket


def test_custom_periods_are_day_labels(mod, real_data, frozen_today):
    body = call(mod, {"start_date": "2025-01-01", "end_date": "2025-12-31"})
    periods = [e["period"] for e in body["Custom"]["growth_trend"]["total_organizations"]]
    assert periods and all(DAY_LABEL.match(p) for p in periods)


# --------------------------------------------------------------------------
# Cumulative semantics - the core of the issue
# --------------------------------------------------------------------------


def test_total_organizations_is_all_time_cumulative_not_window_reset(mod, write_csvs, frozen_today):
    """Three orgs predate the 1Y window; the first in-window period must start at 4, not 1."""
    write_csvs(
        [
            org("OLD1", "2020-01-05 10:00:00"),
            org("OLD2", "2020-02-05 10:00:00"),
            org("OLD3", "2020-03-05 10:00:00"),
            org("NEW1", f"{FROZEN_TODAY - timedelta(days=60)} 10:00:00"),
            org("NEW2", f"{FROZEN_TODAY - timedelta(days=30)} 10:00:00"),
        ]
    )
    totals = call(mod, {})["1Y"]["growth_trend"]["total_organizations"]
    assert totals[0]["count"] == 4
    assert totals[-1]["count"] == 5


def test_total_organizations_is_monotonically_non_decreasing(mod, real_data, frozen_today):
    body = call(mod, {"start_date": "2024-01-01", "end_date": "2026-01-31"})
    for bucket, payload in body.items():
        counts = [e["count"] for e in payload["growth_trend"]["total_organizations"]]
        assert all(a <= b for a, b in zip(counts, counts[1:])), bucket


def test_all_bucket_final_total_equals_dataset_row_count(mod, real_data, frozen_today):
    totals = call(mod, {})["All"]["growth_trend"]["total_organizations"]
    assert totals[-1]["count"] == REAL_ORG_COUNT


def test_one_year_first_period_matches_known_cumulative(mod, real_data, frozen_today):
    """32 organizations existed by end of 2025-09, though only 9 fall inside the 1Y window."""
    totals = call(mod, {})["1Y"]["growth_trend"]["total_organizations"]
    assert totals[0] == {"period": "2025-09", "count": 32}
    assert totals[-1] == {"period": "2026-01", "count": REAL_ORG_COUNT}


def test_collaborators_are_per_period_not_cumulative(mod, real_data, frozen_today):
    counts = [e["count"] for e in call(mod, {})["All"]["growth_trend"]["collaborators"]]
    assert not all(a <= b for a, b in zip(counts, counts[1:]))


def test_collaborators_are_window_scoped(mod, write_csvs, frozen_today):
    """A pre-window collaborator lifts the running total but appears in no collaborator period."""
    write_csvs(
        [
            org("OLD", "2020-01-05 10:00:00", is_collaborator=True),
            org("NEW", f"{FROZEN_TODAY - timedelta(days=10)} 10:00:00", is_collaborator=True),
        ]
    )
    trend = call(mod, {})["1Y"]["growth_trend"]
    assert trend["total_organizations"][0]["count"] == 2
    assert sum(e["count"] for e in trend["collaborators"]) == 1


def test_both_series_share_the_same_period_list(mod, real_data, frozen_today):
    body = call(mod, {"start_date": "2024-01-01", "end_date": "2026-01-31"})
    for bucket, payload in body.items():
        trend = payload["growth_trend"]
        assert [e["period"] for e in trend["total_organizations"]] == [
            e["period"] for e in trend["collaborators"]
        ], bucket


def test_period_with_orgs_but_no_collaborators_reports_zero(mod, real_data, frozen_today):
    """2026-01 has an organization but no collaborator, so it stays in the series at 0."""
    collaborators = call(mod, {})["1Y"]["growth_trend"]["collaborators"]
    assert {"period": "2026-01", "count": 0} in collaborators


def test_periods_are_sorted_ascending(mod, real_data, frozen_today):
    body = call(mod, {"start_date": "2024-01-01", "end_date": "2026-01-31"})
    for bucket, payload in body.items():
        for name, series in payload["growth_trend"].items():
            periods = [e["period"] for e in series]
            assert periods == sorted(periods), f"{bucket}.{name}"


def test_inactive_periods_are_omitted_no_zero_filling(mod, write_csvs, frozen_today):
    """A three-month gap produces no entries for the quiet months."""
    write_csvs([org("A", "2025-01-10 10:00:00"), org("B", "2025-05-10 10:00:00")])
    periods = [
        e["period"]
        for e in call(mod, {})["All"]["growth_trend"]["total_organizations"]
    ]
    assert periods == ["2025-01", "2025-05"]


def test_real_all_bucket_is_sparse(mod, real_data, frozen_today):
    """2023-09..2026-01 spans 29 calendar months but only 20 had activity."""
    periods = [e["period"] for e in call(mod, {})["All"]["growth_trend"]["total_organizations"]]
    assert len(periods) == REAL_ALL_PERIOD_COUNT
    assert periods[0] == "2023-09"
    assert periods[-1] == "2026-01"


def test_all_false_collaborator_dataset_yields_all_zero_counts(mod, write_csvs, frozen_today):
    write_csvs([org("A", "2025-01-10 10:00:00"), org("B", "2025-02-10 10:00:00")])
    trend = call(mod, {})["All"]["growth_trend"]
    assert [e["count"] for e in trend["total_organizations"]] == [1, 2]
    assert all(e["count"] == 0 for e in trend["collaborators"])


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------


def test_seven_and_thirty_day_buckets_are_empty_for_stale_dataset(mod, real_data, frozen_today):
    """Newest seed organization is 2026-01-10, so both rolling buckets are legitimately empty."""
    body = call(mod, {})
    for bucket in ("7D", "30D"):
        assert body[bucket]["growth_trend"]["total_organizations"] == []
        assert body[bucket]["growth_trend"]["collaborators"] == []
        assert body[bucket]["organizations_by_location"] == []


def test_seven_day_window_boundaries(mod, write_csvs, frozen_today):
    write_csvs(
        [
            org("IN", f"{FROZEN_TODAY - timedelta(days=7)} 23:30:00"),
            org("OUT", f"{FROZEN_TODAY - timedelta(days=8)} 23:30:00"),
        ]
    )
    periods = [e["period"] for e in call(mod, {})["7D"]["growth_trend"]["total_organizations"]]
    assert periods == [str(FROZEN_TODAY - timedelta(days=7))]


def test_one_year_window_boundaries(mod, write_csvs, frozen_today):
    write_csvs(
        [
            org("IN", f"{FROZEN_TODAY - timedelta(days=365)} 10:00:00"),
            org("OUT", f"{FROZEN_TODAY - timedelta(days=366)} 10:00:00"),
        ]
    )
    totals = call(mod, {})["1Y"]["growth_trend"]["total_organizations"]
    assert len(totals) == 1
    # The out-of-window row still counts toward the all-time running total.
    assert totals[0]["count"] == 2


def test_all_bucket_has_no_lower_bound(mod, real_data, frozen_today):
    periods = [e["period"] for e in call(mod, {})["All"]["growth_trend"]["total_organizations"]]
    assert "2023-09" in periods


# --------------------------------------------------------------------------
# Custom bucket
# --------------------------------------------------------------------------


def test_custom_is_empty_when_no_dates_supplied(mod, real_data, frozen_today):
    custom = call(mod, {})["Custom"]
    assert custom["growth_trend"] == {"total_organizations": [], "collaborators": []}
    assert custom["organizations_by_location"] == []


def test_custom_growth_range_leaves_locations_empty(mod, real_data, frozen_today):
    custom = call(mod, {"start_date": "2025-01-01", "end_date": "2025-12-31"})["Custom"]
    assert custom["growth_trend"]["total_organizations"]
    assert custom["organizations_by_location"] == []


def test_custom_location_range_leaves_growth_empty(mod, real_data, frozen_today):
    custom = call(
        mod, {"location_start_date": "2024-01-01", "location_end_date": "2024-12-31"}
    )["Custom"]
    assert custom["growth_trend"]["total_organizations"] == []
    assert custom["organizations_by_location"] == [{"country": "AFG", "count": 15}]


def test_custom_pairs_are_independent(mod, real_data, frozen_today):
    custom = call(
        mod,
        {
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "location_start_date": "2024-01-01",
            "location_end_date": "2024-12-31",
        },
    )["Custom"]
    periods = [e["period"] for e in custom["growth_trend"]["total_organizations"]]
    assert all(p.startswith("2025-") for p in periods)
    # The location half is scoped to 2024, independently of the 2025 growth range.
    assert custom["organizations_by_location"] == [{"country": "AFG", "count": 15}]


def test_custom_range_is_inclusive_of_both_endpoints(mod, write_csvs, frozen_today):
    """Rows carry a clock time, so the end bound must cover the whole end day."""
    write_csvs(
        [
            org("START", "2025-03-01 08:15:00"),
            org("MIDDLE", "2025-03-15 12:00:00"),
            org("END", "2025-03-31 23:45:00"),
            org("AFTER", "2025-04-01 00:30:00"),
        ]
    )
    body = call(mod, {"start_date": "2025-03-01", "end_date": "2025-03-31"})
    periods = [e["period"] for e in body["Custom"]["growth_trend"]["total_organizations"]]
    assert periods == ["2025-03-01", "2025-03-15", "2025-03-31"]


def test_custom_total_organizations_is_still_all_time_cumulative(mod, real_data, frozen_today):
    totals = call(mod, {"start_date": "2025-01-01", "end_date": "2025-12-31"})["Custom"][
        "growth_trend"
    ]["total_organizations"]
    assert totals[0] == {"period": "2025-01-05", "count": 21}
    assert totals[-1] == {"period": "2025-12-19", "count": 39}
    assert len(totals) == 18


def test_start_date_without_end_date_is_open_ended(mod, write_csvs, frozen_today):
    write_csvs([org("OLD", "2024-01-10 10:00:00"), org("NEW", "2025-06-10 10:00:00")])
    periods = [
        e["period"]
        for e in call(mod, {"start_date": "2025-01-01"})["Custom"]["growth_trend"][
            "total_organizations"
        ]
    ]
    assert periods == ["2025-06-10"]


def test_end_date_without_start_date_is_open_ended(mod, write_csvs, frozen_today):
    write_csvs([org("OLD", "2024-01-10 10:00:00"), org("NEW", "2025-06-10 10:00:00")])
    periods = [
        e["period"]
        for e in call(mod, {"end_date": "2024-12-31"})["Custom"]["growth_trend"][
            "total_organizations"
        ]
    ]
    assert periods == ["2024-01-10"]


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event, field",
    [
        ({"start_date": "2025-13-45", "end_date": "2025-12-31"}, "start_date"),
        ({"start_date": "2025-01-01", "end_date": "not-a-date"}, "end_date"),
        ({"location_start_date": "01-01-2025"}, "location_start_date"),
        ({"location_end_date": "2025/12/31"}, "location_end_date"),
        ({"start_date": 20250101}, "start_date"),
    ],
)
def test_invalid_date_formats_return_400(mod, real_data, event, field):
    body = call(mod, event, expected_status=400)
    assert set(body) == {"error"}
    assert field in body["error"]


def test_start_date_after_end_date_returns_400(mod, real_data):
    body = call(mod, {"start_date": "2025-12-31", "end_date": "2025-01-01"}, expected_status=400)
    assert "start_date" in body["error"]


def test_location_start_after_location_end_returns_400(mod, real_data):
    body = call(
        mod,
        {"location_start_date": "2025-12-31", "location_end_date": "2025-01-01"},
        expected_status=400,
    )
    assert "location_start_date" in body["error"]


def test_valid_growth_pair_with_invalid_location_pair_returns_400(mod, real_data):
    """Each pair is validated on its own, not only when the first pair was supplied."""
    body = call(
        mod,
        {
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "location_start_date": "2025-12-31",
            "location_end_date": "2025-01-01",
        },
        expected_status=400,
    )
    assert "location_start_date" in body["error"]


def test_blank_date_strings_are_treated_as_absent(mod, real_data, frozen_today):
    custom = call(mod, {"start_date": "", "end_date": "  "})["Custom"]
    assert custom["growth_trend"]["total_organizations"] == []


# --------------------------------------------------------------------------
# Event shapes
# --------------------------------------------------------------------------


def test_accepts_json_string_body(mod, real_data, frozen_today):
    body = call(mod, {"body": json.dumps({"start_date": "2025-01-01", "end_date": "2025-12-31"})})
    assert body["Custom"]["growth_trend"]["total_organizations"]


def test_accepts_dict_body(mod, real_data, frozen_today):
    body = call(mod, {"body": {"start_date": "2025-01-01", "end_date": "2025-12-31"}})
    assert body["Custom"]["growth_trend"]["total_organizations"]


def test_accepts_top_level_params_without_body_key(mod, real_data, frozen_today):
    body = call(mod, {"start_date": "2025-01-01", "end_date": "2025-12-31"})
    assert body["Custom"]["growth_trend"]["total_organizations"]


@pytest.mark.parametrize("event", [{}, None, {"body": "not json"}, {"body": "[1, 2]"}])
def test_degenerate_events_return_200_with_empty_custom(mod, real_data, frozen_today, event):
    body = call(mod, event)
    assert set(body) == {"7D", "30D", "1Y", "All", "Custom"}
    assert body["Custom"]["growth_trend"]["total_organizations"] == []


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------


def test_default_data_dir_is_tracked_sql_folder(mod, real_data):
    data_dir = mod.get_mock_data_dir()
    assert data_dir.name == "sql"
    assert (data_dir / "organizations.csv").is_file()


def test_mock_data_dir_env_var_overrides_default(mod, write_csvs, frozen_today):
    tmp_dir = write_csvs([org("A", "2025-01-10 10:00:00")])
    assert mod.get_mock_data_dir() == tmp_dir
    assert call(mod, {})["All"]["growth_trend"]["total_organizations"] == [
        {"period": "2025-01", "count": 1}
    ]


@pytest.mark.parametrize(
    "state_name, country_name",
    [("state.csv", "country.csv"), ("states.csv", "countries.csv")],
)
def test_resolves_both_filename_spellings(mod, write_csvs, frozen_today, state_name, country_name):
    write_csvs(
        [org("A", "2025-01-10 10:00:00", state_id="TX")],
        state_name=state_name,
        country_name=country_name,
    )
    assert call(mod, {})["All"]["organizations_by_location"] == [{"country": "USA", "count": 1}]


def test_missing_organizations_csv_returns_500(mod, monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    body = call(mod, {}, expected_status=500)
    assert "error" in body


def test_missing_lookup_csvs_degrade_to_unknown(mod, write_csvs, frozen_today):
    """Growth data must survive a missing location lookup."""
    write_csvs([org("A", "2025-01-10 10:00:00")], write_lookup=False)
    body = call(mod, {})
    assert body["All"]["growth_trend"]["total_organizations"] == [{"period": "2025-01", "count": 1}]
    assert body["All"]["organizations_by_location"] == [{"country": "Unknown", "count": 1}]


def test_empty_organizations_csv_returns_empty_buckets(mod, write_csvs, frozen_today):
    write_csvs(pd.DataFrame(columns=["org_id", "created_at", "is_collaborator", "state_id"]))
    body = call(mod, {"start_date": "2020-01-01", "end_date": "2030-01-01"})
    assert set(body) == {"7D", "30D", "1Y", "All", "Custom"}
    for payload in body.values():
        assert payload["growth_trend"] == {"total_organizations": [], "collaborators": []}
        assert payload["organizations_by_location"] == []


def test_single_row_dataset(mod, write_csvs, frozen_today):
    write_csvs([org("ONLY", "2025-01-10 10:00:00", is_collaborator=True)])
    body = call(mod, {})
    assert body["All"]["growth_trend"]["total_organizations"] == [{"period": "2025-01", "count": 1}]
    assert body["All"]["growth_trend"]["collaborators"] == [{"period": "2025-01", "count": 1}]
    assert body["All"]["organizations_by_location"] == [{"country": "USA", "count": 1}]


def test_unmatched_state_id_maps_to_unknown_but_row_still_counted(mod, write_csvs, frozen_today):
    write_csvs([org("A", "2025-01-10 10:00:00", state_id="ZZ")])
    body = call(mod, {})
    assert body["All"]["growth_trend"]["total_organizations"] == [{"period": "2025-01", "count": 1}]
    assert body["All"]["organizations_by_location"] == [{"country": "Unknown", "count": 1}]


def test_rows_with_invalid_created_at_are_dropped(mod, write_csvs, frozen_today):
    write_csvs([org("GOOD", "2025-01-10 10:00:00"), org("BAD", "not-a-timestamp")])
    assert call(mod, {})["All"]["growth_trend"]["total_organizations"] == [
        {"period": "2025-01", "count": 1}
    ]


@pytest.mark.parametrize("truthy", ["TRUE", "true", "True", "1", "Yes"])
def test_is_collaborator_accepts_varied_truthy_forms(mod, write_csvs, frozen_today, truthy):
    """Regression guard: pandas infers TRUE/FALSE text as bool dtype.

    Comparing that column against the string "TRUE" silently yields all False
    and zeroes every collaborator count, which no shape-only test would catch.
    """
    write_csvs([org("A", "2025-01-10 10:00:00", is_collaborator=truthy)])
    assert call(mod, {})["All"]["growth_trend"]["collaborators"] == [
        {"period": "2025-01", "count": 1}
    ]


@pytest.mark.parametrize("falsy", ["FALSE", "false", "0", "No"])
def test_is_collaborator_rejects_falsy_forms(mod, write_csvs, frozen_today, falsy):
    write_csvs([org("A", "2025-01-10 10:00:00", is_collaborator=falsy)])
    assert call(mod, {})["All"]["growth_trend"]["collaborators"] == [
        {"period": "2025-01", "count": 0}
    ]


# --------------------------------------------------------------------------
# Organizations by location
# --------------------------------------------------------------------------


def _multi_country_fixture(write_csvs):
    states = [
        {"state_id": "S1", "country_id": 1, "state_name": "One"},
        {"state_id": "S2", "country_id": 2, "state_name": "Two"},
        {"state_id": "S3", "country_id": 3, "state_name": "Three"},
        {"state_id": "S4", "country_id": 4, "state_name": "Four"},
        {"state_id": "S5", "country_id": 5, "state_name": "Five"},
        {"state_id": "S6", "country_id": 6, "state_name": "Six"},
    ]
    countries = [
        {"country_id": 1, "country_code": "AAA"},
        {"country_id": 2, "country_code": "BBB"},
        {"country_id": 3, "country_code": "CCC"},
        {"country_id": 4, "country_code": "DDD"},
        {"country_id": 5, "country_code": "EEE"},
        {"country_id": 6, "country_code": "FFF"},
    ]
    organizations = (
        [org(f"A{i}", "2025-01-10 10:00:00", state_id="S1") for i in range(6)]
        + [org(f"B{i}", "2025-01-10 10:00:00", state_id="S2") for i in range(5)]
        + [org(f"C{i}", "2025-01-10 10:00:00", state_id="S3") for i in range(4)]
        + [org(f"D{i}", "2025-01-10 10:00:00", state_id="S4") for i in range(3)]
        + [org(f"E{i}", "2025-01-10 10:00:00", state_id="S5") for i in range(2)]
        + [org("F0", "2025-01-10 10:00:00", state_id="S6")]
    )
    write_csvs(organizations, states=states, countries=countries)


def test_locations_limited_to_top_four(mod, write_csvs, frozen_today):
    _multi_country_fixture(write_csvs)
    assert call(mod, {})["All"]["organizations_by_location"] == [
        {"country": "AAA", "count": 6},
        {"country": "BBB", "count": 5},
        {"country": "CCC", "count": 4},
        {"country": "DDD", "count": 3},
    ]


def test_locations_returns_all_when_fewer_than_four(mod, write_csvs, frozen_today):
    states = [
        {"state_id": "S1", "country_id": 1, "state_name": "One"},
        {"state_id": "S2", "country_id": 2, "state_name": "Two"},
    ]
    countries = [
        {"country_id": 1, "country_code": "AAA"},
        {"country_id": 2, "country_code": "BBB"},
    ]
    write_csvs(
        [
            org("A", "2025-01-10 10:00:00", state_id="S1"),
            org("B", "2025-01-10 10:00:00", state_id="S2"),
        ],
        states=states,
        countries=countries,
    )
    assert call(mod, {})["All"]["organizations_by_location"] == [
        {"country": "AAA", "count": 1},
        {"country": "BBB", "count": 1},
    ]


def test_locations_tie_break_is_alphabetical(mod, write_csvs, frozen_today):
    states = [
        {"state_id": "S1", "country_id": 1, "state_name": "One"},
        {"state_id": "S2", "country_id": 2, "state_name": "Two"},
    ]
    countries = [
        {"country_id": 1, "country_code": "ZZZ"},
        {"country_id": 2, "country_code": "AAA"},
    ]
    write_csvs(
        [
            org("Z", "2025-01-10 10:00:00", state_id="S1"),
            org("A", "2025-01-10 10:00:00", state_id="S2"),
        ],
        states=states,
        countries=countries,
    )
    countries_out = [e["country"] for e in call(mod, {})["All"]["organizations_by_location"]]
    assert countries_out == ["AAA", "ZZZ"]


def test_locations_aggregate_by_country_not_state(mod, write_csvs, frozen_today):
    """TX and FL both roll into one USA row rather than two state rows."""
    states = [
        {"state_id": "TX", "country_id": 1, "state_name": "Texas"},
        {"state_id": "FL", "country_id": 1, "state_name": "Florida"},
    ]
    write_csvs(
        [
            org("A", "2025-01-10 10:00:00", state_id="TX"),
            org("B", "2025-01-10 10:00:00", state_id="FL"),
        ],
        states=states,
    )
    assert call(mod, {})["All"]["organizations_by_location"] == [{"country": "USA", "count": 2}]


def test_locations_are_window_scoped(mod, write_csvs, frozen_today):
    states = [
        {"state_id": "S1", "country_id": 1, "state_name": "One"},
        {"state_id": "S2", "country_id": 2, "state_name": "Two"},
    ]
    countries = [
        {"country_id": 1, "country_code": "AAA"},
        {"country_id": 2, "country_code": "BBB"},
    ]
    write_csvs(
        [
            org("IN", "2025-06-10 10:00:00", state_id="S1"),
            org("OUT", "2020-06-10 10:00:00", state_id="S2"),
        ],
        states=states,
        countries=countries,
    )
    body = call(mod, {"location_start_date": "2025-01-01", "location_end_date": "2025-12-31"})
    assert body["Custom"]["organizations_by_location"] == [{"country": "AAA", "count": 1}]


def test_real_dataset_locations_are_afg_only(mod, real_data, frozen_today):
    """Pins a seed-data defect, not intended behaviour.

    All 51 rows in state.csv carry country_id = 1, which country.csv defines as
    AFGHANISTAN (AFG); USA is country_id = 233. The join is faithful, so the API
    honestly reports AFG. If this test fails, the seed data was corrected -
    update the expectation to USA rather than changing the join.
    """
    assert call(mod, {})["All"]["organizations_by_location"] == [
        {"country": "AFG", "count": REAL_ORG_COUNT}
    ]
