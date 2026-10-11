"""Synthetic offline tests: no helpers import, AWS, DB, or external provider calls."""

import importlib.util
from pathlib import Path
import sys

import pytest

AGGREGATOR = Path(__file__).resolve().parents[1] / "src/saayam-org-aggregator"


def load_module(name):
    """Load loose Lambda modules without importing live clients."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, AGGREGATOR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


beneficiary = load_module("beneficiary_location")
local_records = load_module("local_location_records")
geocoding = load_module("address_geocoding")
fakes = load_module("local_geocoding")
addresses = load_module("organization_addresses")
ADDRESS = "10 Synthetic St, Synthetic City, Synthetic State, 00123, Synthetic Country"
PAIR = geocoding.CoordinateRecord("0", "-120.5")


def assembler():
    """Use documented generator-shaped relationships, with mixed CSV and integer IDs."""
    return addresses.OrganizationAddressAssembler(
        states=[{"state_id": 7, "country_id": "8", "state_name": "Synthetic State"}],
        countries=[{"country_id": 8, "country_name": "Synthetic Country"}],
    )


def db_row():
    """No country_id or city table is required for a generator-shaped organization."""
    return {
        "org_id": "synthetic-org", "org_name": "Synthetic Org", "street": " 10 Synthetic St ",
        "city_name": "Synthetic City", "state_id": "7", "zip_code": "00123",
        "org_rating": 4, "is_collaborator": False,
    }


def test_database_address_uses_state_country_relationship_and_preserves_fields():
    row = db_row()
    result = assembler().from_database(row)
    assert result.address == ADDRESS
    assert result.record == row
    assert result.record is not row
    assert result.online_only is None


@pytest.mark.parametrize("removed,expected", [
    ("street", "Synthetic City, Synthetic State, 00123, Synthetic Country"),
    ("city_name", "10 Synthetic St, Synthetic State, 00123, Synthetic Country"),
    ("state_id", "10 Synthetic St, Synthetic City, 00123"),
    ("zip_code", "10 Synthetic St, Synthetic City, Synthetic State, Synthetic Country"),
])
def test_missing_database_components(removed, expected):
    row = db_row()
    row.pop(removed)
    assert assembler().from_database(row).address == expected


def test_missing_country_lookup_keeps_state_and_no_internal_ids():
    source = addresses.OrganizationAddressAssembler(
        states=[{"state_id": 7, "state_name": "Synthetic State", "country_id": 999}]
    )
    assert source.from_database(db_row()).address == (
        "10 Synthetic St, Synthetic City, Synthetic State, 00123"
    )


def test_unknown_state_omits_names_and_does_not_use_unconfirmed_country_field():
    row = db_row()
    row.update(state_id=999, country_id=8)
    assert assembler().from_database(row).address == "10 Synthetic St, Synthetic City, 00123"


@pytest.mark.parametrize("bad", [None, "", "  ", False, {}, [], float("nan")])
def test_unusable_components_retain_organization_with_explicit_missing_location(bad):
    row = {key: bad for key in ("street", "city_name", "state_id", "zip_code")}
    row.update(org_name="Synthetic Org", org_rating=5, is_collaborator=True)
    result = assembler().from_database(row)
    assert result.address is None
    assert result.record == dict(row, distance=None, distance_status="unknown_location")
    assert "distance" not in row


def test_integer_zip_and_partial_names_are_supported():
    row = {"zip_code": 0, "state_id": 7}
    assert assembler().from_database(row).address == "Synthetic State, 0, Synthetic Country"


@pytest.mark.parametrize("key,rows", [
    ("states", [{"state_id": 7}, {"state_id": "7"}]),
    ("countries", [{"country_id": 8}, {"country_id": "8"}]),
    ("states", [{}]), ("countries", [{}]),
])
def test_ambiguous_or_missing_lookup_id_raises(key, rows):
    with pytest.raises(ValueError):
        addresses.OrganizationAddressAssembler(**{key: rows})


def test_synthetic_genai_body_organizations_contract():
    payload = {"body": {"organizations": [
        {"organization_name": "Synthetic AI", "location": f"  {ADDRESS}  ", "rating": 4.5},
        {"organization_name": "Synthetic Missing", "contact": "synthetic", "rating": 3},
    ]}}
    results = [addresses.from_genai(row) for row in payload["body"]["organizations"]]
    assert len(results) == 2
    assert results[0].address == ADDRESS
    assert results[0].record == payload["body"]["organizations"][0]
    assert results[1].record["distance"] is None
    assert results[1].record["distance_status"] == "unknown_location"
    assert results[1].record["rating"] == 3


@pytest.mark.parametrize("value", [None, "", " ", {}, [], 123, False, float("nan")])
def test_bad_genai_location_does_not_infer_address_from_name_or_other_fields(value):
    row = {"organization_name": ADDRESS, "location": value, "address": ADDRESS}
    result = addresses.from_genai(row)
    assert result.address is None
    assert result.record["distance_status"] == "unknown_location"


def test_future_genai_mapping_is_explicitly_injected():
    assert addresses.from_genai(
        {"future_field": ADDRESS}, location_reader=lambda row: row["future_field"]
    ).address == ADDRESS


def test_online_classification_is_explicit_and_never_guessed():
    row = {"organization_name": "Online", "location": "Online", "online_only": True}
    assert addresses.from_genai(row).online_only is None
    assert addresses.from_genai(row, online_only=True).online_only is True
    assert assembler().from_database(db_row(), online_only=False).online_only is False


def test_success_saves_validated_coordinates_and_repeat_lookup_bypasses_provider():
    provider = fakes.FakeGeocodingProvider({ADDRESS: PAIR})
    cache = fakes.FakeCoordinateCache()
    first = geocoding.geocode_address(f"  {ADDRESS}  ", provider, cache)
    second = geocoding.geocode_address(ADDRESS, provider, cache)
    assert first.status == second.status == "resolved"
    assert first.coordinates == second.coordinates == (0, -120.5)
    assert first.source == "provider" and second.source == "cache"
    assert provider.calls == [ADDRESS]
    assert cache.reads == [ADDRESS, ADDRESS]
    assert cache.writes == [(ADDRESS, geocoding.CoordinateRecord(0, -120.5))]


def test_beneficiary_profile_and_organization_share_cache():
    records = local_records.LocalMockLocationRecordSource(
        synthetic_requests=[{"request_id": "synthetic-req", "beneficiary_id": "synthetic-user"}],
        users=[{"user_id": "synthetic-user", "addr_ln1": ADDRESS}],
    )
    location = beneficiary.resolve_beneficiary_location("synthetic-req", "synthetic-user", records)
    provider = fakes.FakeGeocodingProvider({ADDRESS: PAIR})
    cache = fakes.FakeCoordinateCache()
    assert geocoding.geocode_beneficiary_profile(location, provider, cache).source == "provider"
    assert geocoding.geocode_address(assembler().from_database(db_row()).address,
                                     provider, cache).source == "cache"
    assert provider.calls == [ADDRESS]


@pytest.mark.parametrize("location", [
    beneficiary.LocationResolution("resolved", "request", (0, 0)),
    beneficiary.LocationResolution("unresolved", reason="missing_request"),
])
def test_profile_entry_point_does_not_geocode_other_task1_outcomes(location):
    provider, cache = fakes.FakeGeocodingProvider({}), fakes.FakeCoordinateCache()
    with pytest.raises(ValueError):
        geocoding.geocode_beneficiary_profile(location, provider, cache)
    assert provider.calls == cache.reads == []


@pytest.mark.parametrize("address", [None, "", "  ", 123, {}, False])
def test_missing_location_never_calls_cache_or_provider(address):
    provider, cache = fakes.FakeGeocodingProvider({}), fakes.FakeCoordinateCache()
    result = geocoding.geocode_address(address, provider, cache)
    assert result.status == "missing_location"
    assert result.coordinates is None
    assert provider.calls == cache.reads == cache.writes == []


@pytest.mark.parametrize("response,status,reason", [
    (None, "not_found", "unmatched_address"),
    (geocoding.GeocodingRateLimit("synthetic"), "deferred", "rate_limit"),
    (TimeoutError("synthetic"), "timeout", "provider_timeout"),
    (RuntimeError("synthetic"), "error", "provider_error"),
])
def test_distinct_failure_outcomes_are_not_cached(response, status, reason):
    provider = fakes.FakeGeocodingProvider({ADDRESS: response})
    cache = fakes.FakeCoordinateCache()
    result = geocoding.geocode_address(ADDRESS, provider, cache)
    assert result.status == status and result.reason == reason
    assert result.coordinates is None
    assert provider.calls == [ADDRESS]
    assert cache.writes == []


@pytest.mark.parametrize("record", [
    geocoding.CoordinateRecord(91, 0), geocoding.CoordinateRecord(0, -181),
    geocoding.CoordinateRecord(True, 0), geocoding.CoordinateRecord(0, None),
    geocoding.CoordinateRecord(float("nan"), 0),
    geocoding.CoordinateRecord(0, float("inf")),
    geocoding.CoordinateRecord("bad", 0), (0, 0), {},
])
def test_invalid_provider_coordinates_are_errors_and_not_written(record):
    cache = fakes.FakeCoordinateCache()
    result = geocoding.geocode_address(
        ADDRESS, fakes.FakeGeocodingProvider({ADDRESS: record}), cache
    )
    assert result.status == "error"
    assert result.reason == "invalid_provider_coordinates"
    assert cache.writes == []


@pytest.mark.parametrize("record", [geocoding.CoordinateRecord(100, 0), {}, (0, 0)])
def test_invalid_cache_entry_falls_back_and_is_replaced(record):
    cache = fakes.FakeCoordinateCache({ADDRESS: record})
    provider = fakes.FakeGeocodingProvider({ADDRESS: PAIR})
    result = geocoding.geocode_address(ADDRESS, provider, cache)
    assert result.status == "resolved" and result.cache_error == "invalid_coordinates"
    assert result.source == "provider"
    assert cache.entries[ADDRESS] == geocoding.CoordinateRecord(0, -120.5)


@pytest.mark.parametrize("operation,diagnostic", [("get", "read_error"), ("put", "write_error")])
def test_cache_failure_preserves_provider_coordinates(monkeypatch, operation, diagnostic):
    cache = fakes.FakeCoordinateCache()

    def fail(*args):
        """Simulate a cache backend outage entirely locally."""
        raise RuntimeError("synthetic cache failure")

    monkeypatch.setattr(cache, operation, fail)
    result = geocoding.geocode_address(ADDRESS, fakes.FakeGeocodingProvider({ADDRESS: PAIR}), cache)
    assert result.status == "resolved"
    assert result.coordinates == (0, -120.5)
    assert result.cache_error == diagnostic


def test_cache_keys_do_not_conflate_case_or_interior_whitespace():
    cache = fakes.FakeCoordinateCache({ADDRESS: PAIR})
    provider = fakes.FakeGeocodingProvider({})
    assert geocoding.geocode_address(ADDRESS.lower(), provider, cache).status == "not_found"
    spaced = ADDRESS.replace(" ", "  ")
    assert geocoding.geocode_address(spaced, provider, cache).status == "not_found"


def test_new_fake_cache_does_not_retain_another_instances_writes():
    first, second = fakes.FakeCoordinateCache(), fakes.FakeCoordinateCache()
    first.put(ADDRESS, PAIR)
    assert second.get(ADDRESS) is None
