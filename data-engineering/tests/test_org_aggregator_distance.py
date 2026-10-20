"""Unit tests for distance calculation in saayam-org-aggregator (issue #433).

All DB and geocoder calls are mocked so these run fully offline.
Run with:  pytest data-engineering/tests/test_org_aggregator_distance.py -v
"""
import json
import math
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub heavy AWS / DB imports so the module loads without real credentials
# ---------------------------------------------------------------------------

aws_powertools_stub = types.ModuleType("aws_lambda_powertools")
aws_powertools_stub.utilities = types.ModuleType("aws_lambda_powertools.utilities")
aws_powertools_stub.utilities.parameters = MagicMock()
aws_powertools_stub.utilities.parameters.get_parameter = MagicMock(
    return_value='{"DATABASE NAME":"testdb","HOST":"localhost","USERNAME":"u","PASSWORD":"p","PORT":5432}'
)
sys.modules.setdefault("aws_lambda_powertools", aws_powertools_stub)
sys.modules.setdefault("aws_lambda_powertools.utilities", aws_powertools_stub.utilities)
sys.modules.setdefault(
    "aws_lambda_powertools.utilities.parameters",
    aws_powertools_stub.utilities.parameters,
)

boto3_stub = types.ModuleType("boto3")
boto3_stub.client = MagicMock(return_value=MagicMock())
boto3_stub.exceptions = types.ModuleType("boto3.exceptions")
boto3_stub.exceptions.Boto3Error = Exception
sys.modules.setdefault("boto3", boto3_stub)
sys.modules.setdefault("boto3.exceptions", boto3_stub.exceptions)

pg8000_stub = types.ModuleType("pg8000")
pg8000_stub.connect = MagicMock(return_value=MagicMock())
pg8000_stub.DatabaseError = Exception
sys.modules.setdefault("pg8000", pg8000_stub)

sys.path.insert(0, "src/saayam-org-aggregator")
import helpers  # noqa: E402


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_cursor(fetchone=None, fetchall=None):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = fetchall or []
    return cur


def _patch_geocoder(coords_map: dict):
    """Return a geocoder class whose lookup() uses coords_map (address -> coords or None)."""
    class FakeGeocoder(helpers._GeocoderBase):
        def lookup(self, address):
            return coords_map.get(address.strip().lower())
    return FakeGeocoder


# ===========================================================================
# _parse_req_loc
# ===========================================================================
class TestParseReqLoc(unittest.TestCase):
    def test_longitude_latitude_key_value(self):
        result = helpers._parse_req_loc("longitude:-121.9780,latitude:37.7799")
        self.assertAlmostEqual(result[0], 37.7799)
        self.assertAlmostEqual(result[1], -121.9780)

    def test_latitude_longitude_key_value_reversed_order(self):
        result = helpers._parse_req_loc("latitude:37.7799,longitude:-121.9780")
        self.assertAlmostEqual(result[0], 37.7799)
        self.assertAlmostEqual(result[1], -121.9780)

    def test_wkt_point(self):
        result = helpers._parse_req_loc("POINT(-122.0841 37.4220)")
        self.assertAlmostEqual(result[0], 37.4220)
        self.assertAlmostEqual(result[1], -122.0841)

    def test_none_input(self):
        self.assertIsNone(helpers._parse_req_loc(None))

    def test_empty_string(self):
        self.assertIsNone(helpers._parse_req_loc(""))

    def test_unrecognised_format(self):
        self.assertIsNone(helpers._parse_req_loc("Mountain View, CA"))


# ===========================================================================
# geocode_address  (pluggable provider + caching)
# ===========================================================================
class TestGeocodeAddress(unittest.TestCase):

    def setUp(self):
        helpers._geocode_cache.clear()

    def _register_fake(self, coords_map):
        FakeGeocoder = _patch_geocoder(coords_map)
        helpers.GEOCODER_REGISTRY["_test"] = FakeGeocoder
        return lambda: helpers.GEOCODER_REGISTRY.pop("_test", None)

    def test_returns_coords_on_success(self):
        cleanup = self._register_fake({"1600 amphitheatre pkwy, mountain view, ca": (37.4220, -122.0841)})
        try:
            with patch.dict("os.environ", {"GEOCODER_PROVIDER": "_test"}):
                coords, status = helpers.geocode_address("1600 Amphitheatre Pkwy, Mountain View, CA")
            self.assertEqual(coords, (37.4220, -122.0841))
            self.assertEqual(status, "ok")
        finally:
            cleanup()

    def test_returns_not_found_when_no_result(self):
        cleanup = self._register_fake({})
        try:
            with patch.dict("os.environ", {"GEOCODER_PROVIDER": "_test"}):
                coords, status = helpers.geocode_address("nonexistent place xyz")
            self.assertIsNone(coords)
            self.assertEqual(status, "not_found")
        finally:
            cleanup()

    def test_returns_deferred_when_no_provider_configured(self):
        with patch.dict("os.environ", {"GEOCODER_PROVIDER": ""}):
            coords, status = helpers.geocode_address("Seattle, WA")
        self.assertIsNone(coords)
        self.assertEqual(status, "deferred")

    def test_deferred_not_cached(self):
        """deferred results are not cached so they are retried next invocation."""
        with patch.dict("os.environ", {"GEOCODER_PROVIDER": ""}):
            helpers.geocode_address("Seattle, WA")
        self.assertNotIn("seattle, wa", helpers._geocode_cache)

    def test_returns_error_on_exception(self):
        class BrokenGeocoder(helpers._GeocoderBase):
            def lookup(self, address):
                raise RuntimeError("network down")
        helpers.GEOCODER_REGISTRY["_broken"] = BrokenGeocoder
        try:
            with patch.dict("os.environ", {"GEOCODER_PROVIDER": "_broken"}):
                coords, status = helpers.geocode_address("Seattle, WA")
            self.assertIsNone(coords)
            self.assertEqual(status, "error")
        finally:
            helpers.GEOCODER_REGISTRY.pop("_broken", None)

    def test_cache_hit_avoids_second_lookup(self):
        call_count = [0]
        class CountingGeocoder(helpers._GeocoderBase):
            def lookup(self, address):
                call_count[0] += 1
                return (37.4220, -122.0841)
        helpers.GEOCODER_REGISTRY["_count"] = CountingGeocoder
        try:
            with patch.dict("os.environ", {"GEOCODER_PROVIDER": "_count"}):
                helpers.geocode_address("Mountain View, CA 94043")
                helpers.geocode_address("Mountain View, CA 94043")
            self.assertEqual(call_count[0], 1)
        finally:
            helpers.GEOCODER_REGISTRY.pop("_count", None)

    def test_cache_is_case_insensitive(self):
        call_count = [0]
        class CountingGeocoder(helpers._GeocoderBase):
            def lookup(self, address):
                call_count[0] += 1
                return (40.7128, -74.0060)
        helpers.GEOCODER_REGISTRY["_count2"] = CountingGeocoder
        try:
            with patch.dict("os.environ", {"GEOCODER_PROVIDER": "_count2"}):
                helpers.geocode_address("New York, NY")
                helpers.geocode_address("new york, ny")
            self.assertEqual(call_count[0], 1)
        finally:
            helpers.GEOCODER_REGISTRY.pop("_count2", None)

    def test_returns_none_for_empty_string(self):
        coords, status = helpers.geocode_address("")
        self.assertIsNone(coords)

    def test_returns_none_for_none(self):
        coords, status = helpers.geocode_address(None)
        self.assertIsNone(coords)

    def test_timeout_returns_deferred_not_cached(self):
        class TimeoutGeocoder(helpers._GeocoderBase):
            def lookup(self, address):
                raise TimeoutError()
        helpers.GEOCODER_REGISTRY["_timeout"] = TimeoutGeocoder
        try:
            with patch.dict("os.environ", {"GEOCODER_PROVIDER": "_timeout"}):
                coords, status = helpers.geocode_address("Seattle, WA")
            self.assertEqual(status, "deferred")
            self.assertNotIn("seattle, wa", helpers._geocode_cache)
        finally:
            helpers.GEOCODER_REGISTRY.pop("_timeout", None)


# ===========================================================================
# calculate_distance  (haversine)
# ===========================================================================
class TestCalculateDistance(unittest.TestCase):
    def test_known_distance_issue_example(self):
        # Issue example: 37.7799,-121.9780 -> 37.4220,-122.0841 ~ 25.5 mi
        dist = helpers.calculate_distance((37.7799, -121.9780), (37.4220, -122.0841))
        self.assertAlmostEqual(dist, 25.5, delta=1.0)

    def test_same_location_is_zero(self):
        dist = helpers.calculate_distance((37.7799, -121.9780), (37.7799, -121.9780))
        self.assertEqual(dist, 0.0)

    def test_returns_float(self):
        dist = helpers.calculate_distance((0.0, 0.0), (1.0, 1.0))
        self.assertIsInstance(dist, float)


# ===========================================================================
# _nan_to_none
# ===========================================================================
class TestNanToNone(unittest.TestCase):
    def test_nan_becomes_none(self):
        self.assertIsNone(helpers._nan_to_none(float("nan")))

    def test_regular_float_unchanged(self):
        self.assertEqual(helpers._nan_to_none(12.6), 12.6)

    def test_zero_unchanged(self):
        self.assertEqual(helpers._nan_to_none(0.0), 0.0)

    def test_none_unchanged(self):
        self.assertIsNone(helpers._nan_to_none(None))

    def test_string_unchanged(self):
        self.assertEqual(helpers._nan_to_none("hello"), "hello")


# ===========================================================================
# _is_online_location
# ===========================================================================
class TestIsOnlineLocation(unittest.TestCase):
    def test_online_keyword(self):
        self.assertTrue(helpers._is_online_location("Online"))
        self.assertTrue(helpers._is_online_location("NATIONWIDE"))
        self.assertTrue(helpers._is_online_location("virtual"))

    def test_regular_location(self):
        self.assertFalse(helpers._is_online_location("Seattle, WA"))
        self.assertFalse(helpers._is_online_location("Mountain View, CA"))

    def test_none_and_empty(self):
        self.assertFalse(helpers._is_online_location(None))
        self.assertFalse(helpers._is_online_location(""))


# ===========================================================================
# attach_distance
# ===========================================================================
class TestAttachDistance(unittest.TestCase):

    def setUp(self):
        helpers._geocode_cache.clear()

    def _make_org(self, **kwargs):
        base = {
            "name": "Test Org",
            "location": "Mountain View, CA",
            "street": "1600 Amphitheatre Pkwy",
            "state_code": "CA",
            "zip_code": "94043",
        }
        base.update(kwargs)
        return base

    def test_unknown_beneficiary_location(self):
        org = self._make_org()
        result = helpers.attach_distance(org, None)
        self.assertIsNone(result["distance"])
        self.assertEqual(result["distance_status"], "unknown_location")
        self.assertEqual(result["distance_unit"], "miles")
        self.assertEqual(result["distance_method"], "straight_line")

    def test_org_address_not_found(self):
        org = {"name": "No Location Org", "location": None, "street": None,
               "state_code": None, "zip_code": None}
        with patch.object(helpers, "geocode_address", return_value=(None, "not_found")):
            result = helpers.attach_distance(org, (37.7799, -121.9780))
        self.assertIsNone(result["distance"])
        self.assertEqual(result["distance_status"], "not_found")

    def test_org_is_online(self):
        org = self._make_org(location="Online", street=None, state_code=None, zip_code=None)
        result = helpers.attach_distance(org, (37.7799, -121.9780))
        self.assertIsNone(result["distance"])
        self.assertEqual(result["distance_status"], "online")

    def test_deferred_when_no_provider(self):
        org = self._make_org()
        with patch.dict("os.environ", {"GEOCODER_PROVIDER": ""}):
            result = helpers.attach_distance(org, (37.7799, -121.9780))
        self.assertIsNone(result["distance"])
        self.assertEqual(result["distance_status"], "deferred")

    def test_happy_path(self):
        org = self._make_org()
        mock_org_coords = (37.4220, -122.0841)
        with patch.object(helpers, "_resolve_org_coords", return_value=(mock_org_coords, "ok")):
            result = helpers.attach_distance(org, (37.7799, -121.9780))
        self.assertIsNotNone(result["distance"])
        self.assertGreater(result["distance"], 0)
        self.assertEqual(result["distance_status"], "ok")

    def test_zero_distance_is_not_null(self):
        """Org at same location as beneficiary → 0.0, not None."""
        org = self._make_org()
        same_coords = (37.7799, -121.9780)
        with patch.object(helpers, "_resolve_org_coords", return_value=(same_coords, "ok")):
            result = helpers.attach_distance(org, same_coords)
        self.assertEqual(result["distance"], 0.0)
        self.assertIsNotNone(result["distance"])
        self.assertEqual(result["distance_status"], "ok")

    def test_error_status_on_exception(self):
        org = self._make_org()
        with patch.object(helpers, "_resolve_org_coords", side_effect=RuntimeError("boom")):
            result = helpers.attach_distance(org, (37.7799, -121.9780))
        self.assertIsNone(result["distance"])
        self.assertEqual(result["distance_status"], "error")

    def test_org_always_returned_when_distance_fails(self):
        org = self._make_org(name="Resilient Org")
        with patch.object(helpers, "_resolve_org_coords", return_value=(None, "not_found")):
            result = helpers.attach_distance(org, (37.7799, -121.9780))
        self.assertEqual(result["name"], "Resilient Org")
        self.assertIn("distance", result)
        self.assertIn("distance_status", result)

    def test_nan_in_org_fields_sanitized_to_none(self):
        """NaN in org fields must become None so json.dumps produces valid JSON."""
        org = self._make_org(rating=float("nan"))
        result = helpers.attach_distance(org, None)
        self.assertIsNone(result["rating"])
        # Verify the result is actually serializable
        serialized = json.dumps(result)
        self.assertNotIn("NaN", serialized)


# ===========================================================================
# get_beneficiary_location  (DB mocked)
# ===========================================================================
class TestGetBeneficiaryLocation(unittest.TestCase):
    def _patch_conn(self, cursor):
        helpers._db_conn.cursor = MagicMock(return_value=cursor)

    def test_uses_req_loc_when_available(self):
        cursor = _make_cursor(fetchone=("longitude:-121.9780,latitude:37.7799",))
        self._patch_conn(cursor)
        coords, status = helpers.get_beneficiary_location("user-123")
        self.assertEqual(status, "req_loc")
        self.assertAlmostEqual(coords[0], 37.7799)

    def test_falls_back_to_user_locations(self):
        call_count = [0]
        def fetchone_side():
            call_count[0] += 1
            if call_count[0] == 1:
                return (None,)           # req_loc NULL
            if call_count[0] == 2:
                return (37.7799, -121.9780)  # user_locations
            return None
        cursor = MagicMock()
        cursor.fetchone.side_effect = fetchone_side
        self._patch_conn(cursor)
        coords, status = helpers.get_beneficiary_location("user-123")
        self.assertEqual(status, "user_loc")
        self.assertAlmostEqual(coords[0], 37.7799)

    def test_falls_back_to_profile_geocoding(self):
        call_count = [0]
        def fetchone_side():
            call_count[0] += 1
            if call_count[0] == 1:
                return (None,)
            if call_count[0] == 2:
                return (None, None)
            if call_count[0] == 3:
                return ("123 Main St", None, "San Jose", "California", "United States", "95101")
            return None
        cursor = MagicMock()
        cursor.fetchone.side_effect = fetchone_side
        self._patch_conn(cursor)
        mock_coords = (37.3382, -121.8863)
        with patch.object(helpers, "geocode_address", return_value=(mock_coords, "ok")):
            coords, status = helpers.get_beneficiary_location("user-123")
        self.assertEqual(status, "profile_address")
        self.assertEqual(coords, mock_coords)

    def test_returns_unknown_when_all_sources_fail(self):
        call_count = [0]
        def fetchone_side():
            call_count[0] += 1
            if call_count[0] == 1:
                return (None,)
            if call_count[0] == 2:
                return (None, None)
            return None
        cursor = MagicMock()
        cursor.fetchone.side_effect = fetchone_side
        self._patch_conn(cursor)
        coords, status = helpers.get_beneficiary_location("user-123")
        self.assertIsNone(coords)
        self.assertEqual(status, "unknown_location")

    def test_empty_beneficiary_id(self):
        coords, status = helpers.get_beneficiary_location("")
        self.assertIsNone(coords)
        self.assertEqual(status, "unknown_location")

    def test_db_error_triggers_rollback(self):
        """A failed DB query must rollback the shared connection."""
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("db down")
        self._patch_conn(cursor)
        helpers._db_conn.rollback = MagicMock()
        coords, status = helpers.get_beneficiary_location("user-123")
        self.assertIsNone(coords)
        helpers._db_conn.rollback.assert_called_once()


# ===========================================================================
# get_beneficiary_location_by_request  (DB mocked)
# ===========================================================================
class TestGetBeneficiaryLocationByRequest(unittest.TestCase):
    def _patch_conn(self, cursor):
        helpers._db_conn.cursor = MagicMock(return_value=cursor)

    def test_uses_req_loc_from_specific_request(self):
        cursor = _make_cursor(fetchone=("latitude:37.7799,longitude:-121.9780", "user-abc"))
        self._patch_conn(cursor)
        coords, status = helpers.get_beneficiary_location_by_request("req-001")
        self.assertEqual(status, "req_loc")
        self.assertAlmostEqual(coords[0], 37.7799)

    def test_returns_unknown_when_request_not_found(self):
        cursor = _make_cursor(fetchone=None)
        self._patch_conn(cursor)
        coords, status = helpers.get_beneficiary_location_by_request("req-missing")
        self.assertIsNone(coords)
        self.assertEqual(status, "unknown_location")

    def test_empty_request_id(self):
        coords, status = helpers.get_beneficiary_location_by_request("")
        self.assertIsNone(coords)
        self.assertEqual(status, "unknown_location")

    def test_db_error_triggers_rollback(self):
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("db down")
        self._patch_conn(cursor)
        helpers._db_conn.rollback = MagicMock()
        coords, status = helpers.get_beneficiary_location_by_request("req-001")
        self.assertIsNone(coords)
        helpers._db_conn.rollback.assert_called_once()


# ===========================================================================
# get_ai_orgs — graceful degradation
# ===========================================================================
class TestGetAiOrgsGracefulDegradation(unittest.TestCase):

    def _invoke_result(self, payload_dict):
        mock_response = MagicMock()
        mock_response["Payload"].read.return_value = json.dumps(payload_dict).encode()
        helpers.lambda_client.invoke = MagicMock(return_value=mock_response)

    def test_returns_empty_df_on_502_unavailable(self):
        self._invoke_result({"statusCode": 502, "body": {"code": "ORG_SEARCH_UNAVAILABLE"}})
        result = helpers.get_ai_orgs("subject", "desc", "Seattle, WA")
        self.assertTrue(result.empty)

    def test_returns_empty_df_on_non_200_status(self):
        self._invoke_result({"statusCode": 500, "body": {}})
        result = helpers.get_ai_orgs("subject", "desc", "Seattle, WA")
        self.assertTrue(result.empty)

    def test_returns_empty_df_on_exception(self):
        helpers.lambda_client.invoke = MagicMock(side_effect=Exception("network error"))
        result = helpers.get_ai_orgs("subject", "desc", "Seattle, WA")
        self.assertTrue(result.empty)

    def test_returns_empty_df_when_no_orgs_in_response(self):
        self._invoke_result({"statusCode": 200, "body": {"organizations": []}})
        result = helpers.get_ai_orgs("subject", "desc", "Seattle, WA")
        self.assertTrue(result.empty)


if __name__ == "__main__":
    unittest.main()
