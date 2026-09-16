"""Focused tests for the Growth & Location Analytics local CSV loader."""

from pathlib import Path

import pandas as pd
import pytest

from src.growth_location_analytics.loader import LocalDataError, load_local_data


ORGANIZATION_COLUMNS = [
    "org_id",
    "state_id",
    "city_name",
    "is_collaborator",
    "created_at",
]


def _write_valid_csvs(directory: Path) -> None:
    pd.DataFrame(
        [
            {
                "org_id": "org-1",
                "state_id": "ST-1",
                "city_name": "Example City",
                "is_collaborator": "false",
                "created_at": "2025-01-02 03:04:05",
            }
        ]
    ).to_csv(directory / "organizations.csv", index=False)
    pd.DataFrame(
        [{"state_id": "ST-1", "state_name": "Example State", "country_id": "001"}]
    ).to_csv(directory / "states.csv", index=False)
    pd.DataFrame([{"country_id": "001", "country_code": "TST"}]).to_csv(
        directory / "countries.csv", index=False
    )


def test_loads_all_three_tables_from_explicit_directory(tmp_path):
    _write_valid_csvs(tmp_path)

    tables = load_local_data(tmp_path)

    assert len(tables.organizations) == 1
    assert len(tables.states) == 1
    assert len(tables.countries) == 1


def test_loads_from_mock_data_dir(tmp_path, monkeypatch):
    _write_valid_csvs(tmp_path)
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))

    tables = load_local_data()

    assert tables.organizations.loc[0, "org_id"] == "org-1"


def test_missing_directory_has_clear_error(tmp_path):
    missing_directory = tmp_path / "not-present"

    with pytest.raises(LocalDataError, match="directory does not exist"):
        load_local_data(missing_directory)


def test_missing_file_identifies_table_and_expected_names(tmp_path):
    _write_valid_csvs(tmp_path)
    (tmp_path / "states.csv").unlink()

    with pytest.raises(LocalDataError, match=r"states CSV.*states\.csv, state\.csv"):
        load_local_data(tmp_path)


def test_missing_required_columns_identifies_file_and_columns(tmp_path):
    _write_valid_csvs(tmp_path)
    pd.DataFrame([{"org_id": "org-1"}]).to_csv(
        tmp_path / "organizations.csv", index=False
    )

    with pytest.raises(LocalDataError) as error:
        load_local_data(tmp_path)

    message = str(error.value)
    assert "organizations.csv" in message
    assert "missing required columns" in message
    assert "created_at" in message
    assert "is_collaborator" in message


def test_extra_columns_are_preserved(tmp_path):
    _write_valid_csvs(tmp_path)
    organizations = pd.read_csv(tmp_path / "organizations.csv", dtype="string")
    organizations["display_name"] = "Synthetic Organization"
    organizations.to_csv(tmp_path / "organizations.csv", index=False)

    tables = load_local_data(tmp_path)

    assert "display_name" in tables.organizations.columns
    assert tables.organizations.loc[0, "display_name"] == "Synthetic Organization"


def test_literal_na_identifier_is_preserved(tmp_path):
    _write_valid_csvs(tmp_path)
    organizations = pd.read_csv(
        tmp_path / "organizations.csv", dtype="string", keep_default_na=False
    )
    organizations.loc[0, "org_id"] = "NA"
    organizations.to_csv(tmp_path / "organizations.csv", index=False)

    tables = load_local_data(tmp_path)

    assert tables.organizations.loc[0, "org_id"] == "NA"


def test_blank_csv_record_is_rejected(tmp_path):
    _write_valid_csvs(tmp_path)
    (tmp_path / "organizations.csv").write_text(
        "org_id,state_id,city_name,is_collaborator,created_at\n"
        "org-1,ST-1,City,false,2025-01-01 00:00:00\n"
        "\n"
        "org-2,ST-1,City,true,2025-01-02 00:00:00\n",
        encoding="utf-8",
    )

    with pytest.raises(LocalDataError, match="blank CSV record"):
        load_local_data(tmp_path)


def test_inconsistent_csv_field_count_is_rejected(tmp_path):
    _write_valid_csvs(tmp_path)
    (tmp_path / "organizations.csv").write_text(
        "org_id,state_id,city_name,is_collaborator,created_at\n"
        "unexpected,org-1,ST-1,City,false,2025-01-01 00:00:00\n",
        encoding="utf-8",
    )

    with pytest.raises(LocalDataError, match="inconsistent field count"):
        load_local_data(tmp_path)


def test_normalizes_ids_timestamps_and_booleans(tmp_path):
    _write_valid_csvs(tmp_path)
    pd.DataFrame(
        [
            {
                "org_id": " 0007 ",
                "state_id": " ST-01 ",
                "city_name": " Test City ",
                "is_collaborator": " FALSE ",
                "created_at": "2025-04-05T03:02:01-05:00",
            },
            {
                "org_id": "0008",
                "state_id": "ST-01",
                "city_name": "Test City",
                "is_collaborator": "true",
                "created_at": "2025-04-05 08:02:01",
            },
        ]
    ).to_csv(tmp_path / "organizations.csv", index=False)
    pd.DataFrame(
        [{"state_id": " ST-01 ", "state_name": " Test State ", "country_id": " 001 "}]
    ).to_csv(tmp_path / "states.csv", index=False)
    pd.DataFrame([{"country_id": " 001 ", "country_code": " TST "}]).to_csv(
        tmp_path / "countries.csv", index=False
    )

    tables = load_local_data(tmp_path)

    assert tables.organizations["org_id"].tolist() == ["0007", "0008"]
    assert tables.organizations["state_id"].tolist() == ["ST-01", "ST-01"]
    assert tables.states.loc[0, "state_id"] == "ST-01"
    assert tables.states.loc[0, "country_id"] == "001"
    assert tables.countries.loc[0, "country_id"] == "001"
    assert tables.organizations["is_collaborator"].tolist() == [False, True]
    assert str(tables.organizations["is_collaborator"].dtype) == "boolean"
    assert str(tables.organizations["created_at"].dtype) == "datetime64[ns, UTC]"
    assert tables.organizations.loc[0, "created_at"] == pd.Timestamp(
        "2025-04-05T08:02:01Z"
    )
    assert tables.organizations.loc[1, "created_at"] == pd.Timestamp(
        "2025-04-05T08:02:01Z"
    )


@pytest.mark.parametrize(
    ("column", "invalid_value", "message"),
    [
        ("org_id", "", "required column 'org_id' contains missing or blank values"),
        ("is_collaborator", "not-sure", "must contain only true or false"),
        ("created_at", "04/05/2025", "invalid ISO 8601 timestamps"),
    ],
)
def test_invalid_required_organization_values_have_clear_errors(
    tmp_path, column, invalid_value, message
):
    _write_valid_csvs(tmp_path)
    organizations = pd.read_csv(tmp_path / "organizations.csv", dtype="string")
    organizations.loc[0, column] = invalid_value
    organizations.to_csv(tmp_path / "organizations.csv", index=False)

    with pytest.raises(LocalDataError, match=message):
        load_local_data(tmp_path)


def test_header_only_organizations_data_is_supported(tmp_path):
    _write_valid_csvs(tmp_path)
    pd.DataFrame(columns=ORGANIZATION_COLUMNS).to_csv(
        tmp_path / "organizations.csv", index=False
    )

    tables = load_local_data(tmp_path)

    assert tables.organizations.empty
    assert list(tables.organizations.columns) == ORGANIZATION_COLUMNS
    assert str(tables.organizations["is_collaborator"].dtype) == "boolean"
    assert str(tables.organizations["created_at"].dtype) == "datetime64[ns, UTC]"


def test_completely_blank_file_reports_missing_header(tmp_path):
    _write_valid_csvs(tmp_path)
    (tmp_path / "organizations.csv").write_text("", encoding="utf-8")

    with pytest.raises(LocalDataError, match=r"organizations\.csv: missing CSV header"):
        load_local_data(tmp_path)


def test_single_organization_row_is_supported(tmp_path):
    _write_valid_csvs(tmp_path)

    tables = load_local_data(tmp_path)

    assert tables.organizations.shape[0] == 1
    assert not bool(tables.organizations.loc[0, "is_collaborator"])


def test_tracked_singular_lookup_filenames_are_supported(tmp_path):
    _write_valid_csvs(tmp_path)
    (tmp_path / "states.csv").rename(tmp_path / "state.csv")
    (tmp_path / "countries.csv").rename(tmp_path / "country.csv")

    tables = load_local_data(tmp_path)

    assert len(tables.states) == 1
    assert len(tables.countries) == 1
