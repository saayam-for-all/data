"""Tests for the Rating & Type Analytics Lambda (#380).

Self-contained: builds its own small mock CSVs rather than depending on any
other in-flight PR, so this suite runs regardless of what else merges.
Mirrors the fixed-bucket / Custom conventions established for #336
(growth_location_analytics), except Custom mode here *replaces* the fixed
buckets instead of riding alongside them -- that's #380's own contract.

Fixture timestamps are relative to the real `datetime.now()` at test-run
time (not a hardcoded past date), since the handler itself buckets against
real wall-clock time -- a fixed historical "now" would silently drift out
of the 7D/30D windows as real time passes.
"""
import csv
import importlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

IMPL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data-analytics", "lambda_functions",
)


def _write_csvs(tmp_path, countries, states, org_rows):
    with open(os.path.join(tmp_path, "countries.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country_id", "country_code"])
        w.writerows(countries)

    with open(os.path.join(tmp_path, "states.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state_id", "country_id"])
        w.writerows(states)

    with open(os.path.join(tmp_path, "organizations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["org_id", "state_id", "org_rating", "org_type", "created_at"])
        w.writerows(org_rows)


def _write_fixture(tmp_path):
    """6 orgs, 2 countries, ratings and mixed-case org_type spellings, one
    entry inside 7D and one just outside it.
    """
    now = datetime.now(timezone.utc)
    countries = [(1, "USA"), (2, "IND")]
    states = [(1, 1), (2, 2)]
    orgs = [
        # org_id, state_id, org_rating, org_type, created_at
        (1, 1, 5, "Non-Profit", (now - timedelta(days=200)).strftime("%Y-%m-%d")),
        (2, 1, 3, "For-profit", (now - timedelta(days=100)).strftime("%Y-%m-%d")),
        (3, 2, 4, "non_profit", (now - timedelta(days=20)).strftime("%Y-%m-%d")),
        (4, 1, 5, "NON_PROFIT", (now - timedelta(days=3)).strftime("%Y-%m-%d")),   # inside 7D
        (5, 1, 2, "for_profit", (now - timedelta(days=10)).strftime("%Y-%m-%d")),  # outside 7D
        (6, 2, 4, "For-profit", (now - timedelta(days=1)).strftime("%Y-%m-%d")),   # inside 7D
    ]
    _write_csvs(tmp_path, countries, states, orgs)
    return orgs


@pytest.fixture
def handler(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.syspath_prepend(IMPL_DIR)
    sys.modules.pop("rating_type_analytics", None)
    module = importlib.import_module("rating_type_analytics")
    return module.lambda_handler


def test_top_level_keys_no_custom_params(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert set(body.keys()) == {"7D", "30D", "1Y", "All", "Custom"}
    for bucket in body.values():
        assert set(bucket.keys()) == {"rating_distribution", "organization_mix_trend"}
        assert set(bucket["organization_mix_trend"].keys()) == {"non_profit", "for_profit"}


def test_custom_mode_returns_only_custom_key(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"}, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert set(body.keys()) == {"Custom"}
    assert set(body["Custom"].keys()) == {"rating_distribution", "organization_mix_trend"}


def test_rating_distribution_no_zero_fill(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])

    # Only org #4 (rating 5) and org #6 (rating 4) fall inside 7D -- rating
    # 1/2/3 must be absent, not reported with a zero count.
    dist = body["7D"]["rating_distribution"]
    assert dist == [{"rating": 4, "count": 1}, {"rating": 5, "count": 1}]


def test_rating_distribution_shape_and_order(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])

    dist = body["All"]["rating_distribution"]
    assert all(set(x.keys()) == {"rating", "count"} for x in dist)
    ratings = [x["rating"] for x in dist]
    assert ratings == sorted(ratings)


def test_organization_mix_trend_always_has_both_keys(handler, tmp_path):
    """Even a window with only one org_type present must still report both
    non_profit and for_profit -- for_profit as an empty series, not absent.
    """
    now = datetime.now(timezone.utc)
    _write_csvs(
        tmp_path,
        countries=[(1, "USA")],
        states=[(1, 1)],
        org_rows=[(1, 1, 5, "non_profit", (now - timedelta(days=1)).strftime("%Y-%m-%d"))],
    )
    result = handler({}, None)
    body = json.loads(result["body"])
    trend = body["All"]["organization_mix_trend"]
    assert set(trend.keys()) == {"non_profit", "for_profit"}
    assert trend["for_profit"] == []
    assert len(trend["non_profit"]) == 1


def test_organization_mix_trend_org_type_is_normalized(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])
    trend = body["All"]["organization_mix_trend"]
    # Mixed-case/hyphenated spellings in the fixture ("Non-Profit", "NON_PROFIT",
    # "For-profit") must all collapse onto exactly these two keys.
    assert set(trend.keys()) == {"non_profit", "for_profit"}


def test_organization_mix_trend_is_cumulative_non_decreasing(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])

    trend = body["All"]["organization_mix_trend"]
    for series in trend.values():
        counts = [p["count"] for p in series]
        assert counts == sorted(counts)


def test_organization_mix_trend_is_all_time_cumulative_not_window_reset(handler, tmp_path):
    """Mirrors #336's growth_trend precedent: a bucket's cumulative count is
    never reset to zero at the window's start -- it's the all-time running
    total as of each period.
    """
    orgs = _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])

    # 3 non_profit orgs exist in total (#1, #3, #4); only #4 falls inside 7D,
    # but its cumulative count must still reflect all 3, not just the 1 new
    # to this window.
    non_profit_types = {"non_profit", "non-profit", "nonprofit", "not_for_profit"}
    total_non_profit = sum(1 for o in orgs if o[3].strip().lower() in non_profit_types)
    last_7d_non_profit = body["7D"]["organization_mix_trend"]["non_profit"][-1]["count"]
    assert last_7d_non_profit == total_non_profit


def test_organization_mix_trend_totals_at_last_period(handler, tmp_path):
    orgs = _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])

    non_profit_types = {"non_profit", "non-profit", "nonprofit", "not_for_profit"}
    trend = body["All"]["organization_mix_trend"]
    non_profit_final = trend["non_profit"][-1]["count"]
    for_profit_final = trend["for_profit"][-1]["count"]
    assert non_profit_final == sum(1 for o in orgs if o[3].strip().lower() in non_profit_types)
    assert for_profit_final == sum(1 for o in orgs if o[3].strip().lower() not in non_profit_types)


def test_rating_custom_populates_independently_of_type_custom(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"}, None)
    body = json.loads(result["body"])

    assert body["Custom"]["rating_distribution"] != []
    assert body["Custom"]["organization_mix_trend"] == {"non_profit": [], "for_profit": []}


def test_type_custom_populates_independently_of_rating_custom(handler, tmp_path):
    now = datetime.now(timezone.utc)
    _write_fixture(tmp_path)
    result = handler(
        {
            "type_start_date": (now - timedelta(days=365)).strftime("%Y-%m-%d"),
            "type_end_date": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
        },
        None,
    )
    body = json.loads(result["body"])

    assert body["Custom"]["rating_distribution"] == []
    assert body["Custom"]["organization_mix_trend"] != {"non_profit": [], "for_profit": []}


def test_both_custom_ranges_populate_both_charts(handler, tmp_path):
    now = datetime.now(timezone.utc)
    _write_fixture(tmp_path)
    result = handler(
        {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
            "type_start_date": (now - timedelta(days=365)).strftime("%Y-%m-%d"),
            "type_end_date": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
        },
        None,
    )
    body = json.loads(result["body"])
    assert body["Custom"]["rating_distribution"] != []
    assert body["Custom"]["organization_mix_trend"] != {"non_profit": [], "for_profit": []}


def test_country_filter_applies_to_both_charts(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"country": "IND"}, None)
    body = json.loads(result["body"])

    # Only orgs #3 and #6 are in IND.
    dist = body["All"]["rating_distribution"]
    assert sum(x["count"] for x in dist) == 2
    trend = body["All"]["organization_mix_trend"]
    total = sum(series[-1]["count"] for series in trend.values() if series)
    assert total == 2


def test_country_filter_is_case_insensitive(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"country": "ind"}, None)
    body = json.loads(result["body"])
    dist = body["All"]["rating_distribution"]
    assert sum(x["count"] for x in dist) == 2


def test_country_all_is_a_no_op(handler, tmp_path):
    _write_fixture(tmp_path)
    all_countries = json.loads(handler({}, None)["body"])
    explicit_all = json.loads(handler({"country": "ALL"}, None)["body"])
    assert explicit_all["All"]["rating_distribution"] == all_countries["All"]["rating_distribution"]


def test_lone_rating_date_param_is_a_400(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"rating_start_date": "2026-01-01"}, None)
    assert result["statusCode"] == 400


def test_lone_type_date_param_is_a_400(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"type_end_date": "2026-06-30"}, None)
    assert result["statusCode"] == 400


def test_malformed_date_is_a_400(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"rating_start_date": "not-a-date", "rating_end_date": "2026-06-30"}, None)
    assert result["statusCode"] == 400


def test_start_after_end_is_a_400(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"type_start_date": "2026-06-30", "type_end_date": "2026-01-01"}, None)
    assert result["statusCode"] == 400


def test_invalid_org_rating_fails_loud(handler, tmp_path):
    _write_csvs(
        tmp_path,
        countries=[(1, "USA")],
        states=[(1, 1)],
        org_rows=[(1, 1, 7, "non_profit", "2026-01-01")],  # out of 1-5 range
    )
    result = handler({}, None)
    assert result["statusCode"] == 500  # loud failure, not silently accepted


def test_garbage_org_type_fails_loud(handler, tmp_path):
    _write_csvs(
        tmp_path,
        countries=[(1, "USA")],
        states=[(1, 1)],
        org_rows=[(1, 1, 5, "banana", "2026-01-01")],
    )
    result = handler({}, None)
    assert result["statusCode"] == 500  # loud failure, not a silently dropped org


def test_duplicate_state_id_fails_loud_instead_of_double_counting(handler, tmp_path):
    with open(os.path.join(tmp_path, "countries.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country_id", "country_code"])
        w.writerow([1, "USA"])
    with open(os.path.join(tmp_path, "states.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state_id", "country_id"])
        w.writerow([1, 1])
        w.writerow([1, 1])  # duplicate state_id
    with open(os.path.join(tmp_path, "organizations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["org_id", "state_id", "org_rating", "org_type", "created_at"])
        w.writerow([1, 1, 5, "non_profit", "2026-01-01"])

    result = handler({}, None)
    assert result["statusCode"] == 500  # loud failure, not silent row duplication


def test_empty_organizations_csv_does_not_crash(handler, tmp_path):
    _write_csvs(tmp_path, countries=[(1, "USA")], states=[(1, 1)], org_rows=[])
    result = handler({}, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    for bucket in body.values():
        assert bucket["rating_distribution"] == []
        assert bucket["organization_mix_trend"] == {"non_profit": [], "for_profit": []}


def test_single_row_organizations_csv_does_not_crash(handler, tmp_path):
    _write_csvs(
        tmp_path,
        countries=[(1, "USA")],
        states=[(1, 1)],
        org_rows=[(1, 1, 3, "non_profit", "2026-01-01")],
    )
    result = handler({}, None)
    assert result["statusCode"] == 200


def test_api_gateway_proxy_event_with_string_body(handler, tmp_path):
    _write_fixture(tmp_path)
    event = {"body": json.dumps({"country": "USA"})}
    result = handler(event, None)
    assert result["statusCode"] == 200


def test_response_body_is_a_json_string(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    assert isinstance(result["body"], str)


def test_data_is_loaded_once_per_warm_instance_not_per_call(handler, tmp_path, monkeypatch):
    _write_fixture(tmp_path)

    module = sys.modules["rating_type_analytics"]
    real_load_data = module.load_data
    call_count = {"n": 0}

    def counting_load_data(*args, **kwargs):
        call_count["n"] += 1
        return real_load_data(*args, **kwargs)

    monkeypatch.setattr(module, "load_data", counting_load_data)

    handler({}, None)
    handler({"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"}, None)
    handler({}, None)

    assert call_count["n"] == 1, "load_data() should run once per warm instance, not per call"


def test_module_imports_without_psycopg2(tmp_path, monkeypatch):
    """USE_MOCK_DATA=true must work even when psycopg2 isn't installed --
    the import is wrapped in try/except ImportError specifically so the
    mock-CSV path never depends on the Postgres driver being present.
    """
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.syspath_prepend(IMPL_DIR)
    sys.modules.pop("rating_type_analytics", None)
    monkeypatch.setitem(sys.modules, "psycopg2", None)

    module = importlib.import_module("rating_type_analytics")
    assert module.psycopg2 is None

    _write_fixture(tmp_path)
    result = module.lambda_handler({}, None)
    assert result["statusCode"] == 200


def test_postgres_path_without_psycopg2_fails_loud(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.syspath_prepend(IMPL_DIR)
    sys.modules.pop("rating_type_analytics", None)
    monkeypatch.setitem(sys.modules, "psycopg2", None)

    module = importlib.import_module("rating_type_analytics")
    result = module.lambda_handler({}, None)
    assert result["statusCode"] == 500
