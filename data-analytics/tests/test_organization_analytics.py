import os
import sys
import json

import pytest
from unittest.mock import MagicMock, patch

sys.path.append(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "lambda_functions",
    )
)

import organization_analytics as oa


def make_filters(**overrides):
    filters = {
        "time_filter": "30D",
        "start_date": None,
        "end_date": None,
        "group_by": "daily",
        "region": "ALL",
        "organization_type": "ALL",
    }

    filters.update(overrides)
    return filters


def test_valid_filters():
    filters = make_filters()

    oa.validate_filters(filters)


def test_invalid_time_filter():
    filters = make_filters(time_filter="90D")

    with pytest.raises(ValueError):
        oa.validate_filters(filters)


def test_invalid_group_by():
    filters = make_filters(group_by="hourly")

    with pytest.raises(ValueError):
        oa.validate_filters(filters)


def test_custom_requires_both_dates():
    filters = make_filters(
        time_filter="CUSTOM",
        start_date="2026-01-01",
        end_date=None,
    )

    with pytest.raises(ValueError):
        oa.validate_filters(filters)


def test_custom_start_date_after_end_date():
    filters = make_filters(
        time_filter="CUSTOM",
        start_date="2026-06-30",
        end_date="2026-01-01",
    )

    with pytest.raises(ValueError):
        oa.validate_filters(filters)

def test_fetch_summary():
    cursor = MagicMock()

    cursor.fetchone.side_effect = [
        {"column_exists": True},
        {
            "total_organizations": 40,
            "total_collaborators": 21,
            "total_contributors": 19,
            "average_org_rating": 3.2,
        },
    ]

    filters = make_filters(
        time_filter="ALL",
        group_by="monthly",
    )

    result = oa.fetch_summary(cursor, filters)

    assert result == {
        "total_organizations": 40,
        "total_collaborators": 21,
        "total_contributors": 19,
        "average_org_rating": 3.2,
    }


def test_fetch_summary_without_contributor_column():
    cursor = MagicMock()

    cursor.fetchone.side_effect = [
        {"column_exists": False},
        {
            "total_organizations": 10,
            "total_collaborators": 4,
            "total_contributors": 0,
            "average_org_rating": 4.1,
        },
    ]

    filters = make_filters(
        time_filter="ALL",
        group_by="monthly",
    )

    result = oa.fetch_summary(cursor, filters)

    assert result["total_organizations"] == 10
    assert result["total_collaborators"] == 4
    assert result["total_contributors"] == 0
    assert result["average_org_rating"] == 4.1


def test_fetch_rating_distribution_zero_fills_missing_ratings():
    cursor = MagicMock()

    cursor.fetchall.return_value = [
        {
            "rating": 3,
            "organization_count": 2,
        },
        {
            "rating": 5,
            "organization_count": 4,
        },
    ]

    filters = make_filters(
        time_filter="ALL",
        group_by="monthly",
    )

    result = oa.fetch_rating_distribution(
        cursor,
        filters,
    )

    assert result == [
        {"rating": 1, "organization_count": 0},
        {"rating": 2, "organization_count": 0},
        {"rating": 3, "organization_count": 2},
        {"rating": 4, "organization_count": 0},
        {"rating": 5, "organization_count": 4},
    ]


def test_fetch_organizations_by_size_zero_fills_missing_sizes():
    cursor = MagicMock()

    cursor.fetchall.return_value = [
        {
            "org_size": "small",
            "organization_count": 3,
        },
        {
            "org_size": "large",
            "organization_count": 7,
        },
    ]

    filters = make_filters(
        time_filter="ALL",
        group_by="monthly",
    )

    result = oa.fetch_organizations_by_size(
        cursor,
        filters,
    )

    assert result == [
        {"org_size": "small", "organization_count": 3},
        {"org_size": "medium", "organization_count": 0},
        {"org_size": "large", "organization_count": 7},
    ]

def test_lambda_handler_success():
    fake_connection = MagicMock()
    fake_cursor = MagicMock()

    fake_connection.cursor.return_value = fake_cursor

    with patch.object(oa, "get_db_connection", return_value=fake_connection), \
         patch.object(oa, "fetch_summary", return_value={
             "total_organizations": 40,
             "total_collaborators": 21,
             "total_contributors": 19,
             "average_org_rating": 3.2,
         }), \
         patch.object(oa, "fetch_growth_trend", return_value=[]), \
         patch.object(oa, "fetch_organizations_by_location", return_value=[]), \
         patch.object(oa, "fetch_organizations_by_size", return_value=[]), \
         patch.object(oa, "fetch_collaborator_vs_contributor", return_value=[]), \
         patch.object(oa, "fetch_rating_distribution", return_value=[]), \
         patch.object(oa, "fetch_organization_type_distribution", return_value=[]):

        event = {
            "time_filter": "ALL",
            "start_date": None,
            "end_date": None,
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "ALL",
        }

        response = oa.lambda_handler(event, None)

    assert response["statusCode"] == 200

    body = json.loads(response["body"])

    assert "summary" in body
    assert "growth_trend" in body
    assert "organizations_by_location" in body
    assert "organizations_by_size" in body
    assert "collaborator_vs_contributor" in body
    assert "rating_distribution" in body
    assert "organization_type_distribution" in body


def test_lambda_handler_invalid_request_returns_400():
    event = {
        "time_filter": "CUSTOM",
        "start_date": "2026-01-01",
        "end_date": None,
        "group_by": "monthly",
        "region": "ALL",
        "organization_type": "ALL",
    }

    response = oa.lambda_handler(event, None)

    assert response["statusCode"] == 400

    body = json.loads(response["body"])

    assert "error" in body


def test_lambda_handler_database_error_returns_500():
    with patch.object(
        oa,
        "get_db_connection",
        side_effect=Exception("Database unavailable"),
    ):
        event = {
            "time_filter": "ALL",
            "start_date": None,
            "end_date": None,
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "ALL",
        }

        response = oa.lambda_handler(event, None)

    assert response["statusCode"] == 500

    body = json.loads(response["body"])

    assert body["error"] == "Unable to fetch organization analytics"

def test_invalid_organization_type():
    filters = make_filters(
        organization_type="government"
    )

    with pytest.raises(ValueError):
        oa.validate_filters(filters)


def test_invalid_custom_date_format():
    filters = make_filters(
        time_filter="CUSTOM",
        start_date="01-01-2026",
        end_date="2026-06-30",
    )

    with pytest.raises(ValueError):
        oa.validate_filters(filters)


def test_build_custom_filter_parameters():
    filters = make_filters(
        time_filter="CUSTOM",
        start_date="2026-01-01",
        end_date="2026-06-30",
        group_by="monthly",
        region="California",
        organization_type="non_profit",
    )

    where_clause, params = oa.build_common_filters(filters)

    assert "o.created_at::date BETWEEN %s AND %s" in where_clause
    assert "s.state_name = %s" in where_clause
    assert "o.org_type = %s" in where_clause

    assert params == [
        "2026-01-01",
        "2026-06-30",
        "California",
        "Non-Profit",
    ]


def test_collaborator_vs_contributor_percentages():
    cursor = MagicMock()

    cursor.fetchone.side_effect = [
        {"column_exists": True},
        {
            "collaborator_count": 42,
            "contributor_count": 84,
        },
    ]

    filters = make_filters(
        time_filter="ALL",
        group_by="monthly",
    )

    result = oa.fetch_collaborator_vs_contributor(
        cursor,
        filters,
    )

    assert result == [
        {
            "type": "collaborator",
            "organization_count": 42,
            "percentage": 33.3,
        },
        {
            "type": "contributor",
            "organization_count": 84,
            "percentage": 66.7,
        },
    ]


def test_location_structure_and_percentage():
    cursor = MagicMock()

    cursor.fetchall.return_value = [
        {
            "state_id": "CA",
            "state_name": "California",
            "city_name": "Los Angeles",
            "organization_count": 2,
        },
        {
            "state_id": "CA",
            "state_name": "California",
            "city_name": "San Francisco",
            "organization_count": 1,
        },
        {
            "state_id": "TX",
            "state_name": "Texas",
            "city_name": "Dallas",
            "organization_count": 1,
        },
    ]

    filters = make_filters(
        time_filter="ALL",
        group_by="monthly",
    )

    result = oa.fetch_organizations_by_location(
        cursor,
        filters,
    )

    california = next(
        item for item in result
        if item["state_id"] == "CA"
    )

    texas = next(
        item for item in result
        if item["state_id"] == "TX"
    )

    assert california["organization_count"] == 3
    assert california["percentage"] == 75.0

    assert texas["organization_count"] == 1
    assert texas["percentage"] == 25.0