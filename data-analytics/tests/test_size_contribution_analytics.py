"""
Unit tests for Size & Contribution Analytics API (Issue #376).
"""

import json
import os
import sys
from datetime import date
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

# Ensure lambda_functions directory is in path
LAMBDA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lambda_functions"))
if LAMBDA_DIR not in sys.path:
    sys.path.insert(0, LAMBDA_DIR)

from size_contribution_analytics import (
    lambda_handler,
    parse_event_body,
    parse_and_validate_date_pair,
    apply_filters,
    filter_by_window,
    calculate_organizations_by_size,
    calculate_collaborator_vs_contributor,
    prepare_dataframe,
)

SAMPLE_REF_DATE = date(2026, 1, 15)


def make_sample_df():
    """Helper to create a reproducible synthetic in-memory DataFrame."""
    return pd.DataFrame([
        {
            "org_id": "ORG001",
            "org_size": "Small",
            "org_type": "Non-Profit",
            "is_collaborator": True,
            "is_contributor": False,
            "created_at": "2026-01-12 10:00:00",
            "country_code": "USA",
            "country_name": "UNITED_STATES_OF_AMERICA"
        },
        {
            "org_id": "ORG002",
            "org_size": "Medium",
            "org_type": "For-profit",
            "is_collaborator": True,
            "is_contributor": True,
            "created_at": "2026-01-05 14:00:00",
            "country_code": "USA",
            "country_name": "UNITED_STATES_OF_AMERICA"
        },
        {
            "org_id": "ORG003",
            "org_size": "Large",
            "org_type": "Non-Profit",
            "is_collaborator": False,
            "is_contributor": True,
            "created_at": "2025-12-20 09:00:00",
            "country_code": "USA",
            "country_name": "UNITED_STATES_OF_AMERICA"
        },
        {
            "org_id": "ORG004",
            "org_size": "Small",
            "org_type": "Non-Profit",
            "is_collaborator": False,
            "is_contributor": False,
            "created_at": "2025-06-15 11:30:00",
            "country_code": "CAN",
            "country_name": "CANADA"
        },
        {
            "org_id": "ORG005",
            "org_size": "Large",
            "org_type": "For-profit",
            "is_collaborator": True,
            "is_contributor": False,
            "created_at": "2024-05-10 16:00:00",
            "country_code": "USA",
            "country_name": "UNITED_STATES_OF_AMERICA"
        }
    ])


# =========================================================================
# 1. RESPONSE SHAPES
# =========================================================================

def test_no_custom_params_returns_all_buckets_and_empty_custom():
    """Default request returns exactly 5 top-level keys: 7D, 30D, 1Y, All, Custom."""
    df = make_sample_df()
    resp = lambda_handler({}, reference_date=SAMPLE_REF_DATE, df_override=df)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])

    assert set(body.keys()) == {"7D", "30D", "1Y", "All", "Custom"}
    # Custom charts must be empty
    assert body["Custom"]["organizations_by_size"] == []
    assert body["Custom"]["collaborator_vs_contributor"] == []

    # Fixed buckets must have both charts
    for bucket in ["7D", "30D", "1Y", "All"]:
        assert "organizations_by_size" in body[bucket]
        assert "collaborator_vs_contributor" in body[bucket]


def test_size_custom_only_returns_custom_only():
    """Only size date range provided -> response has only 'Custom' key."""
    df = make_sample_df()
    event = {
        "size_start_date": "2025-12-01",
        "size_end_date": "2026-01-15"
    }
    resp = lambda_handler(event, reference_date=SAMPLE_REF_DATE, df_override=df)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])

    assert list(body.keys()) == ["Custom"]
    assert len(body["Custom"]["organizations_by_size"]) > 0
    assert body["Custom"]["collaborator_vs_contributor"] == []


def test_contribution_custom_only_returns_custom_only():
    """Only contribution date range provided -> response has only 'Custom' key."""
    df = make_sample_df()
    event = {
        "contribution_start_date": "2025-12-01",
        "contribution_end_date": "2026-01-15"
    }
    resp = lambda_handler(event, reference_date=SAMPLE_REF_DATE, df_override=df)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])

    assert list(body.keys()) == ["Custom"]
    assert body["Custom"]["organizations_by_size"] == []
    assert len(body["Custom"]["collaborator_vs_contributor"]) == 2


def test_both_custom_pairs_populated_independently():
    """Both Custom pairs provided -> response is Custom-only with both sub-charts populated."""
    df = make_sample_df()
    event = {
        "size_start_date": "2026-01-01",
        "size_end_date": "2026-01-15",
        "contribution_start_date": "2025-06-01",
        "contribution_end_date": "2026-01-15"
    }
    resp = lambda_handler(event, reference_date=SAMPLE_REF_DATE, df_override=df)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])

    assert list(body.keys()) == ["Custom"]
    # Size window: 2026-01-01 to 2026-01-15 has ORG001 and ORG002 (2 total)
    size_total = sum(item["count"] for item in body["Custom"]["organizations_by_size"])
    assert size_total == 2

    # Contribution window: 2025-06-01 to 2026-01-15 has ORG001, ORG002, ORG003, ORG004 (4 total)
    collab_row = next(r for r in body["Custom"]["collaborator_vs_contributor"] if r["type"] == "Collaborator")
    contrib_row = next(r for r in body["Custom"]["collaborator_vs_contributor"] if r["type"] == "Contributor")
    # In window of 4: ORG001 (collab=T), ORG002 (collab=T, contrib=T), ORG003 (contrib=T), ORG004 (neither)
    assert collab_row["count"] == 2
    assert collab_row["percentage"] == 50.0
    assert contrib_row["count"] == 2
    assert contrib_row["percentage"] == 50.0


# =========================================================================
# 2. DATE VALIDATION & ERROR HANDLING
# =========================================================================

def test_missing_half_of_size_pair():
    """Supplying only start date without end date returns 400."""
    resp = lambda_handler({"size_start_date": "2026-01-01"}, df_override=make_sample_df())
    assert resp["statusCode"] == 400
    assert "size_start_date and size_end_date must be provided together" in json.loads(resp["body"])["error"]

    resp2 = lambda_handler({"size_end_date": "2026-01-15"}, df_override=make_sample_df())
    assert resp2["statusCode"] == 400
    assert "size_start_date and size_end_date must be provided together" in json.loads(resp2["body"])["error"]


def test_missing_half_of_contribution_pair():
    """Supplying only one half of contribution pair returns 400."""
    resp = lambda_handler({"contribution_start_date": "2026-01-01"}, df_override=make_sample_df())
    assert resp["statusCode"] == 400
    assert "contribution_start_date and contribution_end_date must be provided together" in json.loads(resp["body"])["error"]


def test_malformed_date_format():
    """Invalid date format returns 400."""
    resp = lambda_handler({
        "size_start_date": "01-01-2026",
        "size_end_date": "2026-01-15"
    }, df_override=make_sample_df())
    assert resp["statusCode"] == 400
    assert "Invalid date format" in json.loads(resp["body"])["error"]


def test_start_date_after_end_date():
    """Start date after end date returns 400."""
    resp = lambda_handler({
        "size_start_date": "2026-06-30",
        "size_end_date": "2026-01-01"
    }, df_override=make_sample_df())
    assert resp["statusCode"] == 400
    assert "cannot be after" in json.loads(resp["body"])["error"]


# =========================================================================
# 3. FILTERS (COUNTRY & ORGANIZATION_TYPE)
# =========================================================================

def test_country_filter_matching():
    """Filtering by country only includes organizations for that country."""
    df = make_sample_df()
    resp = lambda_handler({"country": "CAN"}, reference_date=SAMPLE_REF_DATE, df_override=df)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])

    # In synthetic data, only ORG004 is CAN
    all_sizes = body["All"]["organizations_by_size"]
    assert len(all_sizes) == 1
    assert all_sizes[0]["size"] == "Small"
    assert all_sizes[0]["count"] == 1


def test_country_filter_usa_synonyms():
    """USA synonyms ('usa', 'USA', 'United States') work properly."""
    df = make_sample_df()
    for c in ["USA", "usa", "United States", "ALL"]:
        resp = lambda_handler({"country": c}, reference_date=SAMPLE_REF_DATE, df_override=df)
        assert resp["statusCode"] == 200


def test_organization_type_filter():
    """Filtering by organization_type matches expected type."""
    df = make_sample_df()
    resp = lambda_handler({"organization_type": "non_profit"}, reference_date=SAMPLE_REF_DATE, df_override=df)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])

    # ORG001 (Small), ORG003 (Large), ORG004 (Small) -> total 3 Non-Profit
    total_non_profit = sum(x["count"] for x in body["All"]["organizations_by_size"])
    assert total_non_profit == 3


def test_invalid_organization_type():
    """Invalid organization_type returns 400."""
    df = make_sample_df()
    resp = lambda_handler({"organization_type": "government"}, reference_date=SAMPLE_REF_DATE, df_override=df)
    assert resp["statusCode"] == 400
    assert "organization_type must be non_profit, for_profit, or ALL" in json.loads(resp["body"])["error"]


# =========================================================================
# 4. CHART COMPUTATION & DATA RESILIENCE
# =========================================================================

def test_collaborator_vs_contributor_independent_counts():
    """
    Collaborator and Contributor are counted independently against the bucket's total.
    Not expected to sum to 100% or total.
    """
    df = pd.DataFrame([
        {"org_id": "1", "org_size": "Small", "is_collaborator": True, "is_contributor": True, "created_at": "2026-01-10", "country_code": "USA", "country_name": "USA"},
        {"org_id": "2", "org_size": "Medium", "is_collaborator": False, "is_contributor": False, "created_at": "2026-01-10", "country_code": "USA", "country_name": "USA"},
    ])
    resp = lambda_handler({}, reference_date=SAMPLE_REF_DATE, df_override=df)
    body = json.loads(resp["body"])

    all_cc = body["All"]["collaborator_vs_contributor"]
    collab = next(r for r in all_cc if r["type"] == "Collaborator")
    contrib = next(r for r in all_cc if r["type"] == "Contributor")

    # 1 out of 2 is collaborator (50.0%), 1 out of 2 is contributor (50.0%)
    assert collab["count"] == 1
    assert collab["percentage"] == 50.0
    assert contrib["count"] == 1
    assert contrib["percentage"] == 50.0


def test_missing_is_contributor_column_graceful_degradation():
    """Missing is_contributor column in dataset degrades to Contributor count=0, percentage=0.0."""
    df = pd.DataFrame([
        {"org_id": "1", "org_size": "Small", "is_collaborator": True, "created_at": "2026-01-10", "country_code": "USA", "country_name": "USA"}
    ])
    resp = lambda_handler({}, reference_date=SAMPLE_REF_DATE, df_override=df)
    body = json.loads(resp["body"])

    all_cc = body["All"]["collaborator_vs_contributor"]
    contrib = next(r for r in all_cc if r["type"] == "Contributor")
    assert contrib["count"] == 0
    assert contrib["percentage"] == 0.0


def test_empty_dataframe_does_not_crash():
    """Empty dataset returns empty arrays without error."""
    df = pd.DataFrame(columns=["org_id", "org_size", "org_type", "is_collaborator", "is_contributor", "created_at"])
    resp = lambda_handler({}, reference_date=SAMPLE_REF_DATE, df_override=df)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["All"]["organizations_by_size"] == []
    assert body["All"]["collaborator_vs_contributor"] == []


def test_single_row_dataframe():
    """1-row dataset works cleanly without error."""
    df = pd.DataFrame([{
        "org_id": "1",
        "org_size": "Small",
        "org_type": "Non-Profit",
        "is_collaborator": True,
        "is_contributor": False,
        "created_at": "2026-01-10",
        "country_code": "USA",
        "country_name": "USA"
    }])
    resp = lambda_handler({}, reference_date=SAMPLE_REF_DATE, df_override=df)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["All"]["organizations_by_size"] == [{"size": "Small", "count": 1}]
    assert body["All"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 100.0},
        {"type": "Contributor", "count": 0, "percentage": 0.0}
    ]


def test_raw_enum_values_preserved():
    """Emits whatever size categories actually appear, using raw values as-is."""
    df = pd.DataFrame([
        {"org_id": "1", "org_size": "custom_small", "is_collaborator": True, "created_at": "2026-01-10", "country_code": "USA", "country_name": "USA"},
        {"org_id": "2", "org_size": "custom_large", "is_collaborator": False, "created_at": "2026-01-10", "country_code": "USA", "country_name": "USA"}
    ])
    resp = lambda_handler({}, reference_date=SAMPLE_REF_DATE, df_override=df)
    body = json.loads(resp["body"])
    sizes = [x["size"] for x in body["All"]["organizations_by_size"]]
    assert "custom_small" in sizes
    assert "custom_large" in sizes


def test_api_gateway_event_body_parsing():
    """Accepts event with 'body' stringified JSON or dict."""
    df = make_sample_df()
    event_str = {"body": json.dumps({"country": "USA"})}
    resp = lambda_handler(event_str, reference_date=SAMPLE_REF_DATE, df_override=df)
    assert resp["statusCode"] == 200

    event_invalid = {"body": "invalid-json{{"}
    resp_invalid = lambda_handler(event_invalid, df_override=df)
    assert resp_invalid["statusCode"] == 400


# =========================================================================
# 5. REAL CSV AND POSTGRES INTEGRATION TESTS
# =========================================================================

def test_full_pipeline_against_local_csvs():
    """Verify execution against actual repository sample CSV files."""
    resp = lambda_handler({}, reference_date=SAMPLE_REF_DATE)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "All" in body
    assert len(body["All"]["organizations_by_size"]) > 0
    assert len(body["All"]["collaborator_vs_contributor"]) == 2


def test_database_path_when_mock_data_disabled(monkeypatch):
    """Test optional psycopg2 PostgreSQL path with mock DB connection."""
    monkeypatch.setenv("USE_MOCK_DATA", "false")

    fake_df = pd.DataFrame([{
        "org_id": "DB001",
        "org_size": "Medium",
        "org_type": "non_profit",
        "created_at": "2026-01-10 12:00:00",
        "is_collaborator": True,
        "is_contributor": True,
        "country_code": "USA",
        "country_name": "UNITED_STATES_OF_AMERICA"
    }])

    with patch("psycopg2.connect") as mock_connect, \
         patch("pandas.read_sql", return_value=fake_df):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        resp = lambda_handler({}, reference_date=SAMPLE_REF_DATE)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["All"]["organizations_by_size"] == [{"size": "Medium", "count": 1}]
