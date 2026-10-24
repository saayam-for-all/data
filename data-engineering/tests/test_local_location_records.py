"""Local-only synthetic tests of the mock generator adapter; never run the generator."""

import csv
import importlib.util
import json
from pathlib import Path
import sys

import pytest


AGGREGATOR = Path(__file__).resolve().parents[1] / "src/saayam-org-aggregator"


def load_module(name):
    """Load loose Lambda modules without importing live helpers or changing sys.path."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, AGGREGATOR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


location = load_module("beneficiary_location")
adapter = load_module("local_location_records")
BENEFICIARY = "synthetic-beneficiary"
FIXTURE_PATH = Path(__file__).parent / "fixtures/synthetic_requests.json"
REQUESTS = json.loads(FIXTURE_PATH.read_text())["requests"]


def synthetic_tables():
    """Supply generator-shaped synthetic rows, with mixed integer/CSV-string lookup IDs."""
    return {
        "synthetic_requests": REQUESTS,
        "users": [{
            "user_id": BENEFICIARY,
            "addr_ln1": "  10 Synthetic Lane  ",
            "addr_ln2": "",
            "addr_ln3": None,
            "city_name": "Synthetic City",
            "zip_code": "00123",
            "state_id": "7",
            "country_id": "8",
            "last_location": "SRID=4326;POINT(30 40)",
        }],
        "user_locations": [{
            "user_id": BENEFICIARY,
            "curr_loc": "SRID=4326;POINT(-100.75 22.5)",
            "prev_loc": "SRID=4326;POINT(30 40)",
        }],
        "states": [{"state_id": 7, "state_name": "Synthetic State", "country_id": 8}],
        "countries": [{"country_id": 8, "country_name": "Synthetic Country"}],
    }


def resolve(tables, request_id="synthetic-request-current", beneficiary_id=BENEFICIARY):
    """Run the existing resolver with the explicitly constructed local adapter."""
    source = adapter.LocalMockLocationRecordSource(**tables)
    return location.resolve_beneficiary_location(request_id, beneficiary_id, source)


@pytest.mark.parametrize(
    "point,expected",
    [
        ("SRID=4326;POINT(-120.5 35.25)", (35.25, -120.5)),
        ("SRID=4326;POINT(0 0)", (0, 0)),
        ("SRID=4326;POINT(180 90)", (90, 180)),
        ("SRID=4326;POINT(-180 -90)", (-90, -180)),
        ("SRID=4326;POINT(0 45)", (45, 0)),
        ("SRID=4326;POINT(45 0)", (0, 45)),
        (" srid=4326; point ( +1e2 -2.5e1 ) ", (-25, 100)),
    ],
)
def test_point_parsing_returns_latitude_then_longitude(point, expected):
    assert adapter.parse_mock_point(point) == expected


BAD_POINTS = [
    None, "", False, 0, [], {},
    "SRID=3857;POINT(10 20)",
    "POINT(10 20)",
    "SRID=4326;POINT(10,20)",
    "SRID=4326;POINT(10)",
    "SRID=4326;POINT(10 20 30)",
    "SRID=4326;POINT Z(10 20 30)",
    "SRID=4326;POINT(NaN 20)",
    "SRID=4326;POINT(10 inf)",
    "SRID=4326;POINT(1e999 20)",
    "SRID=4326;POINT(181 20)",
    "SRID=4326;POINT(-181 20)",
    "SRID=4326;POINT(10 91)",
    "SRID=4326;POINT(10 -91)",
    "SRID=4326;POINT(10 20) trailing",
]


@pytest.mark.parametrize("point", BAD_POINTS)
def test_malformed_points_fall_back_to_current(point):
    tables = synthetic_tables()
    tables["synthetic_requests"] = [{
        "request_id": "synthetic-request-current", "beneficiary_id": BENEFICIARY, "req_loc": point
    }]
    result = resolve(tables)
    assert result.status == "resolved"
    assert result.source == "beneficiary_current"
    assert result.coordinates == (22.5, -100.75)


def test_request_wins_over_current_and_address():
    result = resolve(synthetic_tables(), "synthetic-request-coordinate")
    assert result.source == "request"
    assert result.coordinates == (35.25, -120.5)


def test_request_zero_is_preserved():
    result = resolve(synthetic_tables(), "synthetic-request-zero")
    assert result.source == "request"
    assert result.coordinates == (0, 0)


def test_current_zero_is_preserved():
    tables = synthetic_tables()
    tables["user_locations"][0]["curr_loc"] = "SRID=4326;POINT(0 0)"
    result = resolve(tables)
    assert result.source == "beneficiary_current"
    assert result.coordinates == (0, 0)


@pytest.mark.parametrize("point", BAD_POINTS)
def test_bad_current_uses_profile_names_without_geocoding(point):
    tables = synthetic_tables()
    tables["user_locations"][0]["curr_loc"] = point
    result = resolve(tables, "synthetic-request-profile")
    assert result.status == "requires_geocoding"
    assert result.coordinates is None
    assert result.address == (
        "10 Synthetic Lane, Synthetic City, Synthetic State, 00123, Synthetic Country"
    )


def test_missing_current_uses_users_city_without_cities_table():
    tables = synthetic_tables()
    tables["user_locations"] = []
    assert resolve(tables).address.startswith("10 Synthetic Lane, Synthetic City,")


def test_lookup_misses_omit_ids_and_do_not_default_country():
    tables = synthetic_tables()
    tables["user_locations"] = tables["states"] = tables["countries"] = []
    assert resolve(tables).address == "10 Synthetic Lane, Synthetic City, 00123"


def test_country_lookup_can_follow_supplied_state_relationship():
    tables = synthetic_tables()
    tables["user_locations"] = []
    tables["users"][0]["country_id"] = None
    assert resolve(tables).address.endswith("Synthetic State, 00123, Synthetic Country")


def test_inconsistent_country_does_not_include_wrong_state():
    tables = synthetic_tables()
    tables["user_locations"] = []
    tables["users"][0]["country_id"] = 9
    tables["countries"].append({"country_id": 9, "country_name": "Other Synthetic Country"})
    assert resolve(tables).address == (
        "10 Synthetic Lane, Synthetic City, 00123, Other Synthetic Country"
    )


def test_missing_and_malformed_profile_components_leave_no_invented_address():
    tables = synthetic_tables()
    tables["user_locations"] = []
    tables["users"] = [{
        "user_id": BENEFICIARY, "addr_ln1": None, "addr_ln2": float("nan"),
        "addr_ln3": {}, "city_name": "  ", "zip_code": False,
        "state_id": "missing", "country_id": "missing",
    }]
    result = resolve(tables)
    assert result.status == "unresolved"
    assert result.address is result.coordinates is None


def test_viewer_previous_and_last_locations_are_excluded():
    tables = synthetic_tables()
    tables["users"] = []
    tables["user_locations"][0]["curr_loc"] = None
    tables["user_locations"][0]["viewer_location"] = "SRID=4326;POINT(45 60)"
    assert resolve(tables).status == "unresolved"


def test_missing_records():
    tables = synthetic_tables()
    tables["users"] = tables["user_locations"] = []
    assert resolve(tables).reason == "no_usable_beneficiary_location"
    assert resolve(tables, "synthetic-missing-request").reason == "missing_request"


def test_request_beneficiary_mismatch_blocks_even_valid_request():
    result = resolve(synthetic_tables(), "synthetic-request-coordinate", "synthetic-viewer")
    assert result.reason == "request_beneficiary_mismatch"
    assert result.coordinates is None


def test_other_user_location_is_not_selected():
    tables = synthetic_tables()
    tables["user_locations"][0]["user_id"] = "synthetic-viewer"
    assert resolve(tables).status == "requires_geocoding"


def test_missing_request_beneficiary_cannot_pass_identity_check():
    tables = synthetic_tables()
    tables["synthetic_requests"] = [{"request_id": "synthetic-request-current"}]
    assert resolve(tables).reason == "request_beneficiary_mismatch"


@pytest.mark.parametrize("table,key", [
    ("synthetic_requests", "request_id"), ("users", "user_id"),
    ("user_locations", "user_id"), ("states", "state_id"), ("countries", "country_id"),
])
def test_duplicate_identities_are_rejected(table, key):
    tables = synthetic_tables()
    tables[table] = [{key: "duplicate"}, {key: "duplicate"}]
    with pytest.raises(ValueError, match="Duplicate local mock record"):
        adapter.LocalMockLocationRecordSource(**tables)


def write_synthetic_csvs(directory, tables):
    """Write only pytest temporary synthetic files, never repository CSVs."""
    for name in ("users", "user_locations", "states", "countries"):
        with (directory / f"{name}.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(tables[name][0]))
            writer.writeheader()
            writer.writerows(tables[name])


def test_explicit_csv_loading_is_read_only_and_needs_no_cities_csv(tmp_path):
    write_synthetic_csvs(tmp_path, synthetic_tables())
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    source = adapter.LocalMockLocationRecordSource.from_csv_directory(
        tmp_path, synthetic_requests=REQUESTS
    )
    result = location.resolve_beneficiary_location("synthetic-request-current", BENEFICIARY, source)
    assert result.coordinates == (22.5, -100.75)
    address = source.get_profile_address(BENEFICIARY).address
    assert "Synthetic State" in address and address.endswith("Synthetic Country")
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir()}


def test_missing_csv_is_an_explicit_loading_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        adapter.LocalMockLocationRecordSource.from_csv_directory(
            tmp_path, synthetic_requests=REQUESTS
        )


def test_invalid_csv_header_is_an_explicit_loading_error(tmp_path):
    (tmp_path / "users.csv").write_text("unconfirmed_id\nsynthetic-user\n")
    with pytest.raises(ValueError, match="requires user_id header"):
        adapter.LocalMockLocationRecordSource.from_csv_directory(
            tmp_path, synthetic_requests=REQUESTS
        )
