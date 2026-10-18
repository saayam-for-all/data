import json

import lambda_functions.size_contribution_analytics as analytics
import pandas as pd
import pytest


def make_df():
    return pd.DataFrame(
        [
            {
                "org_id": 1,
                "org_size": "small",
                "is_collaborator": True,
                "is_contributor": False,
                "org_type": "non_profit",
                "country_code": "USA",
                "created_at": pd.Timestamp("2026-06-01T10:00:00Z"),
            },
            {
                "org_id": 2,
                "org_size": "small",
                "is_collaborator": True,
                "is_contributor": True,
                "org_type": "non_profit",
                "country_code": "USA",
                "created_at": pd.Timestamp("2026-06-15T10:00:00Z"),
            },
            {
                "org_id": 3,
                "org_size": "medium",
                "is_collaborator": False,
                "is_contributor": True,
                "org_type": "for_profit",
                "country_code": "USA",
                "created_at": pd.Timestamp("2026-07-01T10:00:00Z"),
            },
            {
                "org_id": 4,
                "org_size": "large",
                "is_collaborator": False,
                "is_contributor": False,
                "org_type": "non_profit",
                "country_code": "CAN",
                "created_at": pd.Timestamp("2025-05-01T10:00:00Z"),
            },
        ]
    )


@pytest.fixture
def mock_data(monkeypatch):
    df = make_df()

    monkeypatch.setattr(analytics, "_load_data", lambda: df.copy())

    return df


def body(response):
    return json.loads(response["body"])


# -------------------------------------------------------------------
# BASIC RESPONSE SHAPE
# -------------------------------------------------------------------


def test_no_custom_params_returns_five_keys(mock_data):
    response = analytics.lambda_handler({})

    assert response["statusCode"] == 200

    result = body(response)

    assert set(result.keys()) == {
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    }


def test_each_fixed_bucket_has_required_shape(mock_data):
    response = analytics.lambda_handler({})

    result = body(response)

    for bucket in ["7D", "30D", "1Y", "All", "Custom"]:
        assert set(result[bucket].keys()) == {
            "organizations_by_size",
            "collaborator_vs_contributor",
        }


def test_custom_is_empty_when_no_custom_params(mock_data):
    response = analytics.lambda_handler({})

    result = body(response)

    assert result["Custom"] == {
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
    }


# -------------------------------------------------------------------
# SIZE CALCULATION
# -------------------------------------------------------------------


def test_organizations_by_size_counts_correctly():
    df = make_df()

    result = analytics._organizations_by_size(df)

    result_map = {row["size"]: row["count"] for row in result}

    assert result_map == {
        "small": 2,
        "medium": 1,
        "large": 1,
    }


def test_size_categories_are_not_zero_filled():
    df = make_df()

    df = df[df["org_size"] != "medium"]

    result = analytics._organizations_by_size(df)

    sizes = {row["size"] for row in result}

    assert "medium" not in sizes


def test_empty_size_data_returns_empty_array():
    df = make_df().iloc[0:0]

    assert analytics._organizations_by_size(df) == []


# -------------------------------------------------------------------
# CONTRIBUTION CALCULATION
# -------------------------------------------------------------------


def test_collaborator_and_contributor_counts_are_independent():
    df = make_df()

    result = analytics._collaborator_vs_contributor(df)

    collaborator = result[0]
    contributor = result[1]

    assert collaborator["type"] == "Collaborator"
    assert collaborator["count"] == 2
    assert collaborator["percentage"] == 50.0

    assert contributor["type"] == "Contributor"
    assert contributor["count"] == 2
    assert contributor["percentage"] == 50.0


def test_both_flags_can_be_true_without_double_count_problem():
    df = pd.DataFrame(
        [
            {
                "is_collaborator": True,
                "is_contributor": True,
            }
        ]
    )

    result = analytics._collaborator_vs_contributor(df)

    assert result == [
        {
            "type": "Collaborator",
            "count": 1,
            "percentage": 100.0,
        },
        {
            "type": "Contributor",
            "count": 1,
            "percentage": 100.0,
        },
    ]


def test_missing_is_contributor_returns_zero():
    df = pd.DataFrame(
        [
            {"is_collaborator": True},
            {"is_collaborator": False},
        ]
    )

    result = analytics._collaborator_vs_contributor(df)

    assert result[0] == {
        "type": "Collaborator",
        "count": 1,
        "percentage": 50.0,
    }

    assert result[1] == {
        "type": "Contributor",
        "count": 0,
        "percentage": 0.0,
    }


def test_empty_contribution_data_returns_empty_array():
    df = pd.DataFrame(columns=["is_collaborator", "is_contributor"])

    assert analytics._collaborator_vs_contributor(df) == []


# -------------------------------------------------------------------
# COUNTRY FILTER
# -------------------------------------------------------------------


def test_country_filter(mock_data):
    response = analytics.lambda_handler({"country": "USA"})

    result = body(response)

    all_bucket = result["All"]

    size_counts = {
        row["size"]: row["count"] for row in all_bucket["organizations_by_size"]
    }

    assert size_counts == {
        "small": 2,
        "medium": 1,
    }


def test_country_all_does_not_filter(mock_data):
    response = analytics.lambda_handler({"country": "ALL"})

    result = body(response)

    counts = sum(item["count"] for item in result["All"]["organizations_by_size"])

    assert counts == 4


# -------------------------------------------------------------------
# ORGANIZATION TYPE FILTER
# -------------------------------------------------------------------


def test_non_profit_filter(mock_data):
    response = analytics.lambda_handler({"organization_type": "non_profit"})

    result = body(response)

    counts = sum(row["count"] for row in result["All"]["organizations_by_size"])

    assert counts == 3


def test_for_profit_filter(mock_data):
    response = analytics.lambda_handler({"organization_type": "for_profit"})

    result = body(response)

    counts = sum(row["count"] for row in result["All"]["organizations_by_size"])

    assert counts == 1


def test_invalid_organization_type_returns_400(mock_data):
    response = analytics.lambda_handler({"organization_type": "random"})

    assert response["statusCode"] == 400


# -------------------------------------------------------------------
# SIZE CUSTOM RANGE
# -------------------------------------------------------------------


def test_size_custom_range_returns_custom_only(mock_data):
    response = analytics.lambda_handler(
        {
            "size_start_date": "2026-06-01",
            "size_end_date": "2026-06-30",
        }
    )

    assert response["statusCode"] == 200

    result = body(response)

    assert list(result.keys()) == ["Custom"]

    assert result["Custom"]["collaborator_vs_contributor"] == []

    sizes = {
        row["size"]: row["count"] for row in result["Custom"]["organizations_by_size"]
    }

    assert sizes == {"small": 2}


# -------------------------------------------------------------------
# CONTRIBUTION CUSTOM RANGE
# -------------------------------------------------------------------


def test_contribution_custom_returns_custom_only(mock_data):
    response = analytics.lambda_handler(
        {
            "contribution_start_date": "2026-06-01",
            "contribution_end_date": "2026-06-30",
        }
    )

    result = body(response)

    assert list(result.keys()) == ["Custom"]

    assert result["Custom"]["organizations_by_size"] == []

    contribution = result["Custom"]["collaborator_vs_contributor"]

    assert contribution == [
        {
            "type": "Collaborator",
            "count": 2,
            "percentage": 100.0,
        },
        {
            "type": "Contributor",
            "count": 1,
            "percentage": 50.0,
        },
    ]


# -------------------------------------------------------------------
# BOTH CUSTOM RANGES
# -------------------------------------------------------------------


def test_both_custom_ranges_are_processed(mock_data):
    response = analytics.lambda_handler(
        {
            "size_start_date": "2026-06-01",
            "size_end_date": "2026-06-30",
            "contribution_start_date": "2026-07-01",
            "contribution_end_date": "2026-07-31",
        }
    )

    result = body(response)

    assert list(result.keys()) == ["Custom"]

    sizes = result["Custom"]["organizations_by_size"]

    contribution = result["Custom"]["collaborator_vs_contributor"]

    assert sizes == [{"size": "small", "count": 2}]

    assert contribution == [
        {
            "type": "Collaborator",
            "count": 0,
            "percentage": 0.0,
        },
        {
            "type": "Contributor",
            "count": 1,
            "percentage": 100.0,
        },
    ]


# -------------------------------------------------------------------
# DATE VALIDATION
# -------------------------------------------------------------------


def test_missing_size_end_date_returns_400(mock_data):
    response = analytics.lambda_handler({"size_start_date": "2026-01-01"})

    assert response["statusCode"] == 400


def test_missing_size_start_date_returns_400(mock_data):
    response = analytics.lambda_handler({"size_end_date": "2026-01-31"})

    assert response["statusCode"] == 400


def test_missing_contribution_end_returns_400(mock_data):
    response = analytics.lambda_handler({"contribution_start_date": "2026-01-01"})

    assert response["statusCode"] == 400


def test_invalid_date_format_returns_400(mock_data):
    response = analytics.lambda_handler(
        {"size_start_date": "January 1 2026", "size_end_date": "2026-06-01"}
    )

    assert response["statusCode"] == 400


def test_start_after_end_returns_400(mock_data):
    response = analytics.lambda_handler(
        {"size_start_date": "2026-12-31", "size_end_date": "2026-01-01"}
    )

    assert response["statusCode"] == 400


# -------------------------------------------------------------------
# DATE END BOUNDARY
# -------------------------------------------------------------------


def test_custom_end_date_is_inclusive(mock_data):
    response = analytics.lambda_handler(
        {"size_start_date": "2026-06-15", "size_end_date": "2026-06-15"}
    )

    result = body(response)

    assert result["Custom"]["organizations_by_size"] == [{"size": "small", "count": 1}]


# -------------------------------------------------------------------
# EMPTY AND ONE-ROW DATA
# -------------------------------------------------------------------


def test_empty_dataframe_does_not_crash(monkeypatch):
    empty_df = make_df().iloc[0:0]

    monkeypatch.setattr(analytics, "_load_data", lambda: empty_df.copy())

    response = analytics.lambda_handler({})

    assert response["statusCode"] == 200

    result = body(response)

    for bucket in ["7D", "30D", "1Y", "All"]:
        assert result[bucket]["organizations_by_size"] == []

        assert result[bucket]["collaborator_vs_contributor"] == []


def test_single_row_does_not_crash(monkeypatch):
    single = make_df().iloc[[0]]

    monkeypatch.setattr(analytics, "_load_data", lambda: single.copy())

    response = analytics.lambda_handler({})

    assert response["statusCode"] == 200


# -------------------------------------------------------------------
# API GATEWAY BODY
# -------------------------------------------------------------------


def test_api_gateway_string_body(mock_data):
    response = analytics.lambda_handler({"body": json.dumps({"country": "USA"})})

    assert response["statusCode"] == 200


def test_filter_date_range_accepts_timezone_aware_start():
    df = make_df()

    start = pd.Timestamp("2026-06-01T00:00:00Z")

    result = analytics._filter_date_range(df, start=start)

    assert len(result) == 3


def test_filter_date_range_accepts_naive_start():
    df = make_df()

    start = pd.Timestamp("2026-06-01")

    result = analytics._filter_date_range(df, start=start)

    assert len(result) == 3
