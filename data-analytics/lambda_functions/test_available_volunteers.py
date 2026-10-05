"""Cursor/mock unit tests for the Available Volunteers API (#289).

These tests do not connect to AWS or a real database.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import available_volunteers as api  # noqa: E402

REQUEST_ID = "REQ-00-000-000-001"


def in_person_request(**overrides):
    row = {
        "req_id": REQUEST_ID,
        "req_user_id": "SID-00-000-000-102",
        "req_cat_id": "5.2",
        "req_type_id": 0,
        "req_loc": "Ashburn, VA",
        "iscalamity": False,
        "req_type": "IN_PERSON",
        "beneficiary_lat": 39.0438,
        "beneficiary_lon": -77.4874,
        "city_lat": None,
        "city_lon": None,
    }
    row.update(overrides)
    return row


def remote_request(**overrides):
    return in_person_request(req_type_id=1, req_type="REMOTE", **overrides)


def volunteer_row(**overrides):
    row = {
        "volunteer_id": "SID-00-000-001-001",
        "name": "Example Volunteer",
        "skills": ["FOOD_ASSISTANCE"],
        "status": "ACTIVE",
        "distance_meters": 1200,
    }
    row.update(overrides)
    return row


class FakeCursor:
    """Minimal DB cursor that returns canned rows based on executed SQL."""

    def __init__(
        self,
        request_row=None,
        volunteer_rows=None,
        fail_on=None,
        empty_volunteers=False,
    ):
        self.request_row = request_row
        self.volunteer_rows = [] if empty_volunteers else list(volunteer_rows or [])
        self.fail_on = fail_on
        self.executed = []
        self.closed = False
        self._result = []
        self._one = None

    def execute(self, query, params=None):
        sql = " ".join(query.split())
        self.executed.append((sql, tuple(params or ())))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("simulated query failure")

        lowered = sql.lower()
        if "from" in lowered and ".request r" in lowered:
            self._one = self.request_row
            self._result = []
            return
        if "matched_cats" in lowered or "user_skills" in lowered:
            self._one = None
            self._result = list(self.volunteer_rows)
            return
        self._one = None
        self._result = []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._result)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self, cursor_factory=None):
        return self._cursor

    def close(self):
        self.closed = True


class ParseRequestIdTests(unittest.TestCase):
    def test_valid_request_id(self):
        self.assertEqual(api.parse_request_id({"request_id": REQUEST_ID}), REQUEST_ID)

    def test_request_id_alias_camel_case(self):
        self.assertEqual(api.parse_request_id({"requestId": REQUEST_ID}), REQUEST_ID)

    def test_missing_request_id(self):
        with self.assertRaises(api.RequestValidationError) as ctx:
            api.parse_request_id({})
        self.assertEqual(str(ctx.exception), "request_id is required")

    def test_blank_request_id(self):
        with self.assertRaises(api.RequestValidationError):
            api.parse_request_id({"request_id": "   "})


class MatchingRuleHelperTests(unittest.TestCase):
    def test_in_person_type_variants(self):
        self.assertTrue(api.is_in_person_request("IN_PERSON"))
        self.assertTrue(api.is_in_person_request("In person"))
        self.assertTrue(api.is_in_person_request("In-Person"))
        self.assertFalse(api.is_in_person_request("REMOTE"))
        self.assertFalse(api.is_in_person_request(None))

    def test_default_radius_matches_spatial_config(self):
        self.assertEqual(api.matching_radius_meters(False), 25000.0)
        self.assertEqual(api.matching_radius_meters(True), 200000.0)

    def test_skill_and_status_formatting(self):
        self.assertEqual(api.format_skill_name("FOOD_ASSISTANCE"), "Food Assistance")
        self.assertEqual(api.format_status("ACTIVE"), "Active")
        self.assertIsNone(api.format_status(None))

    def test_null_optional_volunteer_fields(self):
        formatted = api.format_volunteer(
            {
                "volunteer_id": "SID-00-000-009-009",
                "name": None,
                "skills": None,
                "status": None,
            }
        )
        self.assertEqual(formatted["volunteerId"], "SID-00-000-009-009")
        self.assertEqual(formatted["name"], "SID-00-000-009-009")
        self.assertEqual(formatted["skills"], [])
        self.assertEqual(formatted["status"], "Active")


class SqlBuilderTests(unittest.TestCase):
    def test_request_lookup_is_parameterized(self):
        sql = api.request_lookup_sql()
        self.assertIn("%s", sql)
        self.assertNotIn(REQUEST_ID, sql)
        self.assertIn("req_cat_id", sql)
        self.assertIn("req_type_id", sql)

    def test_skill_match_uses_user_skills_and_category_map(self):
        sql = api.available_volunteers_sql(apply_location=False)
        self.assertIn("user_skills", sql)
        self.assertIn("help_categories_map", sql)
        self.assertIn("help_categories", sql)
        self.assertNotIn("ST_DWithin", sql)
        self.assertNotIn("volunteer_locations", sql)

    def test_in_person_sql_uses_volunteer_geolocation(self):
        sql = api.available_volunteers_sql(apply_location=True)
        self.assertIn("volunteer_locations", sql)
        self.assertIn("ST_DWithin", sql)
        self.assertIn("curr_loc", sql)
        self.assertIn("updated_at DESC", sql)

    def test_status_filter_and_assigned_exclusion_are_parameterized(self):
        sql = api.available_volunteers_sql(apply_location=False)
        self.assertIn("user_status", sql)
        self.assertIn("volunteers_assigned", sql)
        self.assertNotIn("ACTIVE", sql)


class SchemaNameTests(unittest.TestCase):
    def test_allowlisted_schema_is_kept(self):
        self.assertEqual(
            api.resolve_schema_name("ireland_dev_saayam_rdbms"),
            "ireland_dev_saayam_rdbms",
        )

    def test_invalid_schema_falls_back_to_default(self):
        self.assertEqual(
            api.resolve_schema_name("virginia_dev_saayam_rdbms; DROP TABLE users"),
            api.DEFAULT_SCHEMA_NAME,
        )
        self.assertEqual(api.resolve_schema_name("bad-schema"), api.DEFAULT_SCHEMA_NAME)
        self.assertEqual(api.resolve_schema_name(""), api.DEFAULT_SCHEMA_NAME)


class HandlerTests(unittest.TestCase):
    def _run(self, event, cursor):
        conn = FakeConnection(cursor)
        with patch.object(api, "get_db_connection", return_value=conn):
            return api.lambda_handler(event, None), conn, cursor

    def test_valid_request_id_returns_volunteers(self):
        cursor = FakeCursor(
            request_row=remote_request(),
            volunteer_rows=[
                volunteer_row(),
                volunteer_row(
                    volunteer_id="SID-00-000-001-002",
                    name="Second Volunteer",
                    skills=["MEDICINE_DELIVERY"],
                ),
            ],
        )
        response, conn, _ = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["requestId"], REQUEST_ID)
        self.assertEqual(len(body["availableVolunteers"]), 2)
        self.assertEqual(
            body["availableVolunteers"][0],
            {
                "volunteerId": "SID-00-000-001-001",
                "name": "Example Volunteer",
                "skills": ["Food Assistance"],
                "status": "Active",
            },
        )
        self.assertTrue(conn.closed)
        self.assertTrue(cursor.closed)

    def test_one_skill_matched_volunteer(self):
        cursor = FakeCursor(
            request_row=remote_request(),
            volunteer_rows=[volunteer_row()],
        )
        response, _, _ = self._run({"request_id": REQUEST_ID}, cursor)
        body = json.loads(response["body"])
        self.assertEqual(len(body["availableVolunteers"]), 1)

    def test_no_skill_matched_volunteers_returns_empty_list(self):
        cursor = FakeCursor(request_row=remote_request(), empty_volunteers=True)
        response, _, _ = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["availableVolunteers"], [])

    def test_missing_request_id_returns_400(self):
        response, _, cursor = self._run({}, FakeCursor())
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"]), {"error": "request_id is required"})
        self.assertEqual(cursor.executed, [])

    def test_invalid_request_id_returns_404(self):
        cursor = FakeCursor(request_row=None)
        response, _, _ = self._run({"request_id": "REQ-DOES-NOT-EXIST"}, cursor)
        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(json.loads(response["body"]), {"error": "request not found"})

    def test_api_gateway_json_body(self):
        cursor = FakeCursor(
            request_row=remote_request(),
            volunteer_rows=[volunteer_row()],
        )
        response, _, _ = self._run(
            {"body": json.dumps({"request_id": REQUEST_ID})}, cursor
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["requestId"], REQUEST_ID)

    def test_in_person_nearby_volunteer_uses_geospatial_filter(self):
        cursor = FakeCursor(
            request_row=in_person_request(),
            volunteer_rows=[volunteer_row()],
        )
        response, _, cursor = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertEqual(response["statusCode"], 200)
        volunteer_sql, params = cursor.executed[1]
        self.assertIn("ST_DWithin", volunteer_sql)
        self.assertIn("volunteer_locations", volunteer_sql)
        self.assertEqual(params[0], "5.2")
        self.assertEqual(params[1], -77.4874)
        self.assertEqual(params[2], 39.0438)
        self.assertEqual(params[-1], 25000.0)
        self.assertNotIn(REQUEST_ID, volunteer_sql)

    def test_in_person_volunteer_outside_radius_is_empty_when_db_excludes(self):
        cursor = FakeCursor(
            request_row=in_person_request(),
            empty_volunteers=True,
        )
        response, _, cursor = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertEqual(json.loads(response["body"])["availableVolunteers"], [])
        self.assertIn("ST_DWithin", cursor.executed[1][0])

    def test_in_person_missing_volunteer_geo_does_not_fail_request(self):
        cursor = FakeCursor(
            request_row=in_person_request(),
            volunteer_rows=[volunteer_row()],
        )
        response, _, cursor = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("curr_loc IS NOT NULL", cursor.executed[1][0])

    def test_in_person_multiple_candidates_order_by_distance(self):
        cursor = FakeCursor(
            request_row=in_person_request(),
            volunteer_rows=[
                volunteer_row(distance_meters=5000),
                volunteer_row(
                    volunteer_id="SID-00-000-001-002",
                    name="Closer Volunteer",
                    distance_meters=200,
                ),
            ],
        )
        response, _, cursor = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("distance_meters ASC", cursor.executed[1][0])

    def test_calamity_request_uses_spatial_calamity_radius(self):
        cursor = FakeCursor(
            request_row=in_person_request(iscalamity=True),
            volunteer_rows=[volunteer_row()],
        )
        _, _, cursor = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertEqual(cursor.executed[1][1][-1], 200000.0)

    def test_remote_request_does_not_apply_location_filter(self):
        cursor = FakeCursor(
            request_row=remote_request(),
            volunteer_rows=[volunteer_row()],
        )
        response, _, cursor = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertEqual(response["statusCode"], 200)
        volunteer_sql, params = cursor.executed[1]
        self.assertNotIn("ST_DWithin", volunteer_sql)
        self.assertNotIn("volunteer_locations", volunteer_sql)
        self.assertEqual(params[0], "5.2")
        self.assertEqual(params[1], "ACTIVE")
        self.assertEqual(params[2], REQUEST_ID)

    def test_in_person_without_origin_skips_location_instead_of_failing(self):
        cursor = FakeCursor(
            request_row=in_person_request(
                beneficiary_lat=None,
                beneficiary_lon=None,
                city_lat=None,
                city_lon=None,
            ),
            volunteer_rows=[volunteer_row()],
        )
        response, _, cursor = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertEqual(response["statusCode"], 200)
        self.assertNotIn("ST_DWithin", cursor.executed[1][0])

    def test_city_fallback_coordinates_enable_location_match(self):
        cursor = FakeCursor(
            request_row=in_person_request(
                beneficiary_lat=None,
                beneficiary_lon=None,
                city_lat=39.0438,
                city_lon=-77.4874,
            ),
            volunteer_rows=[volunteer_row()],
        )
        _, _, cursor = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertIn("ST_DWithin", cursor.executed[1][0])

    def test_active_status_is_passed_to_query(self):
        cursor = FakeCursor(
            request_row=remote_request(),
            volunteer_rows=[volunteer_row()],
        )
        _, _, cursor = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertIn("ACTIVE", cursor.executed[1][1])

    def test_non_active_volunteer_not_returned_when_db_filters(self):
        cursor = FakeCursor(request_row=remote_request(), empty_volunteers=True)
        response, _, cursor = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertEqual(json.loads(response["body"])["availableVolunteers"], [])
        self.assertIn("user_status", cursor.executed[1][0])

    def test_database_connection_failure_returns_500(self):
        with patch.object(api, "get_db_connection", side_effect=RuntimeError("db down")):
            response = api.lambda_handler({"request_id": REQUEST_ID}, None)
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(
            json.loads(response["body"]), {"error": "internal server error"}
        )

    def test_query_execution_failure_returns_500(self):
        cursor = FakeCursor(
            request_row=remote_request(),
            fail_on="matched_cats",
        )
        response, _, _ = self._run({"request_id": REQUEST_ID}, cursor)
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(
            json.loads(response["body"]), {"error": "internal server error"}
        )

    def test_options_preflight(self):
        response, _, cursor = self._run({"httpMethod": "OPTIONS"}, FakeCursor())
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(cursor.executed, [])
        self.assertEqual(
            response["headers"]["Access-Control-Allow-Methods"], "POST,OPTIONS"
        )

    def test_get_is_rejected(self):
        response, _, cursor = self._run(
            {"httpMethod": "GET", "request_id": REQUEST_ID}, FakeCursor()
        )
        self.assertEqual(response["statusCode"], 405)
        self.assertEqual(json.loads(response["body"]), {"error": "Method not allowed"})
        self.assertEqual(cursor.executed, [])


if __name__ == "__main__":
    unittest.main()
