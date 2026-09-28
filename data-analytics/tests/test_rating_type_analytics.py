"""Tests for the Rating & Type Analytics API (issue #380).

Run from the repo root:
    pytest data-analytics/tests/test_rating_type_analytics.py -v

Every test writes its own tiny CSVs into a temp folder and points MOCK_DATA_DIR
at it, so nothing depends on (or commits) real mock data. "Today" is frozen.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

LAMBDA_DIR = Path(__file__).resolve().parent.parent / "lambda_functions"
if str(LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(LAMBDA_DIR))

import rating_type_analytics as rta  # noqa: E402

TODAY = date(2026, 9, 26)

STATES = [
    {"state_id": "CA", "country_id": 233},
    {"state_id": "ON", "country_id": 39},
]
COUNTRIES = [
    {"country_id": 233, "country_name": "UNITED_STATES", "country_code": "USA"},
    {"country_id": 39, "country_name": "CANADA", "country_code": "CAN"},
]

# (org_id, rating, type, state, created_at)
DEFAULT_ORGS = [
    ("O1", 5, "Non-Profit", "CA", "2024-08-10 10:00:00"),
    ("O2", 4, "For-profit", "CA", "2024-08-20 10:00:00"),
    ("O3", 3, "Non-Profit", "ON", "2025-06-01 10:00:00"),
    ("O4", 4, "For-profit", "CA", "2025-10-15 10:00:00"),
    ("O5", 5, "Non-Profit", "CA", "2026-09-01 09:00:00"),   # inside 30D
    ("O6", 4, "Non-Profit", "ON", "2026-09-24 23:59:00"),   # inside 7D
    ("O7", 4, "For-profit", "CA", "2026-09-25 08:00:00"),   # inside 7D
]


def write_data(folder: Path, orgs):
    pd.DataFrame(
        [{"org_id": o, "org_rating": r, "org_type": t, "state_id": s, "created_at": c}
         for o, r, t, s, c in orgs],
        columns=["org_id", "org_rating", "org_type", "state_id", "created_at"],
    ).to_csv(folder / "organizations.csv", index=False)
    pd.DataFrame(STATES).to_csv(folder / "states.csv", index=False)
    pd.DataFrame(COUNTRIES).to_csv(folder / "countries.csv", index=False)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setattr(rta, "_today", lambda: TODAY)
    write_data(tmp_path, DEFAULT_ORGS)
    return tmp_path


def call(params):
    result = rta.lambda_handler(params, None)
    return result["statusCode"], json.loads(result["body"])


def assert_bucket_shape(bucket):
    assert set(bucket) == {"rating_distribution", "organization_mix_trend"}
    assert set(bucket["organization_mix_trend"]) == {"non_profit", "for_profit"}


def assert_cumulative(series):
    counts = [row["count"] for row in series]
    assert counts == sorted(counts), f"not non-decreasing: {counts}"


# ------------------------------------------------------------------ shapes --
def test_no_body_has_exactly_five_keys(data_dir):
    status, body = call({})
    assert status == 200
    assert list(body) == ["7D", "30D", "1Y", "All", "Custom"]
    for bucket in body.values():
        assert_bucket_shape(bucket)
    assert body["Custom"] == {"rating_distribution": [],
                              "organization_mix_trend": {"non_profit": [], "for_profit": []}}


def test_fixed_bucket_values(data_dir):
    _, body = call({})
    assert body["7D"]["rating_distribution"] == [{"rating": 4, "count": 2}]
    assert body["7D"]["organization_mix_trend"] == {
        "non_profit": [{"period": "2026-09-24", "count": 4}],
        "for_profit": [{"period": "2026-09-25", "count": 3}],
    }
    assert body["All"]["rating_distribution"] == [
        {"rating": 3, "count": 1}, {"rating": 4, "count": 4}, {"rating": 5, "count": 2}]
    assert body["All"]["organization_mix_trend"]["for_profit"] == [
        {"period": "2024-08", "count": 1}, {"period": "2025-10", "count": 2},
        {"period": "2026-09", "count": 3}]


def test_monthly_vs_daily_period_formats(data_dir):
    _, body = call({})
    for bucket, length in (("7D", 10), ("30D", 10), ("1Y", 7), ("All", 7)):
        for series in body[bucket]["organization_mix_trend"].values():
            assert all(len(row["period"]) == length for row in series)


def test_cumulative_and_sparse(data_dir):
    _, body = call({})
    for bucket in ("7D", "30D", "1Y", "All"):
        for series in body[bucket]["organization_mix_trend"].values():
            assert_cumulative(series)
            assert all(row["count"] > 0 for row in series)
    # 1Y starts 2025-09-26, yet non_profit total already includes the 2024/2025 orgs.
    assert body["1Y"]["organization_mix_trend"]["non_profit"] == [
        {"period": "2026-09", "count": 4}]


def test_rating_distribution_not_zero_filled(data_dir):
    _, body = call({})
    ratings = [row["rating"] for row in body["All"]["rating_distribution"]]
    assert 1 not in ratings and 2 not in ratings


# ------------------------------------------------------------------ country --
@pytest.mark.parametrize("country", ["CAN", "can", "Canada", "CANADA"])
def test_country_filter(data_dir, country):
    _, body = call({"country": country})
    assert body["All"]["rating_distribution"] == [
        {"rating": 3, "count": 1}, {"rating": 4, "count": 1}]
    assert body["All"]["organization_mix_trend"]["for_profit"] == []


def test_country_all_equals_no_filter(data_dir):
    assert call({"country": "ALL"}) == call({})


def test_country_filter_applies_to_custom(data_dir):
    _, body = call({"country": "USA", "rating_start_date": "2024-01-01",
                    "rating_end_date": "2026-12-31"})
    assert body["Custom"]["rating_distribution"] == [
        {"rating": 4, "count": 3}, {"rating": 5, "count": 2}]


# ------------------------------------------------------------------ custom --
def test_rating_range_only(data_dir):
    status, body = call({"rating_start_date": "2024-08-01", "rating_end_date": "2024-08-31"})
    assert status == 200
    assert list(body) == ["Custom"]
    assert body["Custom"]["rating_distribution"] == [
        {"rating": 4, "count": 1}, {"rating": 5, "count": 1}]
    assert body["Custom"]["organization_mix_trend"] == {"non_profit": [], "for_profit": []}


def test_type_range_only(data_dir):
    status, body = call({"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"})
    assert status == 200
    assert list(body) == ["Custom"]
    assert body["Custom"]["rating_distribution"] == []
    assert body["Custom"]["organization_mix_trend"] == {
        "non_profit": [{"period": "2025-06-01", "count": 2}],
        "for_profit": [{"period": "2025-10-15", "count": 2}],
    }


def test_both_ranges_are_independent(data_dir):
    _, body = call({"rating_start_date": "2024-08-01", "rating_end_date": "2024-08-31",
                    "type_start_date": "2025-01-01", "type_end_date": "2025-12-31"})
    assert list(body) == ["Custom"]
    assert body["Custom"]["rating_distribution"] == [
        {"rating": 4, "count": 1}, {"rating": 5, "count": 1}]
    assert body["Custom"]["organization_mix_trend"]["for_profit"] == [
        {"period": "2025-10-15", "count": 2}]


def test_end_date_is_inclusive(data_dir):
    _, body = call({"rating_start_date": "2026-09-24", "rating_end_date": "2026-09-24"})
    assert body["Custom"]["rating_distribution"] == [{"rating": 4, "count": 1}]


def test_api_gateway_string_body(data_dir):
    event = {"body": json.dumps({"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"})}
    status, body = call(event)
    assert status == 200 and list(body) == ["Custom"]


# ------------------------------------------------------------------ errors --
@pytest.mark.parametrize("params", [
    {"rating_start_date": "2025-01-01"},
    {"rating_end_date": "2025-01-01"},
    {"type_start_date": "2025-01-01", "type_end_date": ""},
    {"type_start_date": "2025/01/01", "type_end_date": "2025-02-01"},
    {"rating_start_date": "2025-02-30", "rating_end_date": "2025-03-01"},
    {"rating_start_date": "2025-12-31", "rating_end_date": "2025-01-01"},
    {"type_start_date": 20250101, "type_end_date": "2025-02-01"},
    {"country": "Atlantis"},
    {"country": 42},
    {"body": "{not json"},
    # A valid rating pair must not hide a broken type pair.
    {"rating_start_date": "2025-01-01", "rating_end_date": "2025-02-01",
     "type_start_date": "2025-01-01"},
])
def test_bad_input_returns_400(data_dir, params):
    status, body = call(params)
    assert status == 400
    assert set(body) == {"error"}


def test_missing_csv_returns_500(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    status, body = call({})
    assert status == 500 and "error" in body


# ------------------------------------------------------------------ edge data --
def test_empty_organizations_csv(data_dir):
    write_data(data_dir, [])
    status, body = call({})
    assert status == 200
    for bucket in body.values():
        assert bucket == rta.empty_bucket()
    status, body = call({"rating_start_date": "2025-01-01", "rating_end_date": "2025-12-31",
                         "type_start_date": "2025-01-01", "type_end_date": "2025-12-31"})
    assert status == 200 and body == {"Custom": rta.empty_bucket()}


def test_single_row_organizations_csv(data_dir):
    write_data(data_dir, [("O1", 3, "Non-Profit", "CA", "2026-09-25 12:00:00")])
    _, body = call({})
    for bucket in ("7D", "30D", "1Y", "All"):
        assert body[bucket]["rating_distribution"] == [{"rating": 3, "count": 1}]
        assert body[bucket]["organization_mix_trend"]["for_profit"] == []


def test_bad_rows_are_ignored_not_fatal(data_dir):
    write_data(data_dir, DEFAULT_ORGS + [
        ("X1", 9, "Non-Profit", "CA", "2025-01-01 00:00:00"),    # rating out of range
        ("X2", 4, "Mystery", "CA", "2025-01-01 00:00:00"),       # unknown type
        ("X3", 4, "For-profit", "ZZ", "not-a-date"),             # bad date
    ])
    status, body = call({})
    assert status == 200
    ratings = {row["rating"] for row in body["All"]["rating_distribution"]}
    assert ratings <= set(rta.VALID_RATINGS)
