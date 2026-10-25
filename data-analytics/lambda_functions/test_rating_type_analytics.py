import json
from datetime import date, datetime

import pandas as pd
import pytest

import rating_type_analytics as rta

TODAY = date(2026, 9, 1)
FIXED_KEYS = {"7D", "30D", "1Y", "All", "Custom"}


def write_csvs(tmp_path, org_rows):
    pd.DataFrame(
        org_rows, columns=["org_id", "org_rating", "org_type", "state_id", "created_at"]
    ).to_csv(tmp_path / "organizations.csv", index=False)
    pd.DataFrame(
        [{"state_id": 1, "country_id": 10}, {"state_id": 2, "country_id": 20}]
    ).to_csv(tmp_path / "states.csv", index=False)
    pd.DataFrame(
        [
            {"country_id": 10, "country_code": "USA", "country_name": "United States"},
            {"country_id": 20, "country_code": "IND", "country_name": "India"},
        ]
    ).to_csv(tmp_path / "countries.csv", index=False)


SAMPLE_ORGS = [
    (1, 5, "non_profit", 1, "2024-08-10"),
    (2, 4, "for_profit", 1, "2024-08-15"),
    (3, 1, "non_profit", 2, "2025-06-01"),
    (4, 3, "for_profit", 1, "2025-10-05"),
    (5, 4, "non_profit", 1, "2026-03-15"),
    (6, 5, "non_profit", 2, "2026-08-10"),
    (7, 4, "for_profit", 1, "2026-08-27"),
    (8, 2, "non_profit", 1, "2026-08-28"),
]


@pytest.fixture
def mock_env(tmp_path, monkeypatch):
    def _setup(rows=SAMPLE_ORGS):
        write_csvs(tmp_path, rows)
        monkeypatch.setenv("USE_MOCK_DATA", "true")
        monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(rta, "_today", lambda: TODAY)
    return _setup


def call(body=None):
    event = {} if body is None else {"body": json.dumps(body)}
    response = rta.lambda_handler(event, None)
    return response["statusCode"], json.loads(response["body"])


def assert_chart_shape(chart):
    assert set(chart) == {"rating_distribution", "organization_mix_trend"}
    assert set(chart["organization_mix_trend"]) == {"non_profit", "for_profit"}


def assert_cumulative(series):
    counts = [point["count"] for point in series]
    assert counts == sorted(counts)
    periods = [point["period"] for point in series]
    assert periods == sorted(periods) and len(periods) == len(set(periods))


def test_no_body_returns_five_keys(mock_env):
    mock_env()
    status, data = call()
    assert status == 200
    assert set(data) == FIXED_KEYS
    for chart in data.values():
        assert_chart_shape(chart)
    assert data["Custom"] == rta._empty_chart()
    # 7D window (Aug 25 - Sep 1) has orgs 7 and 8
    assert data["7D"]["rating_distribution"] == [
        {"rating": 2, "count": 1},
        {"rating": 4, "count": 1},
    ]


def test_cumulative_trend_includes_history_before_window(mock_env):
    mock_env()
    _, data = call()
    # non_profit: 4 created before Aug 25, org 8 on Aug 28 -> running total 5
    assert data["7D"]["organization_mix_trend"]["non_profit"] == [
        {"period": "2026-08-28", "count": 5}
    ]
    assert data["7D"]["organization_mix_trend"]["for_profit"] == [
        {"period": "2026-08-27", "count": 3}
    ]
    # All uses monthly periods and ends at the all-time total
    all_np = data["All"]["organization_mix_trend"]["non_profit"]
    assert all_np[0]["period"] == "2024-08" and all_np[-1]["count"] == 5


def test_trends_are_non_decreasing_everywhere(mock_env):
    mock_env()
    _, data = call()
    for bucket in ("7D", "30D", "1Y", "All"):
        for series in data[bucket]["organization_mix_trend"].values():
            assert_cumulative(series)


def test_period_formats(mock_env):
    mock_env()
    _, data = call()
    assert len(data["30D"]["organization_mix_trend"]["non_profit"][0]["period"]) == 10
    assert len(data["1Y"]["organization_mix_trend"]["non_profit"][0]["period"]) == 7


def test_country_filter_by_code_and_name(mock_env):
    mock_env()
    _, by_code = call({"country": "IND"})
    _, by_name = call({"country": "india"})
    assert by_code == by_name
    assert by_code["All"]["rating_distribution"] == [
        {"rating": 1, "count": 1},
        {"rating": 5, "count": 1},
    ]


def test_unknown_country_returns_empty(mock_env):
    mock_env()
    status, data = call({"country": "Atlantis"})
    assert status == 200
    assert data["All"] == rta._empty_chart()


def test_rating_custom_only(mock_env):
    mock_env()
    status, data = call({"rating_start_date": "2026-01-01", "rating_end_date": "2026-08-27"})
    assert status == 200 and set(data) == {"Custom"}
    assert data["Custom"]["rating_distribution"] == [
        {"rating": 4, "count": 2},
        {"rating": 5, "count": 1},
    ]
    assert data["Custom"]["organization_mix_trend"] == {"non_profit": [], "for_profit": []}


def test_custom_end_date_is_inclusive(mock_env):
    mock_env()
    _, data = call({"rating_start_date": "2026-08-28", "rating_end_date": "2026-08-28"})
    assert data["Custom"]["rating_distribution"] == [{"rating": 2, "count": 1}]


def test_type_custom_only(mock_env):
    mock_env()
    status, data = call({"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"})
    assert status == 200 and set(data) == {"Custom"}
    assert data["Custom"]["rating_distribution"] == []
    trend = data["Custom"]["organization_mix_trend"]
    assert trend["non_profit"] == [{"period": "2025-06-01", "count": 2}]
    assert trend["for_profit"] == [{"period": "2025-10-05", "count": 2}]


def test_both_custom_pairs(mock_env):
    mock_env()
    _, data = call({
        "rating_start_date": "2026-01-01", "rating_end_date": "2026-12-31",
        "type_start_date": "2025-01-01", "type_end_date": "2025-12-31",
    })
    assert set(data) == {"Custom"}
    assert data["Custom"]["rating_distribution"]
    assert data["Custom"]["organization_mix_trend"]["non_profit"]


@pytest.mark.parametrize("body", [
    {"rating_start_date": "2026-01-01"},
    {"type_end_date": "2025-12-31"},
    {"rating_start_date": "2026/01/01", "rating_end_date": "2026-06-30"},
    {"type_start_date": "2025-02-30", "type_end_date": "2025-12-31"},
    {"rating_start_date": "2026-06-30", "rating_end_date": "2026-01-01"},
    {"type_start_date": 20250101, "type_end_date": "2025-12-31"},
    {"country": 42},
])
def test_invalid_input_returns_400(mock_env, body):
    mock_env()
    status, data = call(body)
    assert status == 400 and "error" in data


def test_malformed_json_body_returns_400(mock_env):
    mock_env()
    response = rta.lambda_handler({"body": "{not json"}, None)
    assert response["statusCode"] == 400


def test_empty_csv_does_not_crash(mock_env):
    mock_env(rows=[])
    status, data = call()
    assert status == 200 and set(data) == FIXED_KEYS
    for chart in data.values():
        assert chart == rta._empty_chart()
    status, data = call({"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"})
    assert status == 200 and data["Custom"] == rta._empty_chart()


def test_single_row_csv(mock_env):
    mock_env(rows=[(1, 3, "for_profit", 1, "2026-08-30")])
    status, data = call()
    assert status == 200
    assert data["7D"]["organization_mix_trend"]["for_profit"] == [
        {"period": "2026-08-30", "count": 1}
    ]


def test_bad_rows_are_skipped(mock_env):
    mock_env(rows=[
        (1, 9, "non_profit", 1, "2026-08-30"),      # rating out of range
        (2, None, "for_profit", 1, "2026-08-30"),   # missing rating
        (3, 4, "non_profit", 1, "not-a-date"),      # unparseable date
        (4, 4, "Non-Profit", 1, "2026-08-31"),      # messy type spelling
    ])
    status, data = call()
    assert status == 200
    assert data["7D"]["rating_distribution"] == [{"rating": 4, "count": 1}]
    assert data["7D"]["organization_mix_trend"]["non_profit"][-1]["count"] == 2


def test_one_year_window_is_calendar_year(mock_env):
    # 2025-09-01 is exactly CURRENT_DATE - 1 year, so it is inside 1Y; 2025-08-31 is not
    mock_env(rows=[
        (1, 3, "non_profit", 1, "2025-08-31"),
        (2, 4, "non_profit", 1, "2025-09-01"),
    ])
    _, data = call()
    assert data["1Y"]["rating_distribution"] == [{"rating": 4, "count": 1}]
    assert data["1Y"]["organization_mix_trend"]["non_profit"] == [
        {"period": "2025-09", "count": 2}
    ]


class FakeCursor:
    def __init__(self, rows):
        self.rows, self.closed = rows, False

    def execute(self, query):
        self.query = query

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, rows):
        self.fake_cursor, self.closed = FakeCursor(rows), False

    def cursor(self, cursor_factory=None):
        return self.fake_cursor

    def close(self):
        self.closed = True


def test_db_path_uses_same_chart_logic(monkeypatch):
    rows = [
        {"org_id": 1, "org_rating": 5, "org_type": "non_profit",
         "created_at": datetime(2026, 8, 28, 9, 30), "country_code": "USA", "country_name": "United States"},
        {"org_id": 2, "org_rating": 3, "org_type": "for_profit",
         "created_at": datetime(2026, 8, 29, 10, 0), "country_code": "IND", "country_name": "India"},
    ]
    conn = FakeConnection(rows)
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.setattr(rta, "get_db_connection", lambda: conn)
    monkeypatch.setattr(rta, "_today", lambda: TODAY)

    status, data = call({"country": "USA"})
    assert status == 200
    assert data["7D"]["rating_distribution"] == [{"rating": 5, "count": 1}]
    assert "virginia_dev_saayam_rdbms.organizations" in conn.fake_cursor.query
    assert conn.closed and conn.fake_cursor.closed


def test_db_failure_returns_500(monkeypatch):
    def boom():
        raise RuntimeError("connection refused")
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.setattr(rta, "get_db_connection", boom)
    status, data = call()
    assert status == 500 and "connection refused" in data["error"]
