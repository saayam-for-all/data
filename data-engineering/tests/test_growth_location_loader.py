"""Focused tests for the Growth & Location Analytics local CSV loader."""

import sys
from pathlib import Path

import pandas as pd
import pytest

LAMBDA_ROOT = Path(__file__).resolve().parents[2] / "data-analytics" / "lambda_functions"
sys.path.insert(0, str(LAMBDA_ROOT))

from growth_location_analytics.loader import LocalDataError, load_local_data
from tests.growth_location_helpers import ORGANIZATION_COLUMNS, write_csvs


def _write_valid_csvs(directory: Path) -> None:
    """Create one organization with matching lookups and a leading-zero country ID."""

    write_csvs(
        directory,
        [
            {
                "org_id": "org-1",
                "state_id": "ST-1",
                "city_name": "Example City",
                "is_collaborator": "false",
                "created_at": "2025-01-02 03:04:05",
            }
        ],
        states=[("ST-1", "Example State", "001")],
        countries=[("001", "TST")],
    )


@pytest.mark.parametrize("use_environment", [False, True], ids=["explicit", "environment"])
def test_loads_all_three_tables_and_single_row(tmp_path, monkeypatch, use_environment):
    """Both directory interfaces preserve the single row and its false collaborator flag."""

    _write_valid_csvs(tmp_path)
    if use_environment:
        monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    else:
        monkeypatch.delenv("MOCK_DATA_DIR", raising=False)

    tables = load_local_data() if use_environment else load_local_data(tmp_path)

    assert len(tables.organizations) == 1
    assert len(tables.states) == 1
    assert len(tables.countries) == 1
    assert tables.organizations.loc[0, "org_id"] == "org-1"
    assert not bool(tables.organizations.loc[0, "is_collaborator"])


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
    pd.DataFrame([{"org_id": "org-1"}]).to_csv(tmp_path / "organizations.csv", index=False)

    with pytest.raises(LocalDataError) as error:
        load_local_data(tmp_path)

    message = str(error.value)
    assert "organizations.csv" in message
    assert "missing required columns" in message
    assert "created_at" in message
    assert "is_collaborator" in message


def test_extra_columns_are_tolerated(tmp_path):
    _write_valid_csvs(tmp_path)
    organizations = pd.read_csv(tmp_path / "organizations.csv", dtype="string")
    organizations["display_name"] = "Synthetic Organization"
    organizations.to_csv(tmp_path / "organizations.csv", index=False)

    tables = load_local_data(tmp_path)

    assert len(tables.organizations) == 1
    assert tables.organizations.loc[0, "org_id"] == "org-1"


@pytest.mark.parametrize(
    "contents,valid",
    [
        (
            "org_id,state_id,city_name,is_collaborator,created_at\n"
            "org-1,ST-1,City,false,2025-01-01\n\n",
            True,
        ),
        (
            "org_id,state_id,is_collaborator,created_at,city_name\n"
            "org-1,ST-1,false,2025-01-01\n",
            True,
        ),
        ("org_id,state_id,city_name,is_collaborator,created_at\n" "org-1,ST-1,City,false\n", False),
        (
            "org_id,state_id,city_name,is_collaborator,created_at\n"
            "unexpected,org-1,ST-1,City,false,2025-01-01\n",
            False,
        ),
        (
            "org_id,state_id,city_name,is_collaborator,created_at\n"
            "org-1,ST-1,City,false,2025-01-01\n"
            "org-2,ST-1,City,true,2025-01-02,extra\n",
            False,
        ),
        (
            "org_id,state_id,city_name,is_collaborator,created_at\n"
            "org-1,ST-1,City,false,2025-01-01,\n",
            False,
        ),
        ('org_id,state_id,city_name,is_collaborator,created_at\n"unfinished', False),
        ("", False),
    ],
    ids=[
        "blank-line",
        "short-description",
        "short-required",
        "extra-first",
        "extra-later",
        "extra-empty",
        "unclosed-quote",
        "zero-byte",
    ],
)
def test_csv_parsing_policy(tmp_path, contents, valid):
    _write_valid_csvs(tmp_path)
    (tmp_path / "organizations.csv").write_text(contents, encoding="utf-8")

    if valid:
        tables = load_local_data(tmp_path)
        assert tables.organizations["org_id"].tolist() == ["org-1"]
        assert tables.organizations["created_at"].tolist() == [pd.Timestamp("2025-01-01T00:00:00Z")]
    else:
        with pytest.raises(LocalDataError) as error:
            load_local_data(tmp_path)
        assert "organizations.csv" in str(error.value)


def test_normalizes_ids_timestamps_and_booleans(tmp_path):
    timestamps = [
        (" 2025-04-05T03:02:01-05:00 ", "2025-04-05T08:02:01Z"),
        ("2025-04-05 08:02:01", "2025-04-05T08:02:01Z"),
        ("2025-04-05", "2025-04-05T00:00:00Z"),
        ("2025-04-05T08:02Z", "2025-04-05T08:02:00Z"),
        ("2025-04-05 08:02", "2025-04-05T08:02:00Z"),
        ("2025-04-05T08:02:01.123456789+0000", "2025-04-05T08:02:01.123456789Z"),
        ("2025-04-05T23:30:00-0500", "2025-04-06T04:30:00Z"),
    ]
    ids = [" 0007 ", "NA", "3", "4", "5", "6", "7"]
    write_csvs(
        tmp_path,
        [
            {
                "org_id": org_id,
                "state_id": " ST-01 ",
                "city_name": "",
                "is_collaborator": " FALSE " if index == 0 else "true",
                "created_at": timestamp,
            }
            for index, (org_id, (timestamp, _)) in enumerate(zip(ids, timestamps))
        ],
        states=[(" ST-01 ", "", " 001 ")],
        countries=[(" 001 ", " TST ")],
    )

    tables = load_local_data(tmp_path)

    assert tables.organizations["org_id"].tolist() == [value.strip() for value in ids]
    assert tables.organizations["state_id"].tolist() == ["ST-01"] * len(timestamps)
    assert tables.states.loc[0, "state_id"] == "ST-01"
    assert tables.states.loc[0, "country_id"] == "001"
    assert tables.countries.loc[0, "country_id"] == "001"
    assert tables.countries.loc[0, "country_code"] == "TST"
    assert tables.organizations["is_collaborator"].tolist() == [False] + [True] * (
        len(timestamps) - 1
    )
    assert str(tables.organizations["is_collaborator"].dtype) == "boolean"
    assert str(tables.organizations["created_at"].dtype) == "datetime64[ns, UTC]"
    assert tables.organizations["created_at"].tolist() == [
        pd.Timestamp(expected) for _, expected in timestamps
    ]


@pytest.mark.parametrize(
    "table,column,invalid_value",
    [
        ("organizations", "org_id", ""),
        ("organizations", "state_id", " "),
        ("organizations", "is_collaborator", "not-sure"),
        ("organizations", "is_collaborator", ""),
        ("organizations", "created_at", "04/05/2025"),
        ("organizations", "created_at", "2025-02-30"),
        ("organizations", "created_at", ""),
        ("organizations", "created_at", "NaT"),
        ("states", "state_id", ""),
        ("states", "country_id", ""),
        ("countries", "country_id", ""),
        ("countries", "country_code", ""),
    ],
)
def test_invalid_required_values_have_useful_errors(tmp_path, table, column, invalid_value):
    _write_valid_csvs(tmp_path)
    path = tmp_path / f"{table}.csv"
    frame = pd.read_csv(path, dtype="string", keep_default_na=False)
    frame.loc[0, column] = invalid_value
    frame.to_csv(path, index=False)

    with pytest.raises(LocalDataError) as error:
        load_local_data(tmp_path)

    assert path.name in str(error.value)
    assert column in str(error.value)


@pytest.mark.parametrize("empty_lookups", [False, True])
def test_header_only_organizations_data_is_supported(tmp_path, empty_lookups):
    _write_valid_csvs(tmp_path)
    pd.DataFrame(columns=ORGANIZATION_COLUMNS).to_csv(tmp_path / "organizations.csv", index=False)

    if empty_lookups:
        for table in ("states", "countries"):
            path = tmp_path / f"{table}.csv"
            pd.read_csv(path).iloc[:0].to_csv(path, index=False)
    tables = load_local_data(tmp_path)

    assert tables.organizations.empty
    assert list(tables.organizations.columns) == ORGANIZATION_COLUMNS
    assert str(tables.organizations["is_collaborator"].dtype) == "boolean"
    assert str(tables.organizations["created_at"].dtype) == "datetime64[ns, UTC]"


def test_tracked_singular_lookup_filenames_are_supported(tmp_path):
    _write_valid_csvs(tmp_path)
    (tmp_path / "states.csv").rename(tmp_path / "state.csv")
    (tmp_path / "countries.csv").rename(tmp_path / "country.csv")

    tables = load_local_data(tmp_path)

    assert len(tables.states) == 1
    assert len(tables.countries) == 1
