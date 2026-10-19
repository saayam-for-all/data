"""
Tests for Issue #433 – distance calculation in saayam-org-aggregator.

Run (PowerShell, from the repo root):
    $env:PYTHONPATH="data-engineering\\src\\saayam-org-aggregator"
    python -m pytest -q data-engineering\\tests\\test_org_distance.py

AWS (SSM, Lambda) and the database are stubbed, so no credentials are needed.
"""
import json
import sys
import types

import pandas as pd
import pytest

import org_distance as od
from org_distance import (
    BeneficiaryLocation, CoordinateCache, GeocodeResult, Geocoder,
    add_distances, beneficiary_from_body, geocode_address, haversine_miles,
    parse_coordinates, resolve_beneficiary_location, sort_by_distance,
)

BENEF = (37.7799, -121.9780)
KHAN = (37.4220, -122.0841)


# ---------------------------------------------------------------- fakes

class FakeGeocoder(Geocoder):
    def __init__(self, table=None, exc=None):
        self.table, self.exc, self.calls = table or {}, exc, 0

    def lookup(self, address):
        self.calls += 1
        if self.exc:
            raise self.exc
        coords = self.table.get(address)
        return GeocodeResult(coords, "ok" if coords else "not_found")


class FakeCursor:
    """Returns the canned result whose key appears in the SQL text."""

    def __init__(self, conn):
        self.conn, self.result = conn, None

    def execute(self, sql, params=None):
        for key, value in self.conn.rows.items():
            if key in sql:
                if isinstance(value, Exception):
                    raise value
                self.result = value
                return
        self.result = None

    def fetchone(self):
        return self.result[0] if isinstance(self.result, list) else self.result

    def fetchall(self):
        return self.result if isinstance(self.result, list) else []

    def close(self):
        pass


class FakeConn:
    def __init__(self, rows=None):
        self.rows, self.rollbacks = rows or {}, 0

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture(autouse=True)
def clear_cache():
    CoordinateCache._memory.clear()


def ok_benef():
    return BeneficiaryLocation(BENEF, "request", "ok")


# ---------------------------------------------------------------- parsing & math

@pytest.mark.parametrize("raw", [
    "longitude:-121.9780,latitude:37.7799",
    "POINT(-121.9780 37.7799)",
    '{"latitude": 37.7799, "longitude": -121.9780}',
    {"lat": 37.7799, "lng": -121.9780},
])
def test_parse_formats(raw):
    assert parse_coordinates(raw) == pytest.approx(BENEF)


@pytest.mark.parametrize("raw", [None, "", float("nan"), "United States", "San Jose",
                                 "lat:999,lon:0", "garbage"])
def test_parse_invalid(raw):
    assert parse_coordinates(raw) is None


def test_issue_example_distance():
    assert round(haversine_miles(BENEF, KHAN), 1) == pytest.approx(25.4, abs=0.2)


# ---------------------------------------------------------------- beneficiary chain

def test_request_coords_used_first():
    conn = FakeConn({"requests": ("longitude:-121.9780,latitude:37.7799", 7)})
    loc = resolve_beneficiary_location(conn, 1)
    assert loc.source == "request" and loc.coords == pytest.approx(BENEF)


def test_falls_back_to_user_locations():
    conn = FakeConn({"requests": (None, 7), "user_locations": ("POINT(-112.07 33.45)",)})
    assert resolve_beneficiary_location(conn, 1).source == "user_location"


def test_falls_back_to_profile_address():
    addr_row = ("1 Main St", "Tempe", "Arizona", "85281", "United States")
    conn = FakeConn({"requests": (None, 7), "users u": addr_row})
    geo = FakeGeocoder({"1 Main St, Tempe, Arizona, 85281, United States": (33.42, -111.94)})
    loc = resolve_beneficiary_location(conn, 1, geocoder=geo)
    assert loc.source == "profile_address" and loc.coords == (33.42, -111.94)


def test_country_only_profile_is_not_used():
    conn = FakeConn({"requests": (None, 7), "users u": (None, None, None, None, "United States")})
    geo = FakeGeocoder({"United States": (39.8, -98.6)})
    loc = resolve_beneficiary_location(conn, 1, geocoder=geo)
    assert loc.coords is None and loc.status == "unknown_location" and geo.calls == 0


def test_no_beneficiary_location():
    loc = resolve_beneficiary_location(FakeConn(), 1)
    assert loc.coords is None and loc.status == "unknown_location"


def test_failed_query_rolls_back_shared_connection():
    conn = FakeConn({"requests": RuntimeError("column does not exist")})
    resolve_beneficiary_location(conn, 1)
    assert conn.rollbacks == 1


def test_body_coordinates_win_and_city_name_is_not_used():
    assert beneficiary_from_body({"latitude": 37.7799, "longitude": -121.978}, None).coords \
        == pytest.approx(BENEF)
    assert beneficiary_from_body({"req_loc": "longitude:-121.978,latitude:37.7799"}, None).source == "request"
    plain = beneficiary_from_body({"location": "San Jose", "category": "Food"}, FakeConn())
    assert plain.coords is None and plain.status == "unknown_location"


# ---------------------------------------------------------------- org distance

def test_db_org_valid_address_uses_state_and_country_names():
    rows = [("org-1", "1200 Villa St", "Mountain View", "California", "94043", "United States")]
    conn = FakeConn({"organizations": rows})
    geo = FakeGeocoder({"1200 Villa St, Mountain View, California, 94043, United States": KHAN})
    [out] = od.distance_fields_for_db_orgs(
        [{"org_id": "org-1", "org_name": "Khan", "state_id": "CA"}], ok_benef(), conn, geo)
    assert out == {"distance": pytest.approx(25.4, abs=0.2), "distance_unit": "miles",
                   "distance_method": "straight_line", "distance_status": "ok"}


def test_db_org_address_lookup_failure_falls_back_to_row():
    conn = FakeConn({"organizations": RuntimeError("db down")})
    geo = FakeGeocoder({"1200 Villa St, Mountain View, 94043": KHAN})
    [out] = od.distance_fields_for_db_orgs(
        [{"org_id": "org-1", "street": "1200 Villa St", "city_name": "Mountain View",
          "zip_code": "94043"}], ok_benef(), conn, geo)
    assert out["distance_status"] == "ok" and conn.rollbacks == 1


def test_same_location_is_zero_not_none():
    geo = FakeGeocoder({"Here": BENEF})
    [out] = add_distances([{"name": "X", "location": "Here"}], ok_benef(), geo)
    assert out["distance"] == 0 and out["distance"] is not None and out["distance_status"] == "ok"


def test_missing_org_address():
    [out] = add_distances([{"name": "X", "location": float("nan")}], ok_benef(), FakeGeocoder())
    assert out["distance"] is None and out["distance_status"] == "unknown_location"


def test_genai_org_location_and_unmatched():
    geo = FakeGeocoder({"Mountain View, CA 94043": (37.42, -122.08)})
    a, b = od.distance_fields_for_ai_orgs(
        [{"organization_name": "A", "location": "Mountain View, CA 94043"},
         {"organization_name": "B", "location": "Nowhere Land"}], ok_benef(), geo)
    assert a["distance_status"] == "ok"
    assert b["distance"] is None and b["distance_status"] == "not_found"


def test_online_org():
    [out] = add_distances([{"name": "X", "location": "Online"}], ok_benef(), FakeGeocoder())
    assert out["distance_status"] == "online" and out["distance"] is None


def test_unknown_beneficiary_still_returns_orgs():
    benef = BeneficiaryLocation(None, "none", "unknown_location")
    out = add_distances([{"name": "A", "location": "Tempe"}], benef, FakeGeocoder())
    assert len(out) == 1 and out[0]["distance"] is None
    assert out[0]["distance_status"] == "unknown_location"


def test_geocoder_failure_and_timeout():
    [err] = add_distances([{"name": "A", "location": "Tempe"}], ok_benef(),
                          FakeGeocoder(exc=RuntimeError("boom")))
    assert err["distance_status"] == "error" and err["distance"] is None
    [slow] = add_distances([{"name": "A", "location": "Tempe"}], ok_benef(),
                           FakeGeocoder(exc=TimeoutError()))
    assert slow["distance_status"] == "deferred"


def test_default_provider_defers():
    [out] = add_distances([{"name": "A", "location": "Tempe"}], ok_benef())
    assert out["distance_status"] == "deferred" and out["distance"] is None


def test_cache_reused():
    geo = FakeGeocoder({"Tempe, AZ": (33.42, -111.94)})
    geocode_address("Tempe, AZ", geo)
    geocode_address("  tempe,   az ", geo)
    assert geo.calls == 1


def test_failures_not_cached():
    geo = FakeGeocoder(exc=RuntimeError())
    geocode_address("Tempe", geo)
    geocode_address("Tempe", geo)
    assert geo.calls == 2


def test_sort_nearest_then_na():
    orgs = [{"name": "c", "distance": None}, {"name": "b", "distance": 12.6},
            {"name": "z", "distance": 0}, {"name": "a", "distance": 4.8}]
    assert [o["name"] for o in sort_by_distance(orgs)] == ["z", "a", "b", "c"]


# ---------------------------------------------------------------- full Lambda handler

@pytest.fixture
def aggregator(monkeypatch):
    """Import helpers + lambda_function with SSM, boto3 and pg8000 stubbed."""
    db = FakeConn()

    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *a, **k: object()
    boto3.exceptions = types.SimpleNamespace(Boto3Error=type("Boto3Error", (Exception,), {}))
    pg8000 = types.ModuleType("pg8000")
    pg8000.connect = lambda **k: db
    pg8000.DatabaseError = type("DatabaseError", (Exception,), {})
    params = types.ModuleType("aws_lambda_powertools.utilities.parameters")
    params.get_parameter = lambda *a, **k: json.dumps(
        {"DATABASE NAME": "virginia_dev_saayam_rdbms", "HOST": "h", "USERNAME": "u",
         "PASSWORD": "p", "PORT": 5432})
    utilities = types.ModuleType("aws_lambda_powertools.utilities")
    utilities.parameters = params
    for name, mod in {"boto3": boto3, "pg8000": pg8000,
                      "aws_lambda_powertools": types.ModuleType("aws_lambda_powertools"),
                      "aws_lambda_powertools.utilities": utilities,
                      "aws_lambda_powertools.utilities.parameters": params}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    for name in ("helpers", "lambda_function"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    import lambda_function

    geo = FakeGeocoder({
        "1200 Villa St, Mountain View, California, 94043, United States": KHAN,
        "Mountain View, CA 94043": (37.42, -122.08),
    })
    monkeypatch.setitem(od.GEOCODER_REGISTRY, "fake", lambda: geo)
    monkeypatch.setenv("GEOCODER_PROVIDER", "fake")

    db_orgs = pd.DataFrame([{
        "org_id": "org-1", "org_name": "Khan Academy", "street": "1200 Villa St",
        "city_name": "Mountain View", "state_id": "CA", "zip_code": "94043",
        "phone": "1", "email": "e", "web_url": "w", "mission": "Education",
        "source": "db", "db_or_ai": "db"}])
    ai_orgs = pd.DataFrame([
        {"organization_name": "AI Org", "location": "Mountain View, CA 94043", "contact": "2",
         "email": "e", "web_url": "w", "mission": "Education", "source": "ai", "db_or_ai": "ai"},
        {"organization_name": "No Location Org", "location": None, "contact": "3",
         "email": "e", "web_url": "w", "mission": "Education", "source": "ai", "db_or_ai": "ai"},
    ])
    monkeypatch.setattr(lambda_function, "get_orgs_from_db", lambda *a: db_orgs)
    monkeypatch.setattr(lambda_function, "get_ai_orgs", lambda *a: ai_orgs)
    db.rows = {"organizations": [("org-1", "1200 Villa St", "Mountain View", "California",
                                  "94043", "United States")]}
    return lambda_function, db


def _call(handler, body):
    resp = handler.lambda_handler({"body": json.dumps(body)}, None)
    assert resp["statusCode"] == 200, resp
    return resp


def test_handler_returns_distance_for_every_org(aggregator):
    handler, _ = aggregator
    resp = _call(handler, {"subject": "s", "description": "d", "location": "Mountain View",
                           "category": "Education", "latitude": 37.7799, "longitude": -121.978})
    assert "NaN" not in resp["body"]  # missing distance must be JSON null
    orgs = {o["name"]: o for o in json.loads(resp["body"])}
    assert set(orgs) == {"Khan Academy", "AI Org", "No Location Org"}
    assert orgs["Khan Academy"]["distance"] == pytest.approx(25.4, abs=0.2)
    assert orgs["Khan Academy"]["distance_status"] == "ok"
    assert orgs["AI Org"]["distance_status"] == "ok"
    assert orgs["No Location Org"]["distance"] is None
    assert orgs["No Location Org"]["distance_status"] == "unknown_location"
    for o in orgs.values():
        assert o["distance_unit"] == "miles" and o["distance_method"] == "straight_line"
        assert o["email"] == "e" and o["web_url"] == "w"  # existing fields unchanged


def test_handler_uses_request_id_lookup(aggregator):
    handler, db = aggregator
    db.rows["requests"] = ("longitude:-121.9780,latitude:37.7799", "ben-1")
    orgs = json.loads(_call(handler, {"location": "Mountain View", "category": "Education",
                                      "request_id": "req-1"})["body"])
    assert {o["distance_status"] for o in orgs} == {"ok", "unknown_location"}


def test_handler_without_beneficiary_still_returns_orgs(aggregator):
    handler, _ = aggregator
    orgs = json.loads(_call(handler, {"location": "Mountain View", "category": "Education"})["body"])
    assert len(orgs) == 3
    assert all(o["distance"] is None and o["distance_status"] == "unknown_location" for o in orgs)


def test_handler_survives_distance_db_errors(aggregator):
    handler, db = aggregator
    db.rows = {"requests": RuntimeError("relation does not exist"),
               "organizations": RuntimeError("db down")}
    orgs = json.loads(_call(handler, {"location": "Mountain View", "category": "Education",
                                      "request_id": "req-1"})["body"])
    assert len(orgs) == 3 and db.rollbacks >= 1
