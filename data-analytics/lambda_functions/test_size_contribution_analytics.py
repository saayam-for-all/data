import json

import pandas as pd
import pytest

import size_contribution_analytics as analytics


@pytest.fixture
def mock_data_dir(tmp_path, monkeypatch):
    organizations = pd.DataFrame([
        {
            "org_id": 1,
            "org_size": "small",
            "is_collaborator": True,
            "is_contributor": False,
            "org_type": "non_profit",
            "state_id": 101,
            "created_at": "2026-01-10"
        },
        {
            "org_id": 2,
            "org_size": "medium",
            "is_collaborator": True,
            "is_contributor": True,
            "org_type": "non_profit",
            "state_id": 101,
            "created_at": "2026-02-15"
        },
        {
            "org_id": 3,
            "org_size": "large",
            "is_collaborator": False,
            "is_contributor": True,
            "org_type": "for_profit",
            "state_id": 102,
            "created_at": "2025-06-20"
        },
        {
            "org_id": 4,
            "org_size": "small",
            "is_collaborator": True,
            "is_contributor": True,
            "org_type": "for_profit",
            "state_id": 102,
            "created_at": "2025-12-01"
        }
    ])

    states = pd.DataFrame([
        {
            "state_id": 101,
            "country_id": 1
        },
        {
            "state_id": 102,
            "country_id": 2
        }
    ])

    countries = pd.DataFrame([
        {
            "country_id": 1,
            "country_code": "US",
            "country_name": "United States"
        },
        {
            "country_id": 2,
            "country_code": "CA",
            "country_name": "Canada"
        }
    ])

    organizations.to_csv(
        tmp_path / "organizations.csv",
        index=False
    )

    states.to_csv(
        tmp_path / "state.csv",
        index=False
    )

    countries.to_csv(
        tmp_path / "country.csv",
        index=False
    )

    monkeypatch.setattr(
        analytics,
        "USE_MOCK_DATA",
        True
    )

    monkeypatch.setattr(
        analytics,
        "MOCK_DATA_DIR",
        str(tmp_path)
    )

    return tmp_path


def get_body(response):
    return json.loads(response["body"])


def test_no_custom_returns_five_keys(mock_data_dir):
    response = analytics.lambda_handler(
        {"body": {}},
        None
    )

    assert response["statusCode"] == 200

    body = get_body(response)

    assert list(body.keys()) == [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom"
    ]

    assert body["Custom"]["organizations_by_size"] == []
    assert body["Custom"]["collaborator_vs_contributor"] == []


def test_country_filter(mock_data_dir):
    response = analytics.lambda_handler(
        {
            "body": {
                "country": "US"
            }
        },
        None
    )

    assert response["statusCode"] == 200

    body = get_body(response)

    all_sizes = body["All"]["organizations_by_size"]

    counts = {
        item["size"]: item["count"]
        for item in all_sizes
    }

    assert counts == {
        "small": 1,
        "medium": 1
    }


def test_organization_type_filter(mock_data_dir):
    response = analytics.lambda_handler(
        {
            "body": {
                "organization_type": "non_profit"
            }
        },
        None
    )

    assert response["statusCode"] == 200

    body = get_body(response)

    all_sizes = body["All"]["organizations_by_size"]

    counts = {
        item["size"]: item["count"]
        for item in all_sizes
    }

    assert counts == {
        "small": 1,
        "medium": 1
    }


def test_size_custom_only(mock_data_dir):
    response = analytics.lambda_handler(
        {
            "body": {
                "size_start_date": "2026-01-01",
                "size_end_date": "2026-06-30"
            }
        },
        None
    )

    assert response["statusCode"] == 200

    body = get_body(response)

    assert list(body.keys()) == ["Custom"]

    assert body["Custom"]["collaborator_vs_contributor"] == []

    sizes = body["Custom"]["organizations_by_size"]

    counts = {
        item["size"]: item["count"]
        for item in sizes
    }

    assert counts == {
        "small": 1,
        "medium": 1
    }


def test_contribution_custom_only(mock_data_dir):
    response = analytics.lambda_handler(
        {
            "body": {
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2025-12-31"
            }
        },
        None
    )

    assert response["statusCode"] == 200

    body = get_body(response)

    assert list(body.keys()) == ["Custom"]

    assert body["Custom"]["organizations_by_size"] == []

    contribution = body["Custom"]["collaborator_vs_contributor"]

    assert contribution == [
        {
            "type": "Collaborator",
            "count": 1,
            "percentage": 50.0
        },
        {
            "type": "Contributor",
            "count": 2,
            "percentage": 100.0
        }
    ]


def test_both_custom_ranges(mock_data_dir):
    response = analytics.lambda_handler(
        {
            "body": {
                "size_start_date": "2026-01-01",
                "size_end_date": "2026-06-30",
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2025-12-31"
            }
        },
        None
    )

    assert response["statusCode"] == 200

    body = get_body(response)

    assert list(body.keys()) == ["Custom"]

    assert body["Custom"]["organizations_by_size"]

    assert body["Custom"]["collaborator_vs_contributor"]


def test_custom_with_country_and_type_filters(mock_data_dir):
    response = analytics.lambda_handler(
        {
            "body": {
                "country": "US",
                "organization_type": "non_profit",
                "size_start_date": "2026-01-01",
                "size_end_date": "2026-06-30"
            }
        },
        None
    )

    assert response["statusCode"] == 200

    body = get_body(response)

    assert list(body.keys()) == ["Custom"]

    sizes = body["Custom"]["organizations_by_size"]

    counts = {
        item["size"]: item["count"]
        for item in sizes
    }

    assert counts == {
        "small": 1,
        "medium": 1
    }


@pytest.mark.parametrize(
    "event",
    [
        {
            "body": {
                "size_start_date": "2026-01-01"
            }
        },
        {
            "body": {
                "size_end_date": "2026-06-30"
            }
        },
        {
            "body": {
                "size_start_date": "01-01-2026",
                "size_end_date": "2026-06-30"
            }
        },
        {
            "body": {
                "size_start_date": "2026-07-01",
                "size_end_date": "2026-06-30"
            }
        },
        {
            "body": {
                "contribution_start_date": "2025-01-01"
            }
        },
        {
            "body": {
                "contribution_end_date": "2025-12-31"
            }
        },
        {
            "body": {
                "contribution_start_date": "2026-01-01",
                "contribution_end_date": "2025-12-31"
            }
        }
    ]
)
def test_invalid_date_ranges(mock_data_dir, event):
    response = analytics.lambda_handler(
        event,
        None
    )

    assert response["statusCode"] == 400

    body = get_body(response)

    assert "error" in body


def test_collaborator_and_contributor_are_independent(mock_data_dir):
    response = analytics.lambda_handler(
        {
            "body": {
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2025-12-31"
            }
        },
        None
    )

    body = get_body(response)
    rows = body["Custom"]["collaborator_vs_contributor"]

    collaborator = rows[0]
    contributor = rows[1]

    collaborator = rows[0]
    contributor = rows[1]

    assert collaborator["count"] == 1
    assert contributor["count"] == 2

    assert collaborator["percentage"] == 50.0
    assert contributor["percentage"] == 100.0


def test_missing_is_contributor_column(mock_data_dir):
    organizations_path = mock_data_dir / "organizations.csv"

    organizations = pd.read_csv(organizations_path)

    organizations = organizations.drop(
        columns=["is_contributor"]
    )

    organizations.to_csv(
        organizations_path,
        index=False
    )

    response = analytics.lambda_handler(
        {
            "body": {
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2025-12-31"
            }
        },
        None
    )

    assert response["statusCode"] == 200

    body = get_body(response)

    contributor = (
        body["Custom"]["collaborator_vs_contributor"][1]
    )

    assert contributor["count"] == 0
    assert contributor["percentage"] == 0.0


def test_empty_organizations_file(mock_data_dir):
    organizations_path = mock_data_dir / "organizations.csv"

    empty_organizations = pd.DataFrame(
        columns=[
            "org_id",
            "org_size",
            "is_collaborator",
            "is_contributor",
            "org_type",
            "state_id",
            "created_at"
        ]
    )

    empty_organizations.to_csv(
        organizations_path,
        index=False
    )

    response = analytics.lambda_handler(
        {
            "body": {}
        },
        None
    )

    assert response["statusCode"] == 200

    body = get_body(response)

    for bucket in ["7D", "30D", "1Y", "All"]:
        assert body[bucket]["organizations_by_size"] == []

        contribution = (
            body[bucket]["collaborator_vs_contributor"]
        )

        assert contribution[0]["count"] == 0
        assert contribution[1]["count"] == 0


def test_one_row_organizations_file(mock_data_dir):
    organizations_path = mock_data_dir / "organizations.csv"

    organizations = pd.DataFrame([
        {
            "org_id": 1,
            "org_size": "small",
            "is_collaborator": True,
            "is_contributor": True,
            "org_type": "non_profit",
            "state_id": 101,
            "created_at": "2026-01-10"
        }
    ])

    organizations.to_csv(
        organizations_path,
        index=False
    )

    response = analytics.lambda_handler(
        {
            "body": {}
        },
        None
    )

    assert response["statusCode"] == 200

    body = get_body(response)

    all_bucket = body["All"]

    assert all_bucket["organizations_by_size"] == [
        {
            "size": "small",
            "count": 1
        }
    ]

    assert all_bucket["collaborator_vs_contributor"] == [
        {
            "type": "Collaborator",
            "count": 1,
            "percentage": 100.0
        },
        {
            "type": "Contributor",
            "count": 1,
            "percentage": 100.0
        }
    ]