"""Tests for Growth & Location Analytics API."""

import json
import os
import sys

import pandas as pd
import pytest


LAMBDA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "lambda_functions",
    )
)

sys.path.insert(0, LAMBDA_DIR)

import growth_location_analytics as api


def make_organizations():
    return pd.DataFrame(
        [
            {
                "org_id": 1,
                "state_id": "TX",
                "city_name": "Austin",
                "is_collaborator": True,
                "created_at": pd.Timestamp("2026-01-01 10:00:00"),
            },
            {
                "org_id": 2,
                "state_id": "FL",
                "city_name": "Miami",
                "is_collaborator": False,
                "created_at": pd.Timestamp("2026-01-02 10:00:00"),
            },
            {
                "org_id": 3,
                "state_id": "KA",
                "city_name": "Bengaluru",
                "is_collaborator": True,
                "created_at": pd.Timestamp("2026-02-05 10:00:00"),
            },
            {
                "org_id": 4,
                "state_id": "TX",
                "city_name": "Dallas",
                "is_collaborator": True,
                "created_at": pd.Timestamp("2026-03-10 10:00:00"),
            },
        ]
    )


def make_states():
    return pd.DataFrame(
        [
            {
                "state_id": "TX",
                "state_name": "Texas",
                "country_id": 1,
            },
            {
                "state_id": "FL",
                "state_name": "Florida",
                "country_id": 1,
            },
            {
                "state_id": "KA",
                "state_name": "Karnataka",
                "country_id": 2,
            },
        ]
    )


def make_countries():
    return pd.DataFrame(
        [
            {
                "country_id": 1,
                "country_code": "USA",
            },
            {
                "country_id": 2,
                "country_code": "IND",
            },
        ]
    )


@pytest.fixture
def mock_data(monkeypatch):
    organizations = make_organizations()
    states = make_states()
    countries = make_countries()

    monkeypatch.setattr(
        api,
        "load_data",
        lambda: (
            organizations.copy(),
            states.copy(),
            countries.copy(),
        ),
    )

    monkeypatch.setattr(
        api,
        "current_date",
        lambda: pd.Timestamp("2026-03-15"),
    )

    return organizations, states, countries


def parse_body(response):
    return json.loads(response["body"])


def test_no_body_returns_exact_five_buckets(mock_data):
    response = api.lambda_handler({}, None)

    assert response["statusCode"] == 200

    body = parse_body(response)

    assert list(body.keys()) == [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]

    for bucket in body.values():
        assert set(bucket.keys()) == {
            "growth_trend",
            "organizations_by_location",
        }

        assert set(bucket["growth_trend"].keys()) == {
            "total_organizations",
            "collaborators",
        }

    assert body["Custom"] == {
        "growth_trend": {
            "total_organizations": [],
            "collaborators": [],
        },
        "organizations_by_location": [],
    }


def test_growth_custom_only_populates_growth(mock_data):
    event = {
        "body": json.dumps(
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            }
        )
    }

    body = parse_body(api.lambda_handler(event, None))

    assert body["Custom"]["growth_trend"]["total_organizations"]
    assert body["Custom"]["organizations_by_location"] == []


def test_location_custom_only_populates_location(mock_data):
    event = {
        "body": json.dumps(
            {
                "location_start_date": "2026-01-01",
                "location_end_date": "2026-01-31",
            }
        )
    }

    body = parse_body(api.lambda_handler(event, None))

    assert body["Custom"]["growth_trend"] == {
        "total_organizations": [],
        "collaborators": [],
    }

    assert body["Custom"]["organizations_by_location"] == [
        {
            "country": "USA",
            "count": 2,
        }
    ]


def test_both_custom_ranges_are_independent(mock_data):
    event = {
        "body": json.dumps(
            {
                "start_date": "2026-02-01",
                "end_date": "2026-02-28",
                "location_start_date": "2026-01-01",
                "location_end_date": "2026-01-31",
            }
        )
    }

    body = parse_body(api.lambda_handler(event, None))

    growth = body["Custom"]["growth_trend"]

    assert growth["total_organizations"] == [
        {
            "period": "2026-02-05",
            "count": 3,
        }
    ]

    assert growth["collaborators"] == [
        {
            "period": "2026-02-05",
            "count": 1,
        }
    ]

    assert body["Custom"]["organizations_by_location"] == [
        {
            "country": "USA",
            "count": 2,
        }
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "start_date": "bad-date",
            "end_date": "2026-02-01",
        },
        {
            "start_date": "2026-03-01",
            "end_date": "2026-02-01",
        },
        {
            "location_start_date": "bad-date",
            "location_end_date": "2026-02-01",
        },
        {
            "location_start_date": "2026-03-01",
            "location_end_date": "2026-02-01",
        },
    ],
)
def test_invalid_custom_ranges_return_400(mock_data, payload):
    response = api.lambda_handler(
        {"body": json.dumps(payload)},
        None,
    )

    assert response["statusCode"] == 400
    assert "error" in parse_body(response)


def test_running_total_does_not_reset_at_window_start():
    organizations = make_organizations()

    result = api.build_growth_trend(
        organizations,
        (
            pd.Timestamp("2026-02-01"),
            pd.Timestamp("2026-03-31"),
        ),
        "month",
    )

    assert result["total_organizations"] == [
        {
            "period": "2026-02",
            "count": 3,
        },
        {
            "period": "2026-03",
            "count": 4,
        },
    ]

    assert result["collaborators"] == [
        {
            "period": "2026-02",
            "count": 1,
        },
        {
            "period": "2026-03",
            "count": 1,
        },
    ]


def test_one_year_window_is_exactly_365_inclusive_days(monkeypatch):
    monkeypatch.setattr(
        api,
        "current_date",
        lambda: pd.Timestamp("2026-09-29"),
    )

    start_date, end_date = api.get_fixed_window("1Y")

    assert start_date == pd.Timestamp("2025-09-30")
    assert end_date == pd.Timestamp("2026-09-29")
    assert (end_date - start_date).days + 1 == 365


def test_day_and_month_grouping():
    organizations = make_organizations()

    day_result = api.build_growth_trend(
        organizations,
        (
            pd.Timestamp("2026-01-01"),
            pd.Timestamp("2026-01-31"),
        ),
        "day",
    )

    month_result = api.build_growth_trend(
        organizations,
        None,
        "month",
    )

    assert [
        row["period"]
        for row in day_result["total_organizations"]
    ] == [
        "2026-01-01",
        "2026-01-02",
    ]

    assert [
        row["period"]
        for row in month_result["total_organizations"]
    ] == [
        "2026-01",
        "2026-02",
        "2026-03",
    ]


def test_location_aggregates_states_into_country():
    organizations = make_organizations()
    states = make_states()
    countries = make_countries()

    result = api.build_location_data(
        organizations,
        states,
        countries,
        None,
    )

    assert result == [
        {
            "country": "USA",
            "count": 3,
        },
        {
            "country": "IND",
            "count": 1,
        },
    ]

    assert all("percentage" not in row for row in result)
    assert all(row["country"] != "Other" for row in result)


def test_location_never_exceeds_four_countries():
    organizations = pd.DataFrame(
        [
            {
                "org_id": number,
                "state_id": f"S{number}",
                "city_name": f"City{number}",
                "is_collaborator": False,
                "created_at": pd.Timestamp("2026-01-01"),
            }
            for number in range(1, 7)
        ]
    )

    states = pd.DataFrame(
        [
            {
                "state_id": f"S{number}",
                "state_name": f"State{number}",
                "country_id": number,
            }
            for number in range(1, 7)
        ]
    )

    countries = pd.DataFrame(
        [
            {
                "country_id": number,
                "country_code": f"C{number}",
            }
            for number in range(1, 7)
        ]
    )

    result = api.build_location_data(
        organizations,
        states,
        countries,
        None,
    )

    assert len(result) == 4


def test_empty_organizations_does_not_crash(monkeypatch):
    organizations = pd.DataFrame(
        columns=[
            "org_id",
            "state_id",
            "city_name",
            "is_collaborator",
            "created_at",
        ]
    )

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"]
    )

    monkeypatch.setattr(
        api,
        "load_data",
        lambda: (
            organizations,
            make_states(),
            make_countries(),
        ),
    )

    response = api.lambda_handler({}, None)

    assert response["statusCode"] == 200


def test_single_organization_does_not_crash(monkeypatch):
    organizations = make_organizations().iloc[[0]].copy()

    monkeypatch.setattr(
        api,
        "load_data",
        lambda: (
            organizations,
            make_states(),
            make_countries(),
        ),
    )

    response = api.lambda_handler({}, None)

    assert response["statusCode"] == 200


def test_all_running_total_ends_at_dataset_size(mock_data):
    response = api.lambda_handler({}, None)
    body = parse_body(response)

    all_totals = body["All"]["growth_trend"][
        "total_organizations"
    ]

    assert all_totals[-1]["count"] == 4


def test_sparse_periods_are_not_zero_filled():
    organizations = make_organizations()

    result = api.build_growth_trend(
        organizations,
        None,
        "month",
    )

    periods = [
        row["period"]
        for row in result["total_organizations"]
    ]

    assert periods == [
        "2026-01",
        "2026-02",
        "2026-03",
    ]
    assert "2026-04" not in periods