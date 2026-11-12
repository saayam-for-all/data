"""Tests for the Organization Analytics Size and Contribution Lambda."""

import json
from datetime import date

import pandas as pd
import pytest

from src.organization_size_contribution_analytics.lambda_function import (
    build_response,
    lambda_handler,
)


@pytest.fixture
def organizations():
    """Provide representative organizations for response-shape tests."""
    return pd.DataFrame(
        [
            {"org_size": "small", "org_type": "Non-Profit", "is_collaborator": "TRUE", "is_contributor": "FALSE", "created_at": "2026-01-01", "country_code": "USA", "country_name": "United States"},
            {"org_size": "medium", "org_type": "For-profit", "is_collaborator": "TRUE", "is_contributor": "TRUE", "created_at": "2026-02-01", "country_code": "USA", "country_name": "United States"},
            {"org_size": "large", "org_type": "Non-Profit", "is_collaborator": "FALSE", "is_contributor": "TRUE", "created_at": "2026-03-01", "country_code": "CAN", "country_name": "Canada"},
        ]
    )


def test_no_custom_ranges_returns_five_keys(organizations):
    """The default response includes four buckets and an empty Custom bucket."""
    response = build_response(organizations, {}, today=date(2026, 3, 15))

    assert list(response) == ["7D", "30D", "1Y", "All", "Custom"]
    assert response["Custom"] == {"organizations_by_size": [], "collaborator_vs_contributor": []}
    assert response["All"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 2, "percentage": 66.7},
        {"type": "Contributor", "count": 2, "percentage": 66.7},
    ]


def test_both_custom_ranges_are_independent(organizations):
    """Both custom charts use their own date range in one Custom response."""
    response = build_response(
        organizations,
        {
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-01-31",
            "contribution_start_date": "2026-02-01",
            "contribution_end_date": "2026-02-28",
        },
    )

    assert list(response) == ["Custom"]
    assert response["Custom"]["organizations_by_size"] == [{"size": "small", "count": 1}]
    assert response["Custom"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 100.0},
        {"type": "Contributor", "count": 1, "percentage": 100.0},
    ]


def test_filters_apply_to_custom_chart(organizations):
    """Country and organization type filters apply before chart aggregation."""
    response = build_response(
        organizations,
        {
            "country": "USA",
            "organization_type": "for_profit",
            "contribution_start_date": "2026-01-01",
            "contribution_end_date": "2026-12-31",
        },
    )

    assert response["Custom"]["collaborator_vs_contributor"][0]["count"] == 1
    assert response["Custom"]["collaborator_vs_contributor"][1]["count"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"size_start_date": "2026-01-01"},
        {"contribution_end_date": "2026-01-01"},
        {"size_start_date": "bad", "size_end_date": "2026-01-01"},
        {"contribution_start_date": "2026-02-01", "contribution_end_date": "2026-01-01"},
    ],
)
def test_invalid_custom_ranges_return_bad_request(monkeypatch, payload):
    """Malformed custom ranges return a clear 400 response before loading data."""
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    response = lambda_handler(payload, None)

    assert response["statusCode"] == 400
    assert "error" in json.loads(response["body"])


def test_missing_contributor_column_degrades_to_zero(organizations):
    """A source without is_contributor still returns the required two rows."""
    response = build_response(
        organizations.drop(columns=["is_contributor"]),
        {"contribution_start_date": "2026-01-01", "contribution_end_date": "2026-12-31"},
    )

    assert response["Custom"]["collaborator_vs_contributor"][1] == {
        "type": "Contributor",
        "count": 0,
        "percentage": 0.0,
    }


def test_empty_custom_window_returns_empty_charts(organizations):
    """A date range without organizations returns empty arrays."""
    response = build_response(
        organizations,
        {"size_start_date": "2027-01-01", "size_end_date": "2027-01-31"},
    )

    assert response == {"Custom": {"organizations_by_size": [], "collaborator_vs_contributor": []}}