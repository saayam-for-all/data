"""Offline distance and consumer-contract checks; no live DB, AWS, or provider access."""

import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

AGGREGATOR = Path(__file__).resolve().parents[1] / "src/saayam-org-aggregator"


def load(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, AGGREGATOR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


beneficiary = load("beneficiary_location")
local = load("local_location_records")
geo = load("address_geocoding")
fakes = load("local_geocoding")
addresses = load("organization_addresses")
distance = load("organization_distance")
aggregator = load("offline_aggregator")
spec = importlib.util.spec_from_file_location("distance_lambda", AGGREGATOR / "lambda_function.py")
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)


@pytest.mark.parametrize("start,end,expected", [
    ((0, 0), (0, 0), 0),
    ((0, 0), (0, 1), 69.0934195756),
    ((40.7128, -74.0060), (51.5074, -0.1278), 3461.180348),
    ((0, 0), (0, 180), 12436.8155236),
    ((0, 179.5), (0, -179.5), 69.0934195756),
    ((90, 0), (-90, 0), 12436.8155236),
])
def test_known_spherical_benchmarks(start, end, expected):
    assert distance.straight_line_miles(start, end) == pytest.approx(expected, abs=0.001)
    assert distance.straight_line_miles(end, start) == pytest.approx(expected, abs=0.001)


@pytest.mark.parametrize("pair", [(91, 0), (0, 181), (float("nan"), 0), (0, float("inf")), (True, 0)])
def test_invalid_calculation_coordinates(pair):
    with pytest.raises(ValueError):
        distance.straight_line_miles((0, 0), pair)


def enrich(row, response=None, *, online=None, reader=None, origin=None):
    provider = fakes.FakeGeocodingProvider({"Address": response})
    record = addresses.from_genai(row, online_only=online)
    result = distance.enrich_organizations(
        [record], origin or geo.GeocodingResult("resolved", (0, 0)), provider,
        fakes.FakeCoordinateCache(), coordinate_reader=reader,
    )[0]
    return result, provider


@pytest.mark.parametrize("response,status", [
    (geo.CoordinateRecord(0, 1), "ok"), (None, "not_found"),
    (geo.GeocodingRateLimit(), "deferred"), (TimeoutError(), "error"),
    (RuntimeError(), "error"), (geo.CoordinateRecord(float("nan"), 0), "error"),
])
def test_provider_statuses_and_null_serialization(response, status):
    result, _ = enrich({"name": "Org", "location": "Address"}, response)
    assert result["distance_status"] == status
    assert result["distance_unit"] == "miles"
    assert result["distance_method"] == "straight_line"
    parsed = json.loads(json.dumps(result, allow_nan=False))
    assert (parsed["distance"] is None) == (status != "ok")


def test_online_and_unknown_do_not_geocode():
    for row, online, status in [
        ({"location": "Address"}, True, "online"), ({}, None, "unknown_location"),
        ({"location": "online"}, None, "not_found"),
    ]:
        result, provider = enrich(row, online=online)
        assert result["distance_status"] == status
        assert result["distance"] is None
        assert bool(provider.calls) == (status == "not_found")


def test_explicit_coordinates_zero_and_full_precision():
    result, provider = enrich({}, reader=lambda org: geo.CoordinateRecord(0, 0))
    assert result["distance"] == 0 and result["distance_status"] == "ok"
    assert provider.calls == []
    result, _ = enrich({}, reader=lambda org: geo.CoordinateRecord(0, 1))
    assert result["distance"] != round(result["distance"], 2)


def test_no_implicit_generator_centroid():
    result, provider = enrich({"latitude": 0, "longitude": 0, "location": "Address"})
    assert result["distance_status"] == "not_found"
    assert provider.calls == ["Address"]


def test_per_organization_reader_failure_isolated():
    def reader(org):
        if org.record["name"] == "Broken":
            raise RuntimeError("private diagnostic")
        return geo.CoordinateRecord(0, 0)

    rows = [addresses.from_genai({"name": name}) for name in ("Broken", "Valid")]
    results = distance.enrich_organizations(
        rows, geo.GeocodingResult("resolved", (0, 0)), fakes.FakeGeocodingProvider({}),
        fakes.FakeCoordinateCache(), coordinate_reader=reader,
    )
    assert [r["distance_status"] for r in results] == ["error", "ok"]
    assert results[1]["distance"] == 0
    assert "private diagnostic" not in json.dumps(results)


def dependencies(db=None, ai=None, provider=None):
    records = local.LocalMockLocationRecordSource(
        synthetic_requests=[{"request_id": "r", "beneficiary_id": "b", "req_loc": "SRID=4326;POINT(0 0)"}],
        users=[{"user_id": "b"}],
    )
    return aggregator.AggregatorDependencies(
        records=records, provider=provider or fakes.FakeGeocodingProvider({
            "City": geo.CoordinateRecord(0, 1), "Address": geo.CoordinateRecord(0, 0),
        }), cache=fakes.FakeCoordinateCache(), db_source=lambda body: db or [],
        ai_source=lambda body: ai or [],
    )


BODY = {"request_id": "r", "beneficiary_id": "b", "category": "Food"}
DB = {
    "org_name": "DB Org", "org_type": "NGO", "is_collaborator": False,
    "city_name": "City", "org_size": 0, "org_rating": 4.2, "phone": "555",
    "Representatives": [{"PersonName": "Person"}],
}
AI = {
    "organization_name": "AI Org", "organization_type": "Charity", "collaborator": True,
    "location": "Address", "size": 12, "rating": 0, "email": "example@example.org",
}


def test_both_sources_helper_fields_and_gateway_contract():
    deps = dependencies([DB], {"statusCode": 200, "body": json.dumps({"organizations": [AI]})})
    response = handler.lambda_handler({"body": json.dumps(BODY)}, None, dependencies=deps)
    assert response["statusCode"] == 200
    rows = json.loads(response["body"])
    assert len(rows) == 2
    for row, expected in zip(rows, [
        ["DB Org", "NGO", False, "City", 0, 4.2],
        ["AI Org", "Charity", True, "Address", 12, 0],
    ]):
        assert [row[key] for key in aggregator.ORG_COLUMNS[:6]] == expected
        assert set(aggregator.ORG_COLUMNS) <= row.keys()
        assert row["distance_status"] == "ok"
    assert rows[0]["Representatives"] == DB["Representatives"]
    assert rows[1]["distance"] == 0
    assert DB.get("distance") is None and "name" not in DB
    assert deps.provider.calls == ["City", "Address"]
    handler.lambda_handler(BODY, None, dependencies=deps)
    assert deps.provider.calls == ["City", "Address"]  # shared injected cache


@pytest.mark.parametrize("ai", [
    {"statusCode": 502, "body": {"code": "ORG_SEARCH_UNAVAILABLE"}},
    {"statusCode": 500, "body": "bad"}, {"statusCode": 200, "body": "bad json"},
    {"statusCode": 200, "body": {"organizations": []}}, [],
])
def test_ai_unavailability_retains_db(ai):
    result = aggregator.aggregate_organizations(BODY, dependencies([DB], ai))
    assert len(result) == 1 and result[0]["name"] == "DB Org"


def test_source_and_adapter_exceptions_isolated():
    deps = dependencies([DB], [AI])
    deps.ai_source = lambda body: (_ for _ in ()).throw(RuntimeError("unavailable"))
    assert len(aggregator.aggregate_organizations(BODY, deps)) == 1
    deps = dependencies([DB], [AI])
    deps.online_reader = lambda org: (_ for _ in ()).throw(RuntimeError()) if org.source == "db" else False
    results = aggregator.aggregate_organizations(BODY, deps)
    assert [row["distance_status"] for row in results] == ["error", "ok"]
    assert results[0]["name"] == "DB Org"


@pytest.mark.parametrize("status,expected", [
    ("missing_location", "unknown_location"), ("not_found", "not_found"),
    ("deferred", "deferred"), ("timeout", "error"), ("error", "error"),
])
def test_unavailable_beneficiary_status_propagates(status, expected):
    result, provider = enrich({"location": "Address"}, origin=geo.GeocodingResult(status))
    assert result["distance_status"] == expected and result["distance"] is None
    assert provider.calls == []


def test_resolver_injection_profile_geocoding_and_failure():
    deps = dependencies([DB])
    deps.resolver = lambda *args: beneficiary.LocationResolution(
        "requires_geocoding", "profile_address", address="Address"
    )
    assert aggregator.aggregate_organizations(BODY, deps)[0]["distance_status"] == "ok"
    assert deps.provider.calls == ["Address", "City"]
    deps.resolver = lambda *args: (_ for _ in ()).throw(RuntimeError())
    assert aggregator.aggregate_organizations(BODY, deps)[0]["distance_status"] == "error"
    deps.resolver = beneficiary.resolve_beneficiary_location
    assert aggregator.aggregate_organizations({**BODY, "beneficiary_id": "wrong"}, deps)[0]["distance_status"] == "unknown_location"


def test_nonfinite_values_serialize_null_and_zero_survives():
    row = {**AI, "rating": math.nan, "size": math.inf, "other": [-math.inf, 0]}
    response = handler.lambda_handler(BODY, None, dependencies=dependencies(ai=[row]))
    result = json.loads(response["body"])[0]
    assert result["rating"] is None and result["size"] is None
    assert result["other"] == [None, 0] and result["distance"] == 0
    assert "NaN" not in response["body"] and "Infinity" not in response["body"]


@pytest.mark.parametrize("event", [{"body": "{"}, {"body": "[]"}, {}, {"request_id": "r"}])
def test_invalid_request_contract(event):
    assert handler.lambda_handler(event, None, dependencies=dependencies())["statusCode"] == 400


def test_import_opens_no_live_clients():
    code = f'''
import sys
sys.path.insert(0, {str(AGGREGATOR)!r})
import lambda_function, offline_aggregator
assert "helpers" not in sys.modules
assert "boto3" not in sys.modules
assert "pg8000" not in sys.modules
'''
    subprocess.run([sys.executable, "-c", code], check=True)


def test_full_mock_address_relationships_and_profile_origin():
    deps = dependencies()
    states = [{"state_id": "s", "country_id": "c", "state_name": "State"}]
    countries = [{"country_id": "c", "country_name": "Country"}]
    deps.records = local.LocalMockLocationRecordSource(
        synthetic_requests=[{"request_id": "r", "beneficiary_id": "b"}],
        users=[{"user_id": "b", "addr_ln1": "Home", "city_name": "City",
                "state_id": "s", "country_id": "c", "zip_code": "00123"}],
        states=states, countries=countries,
    )
    deps.addresses = addresses.OrganizationAddressAssembler(states=states, countries=countries)
    deps.db_source = lambda body: [{**DB, "street": "Office", "state_id": "s", "zip_code": "00456",
                                   "latitude": 45, "longitude": 45}]
    deps.ai_source = lambda body: {"statusCode": 200, "body": {"organizations": [AI]}}
    deps.provider = fakes.FakeGeocodingProvider({
        "Home, City, State, 00123, Country": geo.CoordinateRecord(0, 0),
        "Office, City, State, 00456, Country": geo.CoordinateRecord(0, 1),
        "Address": geo.CoordinateRecord(0, 0),
    })
    response = handler.lambda_handler(BODY, None, dependencies=deps)
    rows = json.loads(response["body"])
    assert [row["distance_status"] for row in rows] == ["ok", "ok"]
    assert rows[0]["distance"] == pytest.approx(69.0934195756)
    assert rows[1]["distance"] == 0
    assert deps.provider.calls == [
        "Home, City, State, 00123, Country", "Office, City, State, 00456, Country", "Address",
    ]


def test_current_beneficiary_coordinates_and_explicit_org_coordinates():
    deps = dependencies([DB])
    deps.records = local.LocalMockLocationRecordSource(
        synthetic_requests=[{"request_id": "r", "beneficiary_id": "b"}],
        user_locations=[{"user_id": "b", "curr_loc": "SRID=4326;POINT(0 0)"}],
    )
    deps.coordinate_reader = lambda org: geo.CoordinateRecord(0, 0)
    result = aggregator.aggregate_organizations(BODY, deps)[0]
    assert result["distance"] == 0 and result["distance_status"] == "ok"
    assert deps.provider.calls == []


def test_consumer_contract_contains_all_six_statuses():
    rows = [
        {"name": "ok", "location": "same"}, {"name": "online"}, {"name": "unknown_location"},
        {"name": "not_found", "location": "absent"},
        {"name": "deferred", "location": "limited"}, {"name": "error", "location": "broken"},
    ]
    deps = dependencies(ai=rows, provider=fakes.FakeGeocodingProvider({
        "same": geo.CoordinateRecord(0, 0), "limited": geo.GeocodingRateLimit(),
        "broken": TimeoutError(),
    }))
    deps.online_reader = lambda org: org.record["name"] == "online"
    result = json.loads(handler.lambda_handler(BODY, None, dependencies=deps)["body"])
    for row in result:
        assert row["name"] == row["distance_status"]
        assert row["distance_unit"] == "miles" and row["distance_method"] == "straight_line"
        assert set(aggregator.ORG_COLUMNS) <= row.keys()
        assert row["distance"] == (0 if row["name"] == "ok" else None)


def test_frame_sources_and_existing_consumer_fields_win_over_aliases():
    import pandas as pd

    row = {**DB, "name": "Consumer name", "location": "Address", "rating": 0}
    deps = dependencies()
    deps.db_source = lambda body: pd.DataFrame([row])
    deps.ai_source = lambda body: pd.DataFrame([AI])
    results = json.loads(handler.lambda_handler(BODY, None, dependencies=deps)["body"])
    assert results[0]["name"] == "Consumer name" and results[0]["rating"] == 0
    assert results[0]["location"] == "Address"
    assert len(results) == 2


def test_both_failed_sources_distinct_from_valid_empty_sources():
    deps = dependencies()
    assert json.loads(handler.lambda_handler(BODY, None, dependencies=deps)["body"]) == []
    deps.db_source = deps.ai_source = lambda body: (_ for _ in ()).throw(RuntimeError("private"))
    result = handler.lambda_handler(BODY, None, dependencies=deps)
    assert result["statusCode"] == 502 and "private" not in result["body"]


@pytest.mark.parametrize("record", [geo.CoordinateRecord(100, 0), (0, 0)])
def test_invalid_injected_coordinates_do_not_geocode(record):
    result, provider = enrich({"location": "Address"}, reader=lambda org: record)
    assert result["distance_status"] == "error" and result["distance"] is None
    assert provider.calls == []


def test_nullable_frame_values_serialize_as_null():
    import pandas as pd

    deps = dependencies()
    frame = pd.DataFrame([AI])
    frame["rating"] = pd.Series([pd.NA], dtype="Float64")
    frame["size"] = pd.Series([pd.NA], dtype="Int64")
    deps.ai_source = lambda body: frame
    result = json.loads(handler.lambda_handler(BODY, None, dependencies=deps)["body"])[0]
    assert result["rating"] is None and result["size"] is None
    assert result["distance"] == 0


@pytest.mark.parametrize("source", ["db", "ai"])
def test_malformed_rows_preserve_other_records_from_both_sources(source):
    deps = dependencies([DB], [AI])
    mixed = [None, DB if source == "db" else AI, "malformed", 17]
    if source == "db":
        deps.db_source = lambda body: mixed
    else:
        deps.ai_source = lambda body: {
            "statusCode": 200, "body": {"organizations": mixed}
        }
    response = handler.lambda_handler(BODY, None, dependencies=deps)
    assert response["statusCode"] == 200
    rows = json.loads(response["body"])
    assert [row["name"] for row in rows] == ["DB Org", "AI Org"]
    assert all(row["distance_status"] == "ok" for row in rows)


@pytest.mark.parametrize("malformed", ["invalid rows", {"organization_name": "not a list"}])
def test_invalid_source_containers_still_degrade_to_other_source(malformed):
    deps = dependencies([DB])
    deps.ai_source = lambda body: {
        "statusCode": 200, "body": {"organizations": malformed}
    }
    rows = json.loads(handler.lambda_handler(BODY, None, dependencies=deps)["body"])
    assert [row["name"] for row in rows] == ["DB Org"]


@pytest.mark.parametrize("as_frame", [False, True])
def test_timestamp_fields_serialize_without_losing_organizations(as_frame):
    from datetime import date, datetime, timezone

    import pandas as pd

    row = {
        **DB,
        "created_at": datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc),
        "last_updated_at": pd.Timestamp("2026-01-02T12:00:00-06:00"),
        "metadata": {"date": date(2026, 1, 3)},
    }
    deps = dependencies(ai=[AI])
    deps.db_source = lambda body: pd.DataFrame([row]) if as_frame else [row]
    response = handler.lambda_handler(BODY, None, dependencies=deps)
    assert response["statusCode"] == 200
    rows = json.loads(response["body"])
    assert len(rows) == 2
    assert rows[0]["created_at"] == "2026-01-01T12:30:00+00:00"
    assert rows[0]["last_updated_at"] == "2026-01-02T12:00:00-06:00"
    assert rows[0]["metadata"] == {"date": "2026-01-03"}
    assert [row["distance_status"] for row in rows] == ["ok", "ok"]
    assert rows[1]["distance"] == 0


@pytest.mark.parametrize("failure", ["unsupported", "circular"])
def test_unserializable_field_preserves_record_and_other_organizations(failure):
    value = object()
    if failure == "circular":
        value = []
        value.append(value)
    deps = dependencies([{**DB, "metadata": value}], [AI])
    response = handler.lambda_handler(BODY, None, dependencies=deps)
    assert response["statusCode"] == 200
    rows = json.loads(response["body"])
    assert [row["name"] for row in rows] == ["DB Org", "AI Org"]
    assert rows[0]["metadata"] is None
    assert rows[0]["rating"] == 4.2 and rows[0]["collaborator"] is False
    assert all(row["distance_status"] == "ok" for row in rows)


@pytest.mark.parametrize("fields,expected", [
    ({}, False),
    ({"is_collaborator": True}, True),
    ({"is_collaborator": False}, False),
    ({"collaborator": True, "is_collaborator": False}, True),
    ({"collaborator": False, "is_collaborator": True}, False),
    ({"collaborator": None}, None),
])
def test_genai_collaborator_default_and_explicit_values(fields, expected):
    row = {"organization_name": "AI Org", "location": "Address", **fields}
    deps = dependencies(ai={"statusCode": 200, "body": {"organizations": [row]}})
    response = handler.lambda_handler(BODY, None, dependencies=deps)
    result = json.loads(response["body"])[0]
    assert result["collaborator"] is expected
    assert result["distance"] == 0 and result["distance_status"] == "ok"
    assert row == {"organization_name": "AI Org", "location": "Address", **fields}
