"""Tests for the Rating & Type Analytics API (issue #380).

These run entirely offline: USE_MOCK_DATA defaults to true and the handler reads
CSVs, so there is nothing to mock out. The `frozen_now` fixture is autouse
because the fixed buckets are relative to the current date - without it the 1Y
and All golden assertions would start failing on their own as the calendar moves.

The tracked seed data resolves every organization to a single country, so the
country filter's interesting cases use synthetic fixtures.

Run with:
    python -m pytest data-analytics/tests -q
"""
import json
import re
from datetime import datetime, timedelta

import pandas as pd
import pytest

import rating_type_analytics as rating_module


FROZEN_NOW = datetime(2026, 9, 29)

DAY_LABEL = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_LABEL = re.compile(r"^\d{4}-\d{2}$")

# Golden values read off the tracked data-analytics/sql CSVs.
REAL_ORG_COUNT = 40
REAL_NON_PROFIT_TOTAL = 21
REAL_FOR_PROFIT_TOTAL = 19
REAL_ALL_RATINGS = [
    {"rating": 1, "count": 5},
    {"rating": 2, "count": 9},
    {"rating": 3, "count": 10},
    {"rating": 4, "count": 4},
    {"rating": 5, "count": 12},
]
REAL_1Y_RATINGS = [
    {"rating": 1, "count": 3},
    {"rating": 2, "count": 1},
    {"rating": 3, "count": 2},
    {"rating": 5, "count": 2},
]
REAL_1Y_NON_PROFIT = [
    {"period": "2025-10", "count": 16},
    {"period": "2025-11", "count": 18},
    {"period": "2025-12", "count": 20},
    {"period": "2026-01", "count": 21},
]
REAL_1Y_FOR_PROFIT = [
    {"period": "2025-11", "count": 18},
    {"period": "2025-12", "count": 19},
]


@pytest.fixture
def mod():
    return rating_module


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    """Pin the clock so window-relative buckets stay deterministic."""
    monkeypatch.setattr(rating_module, "current_time", lambda: FROZEN_NOW)
    return FROZEN_NOW


@pytest.fixture
def real_data(monkeypatch):
    """Use the tracked data-analytics/sql CSVs."""
    monkeypatch.delenv("MOCK_DATA_DIR", raising=False)
    monkeypatch.setenv("USE_MOCK_DATA", "true")


@pytest.fixture
def write_csvs(tmp_path, monkeypatch):
    """Write synthetic CSVs into a temp dir and point MOCK_DATA_DIR at it."""

    def _write(organizations, states=None, countries=None, state_name="state.csv",
               country_name="country.csv", write_lookup=True):
        frame = organizations if isinstance(organizations, pd.DataFrame) else pd.DataFrame(organizations)
        frame.to_csv(tmp_path / "organizations.csv", index=False)

        if write_lookup:
            if states is None:
                states = [{"state_id": "TX", "country_id": 1, "state_name": "Texas"}]
            if countries is None:
                countries = [{"country_id": 1, "country_name": "UNITED_STATES", "country_code": "USA"}]
            pd.DataFrame(states).to_csv(tmp_path / state_name, index=False)
            pd.DataFrame(countries).to_csv(tmp_path / country_name, index=False)

        monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("USE_MOCK_DATA", "true")
        return tmp_path

    return _write


def org(org_id="A", created_at="2025-06-10 10:00:00", org_type="Non-Profit", org_rating=3, state_id="TX"):
    """One organizations.csv row."""
    return {
        "org_id": org_id,
        "created_at": created_at,
        "org_type": org_type,
        "org_rating": org_rating,
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


def test_default_response_has_exactly_five_top_level_keys(mod, real_data):
    assert set(call(mod, {})) == {"7D", "30D", "1Y", "All", "Custom"}


def test_every_bucket_has_exactly_two_keys(mod, real_data):
    for bucket, payload in call(mod, {}).items():
        assert set(payload) == {"rating_distribution", "organization_mix_trend"}, bucket


def test_mix_trend_has_exactly_two_series(mod, real_data):
    for bucket, payload in call(mod, {}).items():
        assert set(payload["organization_mix_trend"]) == {"non_profit", "for_profit"}, bucket


def test_custom_is_fully_empty_when_no_dates_supplied(mod, real_data):
    assert call(mod, {})["Custom"] == {
        "rating_distribution": [],
        "organization_mix_trend": {"non_profit": [], "for_profit": []},
    }


def test_rating_rows_have_only_rating_and_count(mod, real_data):
    for payload in call(mod, {}).values():
        for entry in payload["rating_distribution"]:
            assert set(entry) == {"rating", "count"}


def test_mix_trend_entries_have_only_period_and_count(mod, real_data):
    for payload in call(mod, {}).values():
        for series in payload["organization_mix_trend"].values():
            for entry in series:
                assert set(entry) == {"period", "count"}


def test_body_is_a_json_string(mod, real_data):
    response = mod.lambda_handler({}, None)
    assert response["statusCode"] == 200
    assert isinstance(response["body"], str)
    assert isinstance(json.loads(response["body"]), dict)


def test_response_includes_cors_headers(mod, real_data):
    headers = mod.lambda_handler({}, None)["headers"]
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert headers["Content-Type"] == "application/json"


def test_counts_are_plain_python_ints_not_numpy(mod, real_data):
    """numpy.int64 is not JSON-serializable, so every count must be int()-wrapped."""
    body = call(mod, {})
    for payload in body.values():
        for entry in payload["rating_distribution"]:
            assert type(entry["rating"]) is int
            assert type(entry["count"]) is int
        for series in payload["organization_mix_trend"].values():
            for entry in series:
                assert type(entry["count"]) is int
    json.dumps(body)


# --------------------------------------------------------------------------
# Response-shape switch
# --------------------------------------------------------------------------


RATING_RANGE = {"rating_start_date": "2025-10-01", "rating_end_date": "2026-01-31"}
TYPE_RANGE = {"type_start_date": "2025-10-01", "type_end_date": "2026-01-31"}


def test_rating_range_alone_returns_only_custom_key(mod, real_data):
    assert set(call(mod, dict(RATING_RANGE))) == {"Custom"}


def test_type_range_alone_returns_only_custom_key(mod, real_data):
    assert set(call(mod, dict(TYPE_RANGE))) == {"Custom"}


def test_both_ranges_return_only_custom_key(mod, real_data):
    assert set(call(mod, {**RATING_RANGE, **TYPE_RANGE})) == {"Custom"}


def test_rating_range_alone_leaves_mix_trend_empty(mod, real_data):
    custom = call(mod, dict(RATING_RANGE))["Custom"]
    assert custom["rating_distribution"]
    assert custom["organization_mix_trend"] == {"non_profit": [], "for_profit": []}


def test_type_range_alone_leaves_rating_distribution_empty(mod, real_data):
    custom = call(mod, dict(TYPE_RANGE))["Custom"]
    assert custom["rating_distribution"] == []
    assert custom["organization_mix_trend"]["non_profit"]


def test_both_ranges_populate_both_subcharts(mod, real_data):
    custom = call(mod, {**RATING_RANGE, **TYPE_RANGE})["Custom"]
    assert custom["rating_distribution"]
    assert custom["organization_mix_trend"]["non_profit"]


def test_custom_pairs_are_independent(mod, real_data):
    """Each sub-chart honours only its own range."""
    custom = call(
        mod,
        {
            "rating_start_date": "2025-10-01",
            "rating_end_date": "2025-12-31",
            "type_start_date": "2025-11-01",
            "type_end_date": "2026-01-31",
        },
    )["Custom"]
    # The type range opens 2025-11-01, so the October non-profit is not a visible period.
    periods = [e["period"] for e in custom["organization_mix_trend"]["non_profit"]]
    assert periods[0] == "2025-11-03"
    # The rating range closes 2025-12-31, excluding the 2026-01 organization.
    assert sum(e["count"] for e in custom["rating_distribution"]) == 7


def test_custom_response_has_no_fixed_buckets(mod, real_data):
    body = call(mod, dict(RATING_RANGE))
    for bucket in ("7D", "30D", "1Y", "All"):
        assert bucket not in body


# --------------------------------------------------------------------------
# Bucketing granularity
# --------------------------------------------------------------------------


def test_seven_and_thirty_day_periods_are_day_labels(mod, write_csvs):
    write_csvs([org("A", f"{(FROZEN_NOW - timedelta(days=2)).date()} 10:00:00")])
    body = call(mod, {})
    for bucket in ("7D", "30D"):
        periods = [e["period"] for e in body[bucket]["organization_mix_trend"]["non_profit"]]
        assert periods and all(DAY_LABEL.match(p) for p in periods), bucket


def test_one_year_and_all_periods_are_month_labels(mod, real_data):
    body = call(mod, {})
    for bucket in ("1Y", "All"):
        for name, series in body[bucket]["organization_mix_trend"].items():
            assert series and all(MONTH_LABEL.match(e["period"]) for e in series), f"{bucket}.{name}"


def test_custom_periods_are_day_labels(mod, real_data):
    trend = call(mod, dict(TYPE_RANGE))["Custom"]["organization_mix_trend"]
    assert all(DAY_LABEL.match(e["period"]) for e in trend["non_profit"])


def test_periods_are_sorted_ascending(mod, real_data):
    for bucket, payload in call(mod, {}).items():
        for name, series in payload["organization_mix_trend"].items():
            periods = [e["period"] for e in series]
            assert periods == sorted(periods), f"{bucket}.{name}"


# --------------------------------------------------------------------------
# Mix-trend semantics - the core of the issue
# --------------------------------------------------------------------------


def test_mix_trend_is_all_time_cumulative_not_window_reset(mod, real_data):
    """The 1Y window holds only 8 organizations, yet its first point is 16."""
    trend = call(mod, {})["1Y"]["organization_mix_trend"]
    assert trend["non_profit"][0] == {"period": "2025-10", "count": 16}


def test_one_year_mix_trend_matches_verified_values(mod, real_data):
    trend = call(mod, {})["1Y"]["organization_mix_trend"]
    assert trend["non_profit"] == REAL_1Y_NON_PROFIT
    assert trend["for_profit"] == REAL_1Y_FOR_PROFIT


def test_two_series_have_different_period_sets(mod, real_data):
    """Periods are omitted per type, so the two series need not line up."""
    trend = call(mod, {})["1Y"]["organization_mix_trend"]
    non_profit = [e["period"] for e in trend["non_profit"]]
    for_profit = [e["period"] for e in trend["for_profit"]]
    assert non_profit != for_profit
    assert "2025-10" in non_profit
    assert "2025-10" not in for_profit


def test_series_are_monotonically_non_decreasing(mod, real_data):
    for bucket, payload in call(mod, {}).items():
        for name, series in payload["organization_mix_trend"].items():
            counts = [e["count"] for e in series]
            assert all(a <= b for a, b in zip(counts, counts[1:])), f"{bucket}.{name}"


def test_all_bucket_final_counts_match_type_totals(mod, real_data):
    trend = call(mod, {})["All"]["organization_mix_trend"]
    assert trend["non_profit"][-1]["count"] == REAL_NON_PROFIT_TOTAL
    assert trend["for_profit"][-1]["count"] == REAL_FOR_PROFIT_TOTAL


def test_all_bucket_final_counts_sum_to_dataset_row_count(mod, real_data):
    trend = call(mod, {})["All"]["organization_mix_trend"]
    assert trend["non_profit"][-1]["count"] + trend["for_profit"][-1]["count"] == REAL_ORG_COUNT


def test_periods_with_no_new_orgs_of_that_type_are_omitted(mod, write_csvs):
    write_csvs(
        [
            org("N1", "2024-01-10 10:00:00", org_type="Non-Profit"),
            org("F1", "2024-02-10 10:00:00", org_type="For-profit"),
            org("N2", "2024-03-10 10:00:00", org_type="Non-Profit"),
        ]
    )
    trend = call(mod, {})["All"]["organization_mix_trend"]
    assert [e["period"] for e in trend["non_profit"]] == ["2024-01", "2024-03"]
    assert [e["period"] for e in trend["for_profit"]] == ["2024-02"]


def test_no_zero_filling_in_mix_trend(mod, real_data):
    for payload in call(mod, {}).values():
        for series in payload["organization_mix_trend"].values():
            assert all(e["count"] > 0 for e in series)


def test_series_with_no_orgs_is_empty_list_not_missing_key(mod, write_csvs):
    write_csvs([org("A", org_type="Non-Profit"), org("B", org_type="Non-Profit")])
    trend = call(mod, {})["All"]["organization_mix_trend"]
    assert trend["non_profit"]
    assert "for_profit" in trend
    assert trend["for_profit"] == []


def test_seven_and_thirty_day_are_empty_for_stale_real_data(mod, real_data):
    """Newest seed organization is 2026-01-10, so both rolling windows are empty."""
    body = call(mod, {})
    for bucket in ("7D", "30D"):
        assert body[bucket]["rating_distribution"] == []
        assert body[bucket]["organization_mix_trend"] == {"non_profit": [], "for_profit": []}


def test_custom_mix_trend_is_still_all_time_cumulative(mod, real_data):
    trend = call(mod, dict(TYPE_RANGE))["Custom"]["organization_mix_trend"]
    assert trend["non_profit"][0] == {"period": "2025-10-01", "count": 16}
    assert trend["non_profit"][-1] == {"period": "2026-01-10", "count": 21}
    assert trend["for_profit"] == [
        {"period": "2025-11-28", "count": 18},
        {"period": "2025-12-19", "count": 19},
    ]


# --------------------------------------------------------------------------
# Rating distribution semantics
# --------------------------------------------------------------------------


def test_all_bucket_rating_distribution_matches_verified(mod, real_data):
    assert call(mod, {})["All"]["rating_distribution"] == REAL_ALL_RATINGS


def test_one_year_rating_distribution_matches_verified(mod, real_data):
    assert call(mod, {})["1Y"]["rating_distribution"] == REAL_1Y_RATINGS


def test_rating_four_absent_in_one_year_no_zero_filling(mod, real_data):
    ratings = [e["rating"] for e in call(mod, {})["1Y"]["rating_distribution"]]
    assert 4 not in ratings
    assert len(ratings) == 4


def test_rating_distribution_is_window_scoped_not_cumulative(mod, real_data):
    body = call(mod, {})
    assert sum(e["count"] for e in body["1Y"]["rating_distribution"]) == 8
    assert sum(e["count"] for e in body["All"]["rating_distribution"]) == REAL_ORG_COUNT


def test_rating_distribution_sorted_ascending(mod, real_data):
    for payload in call(mod, {}).values():
        ratings = [e["rating"] for e in payload["rating_distribution"]]
        assert ratings == sorted(ratings)


def test_rating_distribution_is_not_a_time_series(mod, real_data):
    for payload in call(mod, {}).values():
        assert all("period" not in e for e in payload["rating_distribution"])


def test_custom_rating_distribution_uses_its_own_range(mod, real_data):
    assert call(mod, dict(RATING_RANGE))["Custom"]["rating_distribution"] == REAL_1Y_RATINGS


# --------------------------------------------------------------------------
# Country filter
# --------------------------------------------------------------------------


def test_country_defaults_to_all_when_absent(mod, real_data):
    assert call(mod, {})["All"]["rating_distribution"] == REAL_ALL_RATINGS


@pytest.mark.parametrize("country", ["ALL", "all", "All"])
def test_country_all_is_case_insensitive(mod, real_data, country):
    assert call(mod, {"country": country})["All"]["rating_distribution"] == REAL_ALL_RATINGS


@pytest.mark.parametrize("country", ["AFG", "afg", "AFGHANISTAN", "Afghanistan"])
def test_real_data_matches_afghanistan_by_code_or_name(mod, real_data, country):
    """The seed data resolves every organization to Afghanistan; see the module docstring."""
    assert call(mod, {"country": country})["All"]["rating_distribution"] == REAL_ALL_RATINGS


@pytest.mark.parametrize("country", ["USA", "ZZZ"])
def test_unmatched_country_returns_200_with_empty_results(mod, real_data, country):
    body = call(mod, {"country": country})
    assert set(body) == {"7D", "30D", "1Y", "All", "Custom"}
    for payload in body.values():
        assert payload["rating_distribution"] == []
        assert payload["organization_mix_trend"] == {"non_profit": [], "for_profit": []}


def test_country_filter_applies_in_custom_shape(mod, real_data):
    body = call(mod, {"country": "USA", **RATING_RANGE})
    assert set(body) == {"Custom"}
    assert body["Custom"]["rating_distribution"] == []


def test_country_filter_narrows_cumulative_baseline(mod, write_csvs):
    """Proves the country filter runs before the cumulative sum, not after."""
    states = [
        {"state_id": "S1", "country_id": 1, "state_name": "One"},
        {"state_id": "S2", "country_id": 2, "state_name": "Two"},
    ]
    countries = [
        {"country_id": 1, "country_name": "ALPHA", "country_code": "AAA"},
        {"country_id": 2, "country_name": "BETA", "country_code": "BBB"},
    ]
    write_csvs(
        [
            org("A1", "2024-01-10 10:00:00", state_id="S1"),
            org("A2", "2024-02-10 10:00:00", state_id="S1"),
            org("B1", "2024-01-10 10:00:00", state_id="S2"),
            org("B2", "2024-02-10 10:00:00", state_id="S2"),
        ],
        states=states,
        countries=countries,
    )
    trend = call(mod, {"country": "AAA"})["All"]["organization_mix_trend"]
    # Filtered to 2 organizations, so the running total must end at 2, not 4.
    assert [e["count"] for e in trend["non_profit"]] == [1, 2]


def test_country_filter_applies_to_rating_distribution(mod, write_csvs):
    states = [
        {"state_id": "S1", "country_id": 1, "state_name": "One"},
        {"state_id": "S2", "country_id": 2, "state_name": "Two"},
    ]
    countries = [
        {"country_id": 1, "country_name": "ALPHA", "country_code": "AAA"},
        {"country_id": 2, "country_name": "BETA", "country_code": "BBB"},
    ]
    write_csvs(
        [org("A", org_rating=5, state_id="S1"), org("B", org_rating=2, state_id="S2")],
        states=states,
        countries=countries,
    )
    assert call(mod, {"country": "AAA"})["All"]["rating_distribution"] == [{"rating": 5, "count": 1}]


@pytest.mark.parametrize("country", [123, None, ["USA"], "   "])
def test_unusable_country_falls_back_to_all(mod, real_data, country):
    assert call(mod, {"country": country})["All"]["rating_distribution"] == REAL_ALL_RATINGS


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event, missing_field",
    [
        ({"rating_start_date": "2025-01-01"}, "rating_end_date"),
        ({"rating_end_date": "2025-01-01"}, "rating_start_date"),
        ({"type_start_date": "2025-01-01"}, "type_end_date"),
        ({"type_end_date": "2025-01-01"}, "type_start_date"),
    ],
)
def test_half_supplied_pair_returns_400(mod, real_data, event, missing_field):
    body = call(mod, event, expected_status=400)
    assert set(body) == {"error"}
    assert missing_field in body["error"]


@pytest.mark.parametrize(
    "bad",
    ["01-15-2026", "2026/01/15", "not-a-date", "2026-13-01", "2026-02-30", "2026-1-5",
     "2026-01-15 00:00:00", ""],
)
def test_invalid_date_formats_return_400(mod, real_data, bad):
    if bad == "":
        # A blank pair is "absent", not invalid - it yields the default shape.
        assert set(call(mod, {"rating_start_date": bad, "rating_end_date": bad})) == {
            "7D", "30D", "1Y", "All", "Custom"
        }
        return
    body = call(mod, {"rating_start_date": bad, "rating_end_date": "2026-03-01"}, expected_status=400)
    assert "rating_start_date" in body["error"]


def test_invalid_type_date_format_returns_400(mod, real_data):
    body = call(
        mod, {"type_start_date": "2026/01/15", "type_end_date": "2026-03-01"}, expected_status=400
    )
    assert "type_start_date" in body["error"]


def test_rating_start_after_end_returns_400(mod, real_data):
    body = call(
        mod, {"rating_start_date": "2026-03-01", "rating_end_date": "2026-01-01"}, expected_status=400
    )
    assert "rating_start_date must be on or before rating_end_date" in body["error"]


def test_type_start_after_end_returns_400(mod, real_data):
    body = call(
        mod, {"type_start_date": "2026-03-01", "type_end_date": "2026-01-01"}, expected_status=400
    )
    assert "type_start_date must be on or before type_end_date" in body["error"]


def test_valid_rating_pair_with_broken_type_pair_returns_400(mod, real_data):
    """One good pair never rescues the other; each is validated independently."""
    body = call(mod, {**RATING_RANGE, "type_start_date": "2026-03-01"}, expected_status=400)
    assert "type_end_date" in body["error"]


def test_error_response_has_cors_headers(mod, real_data):
    response = mod.lambda_handler({"rating_start_date": "2025-01-01"}, None)
    assert response["statusCode"] == 400
    assert response["headers"]["Access-Control-Allow-Origin"] == "*"


def test_equal_start_and_end_dates_are_valid(mod, real_data):
    body = call(mod, {"rating_start_date": "2026-01-10", "rating_end_date": "2026-01-10"})
    assert set(body) == {"Custom"}


def test_blank_date_strings_are_treated_as_absent(mod, real_data):
    body = call(mod, {"rating_start_date": "", "rating_end_date": "  "})
    assert set(body) == {"7D", "30D", "1Y", "All", "Custom"}


def test_one_blank_one_filled_is_a_half_pair_400(mod, real_data):
    body = call(mod, {"rating_start_date": "", "rating_end_date": "2026-01-10"}, expected_status=400)
    assert "rating_start_date" in body["error"]


# --------------------------------------------------------------------------
# Window boundaries
# --------------------------------------------------------------------------


def test_custom_range_includes_orgs_created_late_on_the_end_date(mod, real_data):
    """A real seed row sits at 2026-01-10 23:29:11; an end bound must cover its whole day."""
    body = call(mod, {"type_start_date": "2026-01-01", "type_end_date": "2026-01-10"})
    periods = [e["period"] for e in body["Custom"]["organization_mix_trend"]["non_profit"]]
    assert periods == ["2026-01-10"]


def test_custom_range_includes_orgs_created_on_the_start_date(mod, write_csvs):
    write_csvs([org("A", "2025-03-01 08:15:00")])
    body = call(mod, {"type_start_date": "2025-03-01", "type_end_date": "2025-03-31"})
    assert [e["period"] for e in body["Custom"]["organization_mix_trend"]["non_profit"]] == ["2025-03-01"]


def test_one_year_window_boundaries(mod, write_csvs):
    write_csvs(
        [
            org("IN", f"{(FROZEN_NOW - timedelta(days=364)).date()} 10:00:00"),
            org("OUT", f"{(FROZEN_NOW - timedelta(days=366)).date()} 10:00:00"),
        ]
    )
    trend = call(mod, {})["1Y"]["organization_mix_trend"]
    assert len(trend["non_profit"]) == 1
    # The out-of-window row still lifts the all-time running total.
    assert trend["non_profit"][0]["count"] == 2


def test_all_bucket_has_no_lower_bound(mod, write_csvs):
    write_csvs([org("ANCIENT", "1990-01-01 00:00:00")])
    assert call(mod, {})["All"]["organization_mix_trend"]["non_profit"] == [
        {"period": "1990-01", "count": 1}
    ]


# --------------------------------------------------------------------------
# Event parsing
# --------------------------------------------------------------------------


def test_accepts_dict_body(mod, real_data):
    assert set(call(mod, {"body": dict(RATING_RANGE)})) == {"Custom"}


def test_accepts_json_string_body(mod, real_data):
    assert set(call(mod, {"body": json.dumps(RATING_RANGE)})) == {"Custom"}


def test_accepts_top_level_params_without_body_key(mod, real_data):
    assert set(call(mod, dict(RATING_RANGE))) == {"Custom"}


@pytest.mark.parametrize("event", [{}, None, {"body": "not json"}, {"body": "[1, 2]"}])
def test_degenerate_events_return_default_shape(mod, real_data, event):
    assert set(call(mod, event)) == {"7D", "30D", "1Y", "All", "Custom"}


# --------------------------------------------------------------------------
# Loading and environment gating
# --------------------------------------------------------------------------


def test_use_mock_data_defaults_to_true(mod, monkeypatch):
    monkeypatch.delenv("USE_MOCK_DATA", raising=False)
    monkeypatch.delenv("MOCK_DATA_DIR", raising=False)
    assert mod.use_mock_data() is True
    assert call(mod, {})["All"]["rating_distribution"] == REAL_ALL_RATINGS


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "y", "on", " True "])
def test_use_mock_data_accepts_truthy_variants(mod, monkeypatch, value):
    monkeypatch.setenv("USE_MOCK_DATA", value)
    assert mod.use_mock_data() is True


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off"])
def test_use_mock_data_accepts_falsy_variants(mod, monkeypatch, value):
    monkeypatch.setenv("USE_MOCK_DATA", value)
    assert mod.use_mock_data() is False


def test_use_mock_data_false_without_psycopg2_returns_500(mod, monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.setattr(mod, "PSYCOPG2_AVAILABLE", False)
    body = call(mod, {}, expected_status=500)
    assert "error" in body


def test_module_exposes_psycopg2_available_flag(mod):
    assert isinstance(mod.PSYCOPG2_AVAILABLE, bool)


def test_default_data_dir_is_tracked_sql_folder(mod):
    assert mod.DEFAULT_DATA_DIR.name == "sql"
    assert (mod.DEFAULT_DATA_DIR / "organizations.csv").is_file()


def test_mock_data_dir_env_var_overrides_default(mod, write_csvs):
    tmp_dir = write_csvs([org("A", "2025-01-10 10:00:00")])
    assert mod.resolve_data_dir() == tmp_dir
    assert call(mod, {})["All"]["rating_distribution"] == [{"rating": 3, "count": 1}]


@pytest.mark.parametrize(
    "state_name, country_name",
    [("state.csv", "country.csv"), ("states.csv", "countries.csv")],
)
def test_resolves_both_filename_spellings(mod, write_csvs, state_name, country_name):
    write_csvs([org("A", "2025-01-10 10:00:00")], state_name=state_name, country_name=country_name)
    assert call(mod, {"country": "USA"})["All"]["rating_distribution"] == [{"rating": 3, "count": 1}]


def test_missing_organizations_csv_returns_500(mod, monkeypatch, tmp_path):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    assert "error" in call(mod, {}, expected_status=500)


def test_missing_lookup_csvs_degrade_to_unknown_country(mod, write_csvs):
    write_csvs([org("A", "2025-01-10 10:00:00")], write_lookup=False)
    body = call(mod, {})
    assert body["All"]["rating_distribution"] == [{"rating": 3, "count": 1}]
    assert call(mod, {"country": "UNKNOWN"})["All"]["rating_distribution"] == [{"rating": 3, "count": 1}]


def test_db_loader_sql_is_a_thin_select(mod):
    """No aggregation may leak into SQL - it all lives in the shared pandas code."""
    sql = mod.ORGANIZATIONS_SQL
    assert "o.rating                            AS org_rating" in sql
    assert "o.state_code = s.state_code" in sql
    for forbidden in ("GROUP BY", "SUM(", "OVER (", "DATE_TRUNC", "WHERE"):
        assert forbidden not in sql.upper(), forbidden


def test_db_loader_builds_canonical_frame_from_fake_cursor(mod):
    frame = mod.load_organizations_from_db(_FakeConnection(_DB_ROWS))
    assert list(frame.columns) == mod.CANONICAL_COLUMNS
    assert len(frame) == len(_DB_ROWS)


def test_csv_and_db_paths_produce_identical_output(mod, monkeypatch, write_csvs):
    """The shared-aggregation guarantee: same rows in, byte-identical response out."""
    write_csvs(
        [
            org("O1", "2025-01-10 10:00:00", org_type="Non-Profit", org_rating=5),
            org("O2", "2025-02-10 10:00:00", org_type="For-profit", org_rating=3),
        ]
    )
    csv_body = mod.lambda_handler({}, None)["body"]

    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.setattr(mod, "PSYCOPG2_AVAILABLE", True)
    monkeypatch.setattr(mod, "get_db_connection", lambda: _FakeConnection(_DB_ROWS))
    db_body = mod.lambda_handler({}, None)["body"]

    assert json.loads(db_body) == json.loads(csv_body)


_DB_ROWS = [
    {
        "org_id": "O1",
        "org_type": "Non-Profit",
        "org_rating": 5,
        "created_at": "2025-01-10 10:00:00",
        "country_name": "UNITED_STATES",
        "country_code": "USA",
    },
    {
        "org_id": "O2",
        "org_type": "For-profit",
        "org_rating": 3,
        "created_at": "2025-02-10 10:00:00",
        "country_name": "UNITED_STATES",
        "country_code": "USA",
    },
]


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, query):
        self.query = query

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self._rows)

    def close(self):
        pass


# --------------------------------------------------------------------------
# Data quality
# --------------------------------------------------------------------------


def test_empty_organizations_csv_returns_empty_buckets(mod, write_csvs):
    write_csvs(pd.DataFrame(columns=["org_id", "created_at", "org_type", "org_rating", "state_id"]))
    body = call(mod, {})
    assert set(body) == {"7D", "30D", "1Y", "All", "Custom"}
    for payload in body.values():
        assert payload["rating_distribution"] == []
        assert payload["organization_mix_trend"] == {"non_profit": [], "for_profit": []}


def test_single_row_dataset(mod, write_csvs):
    write_csvs([org("ONLY", "2025-01-10 10:00:00", org_type="For-profit", org_rating=4)])
    body = call(mod, {})["All"]
    assert body["rating_distribution"] == [{"rating": 4, "count": 1}]
    assert body["organization_mix_trend"]["for_profit"] == [{"period": "2025-01", "count": 1}]
    assert body["organization_mix_trend"]["non_profit"] == []


def test_rows_with_unparseable_created_at_are_dropped(mod, write_csvs):
    write_csvs([org("GOOD", "2025-01-10 10:00:00"), org("BAD", "not-a-timestamp")])
    assert call(mod, {})["All"]["organization_mix_trend"]["non_profit"] == [
        {"period": "2025-01", "count": 1}
    ]


@pytest.mark.parametrize("bad_rating", ["", "N/A", 4.7, None])
def test_rows_with_bad_rating_still_count_in_mix_trend(mod, write_csvs, bad_rating):
    """The two charts are independent: a bad rating must not remove the row from chart 2."""
    write_csvs([org("A", "2025-01-10 10:00:00", org_rating=bad_rating)])
    body = call(mod, {})["All"]
    assert body["rating_distribution"] == []
    assert body["organization_mix_trend"]["non_profit"] == [{"period": "2025-01", "count": 1}]


def test_unmatched_state_id_maps_to_unknown_but_row_still_counted(mod, write_csvs):
    write_csvs([org("A", "2025-01-10 10:00:00", state_id="ZZ")])
    assert call(mod, {})["All"]["rating_distribution"] == [{"rating": 3, "count": 1}]
    assert call(mod, {"country": "UNKNOWN"})["All"]["rating_distribution"] == [{"rating": 3, "count": 1}]


def test_unexpected_org_type_excluded_from_trend_but_counted_in_ratings(mod, write_csvs):
    write_csvs([org("A", "2025-01-10 10:00:00", org_type="NGO", org_rating=5)])
    body = call(mod, {})["All"]
    assert body["rating_distribution"] == [{"rating": 5, "count": 1}]
    assert body["organization_mix_trend"] == {"non_profit": [], "for_profit": []}


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Non-Profit", "non_profit"),
        ("non_profit", "non_profit"),
        ("NON PROFIT", "non_profit"),
        ("nonprofit", "non_profit"),
        ("For-profit", "for_profit"),
        (" for_profit ", "for_profit"),
        ("FORPROFIT", "for_profit"),
        ("NGO", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_org_type_normalization(mod, raw, expected):
    assert mod.normalize_org_type(raw) == expected


def test_real_dataset_org_types_normalize_to_two_series(mod, real_data):
    trend = call(mod, {})["All"]["organization_mix_trend"]
    assert trend["non_profit"][-1]["count"] == REAL_NON_PROFIT_TOTAL
    assert trend["for_profit"][-1]["count"] == REAL_FOR_PROFIT_TOTAL
