import importlib.util
import json
from pathlib import Path

import pandas as pd


MODULE_PATH = (
    Path(__file__).resolve().parent
    / "rating_type_analytics.py"
)

spec = importlib.util.spec_from_file_location(
    "rating_type_analytics",
    MODULE_PATH,
)

analytics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analytics)


def make_organizations():
    return pd.DataFrame(
        [
            {
                "org_id": "1",
                "org_rating": 1,
                "org_type": "Non-Profit",
                "state_id": "CA",
                "created_at": pd.Timestamp("2024-12-20"),
            },
            {
                "org_id": "2",
                "org_rating": 5,
                "org_type": "For-profit",
                "state_id": "CA",
                "created_at": pd.Timestamp("2025-01-01"),
            },
            {
                "org_id": "3",
                "org_rating": 5,
                "org_type": "Non-Profit",
                "state_id": "TX",
                "created_at": pd.Timestamp("2025-01-02"),
            },
            {
                "org_id": "4",
                "org_rating": 3,
                "org_type": "For-profit",
                "state_id": "ON",
                "created_at": pd.Timestamp("2025-01-04"),
            },
            {
                "org_id": "5",
                "org_rating": 5,
                "org_type": "non profit",
                "state_id": "CA",
                "created_at": pd.Timestamp("2025-02-10"),
            },
        ]
    )


def make_states():
    return pd.DataFrame(
        [
            {"state_id": "CA", "country_id": "US"},
            {"state_id": "TX", "country_id": "US"},
            {"state_id": "ON", "country_id": "CA"},
        ]
    )


def make_countries():
    return pd.DataFrame(
        [
            {
                "country_id": "US",
                "country_code": "USA",
                "country_name": "United States",
            },
            {
                "country_id": "CA",
                "country_code": "CAN",
                "country_name": "Canada",
            },
        ]
    )


def test_rating_distribution_uses_literal_org_rating_and_no_zero_fill():
    organizations = make_organizations()

    result = analytics.calculate_rating_distribution(
        organizations,
        "All",
    )

    assert result == [
        {"rating": 1, "count": 1},
        {"rating": 3, "count": 1},
        {"rating": 5, "count": 3},
    ]


def test_org_type_normalization():
    series = pd.Series(
        [
            "Non-Profit",
            "For-profit",
            "non profit",
            "for profit",
        ]
    )

    result = analytics.normalize_org_type(series).tolist()

    assert result == [
        "non_profit",
        "for_profit",
        "non_profit",
        "for_profit",
    ]


def test_country_filter_accepts_country_code():
    result = analytics.apply_country_filter(
        make_organizations(),
        make_states(),
        make_countries(),
        "USA",
    )

    assert set(result["org_id"]) == {"1", "2", "3", "5"}


def test_country_filter_accepts_country_name():
    result = analytics.apply_country_filter(
        make_organizations(),
        make_states(),
        make_countries(),
        "United States",
    )

    assert set(result["org_id"]) == {"1", "2", "3", "5"}


def test_country_all_does_not_filter():
    organizations = make_organizations()

    result = analytics.apply_country_filter(
        organizations,
        make_states(),
        make_countries(),
        "ALL",
    )

    assert len(result) == len(organizations)


def test_custom_mix_is_day_grouped_and_cumulative():
    organizations = make_organizations()

    result = analytics.calculate_organization_mix_trend(
        organizations,
        "Custom",
        "2025-01-01",
        "2025-01-04",
    )

    assert [
        row["period"]
        for row in result["non_profit"]
    ] == [
        "2025-01-01",
        "2025-01-02",
        "2025-01-04",
    ]

    assert [
        row["count"]
        for row in result["non_profit"]
    ] == [1, 2, 2]

    assert [
        row["count"]
        for row in result["for_profit"]
    ] == [1, 1, 2]


def test_custom_mix_uses_all_time_cumulative_baseline():
    organizations = make_organizations()

    result = analytics.calculate_organization_mix_trend(
        organizations,
        "Custom",
        "2025-01-01",
        "2025-01-02",
    )

    # Organization 1 was created before the custom window,
    # but must still contribute to the cumulative total.
    assert result["non_profit"][0]["count"] == 1

    assert result["non_profit"][1]["count"] == 2


def test_mix_is_sparse():
    organizations = make_organizations()

    result = analytics.calculate_organization_mix_trend(
        organizations,
        "Custom",
        "2025-01-01",
        "2025-01-05",
    )

    periods = [
        row["period"]
        for row in result["non_profit"]
    ]

    assert periods == [
        "2025-01-01",
        "2025-01-02",
        "2025-01-04",
    ]

    assert "2025-01-03" not in periods
    assert "2025-01-05" not in periods


def test_cumulative_counts_are_non_decreasing():
    result = analytics.calculate_organization_mix_trend(
        make_organizations(),
        "All",
    )

    for org_type in ["non_profit", "for_profit"]:
        counts = [
            row["count"]
            for row in result[org_type]
        ]

        assert counts == sorted(counts)


def test_all_uses_month_grouping():
    result = analytics.calculate_organization_mix_trend(
        make_organizations(),
        "All",
    )

    for org_type in ["non_profit", "for_profit"]:
        for row in result[org_type]:
            assert len(row["period"]) == 7


def test_empty_custom_range_is_safe():
    result = analytics.calculate_organization_mix_trend(
        make_organizations(),
        "Custom",
        "2030-01-01",
        "2030-01-31",
    )

    assert result == {
        "non_profit": [],
        "for_profit": [],
    }


def test_empty_organizations_is_safe():
    empty = pd.DataFrame(
        columns=[
            "org_id",
            "org_rating",
            "org_type",
            "state_id",
            "created_at",
        ]
    )

    rating_result = analytics.calculate_rating_distribution(
        empty,
        "All",
    )

    mix_result = analytics.calculate_organization_mix_trend(
        empty,
        "All",
    )

    assert rating_result == []

    assert mix_result == {
        "non_profit": [],
        "for_profit": [],
    }


def test_one_row_organization_is_safe():
    organizations = pd.DataFrame(
        [
            {
                "org_id": "1",
                "org_rating": 4,
                "org_type": "Non-Profit",
                "state_id": "CA",
                "created_at": pd.Timestamp("2025-01-01"),
            }
        ]
    )

    rating_result = analytics.calculate_rating_distribution(
        organizations,
        "All",
    )

    mix_result = analytics.calculate_organization_mix_trend(
        organizations,
        "All",
    )

    assert rating_result == [
        {"rating": 4, "count": 1}
    ]

    assert mix_result["non_profit"][-1]["count"] == 1
    assert mix_result["for_profit"][-1]["count"] == 0


def test_fixed_handler_has_exact_top_level_keys(monkeypatch):
    monkeypatch.setattr(
        analytics,
        "load_data",
        lambda: (
            make_organizations(),
            make_states(),
            make_countries(),
        ),
    )

    response = analytics.lambda_handler({}, None)

    assert response["statusCode"] == 200

    body = json.loads(response["body"])

    assert list(body.keys()) == [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]


def test_fixed_custom_bucket_is_empty(monkeypatch):
    monkeypatch.setattr(
        analytics,
        "load_data",
        lambda: (
            make_organizations(),
            make_states(),
            make_countries(),
        ),
    )

    response = analytics.lambda_handler({}, None)
    body = json.loads(response["body"])

    assert body["Custom"] == {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }


def test_rating_custom_only(monkeypatch):
    monkeypatch.setattr(
        analytics,
        "load_data",
        lambda: (
            make_organizations(),
            make_states(),
            make_countries(),
        ),
    )

    event = {
        "rating_start_date": "2025-01-01",
        "rating_end_date": "2025-01-31",
    }

    response = analytics.lambda_handler(event, None)

    assert response["statusCode"] == 200

    body = json.loads(response["body"])

    assert list(body.keys()) == ["Custom"]

    assert body["Custom"]["rating_distribution"] == [
        {"rating": 3, "count": 1},
        {"rating": 5, "count": 2},
    ]

    assert body["Custom"]["organization_mix_trend"] == {
        "non_profit": [],
        "for_profit": [],
    }


def test_type_custom_only(monkeypatch):
    monkeypatch.setattr(
        analytics,
        "load_data",
        lambda: (
            make_organizations(),
            make_states(),
            make_countries(),
        ),
    )

    event = {
        "type_start_date": "2025-01-01",
        "type_end_date": "2025-01-31",
    }

    response = analytics.lambda_handler(event, None)

    assert response["statusCode"] == 200

    body = json.loads(response["body"])

    assert list(body.keys()) == ["Custom"]
    assert body["Custom"]["rating_distribution"] == []

    assert (
        body["Custom"]["organization_mix_trend"]["non_profit"]
    )


def test_both_custom_ranges_are_independent(monkeypatch):
    monkeypatch.setattr(
        analytics,
        "load_data",
        lambda: (
            make_organizations(),
            make_states(),
            make_countries(),
        ),
    )

    event = {
        "rating_start_date": "2025-02-01",
        "rating_end_date": "2025-02-28",
        "type_start_date": "2025-01-01",
        "type_end_date": "2025-01-04",
    }

    response = analytics.lambda_handler(event, None)

    assert response["statusCode"] == 200

    body = json.loads(response["body"])

    assert list(body.keys()) == ["Custom"]

    assert body["Custom"]["rating_distribution"] == [
        {"rating": 5, "count": 1}
    ]

    periods = [
        row["period"]
        for row in body["Custom"][
            "organization_mix_trend"
        ]["non_profit"]
    ]

    assert periods == [
        "2025-01-01",
        "2025-01-02",
        "2025-01-04",
    ]


def test_missing_rating_end_date_returns_400():
    response = analytics.lambda_handler(
        {
            "rating_start_date": "2025-01-01",
        },
        None,
    )

    assert response["statusCode"] == 400

    body = json.loads(response["body"])
    assert "rating_end_date" in body["error"]


def test_missing_type_start_date_returns_400():
    response = analytics.lambda_handler(
        {
            "type_end_date": "2025-01-31",
        },
        None,
    )

    assert response["statusCode"] == 400

    body = json.loads(response["body"])
    assert "type_start_date" in body["error"]


def test_invalid_rating_date_format_returns_400():
    response = analytics.lambda_handler(
        {
            "rating_start_date": "01/01/2025",
            "rating_end_date": "2025-01-31",
        },
        None,
    )

    assert response["statusCode"] == 400

    body = json.loads(response["body"])
    assert "YYYY-MM-DD" in body["error"]


def test_invalid_type_date_format_returns_400():
    response = analytics.lambda_handler(
        {
            "type_start_date": "bad-date",
            "type_end_date": "2025-01-31",
        },
        None,
    )

    assert response["statusCode"] == 400


def test_rating_start_after_end_returns_400():
    response = analytics.lambda_handler(
        {
            "rating_start_date": "2025-02-01",
            "rating_end_date": "2025-01-01",
        },
        None,
    )

    assert response["statusCode"] == 400


def test_type_start_after_end_returns_400():
    response = analytics.lambda_handler(
        {
            "type_start_date": "2025-02-01",
            "type_end_date": "2025-01-01",
        },
        None,
    )

    assert response["statusCode"] == 400