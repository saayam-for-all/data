"""Task 4 component/consumer contracts, not live integration or React UI verification."""

import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

AGGREGATOR = Path(__file__).resolve().parents[1] / "src/saayam-org-aggregator"


def load(name):
    """Load loose Lambda modules without loading live clients."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, AGGREGATOR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


for name in (
    "beneficiary_location",
    "address_geocoding",
    "local_location_records",
    "local_geocoding",
    "organization_addresses",
    "organization_distance",
    "offline_aggregator",
    "lambda_function",
):
    load(name)
runner = load("local_aggregator_runner")
distance = load("organization_distance")
geo = load("address_geocoding")

HOME = "Home, Unit 2, Building 3, City, State, 00123, Country"
OFFICE = "Office, City, State, 00456, Country"
EVENT = {"request_id": "r", "beneficiary_id": "b"}


@pytest.fixture
def mock_files(tmp_path):
    """Write invented generator-shaped CSVs only in pytest's temporary directory."""
    tables = {
        "users": [
            {
                "user_id": "b",
                "addr_ln1": "Home",
                "addr_ln2": "Unit 2",
                "addr_ln3": "Building 3",
                "city_name": "City",
                "state_id": "s",
                "country_id": "c",
                "zip_code": "00123",
            }
        ],
        "user_locations": [
            {
                "user_id": "b",
                "curr_loc": "SRID=4326;POINT(2 0)",
                "prev_loc": "SRID=4326;POINT(100 50)",
            }
        ],
        "states": [{"state_id": "s", "country_id": "c", "state_name": "State"}],
        "countries": [{"country_id": "c", "country_name": "Country"}],
        "organizations": [
            {
                "org_id": "o",
                "org_name": "DB",
                "street": "Office",
                "city_name": "City",
                "state_id": "s",
                "zip_code": "00456",
                "latitude": 50,
                "longitude": 100,
                "email": "db@example.org",
            }
        ],
    }
    for name, rows in tables.items():
        with (tmp_path / f"{name}.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    return tmp_path


def build(directory, *, point="SRID=4326;POINT(1 0)", ai=None):
    """Build a synthetic request with authoritative search details and both sources."""
    return runner.build_local_dependencies(
        directory,
        synthetic_requests=[
            {
                **EVENT,
                "req_loc": point,
                "category": "Food",
                "subject": "Help",
                "description": "Synthetic request",
            }
        ],
        ai_organizations=(
            ai
            if ai is not None
            else {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "organizations": [
                            {
                                "organization_name": "AI",
                                "location": "AI Address",
                                "rating": 0,
                                "Representatives": [{"PersonName": "Synthetic"}],
                            },
                        ]
                    }
                ),
            }
        ),
        geocoding_responses={
            HOME: {"latitude": 0, "longitude": 3},
            OFFICE: {"latitude": 0, "longitude": 0},
            "AI Address": {"latitude": 0, "longitude": 0},
        },
    )


@pytest.mark.parametrize("gateway", [False, True])
def test_ids_only_request_details_envelope_and_sources(mock_files, gateway):
    deps = build(mock_files)
    seen = []
    original = deps.db_source
    deps.db_source = lambda body: seen.append(body) or original(body)
    event = {**EVENT, "category": "Caller override", "subject": "Override"}
    response = runner.run_local({"body": json.dumps(event)} if gateway else event, deps)
    assert response["statusCode"] == 200
    assert response["headers"] == {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
    }
    rows = json.loads(response["body"])
    assert [r["name"] for r in rows] == ["DB", "AI"]
    assert [r["source"] for r in rows] == ["db", "ai"]
    assert rows[0]["email"] == "db@example.org"
    assert rows[1]["rating"] == 0
    assert rows[1]["Representatives"] == [{"PersonName": "Synthetic"}]
    assert all(r["distance"] == pytest.approx(69.0934195756) for r in rows)
    assert seen[0]["category"] == "Food" and seen[0]["subject"] == "Help"
    assert event["category"] == "Caller override"


@pytest.mark.parametrize("gateway", [False, True])
@pytest.mark.parametrize(
    "rating,collaborator,expected_rating,expected_collaborator",
    [
        ("0", "False", 0, False),
        ("4.5", "True", 4.5, True),
        ("", "", None, None),
        ("NaN", "invalid", None, None),
        ("Infinity", "false", None, False),
    ],
)
def test_csv_consumer_types_and_text_fields(
    mock_files, gateway, rating, collaborator, expected_rating, expected_collaborator
):
    path = mock_files / "organizations.csv"
    with path.open(newline="") as stream:
        row = next(csv.DictReader(stream))
    row.update(org_rating=rating, is_collaborator=collaborator, org_size="small", org_id="001")
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)
    before = path.read_bytes()
    response = runner.run_local(
        {"body": json.dumps(EVENT)} if gateway else EVENT, build(mock_files)
    )
    result = json.loads(response["body"])[0]
    assert result["collaborator"] is expected_collaborator
    assert result["rating"] == expected_rating
    assert result["rating"] is None or type(result["rating"]) in (int, float)
    assert result["org_id"] == "001" and result["zip_code"] == "00456"
    assert result["size"] == "small"
    assert result["distance_status"] == "ok"
    assert path.read_bytes() == before


@pytest.mark.parametrize("gateway", [False, True])
@pytest.mark.parametrize("request_id,beneficiary_id", [(1, 2), ("1", "2"), (" 1 ", " 2 ")])
@pytest.mark.parametrize("origin", ["request", "current", "profile"])
def test_identity_normalization_across_location_fallbacks(
    mock_files, gateway, request_id, beneficiary_id, origin
):
    for name in ("users", "user_locations"):
        path = mock_files / f"{name}.csv"
        with path.open(newline="") as stream:
            row = next(csv.DictReader(stream))
        row["user_id"] = "2"
        if name == "user_locations":
            row["curr_loc"] = "invalid" if origin == "profile" else "SRID=4326;POINT(0 0)"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=row.keys())
            writer.writeheader()
            writer.writerow(row)
    deps = runner.build_local_dependencies(
        mock_files,
        synthetic_requests=[
            {
                "request_id": 1,
                "beneficiary_id": 2,
                "category": "Food",
                "req_loc": "SRID=4326;POINT(0 0)" if origin == "request" else None,
            }
        ],
        ai_organizations=[],
        geocoding_responses={
            HOME: {"latitude": 0, "longitude": 0},
            OFFICE: {"latitude": 0, "longitude": 0},
        },
    )
    seen = []
    source = deps.db_source
    deps.db_source = lambda body: seen.append(body) or source(body)
    event = {"request_id": request_id, "beneficiary_id": beneficiary_id}
    response = runner.run_local({"body": json.dumps(event)} if gateway else event, deps)
    assert response["statusCode"] == 200
    result = json.loads(response["body"])[0]
    assert result["distance_status"] == "ok" and result["distance"] == 0
    assert seen[0]["request_id"] == "1" and seen[0]["beneficiary_id"] == "2"
    assert deps.provider.calls == ([HOME] if origin == "profile" else []) + [OFFICE]
    assert event == {"request_id": request_id, "beneficiary_id": beneficiary_id}


@pytest.mark.parametrize("invalid", [True, False, 1.5, [], {}, " ", None])
@pytest.mark.parametrize("field", ["request_id", "beneficiary_id"])
def test_invalid_id_types_fail_before_search(mock_files, invalid, field):
    deps = build(mock_files)
    deps.db_source = deps.ai_source = lambda body: pytest.fail("must not search")
    response = runner.run_local({**EVENT, field: invalid}, deps)
    assert response["statusCode"] == 400
    assert deps.provider.calls == []


@pytest.mark.parametrize(
    "request_point,current_point,expected,profile_lookup",
    [
        ("SRID=4326;POINT(1 0)", "SRID=4326;POINT(2 0)", 1, False),
        ("invalid", "SRID=4326;POINT(2 0)", 2, False),
        (None, "invalid", 3, True),
        ("SRID=4326;POINT(0 0)", "SRID=4326;POINT(2 0)", 0, False),
    ],
)
def test_precedence_full_addresses_and_cache(
    mock_files, request_point, current_point, expected, profile_lookup
):
    with (mock_files / "user_locations.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["user_id", "curr_loc"])
        writer.writeheader()
        writer.writerow({"user_id": "b", "curr_loc": current_point})
    deps = build(mock_files, point=request_point)
    rows = json.loads(runner.run_local(EVENT, deps)["body"])
    assert all(r["distance"] == pytest.approx(expected * 69.0934195756) for r in rows)
    assert deps.provider.calls == ([HOME] if profile_lookup else []) + [OFFICE, "AI Address"]
    calls = list(deps.provider.calls)
    assert runner.run_local(EVENT, deps)["statusCode"] == 200
    assert deps.provider.calls == calls


@pytest.mark.parametrize(
    "event",
    [
        {"request_id": "missing", "beneficiary_id": "b"},
        {"request_id": "r", "beneficiary_id": "other"},
    ],
)
def test_request_info_association_fails_before_search(mock_files, event):
    deps = build(mock_files)
    deps.db_source = deps.ai_source = lambda body: pytest.fail("must not search")
    assert runner.run_local(event, deps)["statusCode"] == 400
    assert deps.provider.calls == []


def test_unavailable_origin_retains_organizations(mock_files):
    deps = build(mock_files)
    # Optional legacy category path still checks association for distance resolution.
    deps.request_info_reader = None
    rows = json.loads(
        runner.run_local({**EVENT, "beneficiary_id": "other", "category": "Food"}, deps)["body"]
    )
    assert [r["name"] for r in rows] == ["DB", "AI"]
    assert all(r["distance"] is None and r["distance_status"] == "unknown_location" for r in rows)
    assert deps.provider.calls == []


def test_request_details_require_category_and_seeded_cache_skips_provider(mock_files):
    deps = build(mock_files)
    deps.request_info_reader = lambda *args: {"subject": "Synthetic"}
    assert runner.run_local(EVENT, deps)["statusCode"] == 400
    deps = build(mock_files)
    deps.cache.entries.update(
        {OFFICE: geo.CoordinateRecord(0, 0), "AI Address": geo.CoordinateRecord(0, 0)}
    )
    deps.provider.responses.clear()
    rows = json.loads(runner.run_local(EVENT, deps)["body"])
    assert all(row["distance_status"] == "ok" for row in rows)
    assert deps.provider.calls == []


def test_all_distance_outcomes_failure_isolation_and_local_sort(mock_files):
    ai = [
        {"organization_name": status, "location": location, "online_only": online}
        for status, location, online in [
            ("ok", "AI Address", False),
            ("online", "unused", True),
            ("unknown_location", None, False),
            ("not_found", "absent", False),
            ("deferred", "limited", False),
            ("error", "broken", False),
        ]
    ]
    deps = build(mock_files, point="SRID=4326;POINT(0 0)", ai=ai)
    deps.provider.responses.update(
        runner._geocoding_responses({"limited": "deferred", "broken": "timeout"})
    )
    rows = json.loads(runner.run_local(EVENT, deps)["body"])
    assert len(rows) == 7
    for row in rows[1:]:
        assert row["distance_status"] == row["name"]
        assert row["distance"] == (0 if row["name"] == "ok" else None)
        assert row["distance_unit"] == "miles" and row["distance_method"] == "straight_line"
    assert "unused" not in deps.provider.calls
    assert [
        r["name"] for r in json.loads(runner.run_local(EVENT, deps, sort_nearest=True)["body"])
    ] == [r["name"] for r in rows]
    for failing in ("db_source", "ai_source"):
        fresh = build(mock_files)
        setattr(fresh, failing, lambda body: (_ for _ in ()).throw(RuntimeError("private")))
        response = runner.run_local(EVENT, fresh)
        assert response["statusCode"] == 200
        assert len(json.loads(response["body"])) == 1
        assert "private" not in response["body"]


def test_nearest_first_zero_unavailable_and_stable_ties():
    values = [None, 5, 0, 2, 2, -1, float("nan"), float("inf"), True, "1", 0]
    rows = [{"id": i, "distance": value, "distance_status": "ok"} for i, value in enumerate(values)]
    rows[-1]["distance_status"] = "error"
    assert [r["id"] for r in distance.nearest_first(iter(rows))] == [
        2,
        3,
        4,
        1,
        0,
        5,
        6,
        7,
        8,
        9,
        10,
    ]
    assert [r["id"] for r in rows] == list(range(len(values)))
    assert distance.nearest_first([]) == []


@pytest.mark.parametrize("failure", ["deferred", "timeout", "error", None])
def test_profile_geocoding_failure_retains_both_sources(mock_files, failure):
    (mock_files / "user_locations.csv").write_text("user_id,curr_loc\nb,invalid\n")
    deps = build(mock_files, point=None)
    deps.provider.responses.update(runner._geocoding_responses({HOME: failure}))
    rows = json.loads(runner.run_local(EVENT, deps)["body"])
    expected = {"deferred": "deferred", "timeout": "error", "error": "error", None: "not_found"}[
        failure
    ]
    assert [r["name"] for r in rows] == ["DB", "AI"]
    assert all(r["distance_status"] == expected and r["distance"] is None for r in rows)
    assert deps.provider.calls == [HOME]


def test_record_and_cache_failures_preserve_available_organizations(mock_files):
    deps = build(mock_files)
    deps.records.get_request = lambda request_id: (_ for _ in ()).throw(RuntimeError("private"))
    rows = json.loads(runner.run_local(EVENT, deps)["body"])
    assert len(rows) == 2 and all(r["distance_status"] == "error" for r in rows)
    assert deps.provider.calls == []
    deps = build(mock_files)
    deps.cache.get = lambda address: (_ for _ in ()).throw(RuntimeError("private"))
    deps.cache.put = lambda *args: (_ for _ in ()).throw(RuntimeError("private"))
    response = runner.run_local(EVENT, deps)
    rows = json.loads(response["body"])
    assert len(rows) == 2 and all(r["distance_status"] == "ok" for r in rows)
    assert "private" not in response["body"]


@pytest.mark.parametrize(
    "failure,expected", [(ValueError("private"), 400), (RuntimeError("private"), 500)]
)
def test_request_detail_failures_keep_error_envelope(mock_files, failure, expected):
    deps = build(mock_files)
    deps.request_info_reader = lambda *args: (_ for _ in ()).throw(failure)
    response = runner.run_local(EVENT, deps)
    assert response["statusCode"] == expected
    assert set(json.loads(response["body"])) == {"error"}
    assert "private" not in response["body"]


def test_runner_cli_reads_only_explicit_inputs(mock_files):
    inputs = {
        "requests": {
            "requests": [{**EVENT, "category": "Food", "req_loc": "SRID=4326;POINT(0 0)"}]
        },
        "ai": [{"organization_name": "AI", "location": "same"}],
        "geocodes": {
            OFFICE: {"latitude": 0, "longitude": 1},
            "same": {"latitude": 0, "longitude": 0},
        },
        "event": {"body": json.dumps(EVENT)},
    }
    command = [
        sys.executable,
        str(AGGREGATOR / "local_aggregator_runner.py"),
        "--mock-directory",
        str(mock_files),
        "--nearest-first",
    ]
    for name, value in inputs.items():
        path = mock_files / f"{name}.json"
        path.write_text(json.dumps(value))
        command.extend([f"--{name}", str(path)])
    before = {p.name: p.read_bytes() for p in mock_files.iterdir()}
    result = subprocess.run(command, cwd=mock_files, check=True, capture_output=True, text=True)
    response = json.loads(result.stdout)
    assert response["statusCode"] == 200
    assert [r["name"] for r in json.loads(response["body"])] == ["AI", "DB"]
    assert {p.name: p.read_bytes() for p in mock_files.iterdir()} == before


def test_default_handler_does_not_select_mock_runner(monkeypatch):
    from types import SimpleNamespace

    calls = []
    fake = SimpleNamespace(
        get_orgs_from_db=lambda *args: calls.append(("db", args)) or [],
        get_ai_orgs=lambda *args: calls.append(("ai", args)) or [],
        merge_organizations=lambda *args: SimpleNamespace(
            to_dict=lambda **kwargs: [{"name": "Existing"}]
        ),
    )
    monkeypatch.setitem(sys.modules, "helpers", fake)
    response = load("lambda_function").lambda_handler(
        {"location": "City", "category": "Food"}, None
    )
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == [{"name": "Existing"}]
    assert {call[0] for call in calls} == {"db", "ai"}
