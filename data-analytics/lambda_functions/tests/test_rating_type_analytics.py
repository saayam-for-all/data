import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rating_type_analytics as analytics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _response_body(response):
    return json.loads(response["body"])


def _sample_data():
    return pd.DataFrame(
        [
            {
                "org_id": 1,
                "org_rating": 5,
                "org_type": "non_profit",
                "state_id": 1,
                "created_at": pd.Timestamp("2026-09-20"),
                "country_id": 10,
                "country_code": "USA",
                "country_name": "United States",
            },
            {
                "org_id": 2,
                "org_rating": 4,
                "org_type": "for_profit",
                "state_id": 1,
                "created_at": pd.Timestamp("2026-09-23"),
                "country_id": 10,
                "country_code": "USA",
                "country_name": "United States",
            },
            {
                "org_id": 3,
                "org_rating": 5,
                "org_type": "non_profit",
                "state_id": 1,
                "created_at": pd.Timestamp("2026-09-25"),
                "country_id": 10,
                "country_code": "USA",
                "country_name": "United States",
            },
            {
                "org_id": 4,
                "org_rating": 3,
                "org_type": "non_profit",
                "state_id": 2,
                "created_at": pd.Timestamp("2026-09-27"),
                "country_id": 20,
                "country_code": "CAN",
                "country_name": "Canada",
            },
            {
                "org_id": 5,
                "org_rating": 4,
                "org_type": "for_profit",
                "state_id": 1,
                "created_at": pd.Timestamp("2026-09-29"),
                "country_id": 10,
                "country_code": "USA",
                "country_name": "United States",
            },
        ]
    )


@pytest.fixture
def mock_data(monkeypatch):
    data = _sample_data()

    monkeypatch.setattr(
        analytics,
        "_load_data",
        lambda: data.copy(),
    )

    monkeypatch.setattr(
        analytics,
        "_utc_today",
        lambda: pd.Timestamp("2026-09-29").date(),
    )

    return data


# ---------------------------------------------------------------------------
# Top-level response shape
# ---------------------------------------------------------------------------


def test_no_custom_params_returns_exactly_five_top_level_keys(mock_data):
    response = analytics.lambda_handler({}, None)

    body = _response_body(response)

    assert response["statusCode"] == 200

    assert list(body.keys()) == [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]


def test_each_standard_bucket_has_exact_required_shape(mock_data):
    response = analytics.lambda_handler({}, None)

    body = _response_body(response)

    for bucket_name in [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]:
        bucket = body[bucket_name]

        assert set(bucket.keys()) == {
            "rating_distribution",
            "organization_mix_trend",
        }

        assert set(bucket["organization_mix_trend"].keys()) == {
            "non_profit",
            "for_profit",
        }


def test_custom_bucket_is_empty_when_no_custom_params(mock_data):
    response = analytics.lambda_handler({}, None)

    body = _response_body(response)

    assert body["Custom"] == {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [],
            "for_profit": [],
        },
    }


# ---------------------------------------------------------------------------
# Rating Distribution
# ---------------------------------------------------------------------------


def test_rating_distribution_groups_by_literal_rating(mock_data):
    result = analytics._build_rating_distribution(
        data=mock_data,
        start_date=pd.Timestamp("2026-09-20").date(),
        end_date=pd.Timestamp("2026-09-29").date(),
    )

    assert result == [
        {"rating": 3, "count": 1},
        {"rating": 4, "count": 2},
        {"rating": 5, "count": 2},
    ]


def test_rating_distribution_does_not_zero_fill_missing_ratings():
    data = pd.DataFrame(
        [
            {
                "org_rating": 4,
                "created_at": pd.Timestamp("2026-09-01"),
            },
            {
                "org_rating": 5,
                "created_at": pd.Timestamp("2026-09-02"),
            },
            {
                "org_rating": 5,
                "created_at": pd.Timestamp("2026-09-03"),
            },
        ]
    )

    result = analytics._build_rating_distribution(
        data=data,
        start_date=pd.Timestamp("2026-09-01").date(),
        end_date=pd.Timestamp("2026-09-30").date(),
    )

    assert result == [
        {"rating": 4, "count": 1},
        {"rating": 5, "count": 2},
    ]


def test_rating_distribution_empty_window_returns_empty_list(mock_data):
    result = analytics._build_rating_distribution(
        data=mock_data,
        start_date=pd.Timestamp("2030-01-01").date(),
        end_date=pd.Timestamp("2030-01-31").date(),
    )

    assert result == []


# ---------------------------------------------------------------------------
# Organization Mix Trend
# ---------------------------------------------------------------------------


def test_organization_mix_trend_has_exact_two_series(mock_data):
    result = analytics._build_organization_mix_trend(
        data=mock_data,
        start_date=pd.Timestamp("2026-09-20").date(),
        end_date=pd.Timestamp("2026-09-29").date(),
        period_type="day",
    )

    assert set(result.keys()) == {
        "non_profit",
        "for_profit",
    }


def test_organization_mix_trend_uses_cumulative_absolute_counts():
    data = pd.DataFrame(
        [
            {
                "org_type": "non_profit",
                "created_at": pd.Timestamp("2026-09-01"),
            },
            {
                "org_type": "non_profit",
                "created_at": pd.Timestamp("2026-09-10"),
            },
            {
                "org_type": "non_profit",
                "created_at": pd.Timestamp("2026-09-25"),
            },
            {
                "org_type": "non_profit",
                "created_at": pd.Timestamp("2026-09-27"),
            },
        ]
    )

    result = analytics._build_organization_mix_trend(
        data=data,
        start_date=pd.Timestamp("2026-09-23").date(),
        end_date=pd.Timestamp("2026-09-29").date(),
        period_type="day",
    )

    assert result["non_profit"] == [
        {
            "period": "2026-09-25",
            "count": 3,
        },
        {
            "period": "2026-09-27",
            "count": 4,
        },
    ]


def test_organization_mix_trend_is_non_decreasing(mock_data):
    result = analytics._build_organization_mix_trend(
        data=mock_data,
        start_date=pd.Timestamp("2026-09-20").date(),
        end_date=pd.Timestamp("2026-09-29").date(),
        period_type="day",
    )

    for org_type in [
        "non_profit",
        "for_profit",
    ]:
        counts = [item["count"] for item in result[org_type]]

        assert counts == sorted(counts)


def test_organization_mix_trend_is_sparse():
    data = pd.DataFrame(
        [
            {
                "org_type": "non_profit",
                "created_at": pd.Timestamp("2026-09-01"),
            },
            {
                "org_type": "non_profit",
                "created_at": pd.Timestamp("2026-09-03"),
            },
        ]
    )

    result = analytics._build_organization_mix_trend(
        data=data,
        start_date=pd.Timestamp("2026-09-01").date(),
        end_date=pd.Timestamp("2026-09-03").date(),
        period_type="day",
    )

    assert result["non_profit"] == [
        {
            "period": "2026-09-01",
            "count": 1,
        },
        {
            "period": "2026-09-03",
            "count": 2,
        },
    ]

    periods = [item["period"] for item in result["non_profit"]]

    assert "2026-09-02" not in periods


def test_day_grouping_uses_yyyy_mm_dd(mock_data):
    result = analytics._build_organization_mix_trend(
        data=mock_data,
        start_date=pd.Timestamp("2026-09-20").date(),
        end_date=pd.Timestamp("2026-09-29").date(),
        period_type="day",
    )

    all_periods = result["non_profit"] + result["for_profit"]

    for item in all_periods:
        assert len(item["period"]) == 10


def test_month_grouping_uses_yyyy_mm():
    data = pd.DataFrame(
        [
            {
                "org_type": "non_profit",
                "created_at": pd.Timestamp("2026-01-01"),
            },
            {
                "org_type": "non_profit",
                "created_at": pd.Timestamp("2026-02-02"),
            },
        ]
    )

    result = analytics._build_organization_mix_trend(
        data=data,
        start_date=pd.Timestamp("2026-01-01").date(),
        end_date=pd.Timestamp("2026-02-28").date(),
        period_type="month",
    )

    assert result["non_profit"] == [
        {
            "period": "2026-01",
            "count": 1,
        },
        {
            "period": "2026-02",
            "count": 2,
        },
    ]


# ---------------------------------------------------------------------------
# Country filter
# ---------------------------------------------------------------------------


def test_country_filter_by_code(mock_data):
    filtered = analytics._filter_by_country(
        mock_data,
        "USA",
    )

    assert len(filtered) == 4

    assert set(filtered["country_code"]) == {
        "USA",
    }


def test_country_filter_by_name(mock_data):
    filtered = analytics._filter_by_country(
        mock_data,
        "Canada",
    )

    assert len(filtered) == 1

    assert filtered.iloc[0]["country_code"] == "CAN"


def test_country_filter_all_returns_all_rows(mock_data):
    filtered = analytics._filter_by_country(
        mock_data,
        "ALL",
    )

    assert len(filtered) == len(mock_data)


def test_country_filter_applies_to_full_response(mock_data):
    response = analytics.lambda_handler(
        {
            "country": "CAN",
        },
        None,
    )

    body = _response_body(response)

    all_distribution = body["All"]["rating_distribution"]

    assert all_distribution == [
        {
            "rating": 3,
            "count": 1,
        }
    ]


# ---------------------------------------------------------------------------
# Custom response behavior
# ---------------------------------------------------------------------------


def test_rating_custom_only_returns_custom_only(mock_data):
    response = analytics.lambda_handler(
        {
            "rating_start_date": "2026-09-20",
            "rating_end_date": "2026-09-29",
        },
        None,
    )

    body = _response_body(response)

    assert response["statusCode"] == 200

    assert list(body.keys()) == [
        "Custom",
    ]

    assert body["Custom"]["rating_distribution"]

    assert body["Custom"]["organization_mix_trend"] == {
        "non_profit": [],
        "for_profit": [],
    }


def test_type_custom_only_returns_custom_only(mock_data):
    response = analytics.lambda_handler(
        {
            "type_start_date": "2026-09-20",
            "type_end_date": "2026-09-29",
        },
        None,
    )

    body = _response_body(response)

    assert list(body.keys()) == [
        "Custom",
    ]

    assert body["Custom"]["rating_distribution"] == []

    assert (
        body["Custom"]["organization_mix_trend"]["non_profit"]
        or body["Custom"]["organization_mix_trend"]["for_profit"]
    )


def test_both_custom_ranges_populate_both_charts(mock_data):
    response = analytics.lambda_handler(
        {
            "rating_start_date": "2026-09-20",
            "rating_end_date": "2026-09-29",
            "type_start_date": "2026-09-20",
            "type_end_date": "2026-09-29",
        },
        None,
    )

    body = _response_body(response)

    assert list(body.keys()) == [
        "Custom",
    ]

    assert body["Custom"]["rating_distribution"]

    assert (
        body["Custom"]["organization_mix_trend"]["non_profit"]
        or body["Custom"]["organization_mix_trend"]["for_profit"]
    )


def test_custom_ranges_are_independent(mock_data):
    response = analytics.lambda_handler(
        {
            "rating_start_date": "2026-09-27",
            "rating_end_date": "2026-09-27",
            "type_start_date": "2026-09-23",
            "type_end_date": "2026-09-25",
        },
        None,
    )

    body = _response_body(response)

    assert body["Custom"]["rating_distribution"] == [
        {
            "rating": 3,
            "count": 1,
        }
    ]

    trend = body["Custom"]["organization_mix_trend"]

    periods = [item["period"] for series in trend.values() for item in series]

    assert "2026-09-23" in periods
    assert "2026-09-25" in periods
    assert "2026-09-27" not in periods


# ---------------------------------------------------------------------------
# Date validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event",
    [
        {
            "rating_start_date": "2026-01-01",
        },
        {
            "rating_end_date": "2026-01-31",
        },
        {
            "type_start_date": "2026-01-01",
        },
        {
            "type_end_date": "2026-01-31",
        },
    ],
)
def test_incomplete_custom_date_pair_returns_400(
    mock_data,
    event,
):
    response = analytics.lambda_handler(
        event,
        None,
    )

    assert response["statusCode"] == 400

    body = _response_body(response)

    assert "error" in body


@pytest.mark.parametrize(
    "event",
    [
        {
            "rating_start_date": "not-a-date",
            "rating_end_date": "2026-01-31",
        },
        {
            "type_start_date": "2026/01/01",
            "type_end_date": "2026-01-31",
        },
    ],
)
def test_bad_date_format_returns_400(
    mock_data,
    event,
):
    response = analytics.lambda_handler(
        event,
        None,
    )

    assert response["statusCode"] == 400

    assert "YYYY-MM-DD" in _response_body(response)["error"]


@pytest.mark.parametrize(
    "event",
    [
        {
            "rating_start_date": "2026-02-01",
            "rating_end_date": "2026-01-01",
        },
        {
            "type_start_date": "2026-12-31",
            "type_end_date": "2026-01-01",
        },
    ],
)
def test_start_date_after_end_date_returns_400(
    mock_data,
    event,
):
    response = analytics.lambda_handler(
        event,
        None,
    )

    assert response["statusCode"] == 400

    assert "cannot be after" in _response_body(response)["error"]


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------


def test_api_gateway_json_body_is_supported(mock_data):
    response = analytics.lambda_handler(
        {
            "body": json.dumps(
                {
                    "country": "USA",
                }
            )
        },
        None,
    )

    assert response["statusCode"] == 200


def test_invalid_json_body_returns_400(mock_data):
    response = analytics.lambda_handler(
        {
            "body": "{not-valid-json}",
        },
        None,
    )

    assert response["statusCode"] == 400


def test_none_body_behaves_like_empty_request(mock_data):
    response = analytics.lambda_handler(
        {
            "body": None,
        },
        None,
    )

    body = _response_body(response)

    assert set(body.keys()) == {
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    }


# ---------------------------------------------------------------------------
# Time window boundaries
# ---------------------------------------------------------------------------


def test_7d_window_contains_exactly_seven_calendar_days():
    today = pd.Timestamp("2026-09-29").date()

    start = today - pd.Timedelta(days=6)

    assert start.isoformat() == "2026-09-23"


def test_30d_window_contains_exactly_thirty_calendar_days():
    today = pd.Timestamp("2026-09-29").date()

    start = today - pd.Timedelta(days=29)

    assert start.isoformat() == "2026-08-31"


def test_1y_start_is_exactly_twelve_calendar_months():
    today = pd.Timestamp("2026-09-29").date()

    start = analytics._first_day_n_months_ago(
        today,
        11,
    )

    assert start.isoformat() == "2025-10-01"


# ---------------------------------------------------------------------------
# Empty / one-row datasets
# ---------------------------------------------------------------------------


def test_empty_dataset_does_not_crash(monkeypatch):
    empty = pd.DataFrame(
        columns=[
            "org_id",
            "org_rating",
            "org_type",
            "state_id",
            "created_at",
            "country_id",
            "country_code",
            "country_name",
        ]
    )

    empty["created_at"] = pd.to_datetime(empty["created_at"])

    monkeypatch.setattr(
        analytics,
        "_load_data",
        lambda: empty.copy(),
    )

    monkeypatch.setattr(
        analytics,
        "_utc_today",
        lambda: pd.Timestamp("2026-09-29").date(),
    )

    response = analytics.lambda_handler(
        {},
        None,
    )

    body = _response_body(response)

    assert response["statusCode"] == 200

    for bucket_name in [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]:
        assert body[bucket_name]["rating_distribution"] == []

        assert body[bucket_name]["organization_mix_trend"] == {
            "non_profit": [],
            "for_profit": [],
        }


def test_one_row_dataset_does_not_crash(monkeypatch):
    one_row = pd.DataFrame(
        [
            {
                "org_id": 1,
                "org_rating": 5,
                "org_type": "non_profit",
                "state_id": 1,
                "created_at": pd.Timestamp("2026-09-29"),
                "country_id": 10,
                "country_code": "USA",
                "country_name": "United States",
            }
        ]
    )

    monkeypatch.setattr(
        analytics,
        "_load_data",
        lambda: one_row.copy(),
    )

    monkeypatch.setattr(
        analytics,
        "_utc_today",
        lambda: pd.Timestamp("2026-09-29").date(),
    )

    response = analytics.lambda_handler(
        {},
        None,
    )

    body = _response_body(response)

    assert response["statusCode"] == 200

    assert body["7D"]["rating_distribution"] == [
        {
            "rating": 5,
            "count": 1,
        }
    ]


# ---------------------------------------------------------------------------
# Data validation
# ---------------------------------------------------------------------------


def test_missing_required_organization_column_raises_clear_error():
    organizations = pd.DataFrame(
        columns=[
            "org_id",
            "org_type",
            "state_id",
            "created_at",
        ]
    )

    states = pd.DataFrame(
        columns=[
            "state_id",
            "country_id",
        ]
    )

    countries = pd.DataFrame(
        columns=[
            "country_id",
            "country_code",
        ]
    )

    with pytest.raises(
        ValueError,
        match="org_rating",
    ):
        analytics._prepare_data(
            organizations,
            states,
            countries,
        )


def test_country_table_requires_code_or_name():
    organizations = pd.DataFrame(
        columns=[
            "org_id",
            "org_rating",
            "org_type",
            "state_id",
            "created_at",
        ]
    )

    states = pd.DataFrame(
        columns=[
            "state_id",
            "country_id",
        ]
    )

    countries = pd.DataFrame(
        columns=[
            "country_id",
        ]
    )

    with pytest.raises(
        ValueError,
        match="country_code or country_name",
    ):
        analytics._prepare_data(
            organizations,
            states,
            countries,
        )
