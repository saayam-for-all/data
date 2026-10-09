import importlib.util
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "lambda_functions"
    / "rating_type_analytics.py"
)

spec = importlib.util.spec_from_file_location(
    "rating_type_analytics",
    MODULE_PATH,
)
analytics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analytics)


@pytest.fixture
def mock_data_dir(tmp_path):
    organizations = pd.DataFrame(
        [
            {
                "org_id": "ORG1",
                "org_rating": 5,
                "org_type": "Non-Profit",
                "state_id": "MI",
                "created_at": "2025-01-01",
            },
            {
                "org_id": "ORG2",
                "org_rating": 4,
                "org_type": "For-profit",
                "state_id": "MI",
                "created_at": "2025-01-02",
            },
            {
                "org_id": "ORG3",
                "org_rating": 5,
                "org_type": "Non-Profit",
                "state_id": "CA",
                "created_at": "2025-02-01",
            },
            {
                "org_id": "ORG4",
                "org_rating": 2,
                "org_type": "For-profit",
                "state_id": "ON",
                "created_at": "2025-03-01",
            },
        ]
    )

    states = pd.DataFrame(
        [
            {"state_id": "MI", "country_id": 1},
            {"state_id": "CA", "country_id": 1},
            {"state_id": "ON", "country_id": 2},
        ]
    )

    countries = pd.DataFrame(
        [
            {
                "country_id": 1,
                "country_code": "USA",
                "country_name": "UNITED_STATES_OF_AMERICA",
            },
            {
                "country_id": 2,
                "country_code": "CAN",
                "country_name": "CANADA",
            },
        ]
    )

    organizations.to_csv(
        tmp_path / "organizations.csv",
        index=False,
    )
    states.to_csv(
        tmp_path / "states.csv",
        index=False,
    )
    countries.to_csv(
        tmp_path / "countries.csv",
        index=False,
    )

    return tmp_path


@pytest.fixture(autouse=True)
def configure_mock_environment(monkeypatch, mock_data_dir):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv(
        "MOCK_DATA_DIR",
        str(mock_data_dir),
    )


def response_body(response):
    return json.loads(response["body"])


def test_no_body_returns_exact_five_buckets():
    result = analytics.build_response(
        {},
        today=date(2025, 3, 2),
    )

    assert list(result.keys()) == [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]

    assert result["Custom"] == {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }


def test_country_filter_applies_to_both_charts():
    result = analytics.build_response(
        {"country": "CAN"},
        today=date(2025, 3, 2),
    )

    assert result["All"]["rating_distribution"] == [
        {"rating": 2, "count": 1}
    ]

    trend = result["All"]["organization_mix_trend"]

    assert trend["non_profit"] == []
    assert trend["for_profit"] == [
        {
            "period": "2025-03",
            "count": 1,
        }
    ]


def test_country_name_is_accepted():
    result = analytics.build_response(
        {"country": "CANADA"},
        today=date(2025, 3, 2),
    )

    assert result["All"]["rating_distribution"] == [
        {"rating": 2, "count": 1}
    ]


def test_rating_custom_only():
    result = analytics.build_response(
        {
            "rating_start_date": "2025-01-01",
            "rating_end_date": "2025-01-31",
        }
    )

    assert list(result.keys()) == ["Custom"]

    assert result["Custom"]["rating_distribution"] == [
        {"rating": 4, "count": 1},
        {"rating": 5, "count": 1},
    ]

    assert result["Custom"]["organization_mix_trend"] == {
        "non_profit": [],
        "for_profit": [],
    }


def test_type_custom_only():
    result = analytics.build_response(
        {
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-01-31",
        }
    )

    assert list(result.keys()) == ["Custom"]
    assert result["Custom"]["rating_distribution"] == []

    trend = result["Custom"]["organization_mix_trend"]

    assert trend["non_profit"] == [
        {
            "period": "2025-01-01",
            "count": 1,
        }
    ]

    assert trend["for_profit"] == [
        {
            "period": "2025-01-02",
            "count": 1,
        }
    ]


def test_both_custom_ranges_are_independent():
    result = analytics.build_response(
        {
            "rating_start_date": "2025-02-01",
            "rating_end_date": "2025-02-28",
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-01-31",
        }
    )

    assert list(result.keys()) == ["Custom"]

    assert result["Custom"]["rating_distribution"] == [
        {"rating": 5, "count": 1}
    ]

    trend = result["Custom"]["organization_mix_trend"]

    assert trend["non_profit"] == [
        {
            "period": "2025-01-01",
            "count": 1,
        }
    ]

    assert trend["for_profit"] == [
        {
            "period": "2025-01-02",
            "count": 1,
        }
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "rating_start_date": "2025-01-01",
        },
        {
            "type_end_date": "2025-01-31",
        },
        {
            "rating_start_date": "01-01-2025",
            "rating_end_date": "2025-01-31",
        },
        {
            "type_start_date": "2025-02-01",
            "type_end_date": "2025-01-01",
        },
    ],
)
def test_invalid_date_pairs_return_400(payload):
    response = analytics.lambda_handler(payload)

    assert response["statusCode"] == 400
    assert "error" in response_body(response)


def test_type_counts_are_cumulative_and_non_decreasing():
    result = analytics.build_response(
        {},
        today=date(2025, 3, 2),
    )

    trend = result["All"]["organization_mix_trend"]

    for org_type in ("non_profit", "for_profit"):
        counts = [
            item["count"]
            for item in trend[org_type]
        ]

        assert counts == sorted(counts)


def test_sparse_periods_are_not_zero_filled():
    result = analytics.build_response(
        {},
        today=date(2025, 3, 2),
    )

    periods = [
        item["period"]
        for item in result["All"][
            "organization_mix_trend"
        ]["non_profit"]
    ]

    assert periods == [
        "2025-01",
        "2025-02",
    ]


def test_empty_organizations_does_not_crash(
    tmp_path,
    monkeypatch,
):
    pd.DataFrame(
        columns=[
            "org_id",
            "org_rating",
            "org_type",
            "state_id",
            "created_at",
        ]
    ).to_csv(
        tmp_path / "organizations.csv",
        index=False,
    )

    pd.DataFrame(
        columns=["state_id", "country_id"]
    ).to_csv(
        tmp_path / "states.csv",
        index=False,
    )

    pd.DataFrame(
        columns=[
            "country_id",
            "country_code",
            "country_name",
        ]
    ).to_csv(
        tmp_path / "countries.csv",
        index=False,
    )

    monkeypatch.setenv(
        "MOCK_DATA_DIR",
        str(tmp_path),
    )

    result = analytics.build_response(
        {},
        today=date(2025, 3, 2),
    )

    assert result["All"] == {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }


def test_one_row_organizations_does_not_crash(
    tmp_path,
    monkeypatch,
):
    pd.DataFrame(
        [
            {
                "org_id": "ONLY1",
                "org_rating": 3,
                "org_type": "Non-Profit",
                "state_id": "MI",
                "created_at": "2025-01-10",
            }
        ]
    ).to_csv(
        tmp_path / "organizations.csv",
        index=False,
    )

    pd.DataFrame(
        [
            {
                "state_id": "MI",
                "country_id": 1,
            }
        ]
    ).to_csv(
        tmp_path / "states.csv",
        index=False,
    )

    pd.DataFrame(
        [
            {
                "country_id": 1,
                "country_code": "USA",
                "country_name": "UNITED_STATES_OF_AMERICA",
            }
        ]
    ).to_csv(
        tmp_path / "countries.csv",
        index=False,
    )

    monkeypatch.setenv(
        "MOCK_DATA_DIR",
        str(tmp_path),
    )

    result = analytics.build_response(
        {},
        today=date(2025, 1, 10),
    )

    assert result["All"]["rating_distribution"] == [
        {
            "rating": 3,
            "count": 1,
        }
    ]

    assert result["All"]["organization_mix_trend"][
        "non_profit"
    ] == [
        {
            "period": "2025-01",
            "count": 1,
        }
    ]


def test_rating_distribution_does_not_zero_fill():
    result = analytics.build_response(
        {
            "rating_start_date": "2025-01-01",
            "rating_end_date": "2025-01-31",
        }
    )

    ratings = [
        item["rating"]
        for item in result["Custom"][
            "rating_distribution"
        ]
    ]

    assert ratings == [4, 5]