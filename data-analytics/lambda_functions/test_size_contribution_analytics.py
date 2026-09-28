import json
from pathlib import Path

import pandas as pd
import pytest

import size_contribution_analytics as api


def write_fixture(root: Path, include_contributor=True):
    organizations = [
        {
            "org_id": "O1",
            "org_size": "small",
            "is_collaborator": "TRUE",
            "is_contributor": "TRUE",
            "org_type": "non_profit",
            "state_id": "TX",
            "created_at": "2026-09-24",
        },
        {
            "org_id": "O2",
            "org_size": "medium",
            "is_collaborator": "FALSE",
            "is_contributor": "TRUE",
            "org_type": "non_profit",
            "state_id": "TX",
            "created_at": "2026-09-20",
        },
        {
            "org_id": "O3",
            "org_size": "large",
            "is_collaborator": "TRUE",
            "is_contributor": "FALSE",
            "org_type": "for_profit",
            "state_id": "CA",
            "created_at": "2026-05-10",
        },
        {
            "org_id": "O4",
            "org_size": "small",
            "is_collaborator": "FALSE",
            "is_contributor": "FALSE",
            "org_type": "for_profit",
            "state_id": "CA",
            "created_at": "2025-02-01",
        },
        {
            "org_id": "O5",
            "org_size": "medium",
            "is_collaborator": "TRUE",
            "is_contributor": "TRUE",
            "org_type": "non_profit",
            "state_id": "NY",
            "created_at": "2025-01-15",
        },
    ]

    if not include_contributor:
        for row in organizations:
            del row["is_contributor"]

    pd.DataFrame(organizations).to_csv(
        root / "organizations.csv",
        index=False,
    )

    pd.DataFrame(
        [
            {"state_id": "TX", "country_id": "1"},
            {"state_id": "CA", "country_id": "1"},
            {"state_id": "NY", "country_id": "2"},
        ]
    ).to_csv(root / "states.csv", index=False)

    pd.DataFrame(
        [
            {"country_id": "1", "country_code": "USA"},
            {"country_id": "2", "country_code": "CAN"},
        ]
    ).to_csv(root / "countries.csv", index=False)


@pytest.fixture
def data_dir(tmp_path):
    write_fixture(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def mock_env(monkeypatch, data_dir):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        api,
        "get_today",
        lambda: pd.Timestamp("2026-09-24"),
    )


def body(response):
    return json.loads(response["body"])


def test_no_custom_exact_shape():
    result = body(api.lambda_handler({}))

    assert list(result) == [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]

    for key in result:
        assert set(result[key]) == {
            "organizations_by_size",
            "collaborator_vs_contributor",
        }

    assert result["Custom"] == {
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
    }


def test_country_filter():
    result = body(api.lambda_handler({"country": "USA"}))

    assert (
        sum(
            item["count"]
            for item in result["All"]["organizations_by_size"]
        )
        == 4
    )


def test_country_all_is_default():
    result = body(api.lambda_handler({"country": "ALL"}))

    assert (
        sum(
            item["count"]
            for item in result["All"]["organizations_by_size"]
        )
        == 5
    )


def test_organization_type_filter():
    result = body(
        api.lambda_handler(
            {"organization_type": "non_profit"}
        )
    )

    assert (
        sum(
            item["count"]
            for item in result["All"]["organizations_by_size"]
        )
        == 3
    )


def test_invalid_organization_type():
    result = api.lambda_handler(
        {"organization_type": "invalid"}
    )

    assert result["statusCode"] == 400


def test_size_custom_only():
    result = body(
        api.lambda_handler(
            {
                "size_start_date": "2025-01-01",
                "size_end_date": "2025-12-31",
            }
        )
    )

    assert list(result) == ["Custom"]
    assert result["Custom"]["organizations_by_size"]
    assert result["Custom"][
        "collaborator_vs_contributor"
    ] == []


def test_contribution_custom_only():
    result = body(
        api.lambda_handler(
            {
                "contribution_start_date": "2026-01-01",
                "contribution_end_date": "2026-12-31",
            }
        )
    )

    assert list(result) == ["Custom"]
    assert result["Custom"]["organizations_by_size"] == []

    assert result["Custom"][
        "collaborator_vs_contributor"
    ] == [
        {
            "type": "Collaborator",
            "count": 2,
            "percentage": 66.7,
        },
        {
            "type": "Contributor",
            "count": 2,
            "percentage": 66.7,
        },
    ]


def test_both_custom_pairs_are_independent():
    result = body(
        api.lambda_handler(
            {
                "size_start_date": "2025-01-01",
                "size_end_date": "2025-02-28",
                "contribution_start_date": "2026-01-01",
                "contribution_end_date": "2026-12-31",
            }
        )
    )

    assert list(result) == ["Custom"]

    assert result["Custom"]["organizations_by_size"] == [
        {"size": "small", "count": 1},
        {"size": "medium", "count": 1},
    ]

    assert result["Custom"][
        "collaborator_vs_contributor"
    ][0]["count"] == 2


def test_malformed_size_date():
    result = api.lambda_handler(
        {
            "size_start_date": "2026/01/01",
            "size_end_date": "2026-01-02",
        }
    )

    assert result["statusCode"] == 400


def test_incomplete_contribution_date():
    result = api.lambda_handler(
        {"contribution_start_date": "2026-01-01"}
    )

    assert result["statusCode"] == 400


def test_size_start_after_end():
    result = api.lambda_handler(
        {
            "size_start_date": "2026-02-01",
            "size_end_date": "2026-01-01",
        }
    )

    assert result["statusCode"] == 400


def test_contribution_start_after_end():
    result = api.lambda_handler(
        {
            "contribution_start_date": "2026-02-01",
            "contribution_end_date": "2026-01-01",
        }
    )

    assert result["statusCode"] == 400


def test_collaborator_and_contributor_are_independent():
    result = body(
        api.lambda_handler(
            {
                "contribution_start_date": "2026-01-01",
                "contribution_end_date": "2026-12-31",
            }
        )
    )

    rows = {
        item["type"]: item
        for item in result["Custom"][
            "collaborator_vs_contributor"
        ]
    }

    assert rows["Collaborator"]["count"] == 2
    assert rows["Contributor"]["count"] == 2


def test_percentage_uses_half_up_rounding():
    assert api.percentage(133, 400) == 33.3


def test_missing_contributor_gracefully_defaults_to_zero(
    tmp_path,
    monkeypatch,
):
    write_fixture(
        tmp_path,
        include_contributor=False,
    )

    monkeypatch.setenv(
        "USE_MOCK_DATA",
        "true",
    )
    monkeypatch.setenv(
        "MOCK_DATA_DIR",
        str(tmp_path),
    )

    result = body(
        api.lambda_handler(
            {
                "contribution_start_date": "2026-01-01",
                "contribution_end_date": "2026-12-31",
            }
        )
    )

    contributor = next(
        item
        for item in result["Custom"][
            "collaborator_vs_contributor"
        ]
        if item["type"] == "Contributor"
    )

    assert contributor == {
        "type": "Contributor",
        "count": 0,
        "percentage": 0.0,
    }


def test_missing_country_mapping_falls_back_to_unknown(
    data_dir,
    monkeypatch,
):
    states = pd.read_csv(data_dir / "states.csv", dtype=str)
    states.loc[states["state_id"] == "TX", "country_id"] = "999"
    states.to_csv(data_dir / "states.csv", index=False)

    monkeypatch.setenv("MOCK_DATA_DIR", str(data_dir))

    result = body(
        api.lambda_handler({"country": "Unknown"})
    )

    assert (
        sum(
            item["count"]
            for item in result["All"]["organizations_by_size"]
        )
        == 2
    )

def test_missing_required_mock_file_returns_500(
    data_dir,
    monkeypatch,
):
    (data_dir / "countries.csv").unlink()
    monkeypatch.setenv("MOCK_DATA_DIR", str(data_dir))

    result = api.lambda_handler({})

    assert result["statusCode"] == 500


def test_missing_required_mock_column_returns_500(
    data_dir,
    monkeypatch,
):
    states = pd.read_csv(data_dir / "states.csv", dtype=str)
    states[["state_id"]].to_csv(
        data_dir / "states.csv",
        index=False,
    )
    monkeypatch.setenv("MOCK_DATA_DIR", str(data_dir))

    result = api.lambda_handler({})

    assert result["statusCode"] == 500


def test_invalid_server_boolean_returns_500(
    data_dir,
    monkeypatch,
):
    organizations = pd.read_csv(
        data_dir / "organizations.csv",
        dtype=str,
    )
    organizations.loc[0, "is_collaborator"] = "MAYBE"
    organizations.to_csv(
        data_dir / "organizations.csv",
        index=False,
    )
    monkeypatch.setenv("MOCK_DATA_DIR", str(data_dir))

    result = api.lambda_handler({})

    assert result["statusCode"] == 500


def test_empty_window_returns_empty_arrays():
    result = body(
        api.lambda_handler(
            {
                "size_start_date": "2027-01-01",
                "size_end_date": "2027-01-31",
            }
        )
    )

    assert result == {
        "Custom": {
            "organizations_by_size": [],
            "collaborator_vs_contributor": [],
        }
    }


def test_one_row_does_not_crash(
    tmp_path,
    monkeypatch,
):
    pd.DataFrame(
        [
            {
                "org_id": "O1",
                "org_size": "small",
                "is_collaborator": "TRUE",
                "is_contributor": "TRUE",
                "org_type": "non_profit",
                "state_id": "TX",
                "created_at": "2026-01-01",
            }
        ]
    ).to_csv(
        tmp_path / "organizations.csv",
        index=False,
    )

    pd.DataFrame(
        [{"state_id": "TX", "country_id": "1"}]
    ).to_csv(
        tmp_path / "states.csv",
        index=False,
    )

    pd.DataFrame(
        [{"country_id": "1", "country_code": "USA"}]
    ).to_csv(
        tmp_path / "countries.csv",
        index=False,
    )

    monkeypatch.setenv(
        "USE_MOCK_DATA",
        "true",
    )
    monkeypatch.setenv(
        "MOCK_DATA_DIR",
        str(tmp_path),
    )

    assert api.lambda_handler({})["statusCode"] == 200


def test_empty_data_does_not_crash(
    tmp_path,
    monkeypatch,
):
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
    ).to_csv(
        tmp_path / "organizations.csv",
        index=False,
    )

    pd.DataFrame(
        [{"state_id": "TX", "country_id": "1"}]
    ).to_csv(
        tmp_path / "states.csv",
        index=False,
    )

    pd.DataFrame(
        [{"country_id": "1", "country_code": "USA"}]
    ).to_csv(
        tmp_path / "countries.csv",
        index=False,
    )

    monkeypatch.setenv(
        "USE_MOCK_DATA",
        "true",
    )
    monkeypatch.setenv(
        "MOCK_DATA_DIR",
        str(tmp_path),
    )

    assert api.lambda_handler({})["statusCode"] == 200
