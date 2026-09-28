"""Tests for the organization growth and location analytics Lambda."""
import csv
import importlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

IMPL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data-analytics",
    "lambda_functions",
)
NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


def _write_fixture(tmp_path, collab_encoder=None):
    collab_encoder = collab_encoder or (lambda value: "true" if value else "false")
    countries = [(1, "USA"), (2, "IND"), (3, "CAN"), (4, "GBR"), (5, "AUS")]
    states = [
        (1, "New York", 1),
        (2, "Delhi", 2),
        (3, "Ontario", 3),
        (4, "London", 4),
        (5, "Sydney", 5),
    ]
    orgs = [
        (1, 1, "NY", True, NOW - timedelta(days=400)),
        (2, 1, "NY", False, NOW - timedelta(days=200)),
        (3, 2, "DEL", True, NOW - timedelta(days=40)),
        (4, 3, "TOR", False, NOW - timedelta(days=29)),
        (5, 4, "LON", True, NOW - timedelta(days=6)),
        (6, 5, "SYD", False, NOW),
    ]
    with open(tmp_path / "countries.csv", "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["country_id", "country_code"])
        writer.writerows(countries)
    with open(tmp_path / "states.csv", "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["state_id", "state_name", "country_id"])
        writer.writerows(states)
    with open(tmp_path / "organizations.csv", "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["org_id", "state_id", "city_name", "is_collaborator", "created_at"])
        for org_id, state_id, city, collaborator, created_at in orgs:
            writer.writerow([
                org_id,
                state_id,
                city,
                collab_encoder(collaborator),
                created_at.strftime("%Y-%m-%d"),
            ])
    return orgs


@pytest.fixture
def module(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.syspath_prepend(IMPL_DIR)
    sys.modules.pop("growth_location_analytics", None)
    loaded = importlib.import_module("growth_location_analytics")
    loaded.clear_data_cache()
    monkeypatch.setattr(loaded, "datetime", FrozenDateTime)
    return loaded


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def _body(response):
    return json.loads(response["body"])


def test_default_has_all_five_buckets(module, tmp_path):
    _write_fixture(tmp_path)
    response = module.lambda_handler({}, None)
    assert response["statusCode"] == 200
    result = _body(response)
    assert list(result) == [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]

    for bucket in result.values():
        assert set(bucket) == {
            "growth_trend",
            "organizations_by_location",
        }
        assert set(bucket["growth_trend"]) == {
            "total_organizations",
            "collaborators",
        }
    assert result["Custom"] == {
        "growth_trend": {
            "total_organizations": [],
            "collaborators": [],
        },
        "organizations_by_location": [],
    }


def test_growth_custom_adds_custom_bucket(module, tmp_path):
    _write_fixture(tmp_path)
    response = module.lambda_handler(
        {"start_date": "2026-08-01", "end_date": "2026-09-27"}, None
    )
    result = _body(response)
    assert response["statusCode"] == 200
    assert list(result) == ["7D", "30D", "1Y", "All", "Custom"]
    assert result["Custom"]["growth_trend"]["total_organizations"]
    assert result["Custom"]["organizations_by_location"] == []


def test_location_custom_adds_custom_bucket(module, tmp_path):
    _write_fixture(tmp_path)
    response = module.lambda_handler(
        {"location_start_date": "2026-08-01", "location_end_date": "2026-09-27"}, None
    )
    result = _body(response)
    assert response["statusCode"] == 200
    assert result["Custom"]["growth_trend"] == {
        "total_organizations": [],
        "collaborators": [],
    }
    assert result["Custom"]["organizations_by_location"]


def test_both_custom_ranges_are_independent(module, tmp_path):
    _write_fixture(tmp_path)
    response = module.lambda_handler(
        {
            "start_date": "2026-09-21",
            "end_date": "2026-09-27",
            "location_start_date": "2026-08-01",
            "location_end_date": "2026-08-31",
        },
        None,
    )
    custom = _body(response)["Custom"]
    assert custom["growth_trend"]["total_organizations"]
    assert custom["organizations_by_location"]


def test_half_growth_pair_returns_400(module, tmp_path):
    _write_fixture(tmp_path)
    response = module.lambda_handler({"start_date": "2026-01-01"}, None)
    assert response["statusCode"] == 400


def test_half_location_pair_returns_400(module, tmp_path):
    _write_fixture(tmp_path)
    response = module.lambda_handler({"location_end_date": "2026-01-01"}, None)
    assert response["statusCode"] == 400


@pytest.mark.parametrize(
    "event",
    [
        {"start_date": "bad", "end_date": "2026-01-02"},
        {"start_date": "2026-1-1", "end_date": "2026-01-02"},
        {"start_date": "2026-02-30", "end_date": "2026-03-01"},
        {"location_start_date": "2026/01/01", "location_end_date": "2026-01-02"},
    ],
)
def test_invalid_dates_return_400(module, tmp_path, event):
    _write_fixture(tmp_path)
    assert module.lambda_handler(event, None)["statusCode"] == 400


def test_start_after_end_returns_400(module, tmp_path):
    _write_fixture(tmp_path)
    response = module.lambda_handler(
        {"start_date": "2026-06-30", "end_date": "2026-01-01"}, None
    )
    assert response["statusCode"] == 400


def test_seven_day_window_is_exactly_seven_calendar_days(module, tmp_path):
    _write_fixture(tmp_path)
    result = _body(module.lambda_handler({}, None))["7D"]
    periods = [row["period"] for row in result["growth_trend"]["total_organizations"]]
    assert "2026-09-21" in periods
    assert "2026-09-27" in periods


def test_thirty_day_window_includes_day_29(module, tmp_path):
    _write_fixture(tmp_path)
    result = _body(module.lambda_handler({}, None))["30D"]
    periods = [row["period"] for row in result["growth_trend"]["total_organizations"]]
    assert "2026-08-29" in periods


def test_one_year_uses_calendar_month_buckets(module, tmp_path):
    _write_fixture(tmp_path)
    result = _body(module.lambda_handler({}, None))["1Y"]
    periods = [row["period"] for row in result["growth_trend"]["total_organizations"]]
    assert all(len(period) == 7 for period in periods)


def test_all_uses_calendar_month_buckets(module, tmp_path):
    _write_fixture(tmp_path)
    result = _body(module.lambda_handler({}, None))["All"]
    periods = [row["period"] for row in result["growth_trend"]["total_organizations"]]
    assert all(len(period) == 7 for period in periods)


def test_total_organizations_is_all_time_cumulative(module, tmp_path):
    orgs = _write_fixture(tmp_path)
    result = _body(module.lambda_handler({}, None))
    assert result["7D"]["growth_trend"]["total_organizations"][-1]["count"] == len(orgs)
    assert result["All"]["growth_trend"]["total_organizations"][-1]["count"] == len(orgs)


def test_collaborators_are_per_period_not_cumulative(module, tmp_path):
    _write_fixture(tmp_path)
    result = _body(module.lambda_handler({}, None))["All"]["growth_trend"]
    assert sum(row["count"] for row in result["collaborators"]) == 3


def test_growth_series_share_same_periods(module, tmp_path):
    _write_fixture(tmp_path)
    result = _body(module.lambda_handler({}, None))["All"]["growth_trend"]
    total_periods = [row["period"] for row in result["total_organizations"]]
    collaborator_periods = [row["period"] for row in result["collaborators"]]
    assert total_periods == collaborator_periods


def test_locations_return_top_four_without_other_or_percentage(module, tmp_path):
    _write_fixture(tmp_path)
    locations = _body(module.lambda_handler({}, None))["All"]["organizations_by_location"]
    assert len(locations) == 4
    assert all(set(row) == {"country", "count"} for row in locations)
    assert all(row["country"] != "Other" for row in locations)


def test_location_aggregates_states_into_country(module, tmp_path):
    _write_fixture(tmp_path)
    locations = _body(module.lambda_handler({}, None))["All"]["organizations_by_location"]
    usa = next(row for row in locations if row["country"] == "USA")
    assert usa["count"] == 2


def test_y_n_collaborator_encoding(module, tmp_path):
    _write_fixture(tmp_path, collab_encoder=lambda value: "Y" if value else "N")
    result = _body(module.lambda_handler({}, None))["All"]["growth_trend"]
    assert sum(row["count"] for row in result["collaborators"]) == 3


def test_invalid_collaborator_encoding_fails_loudly(module, tmp_path):
    _write_fixture(tmp_path, collab_encoder=lambda value: "MAYBE")
    response = module.lambda_handler({}, None)
    assert response["statusCode"] == 500
    assert "MAYBE" not in response["body"]


def test_mixed_date_and_timestamp_formats(module, tmp_path):
    _write_fixture(tmp_path)
    with open(tmp_path / "organizations.csv", "a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([7, 1, "NY", "true", "2026-09-25T10:30:00+00:00"])
    result = _body(module.lambda_handler({}, None))["All"]["growth_trend"]
    assert result["total_organizations"][-1]["count"] == 7


def test_duplicate_state_id_returns_500(module, tmp_path):
    _write_fixture(tmp_path)
    with open(tmp_path / "states.csv", "a", newline="") as file:
        csv.writer(file).writerow([1, "Duplicate", 1])
    assert module.lambda_handler({}, None)["statusCode"] == 500


def test_duplicate_country_id_returns_500(module, tmp_path):
    _write_fixture(tmp_path)
    with open(tmp_path / "countries.csv", "a", newline="") as file:
        csv.writer(file).writerow([1, "DUP"])
    assert module.lambda_handler({}, None)["statusCode"] == 500


def test_unmatched_state_is_reported_as_unknown(module, tmp_path):
    _write_fixture(tmp_path)

    with open(tmp_path / "organizations.csv", "a", newline="") as file:
        writer = csv.writer(file)

        for org_id in range(100, 110):
            writer.writerow(
                [
                    org_id,
                    999,
                    "Unknown City",
                    "false",
                    "2026-09-27",
                ]
            )

    module.clear_data_cache()

    locations = _body(
        module.lambda_handler({}, None)
    )["All"]["organizations_by_location"]

    unknown = next(
        (
            row
            for row in locations
            if row["country"] == "Unknown"
        ),
        None,
    )

    assert unknown is not None
    assert unknown["count"] == 10


def test_api_gateway_string_body(module, tmp_path):
    _write_fixture(tmp_path)
    event = {"body": json.dumps({"start_date": "2026-09-01", "end_date": "2026-09-27"})}
    response = module.lambda_handler(event, None)
    assert response["statusCode"] == 200
    assert "Custom" in _body(response)


def test_invalid_json_body_returns_400(module, tmp_path):
    _write_fixture(tmp_path)
    response = module.lambda_handler({"body": "{bad json"}, None)
    assert response["statusCode"] == 400


def test_data_is_loaded_once_per_warm_instance(module, tmp_path, monkeypatch):
    _write_fixture(tmp_path)
    calls = {"count": 0}
    original = module.load_data

    def counted_load():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(module, "load_data", counted_load)
    module.clear_data_cache()
    for _ in range(3):
        assert module.lambda_handler({}, None)["statusCode"] == 200
    assert calls["count"] == 1


def test_empty_organizations_does_not_crash(module, tmp_path):
    _write_fixture(tmp_path)
    with open(tmp_path / "organizations.csv", "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["org_id", "state_id", "city_name", "is_collaborator", "created_at"])
    response = module.lambda_handler({}, None)
    assert response["statusCode"] == 200
    result = _body(response)
    assert result["All"]["growth_trend"] == {"total_organizations": [], "collaborators": []}
    assert result["All"]["organizations_by_location"] == []
