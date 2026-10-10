"""Behavior tests for organization aggregator distance calculations."""

import importlib.util
import json
from pathlib import Path
import sys
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "saayam-org-aggregator"
    / "distance.py"
)
SPEC = importlib.util.spec_from_file_location("org_aggregator_distance", MODULE_PATH)
distance_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(distance_module)
AGGREGATOR_DIR = MODULE_PATH.parent
sys.path.insert(0, str(AGGREGATOR_DIR))
import helpers as aggregator_helpers
LAMBDA_SPEC = importlib.util.spec_from_file_location(
    "org_aggregator_lambda", AGGREGATOR_DIR / "lambda_function.py"
)
aggregator_lambda = importlib.util.module_from_spec(LAMBDA_SPEC)
LAMBDA_SPEC.loader.exec_module(aggregator_lambda)


def test_coordinate_formats_return_straight_line_miles():
    """Labeled coordinates and PostGIS WKT produce the expected distance."""
    result = distance_module.resolve_distance(
        "longitude:-121.9780,latitude:37.7799",
        "SRID=4326;POINT(-122.0841 37.4220)",
    )

    assert result["distance"] == pytest.approx(25.5, abs=0.2)
    assert result["distance_unit"] == "miles"
    assert result["distance_method"] == "straight_line"
    assert result["distance_status"] == "ok"


def test_same_coordinates_preserve_zero_distance():
    """A real zero-mile result is distinct from an unavailable distance."""
    coordinates = {"latitude": 37.7799, "longitude": -121.978}

    result = distance_module.resolve_distance(coordinates, coordinates)

    assert result["distance"] == 0
    assert result["distance_status"] == "ok"


def test_geojson_point_uses_longitude_latitude_order():
    """GeoJSON Point coordinates are longitude first, unlike API tuples."""
    coordinates = {"type": "Point", "coordinates": [-121.978, 37.7799]}

    result = distance_module.resolve_distance(coordinates, coordinates)

    assert result["distance"] == 0
    assert result["distance_status"] == "ok"


def test_missing_beneficiary_location_is_unknown_not_zero():
    """Missing beneficiary coordinates never become a numeric zero."""
    result = distance_module.resolve_distance(None, "Some organization address")

    assert result["distance"] is None
    assert result["distance_status"] == "unknown_location"


def test_geocoder_is_cached_and_provider_is_injected():
    """Repeated address lookups reuse cached coordinates without a provider choice."""
    calls = []

    def geocoder(address):
        calls.append(address)
        return {"latitude": 37.422, "longitude": -122.0841}

    cache = {}
    beneficiary = (37.7799, -121.978)
    first = distance_module.resolve_distance(beneficiary, "Google HQ", geocoder, cache)
    second = distance_module.resolve_distance(beneficiary, "google hq", geocoder, cache)

    assert first["distance_status"] == "ok"
    assert second["distance"] == first["distance"]
    assert calls == ["Google HQ"]


def test_default_warm_cache_reuses_geocoder_result():
    """Warm Lambda environments reuse geocoded coordinates across requests."""
    calls = []
    distance_module._COORDINATE_CACHE.clear()

    def geocoder(address):
        calls.append(address)
        return (37.422, -122.0841)

    first = distance_module.resolve_distance((37.7799, -121.978), "Cache address", geocoder)
    second = distance_module.resolve_distance((37.7799, -121.978), " cache  ADDRESS ", geocoder)

    assert first["distance_status"] == "ok"
    assert second["distance"] == first["distance"]
    assert calls == ["Cache address"]
    distance_module._COORDINATE_CACHE.clear()


def test_address_without_configured_geocoder_is_deferred():
    """Address geocoding remains pluggable until the provider is approved."""
    result = distance_module.resolve_distance((37.7799, -121.978), "Unknown address")

    assert result["distance"] is None
    assert result["distance_status"] == "deferred"


def test_missing_address_sentinel_is_unknown_not_deferred():
    """N/A values are missing locations and do not trigger geocoding."""
    calls = []
    result = distance_module.resolve_distance(
        (37.7799, -121.978),
        "N/A",
        geocoder=lambda address: calls.append(address),
    )

    assert result["distance"] is None
    assert result["distance_status"] == "unknown_location"
    assert calls == []


def test_unmatched_address_is_not_found():
    """A configured geocoder that returns no coordinates reports not_found."""
    result = distance_module.resolve_distance(
        (37.7799, -121.978),
        "Unmatched address",
        geocoder=lambda address: None,
        cache={},
    )

    assert result["distance"] is None
    assert result["distance_status"] == "not_found"


def test_geocoder_rate_limit_returns_deferred_status():
    """Provider throttling is distinct from an unexpected geocoder error."""

    def rate_limited_geocoder(address):
        raise distance_module.GeocodingDeferredError("provider rate limit")

    result = distance_module.resolve_distance(
        (37.7799, -121.978),
        "Organization address",
        geocoder=rate_limited_geocoder,
        cache={},
    )

    assert result["distance"] is None
    assert result["distance_status"] == "deferred"


def test_online_only_organization_gets_online_status():
    """Online-only organizations remain in the response with an explicit status."""
    result = distance_module.resolve_distance(
        (37.7799, -121.978),
        {"is_online": True, "address": None},
    )

    assert result["distance"] is None
    assert result["distance_status"] == "online"


def test_enrichment_skips_geocoding_for_online_only_organizations():
    """Online-only records keep their status without resolving beneficiary address."""
    calls = []
    results = distance_module.enrich_organizations(
        [{"name": "Online Organization", "is_online": True}],
        "Beneficiary address",
        geocoder=lambda address: calls.append(address),
        cache={},
    )

    assert results[0]["distance"] is None
    assert results[0]["distance_status"] == "online"
    assert calls == []


@pytest.mark.parametrize(
    ("request_location", "user_location", "profile_address", "expected"),
    [
        (
            "longitude:-121.978,latitude:37.7799",
            "latitude:38.0,longitude:-122.0",
            "Beneficiary Street, City, State",
            (37.7799, -121.978),
        ),
        (
            "unparsed request location",
            "POINT(-122.0 38.0)",
            "Beneficiary Street, City, State",
            (38.0, -122.0),
        ),
        (
            "unparsed request location",
            "456 User Location, Fairfax, Virginia",
            "Beneficiary Profile, Fairfax, Virginia",
            "456 User Location, Fairfax, Virginia",
        ),
        (
            None,
            None,
            "Beneficiary Street, City, State",
            "Beneficiary Street, City, State",
        ),
        (None, None, None, None),
    ],
)
def test_beneficiary_location_uses_request_user_then_profile(
    request_location, user_location, profile_address, expected
):
    """Location resolution follows request, current user location, profile order."""
    result = distance_module.select_beneficiary_location(
        request_location, user_location, profile_address
    )

    assert result == expected


def test_enrichment_preserves_organizations_when_geocoding_fails():
    """Distance failures add metadata but never discard organization results."""
    organizations = [
        {
            "name": "Nearby organization",
            "street": "1 Main St",
            "city_name": "Mountain View",
            "state_name": "California",
            "zip_code": "94043",
            "country_name": "United States",
            "rating": 4.7,
        },
        {"name": "Unmatched organization", "location": "Unknown place"},
    ]
    geocoded_addresses = []

    def geocoder(address):
        geocoded_addresses.append(address)
        if address.startswith("1 Main St"):
            return (37.422, -122.0841)
        raise TimeoutError("geocoder unavailable")

    results = distance_module.enrich_organizations(
        organizations,
        (37.7799, -121.978),
        geocoder=geocoder,
        cache={},
    )

    assert len(results) == 2
    assert results[0]["name"] == "Nearby organization"
    assert results[0]["rating"] == 4.7
    assert results[0]["distance_status"] == "ok"
    assert results[1]["name"] == "Unmatched organization"
    assert results[1]["distance"] is None
    assert results[1]["distance_status"] == "error"
    assert geocoded_addresses[0] == "1 Main St, Mountain View, California, 94043, United States"


def test_enrichment_marks_missing_beneficiary_unknown():
    """Organizations remain present when beneficiary location is unavailable."""
    results = distance_module.enrich_organizations(
        [{"name": "Organization", "location": "City, State"}],
        None,
    )

    assert len(results) == 1
    assert results[0]["distance"] is None
    assert results[0]["distance_status"] == "unknown_location"


def test_beneficiary_geocoding_failure_is_not_repeated_per_organization():
    """An unresolved beneficiary address is geocoded only once per response."""
    calls = []

    def geocoder(address):
        calls.append(address)
        return None

    results = distance_module.enrich_organizations(
        [{"name": "First", "latitude": 37.0, "longitude": -122.0},
         {"name": "Second", "latitude": 38.0, "longitude": -122.0}],
        "Beneficiary address",
        geocoder=geocoder,
        cache={},
    )

    assert len(results) == 2
    assert all(result["distance_status"] == "not_found" for result in results)
    assert calls == ["Beneficiary address"]


def test_nan_address_fields_are_treated_as_missing():
    """Pandas missing-value markers do not become geocodable address text."""
    organization = pd.DataFrame(
        [{"name": "No address", "street": float("nan"), "city_name": float("nan"), "country_name": float("nan")}]
    ).to_dict(orient="records")
    geocoder_calls = []

    result = distance_module.enrich_organizations(
        organization,
        (37.7799, -121.978),
        geocoder=lambda address: geocoder_calls.append(address),
        cache={},
    )

    assert result[0]["distance"] is None
    assert result[0]["distance_status"] == "unknown_location"
    assert geocoder_calls == []


def test_organization_merge_preserves_distance_and_existing_fields():
    """Merge keeps address, rating, and collaborator data for distance output."""
    database_organizations = pd.DataFrame(
        [
            {
                "org_name": "Database Organization",
                "city_name": "Mountain View",
                "phone": "555-0100",
                "email": "db@example.org",
                "web_url": "https://db.example.org",
                "mission": "Education",
                "source": "database",
                "street": "1 Main St",
                "state_name": "California",
                "zip_code": "94043",
                "country_name": "United States",
                "org_type": "nonprofit",
                "is_collaborator": True,
                "rating": 4.7,
                "db_or_ai": "db",
            }
        ]
    )
    genai_organizations = pd.DataFrame(
        [
            {
                "organization_name": "GenAI Organization",
                "location": "Palo Alto, California",
                "contact": "555-0101",
                "email": "ai@example.org",
                "web_url": "https://ai.example.org",
                "mission": "Education",
                "source": "genai",
                "formatted_address": "Palo Alto, California",
                "latitude": 37.4419,
                "longitude": -122.143,
                "db_or_ai": "ai",
            }
        ]
    )

    result = aggregator_helpers.merge_organizations(database_organizations, genai_organizations)

    database_record = result.loc[result["name"] == "Database Organization"].iloc[0]
    assert database_record["street"] == "1 Main St"
    assert database_record["city_name"] == "Mountain View"
    assert database_record["location"] == "Mountain View"
    assert database_record["state_name"] == "California"
    assert database_record["country_name"] == "United States"
    assert database_record["rating"] == 4.7
    assert database_record["is_collaborator"]
    assert result.loc[result["name"] == "GenAI Organization"].shape[0] == 1
    genai_record = result.loc[result["name"] == "GenAI Organization"].iloc[0]
    assert genai_record["formatted_address"] == "Palo Alto, California"
    assert genai_record["latitude"] == 37.4419


def test_request_id_event_returns_database_orgs_when_genai_fails(monkeypatch):
    """A request-only event derives search context and isolates GenAI failure."""
    monkeypatch.setattr(
        aggregator_lambda,
        "get_request_context",
        lambda request_id, beneficiary_id: {
            "beneficiary_location": (37.7799, -121.978),
            "search": {"location": "Mountain View", "category": "Education"},
        },
        raising=False,
    )
    monkeypatch.setattr(
        aggregator_lambda,
        "get_orgs_from_db",
        lambda location, category: pd.DataFrame(
            [
                {
                    "org_name": "Database Organization",
                    "city_name": "Mountain View",
                    "phone": "555-0100",
                    "email": "db@example.org",
                    "web_url": "https://db.example.org",
                    "mission": "Education",
                    "source": "database",
                    "db_or_ai": "db",
                    "street": "1 Main St",
                    "state_name": "California",
                    "country_name": "United States",
                    "rating": 4.7,
                    "is_collaborator": True,
                }
            ]
        ),
    )

    def fail_genai(subject, description, location):
        raise RuntimeError("GenAI is unavailable")

    monkeypatch.setattr(aggregator_lambda, "get_ai_orgs", fail_genai)

    response = aggregator_lambda.lambda_handler({"body": '{"request_id":"req-1"}'}, None)

    assert response["statusCode"] == 200
    organizations = json.loads(response["body"])
    assert len(organizations) == 1
    assert organizations[0]["name"] == "Database Organization"
    assert organizations[0]["rating"] == 4.7
    assert organizations[0]["is_collaborator"]
    assert organizations[0]["distance"] is None
    assert organizations[0]["distance_status"] == "deferred"


def test_legacy_location_category_event_still_returns_organizations(monkeypatch):
    """Existing callers that send location and category remain compatible."""
    monkeypatch.setattr(
        aggregator_lambda,
        "get_orgs_from_db",
        lambda location, category: pd.DataFrame(
            [{"org_name": "Existing Organization", "city_name": location, "mission": category, "source": "db", "db_or_ai": "db"}]
        ),
    )
    monkeypatch.setattr(aggregator_lambda, "get_ai_orgs", lambda *args: pd.DataFrame())
    monkeypatch.setattr(aggregator_lambda, "get_geocoder", lambda: None)

    response = aggregator_lambda.lambda_handler(
        {"location": "Fairfax", "category": "Education"}, None
    )

    assert response["statusCode"] == 200
    organizations = json.loads(response["body"])
    assert organizations[0]["name"] == "Existing Organization"
    assert organizations[0]["distance_status"] == "unknown_location"


def test_genai_helper_degrades_cleanly_without_boto3(monkeypatch):
    """Optional local imports do not cause exception-handler failures."""
    monkeypatch.setattr(aggregator_helpers, "boto3", None)
    monkeypatch.setattr(aggregator_helpers, "_LAMBDA_CLIENT", None)

    with pytest.raises(Exception, match="Error fetching AI orgs: boto3 is required"):
        aggregator_helpers.get_ai_orgs("subject", "description", "location")


def test_configured_dynamodb_cache_persists_coordinates(monkeypatch):
    """An optional DynamoDB table persists normalized address coordinates."""
    class FakeTable:
        def __init__(self):
            self.items = {}

        def get_item(self, Key):
            item = self.items.get(Key["address_key"])
            return {"Item": item} if item else {}

        def put_item(self, Item):
            self.items[Item["address_key"]] = Item

    table = FakeTable()
    fake_resource = SimpleNamespace(Table=lambda name: table)
    fake_boto3 = SimpleNamespace(resource=lambda service: fake_resource)
    monkeypatch.setattr(aggregator_helpers, "boto3", fake_boto3)
    monkeypatch.setattr(aggregator_helpers, "_GEOCODE_CACHE", None, raising=False)
    monkeypatch.setenv("GEOCODE_CACHE_TABLE", "organization-geocode-cache")

    cache = aggregator_helpers.get_geocode_cache()
    cache["address-key"] = (37.5, -122.25)

    assert cache.get("address-key") == (37.5, -122.25)
    assert table.items["address-key"] == {
        "address_key": "address-key",
        "latitude": Decimal("37.5"),
        "longitude": Decimal("-122.25"),
    }
    monkeypatch.setattr(aggregator_helpers, "_GEOCODE_CACHE", None)
    monkeypatch.setattr(aggregator_helpers, "_GEOCODE_CACHE_TABLE", None)
    restored_cache = aggregator_helpers.get_geocode_cache()
    assert restored_cache.get("address-key") == (37.5, -122.25)


def test_geocoder_adapter_maps_rate_limit_to_deferred(monkeypatch):
    """Configured provider rate limits use the deferred distance status."""
    class FakePayload:
        def read(self):
            return json.dumps({"statusCode": 429, "body": {"error": "rate limited"}}).encode()

    class FakeClient:
        def invoke(self, **kwargs):
            return {"Payload": FakePayload()}

    monkeypatch.setenv("GEOCODER_LAMBDA_NAME", "configured-geocoder")
    monkeypatch.setattr(aggregator_helpers, "_get_lambda_client", lambda: FakeClient())

    with pytest.raises(aggregator_helpers.GeocodingDeferredError):
        aggregator_helpers.get_geocoder()("Organization address")


def test_distance_sort_places_unknown_after_near_and_far(monkeypatch):
    """Distance sorting is nearest-first and keeps unknown values at the end."""
    monkeypatch.setattr(
        aggregator_lambda,
        "get_request_context",
        lambda request_id, beneficiary_id: {
            "beneficiary_location": (37.0, -122.0),
            "search": {"location": "City", "category": "Education"},
        },
        raising=False,
    )
    monkeypatch.setattr(
        aggregator_lambda,
        "get_orgs_from_db",
        lambda location, category: pd.DataFrame(
            [
                {"org_name": "Far", "city_name": "City", "mission": "Education", "source": "db", "db_or_ai": "db", "latitude": 38.0, "longitude": -122.0},
                {"org_name": "Unknown", "city_name": None, "mission": "Education", "source": "db", "db_or_ai": "db"},
                {"org_name": "Near", "city_name": "City", "mission": "Education", "source": "db", "db_or_ai": "db", "latitude": 37.1, "longitude": -122.0},
            ]
        ),
    )
    monkeypatch.setattr(aggregator_lambda, "get_ai_orgs", lambda *args: pd.DataFrame())
    monkeypatch.setattr(aggregator_lambda, "get_geocoder", lambda: None)

    response = aggregator_lambda.lambda_handler(
        {"request_id": "req-1", "sort_by": "distance"}, None
    )

    assert response["statusCode"] == 200
    organizations = json.loads(response["body"])
    assert [organization["name"] for organization in organizations] == ["Near", "Far", "Unknown"]
    assert organizations[-1]["distance"] is None


def test_genai_results_survive_database_failure(monkeypatch):
    """A database failure does not discard available GenAI organizations."""
    monkeypatch.setattr(
        aggregator_lambda,
        "get_request_context",
        lambda request_id, beneficiary_id: {
            "beneficiary_location": (37.7799, -121.978),
            "search": {"location": "Mountain View", "category": "Education"},
        },
        raising=False,
    )

    def fail_database(location, category):
        raise RuntimeError("Database unavailable")

    monkeypatch.setattr(aggregator_lambda, "get_orgs_from_db", fail_database)
    monkeypatch.setattr(
        aggregator_lambda,
        "get_ai_orgs",
        lambda *args: pd.DataFrame(
            [
                {
                    "organization_name": "GenAI Organization",
                    "location": "Palo Alto, California",
                    "contact": "555-0101",
                    "email": "ai@example.org",
                    "web_url": "https://ai.example.org",
                    "mission": "Education",
                    "source": "genai",
                    "db_or_ai": "ai",
                }
            ]
        ),
    )
    monkeypatch.setattr(aggregator_lambda, "get_geocoder", lambda: None)

    response = aggregator_lambda.lambda_handler({"request_id": "req-1"}, None)

    assert response["statusCode"] == 200
    organizations = json.loads(response["body"])
    assert len(organizations) == 1
    assert organizations[0]["name"] == "GenAI Organization"
    assert organizations[0]["distance_status"] == "deferred"


def test_request_context_fetches_location_fallback_and_category(monkeypatch):
    """DB context joins named profile fields and resolves the request category."""
    request_record = {
        "req_id": "req-1",
        "beneficiary_id": "beneficiary-2",
        "req_loc": None,
        "req_cat_id": 7,
    }
    current_location = {"beneficiary_id": "beneficiary-2", "curr_loc": "POINT(-77.0 38.0)"}
    profile_records = [
        {"user_id": "beneficiary-2", "street": "1 Main St", "city_id": 4, "zip_code": "22030"},
        {"city_id": 4, "city_name": "Fairfax", "state_id": 8},
        {"state_id": 8, "state_name": "Virginia", "country_id": 12},
        {"country_id": 12, "country_name": "United States"},
    ]
    category_record = {"cat_id": 7, "cat_name": "Education"}

    class FakeCursor:
        def execute(self, query, params=None):
            if "information_schema.columns" in query:
                self.result = ("text",)
            elif "FROM test_schema.requests" in query:
                self.result = (json.dumps(request_record),)
            elif "FROM test_schema.user_locations" in query:
                self.result = (json.dumps(current_location),)
            elif "FROM test_schema.users" in query:
                self.result = tuple(json.dumps(record) for record in profile_records)
            elif "FROM test_schema.help_categories" in query:
                self.result = (json.dumps(category_record),)
            else:
                raise AssertionError(f"Unexpected SQL query: {query}")

        def fetchone(self):
            return self.result

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(aggregator_helpers, "_DB_CONFIG", {"DATABASE NAME": "test_schema"})
    monkeypatch.setattr(aggregator_helpers, "_get_db_connection", FakeConnection)

    context = aggregator_helpers.get_request_context("req-1")

    assert context["beneficiary_location"] == (38.0, -77.0)
    assert context["profile_address"] == {
        "street": "1 Main St",
        "city_name": "Fairfax",
        "state_name": "Virginia",
        "zip_code": "22030",
        "country_name": "United States",
    }
    assert context["search"]["location"] == "Fairfax"
    assert context["search"]["category"] == "Education"