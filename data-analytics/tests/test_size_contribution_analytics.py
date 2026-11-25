"""Tests for Size & Contribution Analytics API (issue #376)."""

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

import size_contribution_analytics as api  # noqa: E402


def make_organizations(include_contributor=True):
    rows = [
        {
            "org_id": "ORG1",
            "org_size": "small",
            "is_collaborator": True,
            "is_contributor": True,
            "org_type": "non_profit",
            "state_id": "CA",
            "created_at": pd.Timestamp("2026-09-22 10:00:00"),
        },
        {
            "org_id": "ORG2",
            "org_size": "medium",
            "is_collaborator": False,
            "is_contributor": True,
            "org_type": "for_profit",
            "state_id": "TX",
            "created_at": pd.Timestamp("2026-09-01 10:00:00"),
        },
        {
            "org_id": "ORG3",
            "org_size": "large",
            "is_collaborator": True,
            "is_contributor": False,
            "org_type": "non_profit",
            "state_id": "MH",
            "created_at": pd.Timestamp("2025-10-01 10:00:00"),
        },
        {
            "org_id": "ORG4",
            "org_size": "small",
            "is_collaborator": False,
            "is_contributor": False,
            "org_type": "Non-Profit",
            "state_id": "CA",
            "created_at": pd.Timestamp("2024-01-01 10:00:00"),
        },
    ]

    frame = pd.DataFrame(rows)
    if not include_contributor:
        frame = frame.drop(columns=["is_contributor"])
    return frame


def make_states():
    return pd.DataFrame(
        [
            {"state_id": "CA", "country_id": 1},
            {"state_id": "TX", "country_id": 1},
            {"state_id": "MH", "country_id": 2},
        ]
    )


def make_countries():
    return pd.DataFrame(
        [
            {
                "country_id": 1,
                "country_code": "USA",
                "country_name": "UNITED_STATES",
            },
            {
                "country_id": 2,
                "country_code": "IND",
                "country_name": "INDIA",
            },
        ]
    )


@pytest.fixture
def mock_data(monkeypatch):
    organizations = make_organizations()
    states = make_states()
    countries = make_countries()

    monkeypatch.setattr(
        api,
        "load_data",
        lambda: (
            organizations.copy(),
            states.copy(),
            countries.copy(),
        ),
    )
    monkeypatch.setattr(
        api,
        "current_date",
        lambda: pd.Timestamp("2026-09-23"),
    )
    return organizations, states, countries


def parse_body(response):
    return json.loads(response["body"])


def test_no_body_returns_exact_five_keys(mock_data):
    body = parse_body(api.lambda_handler({}, None))

    assert list(body.keys()) == ["7D", "30D", "1Y", "All", "Custom"]
    for bucket in body.values():
        assert set(bucket.keys()) == {
            "organizations_by_size",
            "collaborator_vs_contributor",
        }

    assert body["Custom"] == {
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
    }


def test_size_custom_only_returns_custom_key(mock_data):
    event = {
        "body": json.dumps(
            {
                "size_start_date": "2026-01-01",
                "size_end_date": "2026-12-31",
            }
        )
    }
    body = parse_body(api.lambda_handler(event, None))

    assert list(body.keys()) == ["Custom"]
    assert body["Custom"]["organizations_by_size"]
    assert body["Custom"]["collaborator_vs_contributor"] == []


def test_contribution_custom_only_returns_custom_key(mock_data):
    event = {
        "body": json.dumps(
            {
                "contribution_start_date": "2026-01-01",
                "contribution_end_date": "2026-12-31",
            }
        )
    }
    body = parse_body(api.lambda_handler(event, None))

    assert list(body.keys()) == ["Custom"]
    assert body["Custom"]["organizations_by_size"] == []
    assert len(body["Custom"]["collaborator_vs_contributor"]) == 2


def test_both_custom_ranges_populate_both_charts(mock_data):
    event = {
        "body": json.dumps(
            {
                "size_start_date": "2024-01-01",
                "size_end_date": "2026-12-31",
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2026-12-31",
            }
        )
    }
    body = parse_body(api.lambda_handler(event, None))

    assert list(body.keys()) == ["Custom"]
    assert body["Custom"]["organizations_by_size"]
    assert len(body["Custom"]["collaborator_vs_contributor"]) == 2


def test_country_code_filter(mock_data):
    event = {"body": json.dumps({"country": "IND"})}
    body = parse_body(api.lambda_handler(event, None))
    total = sum(
        row["count"] for row in body["All"]["organizations_by_size"]
    )
    assert total == 1


def test_country_name_filter(mock_data):
    event = {"body": json.dumps({"country": "United States"})}
    body = parse_body(api.lambda_handler(event, None))
    total = sum(
        row["count"] for row in body["All"]["organizations_by_size"]
    )
    assert total == 3


def test_organization_type_filter_normalizes(mock_data):
    event = {"body": json.dumps({"organization_type": "non_profit"})}
    body = parse_body(api.lambda_handler(event, None))
    total = sum(
        row["count"] for row in body["All"]["organizations_by_size"]
    )
    assert total == 3


def test_contribution_counts_are_independent(mock_data):
    body = parse_body(api.lambda_handler({}, None))
    rows = body["All"]["collaborator_vs_contributor"]

    assert rows[0] == {
        "type": "Collaborator",
        "count": 2,
        "percentage": 50.0,
    }
    assert rows[1] == {
        "type": "Contributor",
        "count": 2,
        "percentage": 50.0,
    }


def test_missing_contributor_column_becomes_zero(monkeypatch):
    organizations = make_organizations(include_contributor=False)
    states = make_states()
    countries = make_countries()

    prepared = api.prepare_organizations(organizations)

    monkeypatch.setattr(
        api,
        "load_data",
        lambda: (prepared.copy(), states.copy(), countries.copy()),
    )
    monkeypatch.setattr(
        api,
        "current_date",
        lambda: pd.Timestamp("2026-09-23"),
    )

    body = parse_body(api.lambda_handler({}, None))
    contributor = body["All"]["collaborator_vs_contributor"][1]
    assert contributor["count"] == 0
    assert contributor["percentage"] == 0.0


@pytest.mark.parametrize(
    "payload",
    [
        {"size_start_date": "2026-01-01"},
        {"contribution_end_date": "2026-12-31"},
        {
            "size_start_date": "01-01-2026",
            "size_end_date": "12-31-2026",
        },
        {
            "size_start_date": "2026-12-31",
            "size_end_date": "2026-01-01",
        },
        {
            "contribution_start_date": "bad-date",
            "contribution_end_date": "2026-02-01",
        },
        {"organization_type": "government"},
    ],
)
def test_invalid_input_returns_400(mock_data, payload):
    response = api.lambda_handler({"body": json.dumps(payload)}, None)
    assert response["statusCode"] == 400
    assert "error" in parse_body(response)


def test_empty_organizations_does_not_crash(monkeypatch):
    monkeypatch.setattr(
        api,
        "load_data",
        lambda: (
            api.prepare_organizations(
                pd.DataFrame(
                    columns=[
                        "org_id",
                        "org_size",
                        "is_collaborator",
                        "is_contributor",
                        "org_type",
                        "state_id",
                        "created_at",
                    ]
                )
            ),
            make_states(),
            make_countries(),
        ),
    )
    monkeypatch.setattr(
        api,
        "current_date",
        lambda: pd.Timestamp("2026-09-23"),
    )

    body = parse_body(api.lambda_handler({}, None))
    for bucket in body.values():
        assert bucket == api.empty_charts()


def test_single_row_does_not_crash(monkeypatch):
    organizations = make_organizations().iloc[[0]].copy()
    monkeypatch.setattr(
        api,
        "load_data",
        lambda: (
            organizations.copy(),
            make_states(),
            make_countries(),
        ),
    )
    monkeypatch.setattr(
        api,
        "current_date",
        lambda: pd.Timestamp("2026-09-23"),
    )

    body = parse_body(api.lambda_handler({}, None))
    assert body["All"]["organizations_by_size"] == [
        {"size": "small", "count": 1}
    ]


def test_7d_window_is_snapshot_not_all(mock_data):
    body = parse_body(api.lambda_handler({}, None))
    assert body["7D"]["organizations_by_size"] == [
        {"size": "small", "count": 1}
    ]
    assert body["7D"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 100.0},
        {"type": "Contributor", "count": 1, "percentage": 100.0},
    ]


def test_api_gateway_json_body_supported(mock_data):
    response = api.lambda_handler(
        {"body": json.dumps({"organization_type": "non_profit"})},
        None,
    )
    assert response["statusCode"] == 200
    assert set(parse_body(response)) == {
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    }
