import json
from pathlib import Path

import pandas as pd
import pytest

import growth_location_analytics as api


REQUIRED_FILES = ["organizations.csv", "states.csv", "countries.csv"]


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    write_csv(
        tmp_path / "countries.csv",
        [
            {"country_id": "1", "country_code": "USA"},
            {"country_id": "2", "country_code": "IND"},
            {"country_id": "3", "country_code": "CAN"},
            {"country_id": "4", "country_code": "GBR"},
            {"country_id": "5", "country_code": "AUS"},
        ],
        ["country_id", "country_code"],
    )
    write_csv(
        tmp_path / "states.csv",
        [
            {"state_id": "TX", "state_name": "TEXAS", "country_id": "1"},
            {"state_id": "FL", "state_name": "FLORIDA", "country_id": "1"},
            {"state_id": "DL", "state_name": "DELHI", "country_id": "2"},
            {"state_id": "ON", "state_name": "ONTARIO", "country_id": "3"},
            {"state_id": "LDN", "state_name": "LONDON", "country_id": "4"},
            {"state_id": "NSW", "state_name": "NEW_SOUTH_WALES", "country_id": "5"},
        ],
        ["state_id", "state_name", "country_id"],
    )
    write_csv(
        tmp_path / "organizations.csv",
        [
            {"org_id": "ORG1", "state_id": "TX", "city_name": "Austin", "is_collaborator": "TRUE", "created_at": "2020-01-15 08:00:00"},
            {"org_id": "ORG2", "state_id": "TX", "city_name": "Dallas", "is_collaborator": "FALSE", "created_at": "2025-10-03 08:00:00"},
            {"org_id": "ORG3", "state_id": "FL", "city_name": "Miami", "is_collaborator": "TRUE", "created_at": "2025-10-12 08:00:00"},
            {"org_id": "ORG4", "state_id": "DL", "city_name": "Delhi", "is_collaborator": "TRUE", "created_at": "2026-01-10 08:00:00"},
            {"org_id": "ORG5", "state_id": "ON", "city_name": "Toronto", "is_collaborator": "FALSE", "created_at": "2026-01-11 08:00:00"},
            {"org_id": "ORG6", "state_id": "LDN", "city_name": "London", "is_collaborator": "TRUE", "created_at": "2026-02-10 08:00:00"},
            {"org_id": "ORG7", "state_id": "NSW", "city_name": "Sydney", "is_collaborator": "FALSE", "created_at": "2026-03-10 08:00:00"},
            {"org_id": "ORG8", "state_id": "DL", "city_name": "Delhi", "is_collaborator": "TRUE", "created_at": "2026-06-05 08:00:00"},
        ],
        ["org_id", "state_id", "city_name", "is_collaborator", "created_at"],
    )
    return tmp_path


def call_with_data(monkeypatch, fixture_dir, event):
    monkeypatch.setenv("MOCK_DATA_DIR", str(fixture_dir))
    return api.lambda_handler(event)


def body(response):
    return json.loads(response["body"])


def test_no_body_has_exact_top_level_shape(monkeypatch, fixture_dir):
    monkeypatch.setattr(api, "get_today", lambda: pd.Timestamp("2026-09-17"))
    result = body(call_with_data(monkeypatch, fixture_dir, {}))

    assert list(result.keys()) == ["7D", "30D", "1Y", "All", "Custom"]
    for bucket in result:
        assert set(result[bucket].keys()) == {
            "growth_trend",
            "organizations_by_location",
        }
        assert set(result[bucket]["growth_trend"].keys()) == {
            "total_organizations",
            "collaborators",
        }
    assert result["Custom"]["growth_trend"] == {
        "total_organizations": [],
        "collaborators": [],
    }
    assert result["Custom"]["organizations_by_location"] == []


def test_growth_custom_only_populates_growth_not_location(monkeypatch, fixture_dir):
    monkeypatch.setattr(api, "get_today", lambda: pd.Timestamp("2026-09-17"))
    result = body(
        call_with_data(
            monkeypatch,
            fixture_dir,
            {"start_date": "2025-10-01", "end_date": "2026-01-31"},
        )
    )
    assert result["Custom"]["growth_trend"]["total_organizations"]
    assert result["Custom"]["organizations_by_location"] == []


def test_location_custom_only_populates_location_not_growth(monkeypatch, fixture_dir):
    monkeypatch.setattr(api, "get_today", lambda: pd.Timestamp("2026-09-17"))
    result = body(
        call_with_data(
            monkeypatch,
            fixture_dir,
            {
                "location_start_date": "2025-10-01",
                "location_end_date": "2026-01-31",
            },
        )
    )
    assert result["Custom"]["growth_trend"] == {
        "total_organizations": [],
        "collaborators": [],
    }
    assert result["Custom"]["organizations_by_location"]


def test_both_custom_pairs_are_independent(monkeypatch, fixture_dir):
    monkeypatch.setattr(api, "get_today", lambda: pd.Timestamp("2026-09-17"))
    result = body(
        call_with_data(
            monkeypatch,
            fixture_dir,
            {
                "start_date": "2025-10-01",
                "end_date": "2025-10-31",
                "location_start_date": "2026-01-01",
                "location_end_date": "2026-01-31",
            },
        )
    )
    assert result["Custom"]["growth_trend"]["total_organizations"]
    assert result["Custom"]["organizations_by_location"]


def test_invalid_date_format_returns_400(monkeypatch, fixture_dir):
    response = call_with_data(
        monkeypatch,
        fixture_dir,
        {"start_date": "2026/01/01", "end_date": "2026-01-10"},
    )
    assert response["statusCode"] == 400
    assert set(body(response).keys()) == {"error"}


def test_start_after_end_returns_400(monkeypatch, fixture_dir):
    response = call_with_data(
        monkeypatch,
        fixture_dir,
        {"start_date": "2026-02-01", "end_date": "2026-01-01"},
    )
    assert response["statusCode"] == 400


def test_location_start_after_end_returns_400(monkeypatch, fixture_dir):
    response = call_with_data(
        monkeypatch,
        fixture_dir,
        {
            "location_start_date": "2026-02-01",
            "location_end_date": "2026-01-01",
        },
    )
    assert response["statusCode"] == 400


def test_partial_custom_pair_returns_400(monkeypatch, fixture_dir):
    response = call_with_data(monkeypatch, fixture_dir, {"start_date": "2026-01-01"})
    assert response["statusCode"] == 400


def test_total_organizations_is_all_time_and_not_reset(monkeypatch, fixture_dir):
    monkeypatch.setattr(api, "get_today", lambda: pd.Timestamp("2026-09-17"))
    result = body(
        call_with_data(
            monkeypatch,
            fixture_dir,
            {"start_date": "2025-10-01", "end_date": "2026-03-31"},
        )
    )
    totals = result["Custom"]["growth_trend"]["total_organizations"]
    assert totals == [
        {"period": "2025-10-03", "count": 2},
        {"period": "2025-10-12", "count": 3},
        {"period": "2026-01-10", "count": 4},
        {"period": "2026-01-11", "count": 5},
        {"period": "2026-02-10", "count": 6},
        {"period": "2026-03-10", "count": 7},
    ]


def test_collaborators_are_per_period_not_cumulative(monkeypatch, fixture_dir):
    monkeypatch.setattr(api, "get_today", lambda: pd.Timestamp("2026-09-17"))
    result = body(
        call_with_data(
            monkeypatch,
            fixture_dir,
            {"start_date": "2025-10-01", "end_date": "2026-03-31"},
        )
    )
    collaborators = result["Custom"]["growth_trend"]["collaborators"]
    counts = [row["count"] for row in collaborators]
    assert counts == [0, 1, 1, 0, 1, 0]


def test_7d_30d_and_custom_are_daily(monkeypatch, fixture_dir):
    monkeypatch.setattr(api, "get_today", lambda: pd.Timestamp("2026-09-17"))
    organizations, _, _ = api.load_data(fixture_dir)

    daily = api.build_growth_trend(
        organizations,
        pd.Timestamp("2026-01-10"),
        pd.Timestamp("2026-01-31"),
        "day",
    )
    assert all(len(row["period"]) == 10 for row in daily["total_organizations"])


def test_1y_and_all_are_monthly(monkeypatch, fixture_dir):
    monkeypatch.setattr(api, "get_today", lambda: pd.Timestamp("2026-09-17"))
    result = body(call_with_data(monkeypatch, fixture_dir, {}))
    for bucket in ("1Y", "All"):
        for row in result[bucket]["growth_trend"]["total_organizations"]:
            assert len(row["period"]) == 7
            assert row["period"][4] == "-"


def test_all_last_total_equals_dataset_row_count(monkeypatch, fixture_dir):
    monkeypatch.setattr(api, "get_today", lambda: pd.Timestamp("2026-09-17"))
    result = body(call_with_data(monkeypatch, fixture_dir, {}))
    assert result["All"]["growth_trend"]["total_organizations"][-1]["count"] == 8


def test_location_aggregates_by_country_and_top4_only(monkeypatch, fixture_dir):
    organizations, _, _ = api.load_data(fixture_dir)
    result = api.organizations_by_location(
        organizations,
        pd.Timestamp("2020-01-01"),
        pd.Timestamp("2026-12-31"),
    )
    assert len(result) == 4
    assert {item["country"] for item in result} == {"USA", "IND", "CAN", "AUS"}
    assert all("Other" not in item for item in result)
    assert all("percentage" not in item for item in result)
    assert next(item["count"] for item in result if item["country"] == "USA") == 3


def test_no_in_window_activity_returns_empty_arrays(monkeypatch, fixture_dir):
    organizations, _, _ = api.load_data(fixture_dir)
    growth = api.build_growth_trend(
        organizations,
        pd.Timestamp("2027-01-01"),
        pd.Timestamp("2027-01-31"),
        "day",
    )
    location = api.organizations_by_location(
        organizations,
        pd.Timestamp("2027-01-01"),
        pd.Timestamp("2027-01-31"),
    )
    assert growth == {"total_organizations": [], "collaborators": []}
    assert location == []


def test_empty_organizations_does_not_crash(tmp_path: Path):
    write_csv(
        tmp_path / "countries.csv",
        [{"country_id": "1", "country_code": "USA"}],
        ["country_id", "country_code"],
    )
    write_csv(
        tmp_path / "states.csv",
        [{"state_id": "TX", "state_name": "TEXAS", "country_id": "1"}],
        ["state_id", "state_name", "country_id"],
    )
    write_csv(
        tmp_path / "organizations.csv",
        [],
        ["org_id", "state_id", "city_name", "is_collaborator", "created_at"],
    )
    organizations, _, _ = api.load_data(tmp_path)
    assert organizations.empty
    assert api.fixed_ranges(organizations)["All"][2] == "month"


def test_one_row_organizations_does_not_crash(tmp_path: Path):
    write_csv(
        tmp_path / "countries.csv",
        [{"country_id": "1", "country_code": "USA"}],
        ["country_id", "country_code"],
    )
    write_csv(
        tmp_path / "states.csv",
        [{"state_id": "TX", "state_name": "TEXAS", "country_id": "1"}],
        ["state_id", "state_name", "country_id"],
    )
    write_csv(
        tmp_path / "organizations.csv",
        [{"org_id": "ORG1", "state_id": "TX", "city_name": "Austin", "is_collaborator": "TRUE", "created_at": "2026-01-15 08:00:00"}],
        ["org_id", "state_id", "city_name", "is_collaborator", "created_at"],
    )
    organizations, _, _ = api.load_data(tmp_path)
    assert api.build_growth_trend(
        organizations,
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-01-31"),
        "month",
    )["total_organizations"] == [{"period": "2026-01", "count": 1}]


def test_fixed_windows_use_same_window_for_growth_and_location(monkeypatch, fixture_dir):
    monkeypatch.setattr(api, "get_today", lambda: pd.Timestamp("2026-09-17"))
    result = body(call_with_data(monkeypatch, fixture_dir, {}))

    for bucket in ("7D", "30D"):
        assert result[bucket]["growth_trend"] == {
            "total_organizations": [],
            "collaborators": [],
        }
        assert result[bucket]["organizations_by_location"] == []

    # 1Y has in-window activity in the fixture. The two charts therefore use
    # the same fixed date window and both contain data.
    assert result["1Y"]["growth_trend"]["total_organizations"]
    assert result["1Y"]["organizations_by_location"]


def test_growth_series_share_the_same_periods(monkeypatch, fixture_dir):
    organizations, _, _ = api.load_data(fixture_dir)
    result = api.build_growth_trend(
        organizations,
        pd.Timestamp("2025-10-01"),
        pd.Timestamp("2026-03-31"),
        "month",
    )
    total_periods = [row["period"] for row in result["total_organizations"]]
    collaborator_periods = [row["period"] for row in result["collaborators"]]
    assert total_periods == collaborator_periods


def test_monthly_periods_have_month_granularity_and_sorted_order(monkeypatch, fixture_dir):
    organizations, _, _ = api.load_data(fixture_dir)
    result = api.build_growth_trend(
        organizations,
        pd.Timestamp("2025-10-01"),
        pd.Timestamp("2026-03-31"),
        "month",
    )
    periods = [row["period"] for row in result["total_organizations"]]
    assert periods == sorted(periods)
    assert all(len(period) == 7 and period[4] == "-" for period in periods)


def test_location_counts_are_window_scoped(monkeypatch, fixture_dir):
    organizations, _, _ = api.load_data(fixture_dir)
    result = api.organizations_by_location(
        organizations,
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-01-31"),
    )
    assert result == [
        {"country": "CAN", "count": 1},
        {"country": "IND", "count": 1},
    ]
