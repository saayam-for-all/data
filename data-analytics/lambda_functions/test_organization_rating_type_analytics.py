import importlib.util
import json
import os
from pathlib import Path

import pandas as pd
import pytest

MODULE_PATH = Path(__file__).with_name("organization_rating_type_analytics.py")
SPEC = importlib.util.spec_from_file_location("organization_rating_type_analytics", MODULE_PATH)
analytics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analytics)


def write_data(folder, rows, country_name_only=False):
    orgs = pd.DataFrame(rows, columns=["org_id", "org_rating", "org_type", "state_id", "created_at"])
    orgs.to_csv(folder / "organizations.csv", index=False)
    pd.DataFrame(
        [
            {"state_id": "CA", "country_id": "1"},
            {"state_id": "NY", "country_id": "2"},
        ]
    ).to_csv(folder / "states.csv", index=False)
    country_rows = [
        {"country_id": "1", "country_name": "UNITED_STATES", "country_code": "USA"},
        {"country_id": "2", "country_name": "CANADA", "country_code": "CAN"},
    ]
    if country_name_only:
        country_rows = [{"country_id": row["country_id"], "country_name": row["country_name"]} for row in country_rows]
    pd.DataFrame(country_rows).to_csv(folder / "countries.csv", index=False)


def make_rows():
    today = pd.Timestamp.now().normalize()
    return [
        ["O1", 5, "non_profit", "CA", (today - pd.Timedelta(days=1) + pd.Timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")],
        ["O2", 4, "for_profit", "NY", (today - pd.Timedelta(days=3) + pd.Timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")],
        ["O3", 3, "Non-Profit", "CA", (today - pd.Timedelta(days=20) + pd.Timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")],
        ["O4", 5, "For-profit", "CA", (today - pd.Timedelta(days=40) + pd.Timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")],
        ["O5", 2, "non_profit", "NY", (today - pd.Timedelta(days=400) + pd.Timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")],
    ]


@pytest.fixture

def csv_data(monkeypatch, tmp_path):
    write_data(tmp_path, make_rows())
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    return tmp_path


def invoke(params=None, event=None):
    event = event if event is not None else {"body": json.dumps(params or {})}
    response = analytics.lambda_handler(event, None)
    return response["statusCode"], json.loads(response["body"])


def test_full_response_keys_shapes_and_fixed_windows(csv_data):
    status, body = invoke(event={})
    assert status == 200
    assert list(body) == ["7D", "30D", "1Y", "All", "Custom"]
    assert all(set(chart) == {"rating_distribution", "organization_mix_trend"} for chart in body.values())
    assert body["7D"]["rating_distribution"] == [{"rating": 4, "count": 1}, {"rating": 5, "count": 1}]
    assert body["30D"]["rating_distribution"] == [{"rating": 3, "count": 1}, {"rating": 4, "count": 1}, {"rating": 5, "count": 1}]
    assert body["Custom"] == analytics.empty_charts()


def test_mix_trend_is_sparse_and_cumulative_from_all_history(csv_data):
    _, body = invoke()
    non_profit = body["30D"]["organization_mix_trend"]["non_profit"]
    for_profit = body["30D"]["organization_mix_trend"]["for_profit"]
    assert non_profit[-1]["count"] == 3  # includes O5 and O3 from before the 30-day window
    assert for_profit[0]["count"] == 2  # includes O4 from before the 30-day window
    assert all(a["count"] <= b["count"] for series in (non_profit, for_profit) for a, b in zip(series, series[1:]))
    assert all("period" in point and "count" in point for series in (non_profit, for_profit) for point in series)
    for bucket in analytics.FIXED_WINDOWS:
        trend = body[bucket]["organization_mix_trend"]
        for org_type in analytics.ORG_TYPES:
            counts = [point["count"] for point in trend[org_type]]
            assert counts == sorted(counts)
        if bucket in ("1Y", "All"):
            assert all(len(point["period"]) == 7 for org_type in analytics.ORG_TYPES for point in trend[org_type])
        else:
            assert all(len(point["period"]) == 10 for org_type in analytics.ORG_TYPES for point in trend[org_type])


def test_country_filter_applies_to_both_charts_and_names(csv_data):
    _, by_code = invoke({"country": "USA"})
    _, by_name = invoke({"country": "United-States"})
    assert by_code == by_name
    assert sum(point["count"] for point in by_code["All"]["rating_distribution"]) == 3
    assert by_code["All"]["organization_mix_trend"]["non_profit"][-1]["count"] == 2
    _, custom = invoke({
        "country": "USA",
        "rating_start_date": "2025-01-01",
        "rating_end_date": "2026-12-31",
    })
    assert sum(point["count"] for point in custom["Custom"]["rating_distribution"]) == 3


def test_country_name_only_lookup_supported(monkeypatch, tmp_path):
    write_data(tmp_path, make_rows(), country_name_only=True)
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    status, body = invoke({"country": "Canada"})
    assert status == 200
    assert sum(point["count"] for point in body["All"]["rating_distribution"]) == 2


def test_rating_range_only_is_custom_and_end_day_is_inclusive(csv_data):
    today = pd.Timestamp.now().normalize()
    start = (today - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    status, body = invoke({"rating_start_date": start, "rating_end_date": start})
    assert status == 200
    assert list(body) == ["Custom"]
    assert body["Custom"]["rating_distribution"] == [{"rating": 5, "count": 1}]
    assert body["Custom"]["organization_mix_trend"] == {"non_profit": [], "for_profit": []}


def test_type_range_only_and_both_ranges_are_independent(csv_data):
    old_org_day = (pd.Timestamp.now().normalize() - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    _, type_only = invoke({"type_start_date": old_org_day, "type_end_date": old_org_day})
    assert list(type_only) == ["Custom"]
    assert type_only["Custom"]["rating_distribution"] == []
    assert type_only["Custom"]["organization_mix_trend"]["non_profit"]

    _, both = invoke({
        "rating_start_date": old_org_day, "rating_end_date": old_org_day,
        "type_start_date": (pd.Timestamp.now().normalize() - pd.Timedelta(days=40)).strftime("%Y-%m-%d"),
        "type_end_date": (pd.Timestamp.now().normalize() - pd.Timedelta(days=40)).strftime("%Y-%m-%d"),
    })
    assert list(both) == ["Custom"]
    assert both["Custom"]["rating_distribution"] == [{"rating": 2, "count": 1}]
    assert both["Custom"]["organization_mix_trend"]["non_profit"] == []
    assert both["Custom"]["organization_mix_trend"]["for_profit"]


@pytest.mark.parametrize(
    "params",
    [
        {"rating_start_date": "2025-01-01"},
        {"type_end_date": "2025-01-01"},
        {"rating_start_date": "01/01/2025", "rating_end_date": "2025-02-01"},
        {"type_start_date": "2025-02-01", "type_end_date": "2025-01-01"},
    ],
)
def test_invalid_date_ranges_return_clear_400(params, csv_data):
    status, body = invoke(params)
    assert status == 400
    assert body["error"]


def test_query_string_parameters_supported(csv_data):
    status, body = invoke(event={"body": None, "queryStringParameters": {"country": "CAN"}})
    assert status == 200
    assert sum(point["count"] for point in body["All"]["rating_distribution"]) == 2


def test_empty_and_single_row_inputs_do_not_crash(monkeypatch, tmp_path):
    write_data(tmp_path, [])
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    assert invoke()[0] == 200

    write_data(tmp_path, [["O1", 1, "for_profit", "CA", "2025-01-01 10:00:00"]])
    status, body = invoke({"type_start_date": "2025-01-01", "type_end_date": "2025-01-01"})
    assert status == 200
    assert body["Custom"]["organization_mix_trend"]["for_profit"] == [{"period": "2025-01-01", "count": 1}]


def test_real_db_loader_uses_country_join_and_optional_psycopg2(monkeypatch):
    class Cursor:
        description = [("org_rating",), ("org_type",), ("created_at",), ("country_code",), ("country_name",)]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, args):
            self.query = query
            self.args = args

        def fetchall(self):
            return [(5, "Non-Profit", "2025-01-01", "USA", "UNITED_STATES")]

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            self.closed = True

    class Driver:
        @staticmethod
        def connect(**_kwargs):
            return Connection()

    monkeypatch.setattr(analytics, "psycopg2", Driver)
    for key, value in {"PGHOST": "localhost", "PGDATABASE": "analytics", "PGUSER": "test", "PGPASSWORD": "test"}.items():
        monkeypatch.setenv(key, value)
    result = analytics.load_from_db("USA")
    assert len(result) == 1
    assert result.iloc[0]["org_type"] == "non_profit"
