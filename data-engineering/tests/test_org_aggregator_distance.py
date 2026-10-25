"""Tests for distance calculation in saayam-org-aggregator (issue #433).

The DB and the geocoding provider are faked: no AWS, network or provider
account is needed. Each test maps to a scenario in the issue's
"Testing Scenarios" list.
"""

import importlib
import io
import json
import re
import struct
import sys
import types
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
AGGREGATOR_DIR = SRC_DIR / "saayam-org-aggregator"
for path in (SRC_DIR, AGGREGATOR_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import org_distance  # noqa: E402
from utils import geocoding  # noqa: E402
from utils.geo import Coordinates, haversine_distance, parse_coordinates  # noqa: E402
from utils.geocoding import (  # noqa: E402
    CacheEntry,
    GeocodingProvider,
    GeocodingRateLimitError,
    InMemoryCoordinateCache,
    LookupBudget,
    PostgresCoordinateCache,
    TieredCoordinateCache,
    geocode_address,
    get_provider,
    register_provider,
)

SCHEMA = "test_schema"
TABLES = org_distance.SaayamTables(schema=SCHEMA)

BENEFICIARY = Coordinates(37.7799, -121.9780)  # the issue's example origin
GOOGLEPLEX = Coordinates(37.4220, -122.0841)
RESTON = Coordinates(38.9586, -77.3570)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self._rows = []

    def execute(self, sql, params=None):
        self.conn.queries.append((sql, params))
        for pattern, handler in self.conn.routes:
            if re.search(pattern, sql):
                result = handler(params) if callable(handler) else handler
                if isinstance(result, Exception):
                    raise result
                columns, rows = result
                self.description = [(name, None) for name in columns]
                self._rows = list(rows)
                return
        self.description = []
        self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class FakeConn:
    """Minimal DB-API connection that answers queries by regex route."""

    def __init__(self, routes=None):
        self.routes = list(routes or [])
        self.queries = []
        self.rollbacks = 0
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1

    def ran(self, pattern):
        return any(re.search(pattern, sql) for sql, _ in self.queries)


class FakeProvider(GeocodingProvider):
    name = "fake"

    def __init__(self, mapping=None, error=None):
        self.mapping = mapping or {}
        self.error = error
        self.calls = []

    def geocode(self, address):
        self.calls.append(address)
        if self.error is not None:
            raise self.error
        return self.mapping.get(address)


def ewkb_point_hex(lon, lat, srid=4326):
    """PostGIS EWKB hex, as psycopg2 returns a geography column."""
    return struct.pack("<BIIdd", 1, 0x20000001, srid, lon, lat).hex()


def states_route(rows):
    return (rf"FROM {SCHEMA}\.states s", (["state_name", "country_name"], rows))


@pytest.fixture(autouse=True)
def fresh_state():
    org_distance._LOOKUP_MEMO.clear()
    geocoding._MEMORY_CACHE.clear()
    yield
    org_distance._LOOKUP_MEMO.clear()
    geocoding._MEMORY_CACHE.clear()
    geocoding.set_default_provider(None)


@pytest.fixture
def cache():
    return TieredCoordinateCache(InMemoryCoordinateCache())


# --------------------------------------------------------------------------- #
# Straight-line distance and coordinate parsing
# --------------------------------------------------------------------------- #
def test_haversine_matches_issue_example():
    # The issue quotes ~25.5 mi; the great-circle value rounds to 25.4.
    assert round(haversine_distance(BENEFICIARY, GOOGLEPLEX), 1) == 25.4


def test_same_point_is_zero():
    assert haversine_distance(BENEFICIARY, BENEFICIARY) == 0.0


@pytest.mark.parametrize(
    "value",
    [
        "longitude:-121.9780,latitude:37.7799",
        "latitude: 37.7799, longitude: -121.9780",
        '{"lat": 37.7799, "lng": -121.9780}',
        {"latitude": 37.7799, "longitude": -121.9780},
        "SRID=4326;POINT(-121.9780 37.7799)",
        "POINT (-121.9780 37.7799)",
        ewkb_point_hex(-121.9780, 37.7799),
        bytes.fromhex(ewkb_point_hex(-121.9780, 37.7799)),
        "37.7799,-121.9780",
    ],
)
def test_parse_coordinates_supported_formats(value):
    coords = parse_coordinates(value)
    assert coords == Coordinates(37.7799, -121.9780)


@pytest.mark.parametrize(
    "value",
    [None, "", "Suffolk, VA", "latitude:137.0,longitude:10", "SRID=3857;POINT(100 200)", ewkb_point_hex(1, 2, srid=3857)],
)
def test_parse_coordinates_rejects_non_coordinates(value):
    assert parse_coordinates(value) is None


# --------------------------------------------------------------------------- #
# Geocoding helper: provider-agnostic, cached
# --------------------------------------------------------------------------- #
def test_cached_coordinates_are_reused(cache):
    provider = FakeProvider({"1 Main St, Reston, VA": RESTON})

    first = geocode_address("1 Main St, Reston, VA", provider=provider, cache=cache)
    second = geocode_address("1 main st.,  RESTON , va", provider=provider, cache=cache)

    assert first.ok and not first.from_cache
    assert second.ok and second.from_cache and second.coordinates == RESTON
    assert provider.calls == ["1 Main St, Reston, VA"]


def test_not_found_is_cached_but_errors_are_retried(cache):
    missing = FakeProvider({})
    assert geocode_address("Nowhere 123", provider=missing, cache=cache).status == "not_found"
    assert geocode_address("Nowhere 123", provider=missing, cache=cache).status == "not_found"
    assert len(missing.calls) == 1

    failing = FakeProvider(error=TimeoutError("provider timed out"))
    assert geocode_address("Somewhere 1", provider=failing, cache=cache).status == "error"
    assert geocode_address("Somewhere 1", provider=failing, cache=cache).status == "error"
    assert len(failing.calls) == 2


def test_no_provider_configured_defers(cache, monkeypatch):
    monkeypatch.delenv("GEOCODING_PROVIDER", raising=False)
    result = geocode_address("1 Main St, Reston, VA", provider=get_provider(), cache=cache)
    assert result.status == "deferred"


def test_rate_limit_and_budget_defer(cache):
    limited = FakeProvider(error=GeocodingRateLimitError("quota"))
    assert geocode_address("A St, Reston", provider=limited, cache=cache).status == "deferred"

    provider = FakeProvider({"A St, Reston": RESTON, "B St, Reston": RESTON})
    budget = LookupBudget(max_lookups=1, max_seconds=None)
    assert geocode_address("A St, Reston", provider=provider, cache=cache, budget=budget).ok
    assert geocode_address("B St, Reston", provider=provider, cache=cache, budget=budget).status == "deferred"
    # Cached results do not use up the budget.
    assert geocode_address("A St, Reston", provider=provider, cache=cache, budget=budget).ok


def test_provider_registry_and_unknown_provider():
    register_provider("fake-test", lambda: FakeProvider())
    assert isinstance(get_provider("fake-test"), FakeProvider)
    assert get_provider("does-not-exist").name == "none"


def test_postgres_cache_round_trip_and_read_only_fallback():
    conn = FakeConn([(r"SELECT status", (["status", "latitude", "longitude", "provider", "updated_at"], [("ok", 38.9586, -77.357, "fake", None)]))])
    pg_cache = PostgresCoordinateCache(conn, table=f"{SCHEMA}.geocode_cache")

    entry = pg_cache.get("1 main st, reston")
    assert entry.status == "ok" and entry.coordinates == Coordinates(38.9586, -77.357)

    pg_cache.set("k", "addr", CacheEntry("ok", RESTON, "fake"))
    assert conn.commits >= 1

    read_only = FakeConn([(r"INSERT INTO", PermissionError("permission denied"))])
    pg_cache = PostgresCoordinateCache(read_only, table=f"{SCHEMA}.geocode_cache")
    pg_cache.set("k", "addr", CacheEntry("ok", RESTON, "fake"))
    pg_cache.set("k2", "addr", CacheEntry("ok", RESTON, "fake"))
    assert read_only.rollbacks == 1
    assert sum("INSERT INTO" in sql for sql, _ in read_only.queries) == 1


# --------------------------------------------------------------------------- #
# Beneficiary / request location
# --------------------------------------------------------------------------- #
def test_request_coordinates_are_used_directly(cache):
    conn = FakeConn()
    origin = org_distance.resolve_beneficiary_location(
        conn, TABLES, beneficiary_id="B1",
        request_location="longitude:-121.9780,latitude:37.7799", cache=cache,
    )
    assert origin.ok and origin.source == "request"
    assert origin.coordinates == BENEFICIARY
    assert conn.queries == []


def test_user_locations_fallback(cache):
    conn = FakeConn([(rf"{SCHEMA}\.user_locations", (["curr_loc"], [(ewkb_point_hex(-121.9780, 37.7799),)]))])
    origin = org_distance.resolve_beneficiary_location(
        conn, TABLES, beneficiary_id="B1", request_location="Suffolk, VA", cache=cache,
    )
    assert origin.ok and origin.source == "user_locations"
    assert origin.coordinates == BENEFICIARY


def test_profile_address_fallback_uses_real_names_not_ids(cache):
    user = {"user_id": "B1", "addr_ln1": "12 Main St", "city_name": "Reston",
            "state_id": "233.61", "country_id": 233, "zip_code": "20190"}
    conn = FakeConn([
        (rf"{SCHEMA}\.user_locations", (["curr_loc"], [(None,)])),
        (rf"{SCHEMA}\.users\b", (list(user), [tuple(user.values())])),
        states_route([("VIRGINIA", "UNITED_STATES_OF_AMERICA")]),
        (rf"FROM {SCHEMA}\.countries WHERE", (["country_name"], [("UNITED_STATES_OF_AMERICA",)])),
    ])
    expected_address = "12 Main St, Reston, Virginia 20190, United States Of America"
    provider = FakeProvider({expected_address: RESTON})

    origin = org_distance.resolve_beneficiary_location(
        conn, TABLES, beneficiary_id="B1", request_location=None, provider=provider, cache=cache,
    )

    assert origin.ok and origin.source == "profile_address"
    assert provider.calls == [expected_address]


def test_no_beneficiary_location_is_unknown_and_never_defaults(cache):
    user = {"user_id": "B1", "addr_ln1": None, "city_name": None, "state_id": None, "country_id": 233, "zip_code": None}
    conn = FakeConn([
        (rf"{SCHEMA}\.users\b", (list(user), [tuple(user.values())])),
        (rf"FROM {SCHEMA}\.countries WHERE", (["country_name"], [("UNITED_STATES_OF_AMERICA",)])),
    ])
    provider = FakeProvider({"United States Of America": Coordinates(39.8, -98.6)})

    origin = org_distance.resolve_beneficiary_location(
        conn, TABLES, beneficiary_id="B1", request_location=None, provider=provider, cache=cache,
    )

    assert origin.status == "unknown_location" and origin.coordinates is None
    assert provider.calls == []  # a country alone is never geocoded as the origin


def test_db_error_rolls_back_and_tries_next_source(cache):
    conn = FakeConn([
        (rf"{SCHEMA}\.user_locations", RuntimeError("relation does not exist")),
        (rf"{SCHEMA}\.users\b", (["user_id", "city_name", "zip_code"], [("B1", "Reston", "20190")])),
    ])
    provider = FakeProvider({"Reston, 20190": RESTON})

    origin = org_distance.resolve_beneficiary_location(
        conn, TABLES, beneficiary_id="B1", request_location=None, provider=provider, cache=cache,
    )

    assert origin.ok and origin.source == "profile_address"
    assert conn.rollbacks >= 1


def test_request_lookup_by_id_reads_beneficiary_from_request(cache):
    conn = FakeConn([
        (rf"{SCHEMA}\.requests", (["req_id", "beneficiary_id", "req_loc"], [("R1", "B9", None)])),
        (rf"{SCHEMA}\.user_locations", (["curr_loc"], [("SRID=4326;POINT(-121.978 37.7799)",)])),
    ])
    origin = org_distance.resolve_beneficiary_location(conn, TABLES, request_id="R1", cache=cache)
    assert origin.ok and origin.beneficiary_id == "B9"
    assert conn.queries[1][1] == ("B9",)


# --------------------------------------------------------------------------- #
# Organization distances
# --------------------------------------------------------------------------- #
ORIGIN_OK = org_distance.BeneficiaryLocation("ok", BENEFICIARY, "request", "B1")


def enrich(orgs, provider, cache, origin=ORIGIN_OK):
    return org_distance.add_distance_fields(orgs, origin, provider=provider, cache=cache)


def test_database_org_with_valid_address(cache):
    conn = FakeConn([states_route([("CALIFORNIA", "UNITED_STATES_OF_AMERICA")])])
    lookups = org_distance.LocationLookups(conn, TABLES)
    record = {"org_name": "Khan Academy", "street": "1200 Villa St", "city_name": "Mountain View",
              "state_id": "233.7", "zip_code": "94043"}
    address, status = org_distance.database_organization_hints(record, lookups)
    assert address == "1200 Villa St, Mountain View, California 94043, United States Of America"
    assert status is None

    org = {"name": "Khan Academy", "rating": 4.7, "collaborator": False,
           org_distance.ADDRESS_KEY: address, org_distance.LOCATION_STATUS_KEY: status}
    provider = FakeProvider({address: GOOGLEPLEX})
    [result] = enrich([org], provider, cache)

    assert result == {
        "name": "Khan Academy", "rating": 4.7, "collaborator": False,
        "distance": 25.4, "distance_unit": "miles",
        "distance_method": "straight_line", "distance_status": "ok",
    }


def test_database_org_with_missing_address_is_unknown(cache):
    address, status = org_distance.database_organization_hints({"org_name": "X", "state_id": "233.61"}, None)
    assert (address, status) == (None, "unknown_location")

    provider = FakeProvider()
    [result] = enrich([{"name": "X", org_distance.LOCATION_STATUS_KEY: status}], provider, cache)
    assert result["distance"] is None and result["distance_status"] == "unknown_location"
    assert provider.calls == []


def test_org_at_same_location_returns_zero_not_none(cache):
    provider = FakeProvider({"Same Place, Fremont, CA": BENEFICIARY})
    [result] = enrich([{"name": "Same", "location": "Same Place, Fremont, CA"}], provider, cache)
    assert result["distance"] == 0.0 and result["distance"] is not None
    assert result["distance_status"] == "ok"
    assert json.loads(json.dumps(result))["distance"] == 0


def test_genai_org_with_valid_location(cache):
    raw = {"organization_name": "Google", "location": "Mountain View, CA 94043"}
    address, status = org_distance.genai_organization_hints(raw)
    provider = FakeProvider({"Mountain View, CA 94043": GOOGLEPLEX})
    [result] = enrich([{"name": "Google", org_distance.ADDRESS_KEY: address,
                        org_distance.LOCATION_STATUS_KEY: status}], provider, cache)
    assert result["distance"] == 25.4 and result["distance_status"] == "ok"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"organization_name": "Khan Academy", "location": "Online"}, "online"),
        ({"organization_name": "Crisis Text Line", "location": "Virtual / Online only"}, "online"),
        ({"organization_name": "United Way of America", "location": "Nationwide"}, "unknown_location"),
        ({"organization_name": "Some Org", "location": "United States"}, "unknown_location"),
        ({"organization_name": "No Location"}, "unknown_location"),
    ],
)
def test_genai_org_without_usable_location(cache, raw, expected):
    address, status = org_distance.genai_organization_hints(raw)
    provider = FakeProvider()
    [result] = enrich([{"name": raw["organization_name"], org_distance.ADDRESS_KEY: address,
                        org_distance.LOCATION_STATUS_KEY: status}], provider, cache)
    assert result["distance"] is None and result["distance_status"] == expected
    assert provider.calls == []


def test_unmatched_address_is_not_found(cache):
    [result] = enrich([{"name": "Ghost", "location": "123 Imaginary Rd, Atlantis"}], FakeProvider({}), cache)
    assert result["distance"] is None and result["distance_status"] == "not_found"


def test_geocoding_failure_keeps_org_and_other_fields(cache):
    org = {"name": "Microsoft", "rating": 4.5, "collaborator": True, "location": "Redmond, WA"}
    [result] = enrich([org], FakeProvider(error=ConnectionError("provider down")), cache)
    assert result["name"] == "Microsoft" and result["rating"] == 4.5 and result["collaborator"] is True
    assert result["distance"] is None and result["distance_status"] == "error"


def test_unknown_origin_means_null_distance_for_every_org(cache):
    provider = FakeProvider({"Mountain View, CA": GOOGLEPLEX})
    origin = org_distance.BeneficiaryLocation("unknown_location")
    results = enrich(
        [{"name": "A", "location": "Mountain View, CA"}, {"name": "B", "location": "Online"}],
        provider, cache, origin=origin,
    )
    assert [(r["distance"], r["distance_status"]) for r in results] == [(None, "unknown_location"), (None, "online")]
    assert provider.calls == []


def test_apply_distances_never_raises_and_strips_private_keys(cache):
    class BrokenConn:
        def cursor(self):
            raise RuntimeError("connection closed")

        def rollback(self):
            pass

    orgs = [{"name": "A", org_distance.ADDRESS_KEY: "Mountain View, CA", org_distance.LOCATION_STATUS_KEY: None}]
    result = org_distance.apply_distances(
        orgs, BrokenConn(), beneficiary_id="B1", request_location=None,
        tables=TABLES, provider=FakeProvider(), cache=cache,
    )
    assert result == [{"name": "A", "distance": None, "distance_unit": "miles",
                       "distance_method": "straight_line", "distance_status": "error"}]
    json.dumps(result, allow_nan=False)


def test_sort_by_distance_nearest_first_unknown_last():
    orgs = [
        {"name": "United Way", "distance": None},
        {"name": "Microsoft", "distance": 18.3},
        {"name": "Same place", "distance": 0.0},
        {"name": "Khan Academy", "distance": 12.6},
        {"name": "Online org", "distance": None},
    ]
    assert [o["name"] for o in org_distance.sort_by_distance(orgs)] == [
        "Same place", "Khan Academy", "Microsoft", "United Way", "Online org",
    ]


# --------------------------------------------------------------------------- #
# End to end: lambda_handler with the real helpers.py (AWS + DB stubbed)
# --------------------------------------------------------------------------- #
@pytest.fixture
def aggregator(monkeypatch):
    """Import lambda_function/helpers with boto3, SSM and psycopg2 stubbed out."""
    conn = FakeConn()
    genai = {"payload": {"statusCode": 200, "body": {"organizations": []}}, "error": None}

    class FakeLambdaClient:
        def invoke(self, **kwargs):
            if genai["error"]:
                raise genai["error"]
            return {"Payload": io.BytesIO(json.dumps(genai["payload"]).encode())}

    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: FakeLambdaClient()
    boto3.exceptions = types.SimpleNamespace(Boto3Error=type("Boto3Error", (Exception,), {}))

    params = types.ModuleType("aws_lambda_powertools.utilities.parameters")
    params.get_parameter = lambda *args, **kwargs: json.dumps(
        {"DATABASE NAME": SCHEMA, "HOST": "h", "USERNAME": "u", "PASSWORD": "p", "PORT": 5432}
    )
    utilities = types.ModuleType("aws_lambda_powertools.utilities")
    utilities.parameters = params
    powertools = types.ModuleType("aws_lambda_powertools")
    powertools.utilities = utilities

    psycopg2 = types.ModuleType("psycopg2")
    psycopg2.DatabaseError = type("DatabaseError", (Exception,), {})
    psycopg2.connect = lambda **kwargs: conn

    for name, module in {
        "boto3": boto3,
        "aws_lambda_powertools": powertools,
        "aws_lambda_powertools.utilities": utilities,
        "aws_lambda_powertools.utilities.parameters": params,
        "psycopg2": psycopg2,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    for name in ("helpers", "lambda_function"):
        sys.modules.pop(name, None)

    provider = FakeProvider({
        "500 Castro St, Mountain View, California 94041, United States Of America": GOOGLEPLEX,
    })
    geocoding.set_default_provider(provider)

    import lambda_function  # noqa: WPS433

    importlib.reload(lambda_function)
    yield types.SimpleNamespace(handler=lambda_function.lambda_handler, conn=conn, genai=genai, provider=provider)
    for name in ("helpers", "lambda_function"):
        sys.modules.pop(name, None)


def seed_aggregator_db(conn, req_loc):
    user = {"user_id": "B1", "first_name": "Ben", "last_name": "F", "addr_ln1": None, "addr_ln2": None,
            "addr_ln3": None, "city_name": "Mountain View", "state_id": "233.7", "country_id": 233,
            "zip_code": "94041", "primary_phone_number": "1", "primary_email_address": "b@x.org"}
    org_columns = ["org_id", "org_name", "street", "city_name", "state_id", "zip_code", "org_type",
                   "org_size", "org_rating", "is_collaborator", "web_url", "phone", "email", "mission"]
    orgs = [
        ("O1", "Castro Food Bank", "500 Castro St", "Mountain View", "233.7", "94041",
         "Non-Profit", "Small", 5, True, "https://a.org", "111", "a@a.org", "Food"),
        ("O2", "No Address Org", None, None, None, None, "Non-Profit", "Large", 3, False,
         "https://b.org", "222", "b@b.org", "Food"),
    ]
    conn.routes = [
        (r"user_org_map", (["user_id"], [])),
        (r"org_skills", (org_columns, orgs)),
        (rf"{SCHEMA}\.requests", (["req_id", "beneficiary_id", "req_cat_id", "req_subj", "req_desc", "req_loc"],
                                  [("R1", "B1", "1.1", "Need food", "Groceries please", req_loc)])),
        (rf"{SCHEMA}\.help_categories", (["cat_id", "cat_name"], [("1.1", "FOOD_ASSISTANCE")])),
        states_route([("CALIFORNIA", "UNITED_STATES_OF_AMERICA")]),
        (rf"{SCHEMA}\.user_locations", (["curr_loc"], [])),
        (rf"{SCHEMA}\.users\b", (list(user), [tuple(user.values())])),
    ]


def test_handler_returns_distance_for_db_and_genai_orgs(aggregator):
    seed_aggregator_db(aggregator.conn, req_loc="longitude:-121.9780,latitude:37.7799")
    aggregator.genai["payload"] = {"statusCode": 200, "body": {"organizations": [
        {"organization_name": "Khan Academy", "location": "Online", "web_url": "https://khanacademy.org"},
        {"organization_name": "Googleplex Helpers", "location": "latitude:37.4220,longitude:-122.0841"},
    ]}}

    response = aggregator.handler({"body": json.dumps({"request_id": "R1", "beneficiary_id": "B1"})}, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    by_name = {org["name"]: org for org in body}
    assert by_name["Castro Food Bank"]["distance_status"] == "ok"
    assert by_name["Castro Food Bank"]["distance"] == 25.4
    assert by_name["Castro Food Bank"]["rating"] == 5 and by_name["Castro Food Bank"]["collaborator"] is True
    assert (by_name["No Address Org"]["distance"], by_name["No Address Org"]["distance_status"]) == (None, "unknown_location")
    assert (by_name["Khan Academy"]["distance"], by_name["Khan Academy"]["distance_status"]) == (None, "online")
    assert by_name["Googleplex Helpers"]["distance"] == 25.4
    for org in body:
        assert org["distance_unit"] == "miles" and org["distance_method"] == "straight_line"
        assert not set(org) & set(org_distance.PRIVATE_KEYS)
    # Request coordinates were used, so user_locations was never queried.
    assert not aggregator.conn.ran(rf"{SCHEMA}\.user_locations")


def test_handler_sorts_by_distance_and_survives_genai_failure(aggregator):
    seed_aggregator_db(aggregator.conn, req_loc="longitude:-121.9780,latitude:37.7799")
    aggregator.genai["error"] = RuntimeError("GenAI timed out")

    response = aggregator.handler(
        {"body": json.dumps({"request_id": "R1", "beneficiary_id": "B1", "sort_by": "distance"})}, None
    )

    assert response["statusCode"] == 200
    names = [org["name"] for org in json.loads(response["body"])]
    assert names == ["Castro Food Bank", "No Address Org"]


def test_handler_without_any_beneficiary_location(aggregator):
    seed_aggregator_db(aggregator.conn, req_loc=None)
    aggregator.conn.routes = [
        route for route in aggregator.conn.routes if not route[0].startswith(rf"{SCHEMA}\.users")
    ] + [(rf"{SCHEMA}\.users\b", (["user_id", "city_name"], [("B1", None)]))]

    response = aggregator.handler({"body": json.dumps({"request_id": "R1", "beneficiary_id": "B1"})}, None)

    assert response["statusCode"] == 200
    for org in json.loads(response["body"]):
        assert org["distance"] is None
        assert org["distance_status"] == "unknown_location"
