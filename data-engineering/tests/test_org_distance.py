"""Unit tests for organization distance enrichment (#433)."""

from __future__ import annotations

import importlib
import json
import sys
import types
import unittest
from pathlib import Path
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
    parameters.get_parameter = lambda *_args, **_kwargs: json.dumps(
        {
            "DATABASE NAME": "test_schema",
            "HOST": "localhost",
            "USERNAME": "test",
            "PASSWORD": "test",
            "PORT": 5432,
        }
    )
    utilities.parameters = parameters
    powertools.utilities = utilities
    sys.modules["aws_lambda_powertools"] = powertools
    sys.modules["aws_lambda_powertools.utilities"] = utilities
    sys.modules["aws_lambda_powertools.utilities.parameters"] = parameters

    psycopg2 = types.ModuleType("psycopg2")

    class DatabaseError(Exception):
        pass

    psycopg2.DatabaseError = DatabaseError
    psycopg2.connect = lambda *_args, **_kwargs: object()
    sys.modules["psycopg2"] = psycopg2


_install_aws_test_stubs()
AGG_DIR = Path(__file__).resolve().parents[1] / "src" / "saayam-org-aggregator"
sys.path.insert(0, str(AGG_DIR))
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
        self.assertEqual(
            helpers.parse_coordinates({"latitude": 0, "longitude": 0}), (0, 0)
        )
        self.assertAlmostEqual(
            helpers.straight_line_distance_miles((0, 0), (0, 0)), 0
        )

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
        with patch.object(
            helpers,
            "_get_request_and_beneficiary",
            return_value=(
                {"req_loc": "longitude:-121.978,latitude:37.7799"},
                "beneficiary-1",
            ),
        ), patch.object(helpers, "_get_user_coordinates") as user_location:
            result = helpers.resolve_beneficiary_coordinates("request-1")
        self.assertEqual(
            result, {"coordinates": (37.7799, -121.978), "status": "ok"}
        )
        user_location.assert_not_called()

    def test_user_location_is_fallback(self):
        with patch.object(
            helpers,
            "_get_request_and_beneficiary",
            return_value=({"req_loc": "Suffolk, VA"}, "beneficiary-1"),
        ), patch.object(
            helpers, "_get_user_coordinates", return_value=(36.7282, -76.5836)
        ):
            result = helpers.resolve_beneficiary_coordinates("request-1")
        self.assertEqual(
            result, {"coordinates": (36.7282, -76.5836), "status": "ok"}
        )

    def test_no_location_returns_unknown_not_zero(self):
        with patch.object(
            helpers, "_get_request_and_beneficiary", return_value=({}, None)
        ), patch.object(helpers, "_get_user_coordinates", return_value=None), patch.object(
            helpers, "_get_profile_address", return_value=""
        ):
            result = helpers.resolve_beneficiary_coordinates()
        self.assertEqual(
            result, {"coordinates": None, "status": "unknown_location"}
        )
        self.assertIsNone(result["coordinates"])

    def test_profile_address_is_tried_after_ungeocodable_request_text(self):
        geocode_results = [(None, "deferred"), ((37.5, -77.4), "ok")]
        with patch.object(
            helpers,
            "_get_request_and_beneficiary",
            return_value=({"req_loc": "Richmond, VA"}, "beneficiary-1"),
        ), patch.object(
            helpers, "_get_user_coordinates", return_value=None
        ), patch.object(
            helpers, "_get_profile_address", return_value="10 Main St, Richmond, VA"
        ), patch.object(
            helpers, "geocode_address", side_effect=geocode_results
        ) as geocoder:
            result = helpers.resolve_beneficiary_coordinates("request-1")
        self.assertEqual(result, {"coordinates": (37.5, -77.4), "status": "ok"})
        self.assertEqual(geocoder.call_count, 2)


class OrganizationEnrichmentTests(unittest.TestCase):
    def tearDown(self):
        helpers._GEOCODE_CACHE.clear()
        helpers._geocode_address_impl = None

    def test_enriches_coordinate_org_and_preserves_original_fields(self):
        orgs = pd.DataFrame(
            [
                {
                    "name": "Nearby Org",
                    "latitude": 37.7799,
                    "longitude": -121.978,
                    "rating": 4.7,
                    "collaborator": False,
                }
            ]
        )
        result = helpers.add_organization_distances(
            orgs, {"coordinates": (37.7799, -121.978), "status": "ok"}
        )
        self.assertEqual(result.loc[0, "distance"], 0.0)
        self.assertEqual(result.loc[0, "distance_status"], "ok")
        self.assertEqual(result.loc[0, "distance_unit"], "miles")
        self.assertEqual(result.loc[0, "distance_method"], "straight_line")
        self.assertEqual(result.loc[0, "rating"], 4.7)

    def test_unknown_distance_keeps_organization_and_is_null(self):
        orgs = pd.DataFrame([{"name": "No Address Org", "rating": 3.9}])
        result = helpers.add_organization_distances(
            orgs, {"coordinates": None, "status": "unknown_location"}
        )
        self.assertEqual(result.loc[0, "name"], "No Address Org")
        self.assertIsNone(result.loc[0, "distance"])
        self.assertEqual(result.loc[0, "distance_status"], "unknown_location")

    def test_provider_deferred_and_successful_geocode_is_cached(self):
        self.assertEqual(
            helpers.geocode_address("100 Main St, Richmond, VA"),
            (None, "deferred"),
        )
        calls = []
        helpers._geocode_address_impl = (
            lambda address: calls.append(address) or (37.5, -77.4)
        )
        self.assertEqual(
            helpers.geocode_address("100 Main St, Richmond, VA"),
            ((37.5, -77.4), "ok"),
        )
        self.assertEqual(
            helpers.geocode_address("100 Main St, Richmond, VA"),
            ((37.5, -77.4), "ok"),
        )
        self.assertEqual(len(calls), 1)

    def test_online_only_org_does_not_get_a_numeric_distance(self):
        orgs = pd.DataFrame([{"name": "Online Org", "online_only": True}])
        result = helpers.add_organization_distances(
            orgs, {"coordinates": (37.5, -77.4), "status": "ok"}
        )
        self.assertIsNone(result.loc[0, "distance"])
        self.assertEqual(result.loc[0, "distance_status"], "online")

    def test_sort_puts_null_distances_last(self):
        orgs = pd.DataFrame(
            [
                {"name": "Far", "distance": 20.0, "distance_status": "ok"},
                {"name": "Unknown", "distance": None, "distance_status": "unknown_location"},
                {"name": "Near", "distance": 2.0, "distance_status": "ok"},
            ]
        )
        sorted_orgs = helpers.sort_organizations_by_distance(orgs)
        self.assertEqual(
            list(sorted_orgs["name"]), ["Near", "Far", "Unknown"]
        )

    def test_merge_retains_address_and_rating_columns(self):
        db = pd.DataFrame(
            [
                {
                    "org_name": "DB Org",
                    "city_name": "Richmond",
                    "street": "10 Main St",
                    "state_id": "VA",
                    "zip_code": "23220",
                    "org_rating": 4.2,
                    "org_type": "non_profit",
                    "is_collaborator": False,
                    "org_size": "small",
                    "phone": "555",
                    "email": "a@b.c",
                    "web_url": "https://x",
                    "mission": "food",
                    "source": "db",
                    "location": "10 Main St, Richmond, VA 23220",
                }
            ]
        )
        ai = pd.DataFrame(
            [{"organization_name": "AI Org", "location": "Richmond, VA"}]
        )
        merged = helpers.merge_organizations(db, ai)
        self.assertEqual(merged.loc[0, "street"], "10 Main St")
        self.assertEqual(merged.loc[0, "rating"], 4.2)
        self.assertEqual(merged.loc[1, "name"], "AI Org")


class LambdaHandlerTests(unittest.TestCase):
    def test_missing_ids_return_400(self):
        response = lambda_function.lambda_handler({"location": "x"}, None)
        self.assertEqual(response["statusCode"], 400)

    def test_distance_failure_still_returns_organizations(self):
        db_orgs = pd.DataFrame(
            [
                {
                    "org_name": "DB Org",
                    "city_name": "Richmond",
                    "org_rating": 4.2,
                    "org_type": "non_profit",
                    "is_collaborator": False,
                    "org_size": "small",
                    "phone": "555",
                    "email": "a@b.c",
                    "web_url": "https://x",
                    "mission": "food",
                    "source": "db",
                    "location": "Richmond, VA",
                }
            ]
        )
        with patch.object(
            lambda_function, "get_beneficiary_location", return_value=("Richmond, VA", "Richmond")
        ), patch.object(
            lambda_function,
            "get_req_info",
            return_value={
                "category": "food",
                "description": "d",
                "subject": "s",
            },
        ), patch.object(
            lambda_function, "get_orgs_from_db", return_value=db_orgs
        ), patch.object(
            lambda_function, "get_ai_orgs", side_effect=RuntimeError("offline")
        ), patch.object(
            lambda_function,
            "resolve_beneficiary_coordinates",
            return_value={"coordinates": (37.5, -77.4), "status": "ok"},
        ), patch.object(
            lambda_function,
            "add_organization_distances",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertLogs(lambda_function.logger, level="ERROR"):
                response = lambda_function.lambda_handler(
                    {"request_id": "REQ-1", "beneficiary_id": "BEN-1"},
                    None,
                )
        records = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "DB Org")
        self.assertIsNone(records[0]["distance"])
        self.assertEqual(records[0]["distance_status"], "error")
        self.assertEqual(records[0]["rating"], 4.2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
