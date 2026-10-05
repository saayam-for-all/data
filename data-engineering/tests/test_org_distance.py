"""Unit tests for provider-neutral organization distance enrichment."""
import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd


def _install_aws_test_stubs():
    """Prevent helper imports from contacting AWS or opening a DB connection."""
    boto3 = types.ModuleType("boto3")

    class Boto3Error(Exception):
        pass

    boto3.exceptions = types.SimpleNamespace(Boto3Error=Boto3Error)
    boto3.client = lambda *_args, **_kwargs: types.SimpleNamespace(invoke=None)
    sys.modules["boto3"] = boto3

    powertools = types.ModuleType("aws_lambda_powertools")
    utilities = types.ModuleType("aws_lambda_powertools.utilities")
    parameters = types.ModuleType("aws_lambda_powertools.utilities.parameters")
    parameters.get_parameter = lambda *_args, **_kwargs: json.dumps({
        "DATABASE NAME": "test_schema", "HOST": "localhost", "USERNAME": "test",
        "PASSWORD": "test", "PORT": 5432,
    })
    utilities.parameters = parameters
    powertools.utilities = utilities
    sys.modules["aws_lambda_powertools"] = powertools
    sys.modules["aws_lambda_powertools.utilities"] = utilities
    sys.modules["aws_lambda_powertools.utilities.parameters"] = parameters

    pg8000 = types.ModuleType("pg8000")

    class DatabaseError(Exception):
        pass

    pg8000.DatabaseError = DatabaseError
    pg8000.connect = lambda *_args, **_kwargs: object()
    sys.modules["pg8000"] = pg8000


_install_aws_test_stubs()
sys.path.insert(0, "src/saayam-org-aggregator")
helpers = importlib.import_module("helpers")
lambda_function = importlib.import_module("lambda_function")


class CoordinateTests(unittest.TestCase):
    def test_parses_issue_coordinate_format(self):
        self.assertEqual(
            helpers.parse_coordinates("longitude:-121.9780,latitude:37.7799"),
            (37.7799, -121.978),
        )

    def test_parses_postgis_point_in_lon_lat_order(self):
        self.assertEqual(
            helpers.parse_coordinates("SRID=4326;POINT(-121.9780 37.7799)"),
            (37.7799, -121.978),
        )

    def test_zero_coordinates_are_valid(self):
        self.assertEqual(helpers.parse_coordinates({"latitude": 0, "longitude": 0}), (0, 0))
        self.assertAlmostEqual(helpers.straight_line_distance_miles((0, 0), (0, 0)), 0)

    def test_rejects_invalid_or_out_of_range_coordinates(self):
        self.assertIsNone(helpers.parse_coordinates("Suffolk, VA"))
        self.assertIsNone(helpers.parse_coordinates((91, 0)))

    def test_distance_matches_straight_line_example(self):
        miles = helpers.straight_line_distance_miles(
            (37.7799, -121.9780), (37.4220, -122.0841)
        )
        self.assertAlmostEqual(miles, 25.5, delta=0.2)


class BeneficiaryLocationTests(unittest.TestCase):
    def test_request_coordinates_take_precedence(self):
        with patch.object(helpers, "_get_request_and_beneficiary", return_value=(
            {"req_loc": "longitude:-121.978,latitude:37.7799"}, "beneficiary-1"
        )), patch.object(helpers, "_get_user_coordinates") as user_location:
            result = helpers.get_beneficiary_location("request-1")
        self.assertEqual(result, {"coordinates": (37.7799, -121.978), "status": "ok"})
        user_location.assert_not_called()

    def test_user_location_is_fallback(self):
        with patch.object(helpers, "_get_request_and_beneficiary", return_value=(
            {"req_loc": "Suffolk, VA"}, "beneficiary-1"
        )), patch.object(helpers, "_get_user_coordinates", return_value=(36.7282, -76.5836)):
            result = helpers.get_beneficiary_location("request-1")
        self.assertEqual(result, {"coordinates": (36.7282, -76.5836), "status": "ok"})

    def test_request_lookup_uses_request_id_and_beneficiary_fields(self):
        with patch.object(helpers, "_table_columns", return_value={
            "req_id", "req_loc", "beneficiary_id"
        }), patch.object(helpers, "_first_row", return_value={
            "req_id": "REQ-1", "req_loc": "longitude:-77.4,latitude:37.5",
            "beneficiary_id": "BEN-1",
        }) as query:
            row, beneficiary_id = helpers._get_request_and_beneficiary("REQ-1")
        self.assertEqual(row["req_id"], "REQ-1")
        self.assertEqual(beneficiary_id, "BEN-1")
        self.assertIn("FROM test_schema.requests", query.call_args.args[0])
        self.assertEqual(query.call_args.args[1], ("REQ-1",))

    def test_user_coordinate_query_uses_beneficiary_and_postgis_lon_lat_order(self):
        with patch.object(helpers, "_table_columns", return_value={
            "beneficiary_id", "curr_loc", "updated_at"
        }), patch.object(helpers, "_first_row", return_value={
            "latitude": 37.5, "longitude": -77.4
        }) as query:
            coordinates = helpers._get_user_coordinates("BEN-1")
        self.assertEqual(coordinates, (37.5, -77.4))
        self.assertIn("ST_Y(curr_loc::geometry) AS latitude", query.call_args.args[0])
        self.assertIn("ST_X(curr_loc::geometry) AS longitude", query.call_args.args[0])
        self.assertEqual(query.call_args.args[1], ("BEN-1",))

    def test_no_location_returns_unknown_not_zero(self):
        with patch.object(helpers, "_get_request_and_beneficiary", return_value=({}, None)), \
             patch.object(helpers, "_get_user_coordinates", return_value=None):
            result = helpers.get_beneficiary_location()
        self.assertEqual(result, {"coordinates": None, "status": "unknown_location"})

    def test_profile_address_is_tried_after_ungeocodable_request_text(self):
        geocode_results = [(None, "deferred"), ((37.5, -77.4), "ok")]
        with patch.object(helpers, "_get_request_and_beneficiary", return_value=(
            {"req_loc": "Richmond, VA"}, "beneficiary-1"
        )), patch.object(helpers, "_get_user_coordinates", return_value=None), \
             patch.object(helpers, "_get_profile_address", return_value="10 Main St, Richmond, VA"), \
             patch.object(helpers, "geocode_address", side_effect=geocode_results) as geocoder:
            result = helpers.get_beneficiary_location("request-1")
        self.assertEqual(result, {"coordinates": (37.5, -77.4), "status": "ok"})
        self.assertEqual(geocoder.call_count, 2)


class LambdaHandlerTests(unittest.TestCase):
    def test_genai_failure_does_not_drop_database_organizations(self):
        db_orgs = pd.DataFrame([{
            "org_name": "DB Org", "city_name": "Richmond", "rating": 4.2,
        }])
        with patch.object(lambda_function, "get_orgs_from_db", return_value=db_orgs), \
             patch.object(lambda_function, "get_ai_orgs", side_effect=RuntimeError("offline")), \
             patch.object(lambda_function, "get_beneficiary_location", return_value={
                 "coordinates": None, "status": "unknown_location"
             }):
            with self.assertLogs(lambda_function.logger, level="ERROR"):
                response = lambda_function.lambda_handler({
                    "location": "Richmond", "category": "food", "request_id": "REQ-1"
                }, None)
        records = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "DB Org")
        self.assertIsNone(records[0]["distance"])
        self.assertEqual(records[0]["distance_status"], "unknown_location")
        self.assertEqual(records[0]["rating"], 4.2)


class OrganizationEnrichmentTests(unittest.TestCase):
    def tearDown(self):
        helpers._GEOCODE_CACHE.clear()
        helpers._geocode_address_impl = None

    def test_enriches_coordinate_org_and_preserves_original_fields(self):
        orgs = pd.DataFrame([{
            "name": "Nearby Org", "latitude": 37.7799, "longitude": -121.978,
            "rating": 4.7, "is_collaborator": False,
        }])
        result = helpers.add_organization_distances(orgs, {
            "coordinates": (37.7799, -121.978), "status": "ok"
        })
        self.assertEqual(result.loc[0, "distance"], 0.0)
        self.assertEqual(result.loc[0, "distance_status"], "ok")
        self.assertEqual(result.loc[0, "distance_unit"], "miles")
        self.assertEqual(result.loc[0, "distance_method"], "straight_line")
        self.assertEqual(result.loc[0, "rating"], 4.7)
        self.assertFalse(result.loc[0, "is_collaborator"])

    def test_unknown_distance_keeps_organization_and_is_null(self):
        orgs = pd.DataFrame([{"name": "No Address Org", "rating": 3.9}])
        result = helpers.add_organization_distances(orgs, {
            "coordinates": None, "status": "unknown_location"
        })
        self.assertEqual(result.loc[0, "name"], "No Address Org")
        self.assertIsNone(result.loc[0, "distance"])
        self.assertEqual(result.loc[0, "distance_status"], "unknown_location")

    def test_provider_deferred_and_successful_geocode_is_cached(self):
        self.assertEqual(helpers.geocode_address("100 Main St, Richmond, VA"), (None, "deferred"))
        calls = []
        helpers._geocode_address_impl = lambda address: calls.append(address) or (37.5, -77.4)
        self.assertEqual(
            helpers.geocode_address("100 Main St, Richmond, VA"), ((37.5, -77.4), "ok")
        )
        self.assertEqual(
            helpers.geocode_address("100 Main St, Richmond, VA"), ((37.5, -77.4), "ok")
        )
        self.assertEqual(len(calls), 1)

    def test_geocoding_failure_statuses_are_explicit(self):
        helpers._geocode_address_impl = lambda _address: None
        self.assertEqual(helpers.geocode_address("No match"), (None, "not_found"))
        helpers._geocode_address_impl = lambda _address: (_ for _ in ()).throw(TimeoutError())
        self.assertEqual(helpers.geocode_address("Slow address"), (None, "deferred"))
        helpers._geocode_address_impl = lambda _address: (_ for _ in ()).throw(RuntimeError())
        self.assertEqual(helpers.geocode_address("Provider error"), (None, "error"))

    def test_online_only_org_does_not_get_a_numeric_distance(self):
        orgs = pd.DataFrame([{"name": "Online Org", "online_only": True}])
        result = helpers.add_organization_distances(orgs, {
            "coordinates": (37.5, -77.4), "status": "ok"
        })
        self.assertIsNone(result.loc[0, "distance"])
        self.assertEqual(result.loc[0, "distance_status"], "online")

    def test_merge_retains_address_and_rating_columns(self):
        db = pd.DataFrame([{
            "org_name": "DB Org", "city_name": "Richmond", "street": "10 Main St",
            "state_code": "VA", "zip_code": "23220", "rating": 4.2,
        }])
        ai = pd.DataFrame([{"organization_name": "AI Org", "location": "Richmond, VA"}])
        merged = helpers.merge_organizations(db, ai)
        self.assertEqual(merged.loc[0, "street"], "10 Main St")
        self.assertEqual(merged.loc[0, "rating"], 4.2)
        self.assertEqual(merged.loc[1, "name"], "AI Org")

    def test_missing_address_values_are_not_sent_to_geocoder_as_nan(self):
        address = helpers.build_address({"street": float("nan"), "city_name": "Richmond"})
        self.assertEqual(address, "Richmond")


if __name__ == "__main__":
    unittest.main()
