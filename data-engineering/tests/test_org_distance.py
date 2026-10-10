"""Unit tests for the aggregator's distance logic (no AWS/DB needed)."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "saayam-org-aggregator"))

import distance as d


class FakeConn:
    def __init__(self, rows):
        self.rows, self.cur_sql = rows, []

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.cur_sql.append(sql)
        self._row = next((r for k, r in self.rows if k in sql), None)

    def fetchone(self):
        return self._row


def _geocoder(table):
    def fn(addr):
        if addr not in table:
            raise d.GeocodeNotFound(addr)
        return table[addr]
    return fn


def test_parse_coordinates():
    assert d.parse_coordinates("longitude:-121.9780,latitude:37.7799") == (37.7799, -121.978)
    assert d.parse_coordinates("SRID=4326;POINT(-122.08 37.42)") == (37.42, -122.08)
    assert d.parse_coordinates("Suffolk, VA") is None
    assert d.parse_coordinates(None) is None


def test_haversine_example_and_zero():
    assert 25 < d.haversine_miles((37.7799, -121.9780), (37.4220, -122.0841)) < 27
    assert d.haversine_miles((1, 1), (1, 1)) == 0


def test_beneficiary_order_request_then_user_location_then_profile():
    os.environ["GEOCODER_PROVIDER"] = "t"
    d.register_geocoder("t", _geocoder({"1 Main St, Reston, Virginia, 20190, USA": (38.9, -77.3)}))
    req = [("FROM s.requests", ("longitude:-121.9,latitude:37.7", "U1"))]
    assert d.get_beneficiary_coordinates(FakeConn(req), "s", "R1") == (37.7, -121.9)
    ul = [("FROM s.requests", ("Suffolk, VA", "U1")), ("user_locations", ("POINT(-77 38)",))]
    assert d.get_beneficiary_coordinates(FakeConn(ul), "s", "R1") == (38, -77)
    prof = [("FROM s.requests", (None, "U1")),
            ("FROM s.users", ("1 Main St", "Reston", "Virginia", "20190", "USA"))]
    assert d.get_beneficiary_coordinates(FakeConn(prof), "s", "R1") == (38.9, -77.3)
    assert d.get_beneficiary_coordinates(FakeConn([("FROM s.requests", (None, "U1"))]), "s", "R1") is None


def test_statuses_cache_and_zero():
    os.environ["GEOCODER_PROVIDER"] = "t"
    calls = []
    table = {"A": (10.0, 10.0), "ZERO": (5.0, 5.0)}
    inner = _geocoder(table)
    d.register_geocoder("t", lambda a: (calls.append(a), inner(a))[1])
    cache = d.CoordinateCache()
    ben = (5.0, 5.0)
    out = d.add_distances(
        [{"a": "A"}, {"a": "ZERO"}, {"a": "A"}, {"a": "nowhere"}, {"a": None}, {"a": "Online"}],
        ben, cache, lambda o: o["a"])
    got = [(o["distance"], o["distance_status"]) for o in out]
    assert got[0][1] == "ok" and got[0][0] > 0
    assert got[1] == (0.0, "ok")
    assert got[2] == got[0]
    assert got[3] == (None, "not_found")
    assert got[4] == (None, "unknown_location")
    assert got[5] == (None, "online")
    assert calls.count("A") == 1  # cached on second use
    assert out[0]["distance_unit"] == "miles" and out[0]["distance_method"] == "straight_line"


def test_no_beneficiary_no_provider_and_error():
    cache = d.CoordinateCache()
    assert d.compute_org_distance(None, "A", cache, [5])["distance_status"] == "unknown_location"
    os.environ.pop("GEOCODER_PROVIDER", None)
    assert d.compute_org_distance((1, 1), "A", cache, [5])["distance_status"] == "deferred"
    os.environ["GEOCODER_PROVIDER"] = "boom"
    d.register_geocoder("boom", lambda a: 1 / 0)
    assert d.compute_org_distance((1, 1), "A", cache, [5])["distance_status"] == "error"
    assert d.compute_org_distance((1, 1), "B", cache, [0])["distance_status"] == "deferred"


def test_sort_nulls_last():
    orgs = [{"n": 1, "distance": None}, {"n": 2, "distance": 9.0}, {"n": 3, "distance": 0.0}]
    assert [o["n"] for o in d.sort_by_distance(orgs)] == [3, 2, 1]
