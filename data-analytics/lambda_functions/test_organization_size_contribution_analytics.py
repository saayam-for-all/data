import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


MODULE_PATH = Path(__file__).with_name("organization_size_contribution_analytics.py")
SPEC = importlib.util.spec_from_file_location("organization_size_contribution_analytics", MODULE_PATH)
analytics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analytics)


@pytest.fixture
def mock_data_dir(tmp_path, monkeypatch):
    organizations = pd.DataFrame(
        [
            {
                "org_id": "1",
                "org_size": "small",
                "is_collaborator": True,
                "is_contributor": True,
                "org_type": "non_profit",
                "state_id": "CA",
                "created_at": "2026-01-10",
            },
            {
                "org_id": "2",
                "org_size": "medium",
                "is_collaborator": False,
                "is_contributor": True,
                "org_type": "non_profit",
                "state_id": "CA",
                "created_at": "2026-02-15",
            },
            {
                "org_id": "3",
                "org_size": "large",
                "is_collaborator": True,
                "is_contributor": False,
                "org_type": "for_profit",
                "state_id": "ON",
                "created_at": "2025-06-01",
            },
            {
                "org_id": "4",
                "org_size": "small",
                "is_collaborator": False,
                "is_contributor": False,
                "org_type": "non_profit",
                "state_id": "CA",
                "created_at": "2024-01-01",
            },
        ]
    )
    states = pd.DataFrame(
        [
            {"state_id": "CA", "country_id": 1},
            {"state_id": "ON", "country_id": 2},
        ]
    )
    countries = pd.DataFrame(
        [
            {"country_id": 1, "country_code": "USA", "country_name": "United States"},
            {"country_id": 2, "country_code": "CAN", "country_name": "Canada"},
        ]
    )
    organizations.to_csv(tmp_path / "organizations.csv", index=False)
    states.to_csv(tmp_path / "states.csv", index=False)
    countries.to_csv(tmp_path / "countries.csv", index=False)

    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    return tmp_path


def response_body(event):
    response = analytics.lambda_handler(event, None)
    return response["statusCode"], json.loads(response["body"])


def test_no_custom_params_returns_fixed_buckets_and_empty_custom(mock_data_dir):
    status_code, body = response_body({})

    assert status_code == 200
    assert list(body.keys()) == ["7D", "30D", "1Y", "All", "Custom"]
    assert body["Custom"] == {"organizations_by_size": [], "collaborator_vs_contributor": []}
    for bucket in ["7D", "30D", "1Y", "All", "Custom"]:
        assert set(body[bucket].keys()) == {"organizations_by_size", "collaborator_vs_contributor"}


def test_size_custom_range_returns_custom_only_with_size_chart(mock_data_dir):
    status_code, body = response_body({"size_start_date": "2026-01-01", "size_end_date": "2026-12-31"})

    assert status_code == 200
    assert list(body.keys()) == ["Custom"]
    assert body["Custom"]["organizations_by_size"] == [
        {"size": "medium", "count": 1},
        {"size": "small", "count": 1},
    ]
    assert body["Custom"]["collaborator_vs_contributor"] == []


def test_contribution_custom_range_returns_custom_only_with_contribution_chart(mock_data_dir):
    status_code, body = response_body({"contribution_start_date": "2026-01-01", "contribution_end_date": "2026-12-31"})

    assert status_code == 200
    assert list(body.keys()) == ["Custom"]
    assert body["Custom"]["organizations_by_size"] == []
    assert body["Custom"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 50.0},
        {"type": "Contributor", "count": 2, "percentage": 100.0},
    ]


def test_both_custom_ranges_are_evaluated_independently(mock_data_dir):
    status_code, body = response_body(
        {
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-12-31",
            "contribution_start_date": "2025-01-01",
            "contribution_end_date": "2025-12-31",
        }
    )

    assert status_code == 200
    assert list(body.keys()) == ["Custom"]
    assert body["Custom"]["organizations_by_size"] == [
        {"size": "medium", "count": 1},
        {"size": "small", "count": 1},
    ]
    assert body["Custom"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 100.0},
        {"type": "Contributor", "count": 0, "percentage": 0.0},
    ]


def test_country_and_organization_type_filters_apply_to_custom_ranges(mock_data_dir):
    status_code, body = response_body(
        {
            "country": "USA",
            "organization_type": "non_profit",
            "size_start_date": "2024-01-01",
            "size_end_date": "2026-12-31",
            "contribution_start_date": "2024-01-01",
            "contribution_end_date": "2026-12-31",
        }
    )

    assert status_code == 200
    assert body["Custom"]["organizations_by_size"] == [
        {"size": "small", "count": 2},
        {"size": "medium", "count": 1},
    ]
    assert body["Custom"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 33.3},
        {"type": "Contributor", "count": 2, "percentage": 66.7},
    ]


def test_incomplete_bad_or_reversed_date_ranges_return_400(mock_data_dir):
    bad_events = [
        {"size_start_date": "2026-01-01"},
        {"contribution_start_date": "not-a-date", "contribution_end_date": "2026-01-01"},
        {"size_start_date": "2026-02-01", "size_end_date": "2026-01-01"},
    ]

    for event in bad_events:
        status_code, body = response_body(event)
        assert status_code == 400
        assert "error" in body


def test_missing_is_contributor_column_degrades_to_zero(tmp_path, monkeypatch):
    organizations = pd.DataFrame(
        [
            {
                "org_id": "1",
                "org_size": "small",
                "is_collaborator": True,
                "org_type": "non_profit",
                "state_id": "CA",
                "created_at": "2026-01-10",
            }
        ]
    )
    pd.DataFrame([{"state_id": "CA", "country_id": 1}]).to_csv(tmp_path / "states.csv", index=False)
    pd.DataFrame([{"country_id": 1, "country_code": "USA", "country_name": "United States"}]).to_csv(
        tmp_path / "countries.csv",
        index=False,
    )
    organizations.to_csv(tmp_path / "organizations.csv", index=False)

    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))

    status_code, body = response_body({"contribution_start_date": "2026-01-01", "contribution_end_date": "2026-12-31"})

    assert status_code == 200
    assert body["Custom"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 100.0},
        {"type": "Contributor", "count": 0, "percentage": 0.0},
    ]
