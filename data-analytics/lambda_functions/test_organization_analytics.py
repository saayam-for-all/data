"""Unit tests for organization_analytics.py (issue #228).

Runs entirely against in-memory mock data -- no local Postgres or AWS
connection required.
"""

from io import StringIO
from unittest.mock import patch

import pandas as pd
import pytest

import organization_analytics as oa

ORG_CSV = StringIO(
    "org_id,org_name,street,city_name,state_id,zip_code,mission,web_url,phone,email,"
    "org_type,org_size,org_rating,is_collaborator,is_contributor,created_at,last_updated_at\n"
    "ORG001,Org One,1 Main St,CityA,CA,90001,Mission A,https://a.org,111-111-1111,a@a.org,"
    "Non-Profit,Small,5,TRUE,FALSE,2026-07-01 10:00:00,2026-07-01 10:00:00\n"
    "ORG002,Org Two,2 Oak St,CityB,TX,75001,Mission B,https://b.org,222-222-2222,b@b.org,"
    "For-profit,Large,3,FALSE,TRUE,2026-06-15 10:00:00,2026-06-15 10:00:00\n"
    "ORG003,Org Three,3 Elm St,CityC,CA,90002,Mission C,https://c.org,333-333-3333,c@c.org,"
    "Non-Profit,Medium,,TRUE,TRUE,2026-05-01 10:00:00,2026-05-01 10:00:00\n"
)

STATE_CSV = StringIO(
    "state_id,country_id,state_name,state_code,last_update_date\n"
    "CA,1,California,US-CA,2025-08-08 00:00:00\n"
    "TX,1,Texas,US-TX,2025-08-08 00:00:00\n"
)


def _load_mock_data():
    ORG_CSV.seek(0)
    STATE_CSV.seek(0)
    orgs = pd.read_csv(ORG_CSV)
    states = pd.read_csv(STATE_CSV)
    orgs["created_at"] = pd.to_datetime(orgs["created_at"])
    orgs["org_rating"] = pd.to_numeric(orgs["org_rating"], errors="coerce")
    orgs["is_collaborator"] = orgs["is_collaborator"].map(oa.BOOL_MAP)
    orgs["is_contributor"] = orgs["is_contributor"].map(oa.BOOL_MAP)
    return orgs, states


@pytest.fixture
def mock_data():
    return _load_mock_data()


def test_summary_counts_all_orgs(mock_data):
    orgs, states = mock_data
    result = oa.build_analytics(orgs, states, {"time_filter": "ALL"})
    assert result["summary"]["total_organizations"] == 3
    assert result["summary"]["total_collaborators"] == 2
    assert result["summary"]["total_contributors"] == 2


def test_region_filter(mock_data):
    orgs, states = mock_data
    result = oa.build_analytics(orgs, states, {"time_filter": "ALL", "region": "California"})
    assert result["summary"]["total_organizations"] == 2


def test_organization_type_filter(mock_data):
    orgs, states = mock_data
    result = oa.build_analytics(
        orgs, states, {"time_filter": "ALL", "organization_type": "non_profit"}
    )
    assert result["summary"]["total_organizations"] == 2


def test_custom_date_range(mock_data):
    orgs, states = mock_data
    result = oa.build_analytics(
        orgs,
        states,
        {"time_filter": "CUSTOM", "start_date": "2026-06-01", "end_date": "2026-07-31"},
    )
    assert result["summary"]["total_organizations"] == 2


def test_custom_range_missing_dates_falls_back_to_all(mock_data):
    orgs, states = mock_data
    result = oa.build_analytics(orgs, states, {"time_filter": "CUSTOM"})
    assert result["summary"]["total_organizations"] == 3


def test_invalid_time_filter_falls_back_to_all(mock_data):
    orgs, states = mock_data
    result = oa.build_analytics(orgs, states, {"time_filter": "NOT_A_REAL_FILTER"})
    assert result["summary"]["total_organizations"] == 3


def test_unknown_region_returns_empty_result(mock_data):
    orgs, states = mock_data
    result = oa.build_analytics(orgs, states, {"time_filter": "ALL", "region": "Nowhereland"})
    assert result["summary"]["total_organizations"] == 0
    assert result["growth_trend"] == []
    assert result["organizations_by_location"] == []


def test_empty_result_set_has_safe_defaults(mock_data):
    orgs, states = mock_data
    result = oa.build_analytics(
        orgs,
        states,
        {"time_filter": "CUSTOM", "start_date": "2020-01-01", "end_date": "2020-12-31"},
    )
    assert result["summary"] == {
        "total_organizations": 0,
        "total_collaborators": 0,
        "total_contributors": 0,
        "average_org_rating": 0,
    }
    assert result["rating_distribution"] == []
    assert result["organization_type_distribution"] == []


def test_null_rating_excluded_from_distribution_but_not_fatal(mock_data):
    orgs, states = mock_data
    result = oa.build_analytics(orgs, states, {"time_filter": "ALL"})
    # ORG003 has a NULL rating and must not appear, and must not crash the average.
    assert result["summary"]["average_org_rating"] == 4.0
    ratings_seen = [r["rating"] for r in result["rating_distribution"]]
    assert None not in ratings_seen


def test_response_structure_matches_spec(mock_data):
    orgs, states = mock_data
    result = oa.build_analytics(orgs, states, {"time_filter": "ALL"})
    for key in (
        "summary",
        "growth_trend",
        "organizations_by_location",
        "organizations_by_size",
        "collaborator_vs_contributor",
        "rating_distribution",
        "organization_type_distribution",
    ):
        assert key in result


def test_lambda_handler_returns_200_on_success():
    with patch("organization_analytics.load_organizations", return_value=_load_mock_data()):
        response = oa.lambda_handler({"time_filter": "ALL"}, None)
    assert response["statusCode"] == 200
    assert response["body"]["summary"]["total_organizations"] == 3


def test_lambda_handler_returns_500_on_load_failure():
    with patch("organization_analytics.load_organizations", side_effect=FileNotFoundError("missing csv")):
        response = oa.lambda_handler({"time_filter": "ALL"}, None)
    assert response["statusCode"] == 500
    assert response["body"]["summary"]["total_organizations"] == 0


def test_lambda_handler_parses_string_body():
    with patch("organization_analytics.load_organizations", return_value=_load_mock_data()):
        response = oa.lambda_handler({"body": '{"time_filter": "ALL", "region": "Texas"}'}, None)
    assert response["statusCode"] == 200
    assert response["body"]["summary"]["total_organizations"] == 1
