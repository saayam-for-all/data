"""Tests for Rating & Type Analytics API."""

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

import rating_type_analytics as api


def make_data():
    raw = pd.DataFrame(
        [
            {
                "org_id": 1,
                "org_rating": 1,
                "org_type": "Non-Profit",
                "state_id": "TX",
                "created_at": "2025-12-31 10:00:00",
                "country_code": "USA",
                "country_name": "UNITED STATES",
            },
            {
                "org_id": 2,
                "org_rating": 3,
                "org_type": "Non-Profit",
                "state_id": "TX",
                "created_at": "2026-01-01 10:00:00",
                "country_code": "USA",
                "country_name": "UNITED STATES",
            },
            {
                "org_id": 3,
                "org_rating": 4,
                "org_type": "For-profit",
                "state_id": "FL",
                "created_at": "2026-01-02 10:00:00",
                "country_code": "USA",
                "country_name": "UNITED STATES",
            },
            {
                "org_id": 4,
                "org_rating": 5,
                "org_type": "Non-Profit",
                "state_id": "KA",
                "created_at": "2026-02-05 10:00:00",
                "country_code": "IND",
                "country_name": "INDIA",
            },
            {
                "org_id": 5,
                "org_rating": 5,
                "org_type": "For-profit",
                "state_id": "TX",
                "created_at": "2026-03-10 10:00:00",
                "country_code": "USA",
                "country_name": "UNITED STATES",
            },
        ]
    )

    return api.prepare_data(raw)


@pytest.fixture
def mock_data(monkeypatch):
    data = make_data()

    monkeypatch.setattr(
        api,
        "load_data",
        lambda: data.copy(),
    )

    monkeypatch.setattr(
        api,
        "current_date",
        lambda: pd.Timestamp("2026-03-15"),
    )

    return data


def parse_body(response):
    return json.loads(response["body"])


def test_no_body_returns_exact_five_keys(mock_data):
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
            "rating_distribution",
            "organization_mix_trend",
        }

        assert set(
            bucket["organization_mix_trend"].keys()
        ) == {
            "non_profit",
            "for_profit",
        }

    assert body["Custom"] == {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }


def test_rating_custom_returns_custom_only(mock_data):
    event = {
        "body": json.dumps(
            {
                "rating_start_date": "2026-01-01",
                "rating_end_date": "2026-01-31",
            }
        )
    }

    response = api.lambda_handler(event, None)
    body = parse_body(response)

    assert response["statusCode"] == 200
    assert list(body.keys()) == ["Custom"]

    assert body["Custom"]["rating_distribution"] == [
        {
            "rating": 3,
            "count": 1,
        },
        {
            "rating": 4,
            "count": 1,
        },
    ]

    assert body["Custom"]["organization_mix_trend"] == {
        "non_profit": [],
        "for_profit": [],
    }


def test_type_custom_returns_custom_only(mock_data):
    event = {
        "body": json.dumps(
            {
                "type_start_date": "2026-01-01",
                "type_end_date": "2026-01-31",
            }
        )
    }

    response = api.lambda_handler(event, None)
    body = parse_body(response)

    assert response["statusCode"] == 200
    assert list(body.keys()) == ["Custom"]
    assert body["Custom"]["rating_distribution"] == []

    assert body["Custom"]["organization_mix_trend"] == {
        "non_profit": [
            {
                "period": "2026-01-01",
                "count": 2,
            }
        ],
        "for_profit": [
            {
                "period": "2026-01-02",
                "count": 1,
            }
        ],
    }


def test_both_custom_ranges_populate_independently(mock_data):
    event = {
        "body": json.dumps(
            {
                "rating_start_date": "2026-02-01",
                "rating_end_date": "2026-02-28",
                "type_start_date": "2026-01-01",
                "type_end_date": "2026-01-31",
            }
        )
    }

    body = parse_body(
        api.lambda_handler(event, None)
    )

    assert list(body.keys()) == ["Custom"]

    assert body["Custom"]["rating_distribution"] == [
        {
            "rating": 5,
            "count": 1,
        }
    ]

    assert body["Custom"]["organization_mix_trend"] == {
        "non_profit": [
            {
                "period": "2026-01-01",
                "count": 2,
            }
        ],
        "for_profit": [
            {
                "period": "2026-01-02",
                "count": 1,
            }
        ],
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "rating_start_date": "2026-01-01",
        },
        {
            "rating_end_date": "2026-01-31",
        },
        {
            "rating_start_date": "bad-date",
            "rating_end_date": "2026-01-31",
        },
        {
            "rating_start_date": "2026-02-01",
            "rating_end_date": "2026-01-01",
        },
        {
            "type_start_date": "2026-01-01",
        },
        {
            "type_end_date": "2026-01-31",
        },
        {
            "type_start_date": "bad-date",
            "type_end_date": "2026-01-31",
        },
        {
            "type_start_date": "2026-02-01",
            "type_end_date": "2026-01-01",
        },
    ],
)
def test_invalid_custom_ranges_return_400(
    mock_data,
    payload,
):
    response = api.lambda_handler(
        {
            "body": json.dumps(payload),
        },
        None,
    )

    assert response["statusCode"] == 400
    assert "error" in parse_body(response)


def test_country_code_filters_both_charts(mock_data):
    response = api.lambda_handler(
        {
            "body": json.dumps(
                {
                    "country": "USA",
                }
            )
        },
        None,
    )

    body = parse_body(response)

    rating_total = sum(
        row["count"]
        for row in body["All"][
            "rating_distribution"
        ]
    )

    assert rating_total == 4

    trend = body["All"][
        "organization_mix_trend"
    ]

    assert trend["non_profit"][-1]["count"] == 2
    assert trend["for_profit"][-1]["count"] == 2


def test_country_name_filter_works(mock_data):
    response = api.lambda_handler(
        {
            "body": json.dumps(
                {
                    "country": "INDIA",
                }
            )
        },
        None,
    )

    body = parse_body(response)

    assert body["All"]["rating_distribution"] == [
        {
            "rating": 5,
            "count": 1,
        }
    ]


def test_rating_distribution_is_sparse():
    data = make_data()

    result = api.build_rating_distribution(
        data,
        (
            pd.Timestamp("2026-01-01"),
            pd.Timestamp("2026-01-31"),
        ),
    )

    assert result == [
        {
            "rating": 3,
            "count": 1,
        },
        {
            "rating": 4,
            "count": 1,
        },
    ]

    ratings = [
        row["rating"]
        for row in result
    ]

    assert 1 not in ratings
    assert 2 not in ratings
    assert 5 not in ratings


def test_type_trend_is_cumulative():
    data = make_data()

    result = api.build_organization_mix_trend(
        data,
        (
            pd.Timestamp("2026-01-01"),
            pd.Timestamp("2026-03-31"),
        ),
        "month",
    )

    assert result["non_profit"] == [
        {
            "period": "2026-01",
            "count": 2,
        },
        {
            "period": "2026-02",
            "count": 3,
        },
    ]

    assert result["for_profit"] == [
        {
            "period": "2026-01",
            "count": 1,
        },
        {
            "period": "2026-03",
            "count": 2,
        },
    ]


def test_type_trend_counts_are_non_decreasing():
    data = make_data()

    result = api.build_organization_mix_trend(
        data,
        None,
        "month",
    )

    for series in (
        result["non_profit"],
        result["for_profit"],
    ):
        counts = [
            row["count"]
            for row in series
        ]

        assert counts == sorted(counts)


def test_type_trend_is_sparse():
    data = make_data()

    result = api.build_organization_mix_trend(
        data,
        None,
        "month",
    )

    non_profit_periods = [
        row["period"]
        for row in result["non_profit"]
    ]

    for_profit_periods = [
        row["period"]
        for row in result["for_profit"]
    ]

    assert "2026-03" not in non_profit_periods
    assert "2026-02" not in for_profit_periods


def test_daily_and_monthly_grouping():
    data = make_data()

    daily = api.build_organization_mix_trend(
        data,
        (
            pd.Timestamp("2026-01-01"),
            pd.Timestamp("2026-01-31"),
        ),
        "day",
    )

    monthly = api.build_organization_mix_trend(
        data,
        None,
        "month",
    )

    assert daily["non_profit"][0]["period"] == (
        "2026-01-01"
    )

    assert daily["for_profit"][0]["period"] == (
        "2026-01-02"
    )

    assert monthly["non_profit"][0]["period"] == (
        "2025-12"
    )


def test_one_year_window_is_365_inclusive_days(
    monkeypatch,
):
    monkeypatch.setattr(
        api,
        "current_date",
        lambda: pd.Timestamp("2026-09-29"),
    )

    start_date, end_date = api.get_fixed_window(
        "1Y"
    )

    assert start_date == pd.Timestamp(
        "2025-09-30"
    )

    assert end_date == pd.Timestamp(
        "2026-09-29"
    )

    assert (
        end_date - start_date
    ).days + 1 == 365


def test_org_type_normalization():
    assert api.normalize_org_type(
        "Non-Profit"
    ) == "non_profit"

    assert api.normalize_org_type(
        "For-profit"
    ) == "for_profit"

    assert api.normalize_org_type(
        "non_profit"
    ) == "non_profit"

    assert api.normalize_org_type(
        "for_profit"
    ) == "for_profit"


def test_empty_organizations_does_not_crash(
    monkeypatch,
):
    empty = pd.DataFrame(
        columns=[
            "org_id",
            "org_rating",
            "org_type",
            "state_id",
            "created_at",
            "country_code",
            "country_name",
        ]
    )

    empty = api.prepare_data(empty)

    monkeypatch.setattr(
        api,
        "load_data",
        lambda: empty.copy(),
    )

    response = api.lambda_handler({}, None)

    assert response["statusCode"] == 200


def test_single_organization_does_not_crash(
    monkeypatch,
):
    single = make_data().iloc[[0]].copy()

    monkeypatch.setattr(
        api,
        "load_data",
        lambda: single.copy(),
    )

    response = api.lambda_handler({}, None)

    assert response["statusCode"] == 200


def test_invalid_country_type_returns_400(mock_data):
    response = api.lambda_handler(
        {
            "body": json.dumps(
                {
                    "country": 123,
                }
            )
        },
        None,
    )

    assert response["statusCode"] == 400


def test_unknown_country_returns_empty_charts(
    mock_data,
):
    response = api.lambda_handler(
        {
            "body": json.dumps(
                {
                    "country": "ZZZ",
                }
            )
        },
        None,
    )

    body = parse_body(response)

    assert response["statusCode"] == 200

    assert body["All"] == {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }