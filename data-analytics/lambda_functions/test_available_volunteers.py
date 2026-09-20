"""Tests for available_volunteers.py (issue #289).

Standard library only - run with:

    python -m unittest test_available_volunteers -v

psycopg2 and boto3 are stubbed, so no database, no AWS credentials and no
third-party packages are needed. The matching itself runs in SQL, so these
tests assert on the behaviour this module actually owns: request validation,
the response contract, which filters get built into the statement, and the
parameters bound to it. Verifying the SQL semantics needs a live
PostgreSQL + PostGIS instance and is out of scope here.
"""

import contextlib
import importlib
import json
import os
import sys
import types
import unittest


# --- Stub the AWS/DB dependencies before importing the module under test ---

def _install_stubs():
    psycopg2 = types.ModuleType("psycopg2")
    psycopg2.connect = lambda **kwargs: None
    extras = types.ModuleType("psycopg2.extras")
    extras.RealDictCursor = object
    psycopg2.extras = extras
    sys.modules["psycopg2"] = psycopg2
    sys.modules["psycopg2.extras"] = extras

    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: None
    sys.modules["boto3"] = boto3


_install_stubs()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import available_volunteers as av  # noqa: E402


# --- Test doubles ---------------------------------------------------------

class FakeCursor(object):
    """Records statements and replays canned results in order."""

    def __init__(self, results, raise_on_execute=None):
        self._results = list(results)
        self._raise = raise_on_execute
        self.statements = []
        self._current = None

    def execute(self, query, params=None):
        if self._raise:
            raise self._raise
        self.statements.append((query, params))
        self._current = self._results.pop(0) if self._results else None

    def fetchone(self):
        return self._current

    def fetchall(self):
        return self._current or []

    def close(self):
        pass


class FakeConnection(object):
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self, **kwargs):
        return self._cursor

    def close(self):
        self.closed = True


def make_request(req_type="Virtual", has_location=True, cat_id="1.1"):
    return {
        "req_id": "REQ-00-000-000-001",
        "req_cat_id": cat_id,
        "req_type_id": 2,
        "req_type": req_type,
        "location_user_id": "SID-00-000-000-000-000-009",
        "has_location": has_location,
    }


def make_volunteer(user_id="SID-00-000-000-000-000-001",
                   name="Example Volunteer", status="Active",
                   skills=("FOOD_ASSISTANCE",), distance=1234.56):
    return {
        "volunteer_id": user_id,
        "full_name": name,
        "status": status,
        "skills": list(skills),
        "distance_meters": distance,
    }


class HandlerTestCase(unittest.TestCase):
    """Wires a FakeCursor into the module for the duration of one test."""

    def run_handler(self, event, results, raise_on_execute=None,
                    raise_on_connect=None):
        cursor = FakeCursor(results, raise_on_execute)
        original = av.get_db_connection

        def fake_connection():
            if raise_on_connect:
                raise raise_on_connect
            return FakeConnection(cursor)

        av.get_db_connection = fake_connection
        try:
            response = av.lambda_handler(event, None)
        finally:
            av.get_db_connection = original
        self.cursor = cursor
        response["parsed"] = json.loads(response["body"])
        return response


# --- Request validation ---------------------------------------------------

class TestRequestValidation(HandlerTestCase):

    def test_valid_request_id_returns_200(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(), [make_volunteer()]])
        self.assertEqual(200, response["statusCode"])
        self.assertEqual("REQ-00-000-000-001", response["parsed"]["requestId"])

    def test_missing_request_id_returns_400(self):
        response = self.run_handler({}, [])
        self.assertEqual(400, response["statusCode"])
        self.assertEqual("request_id is required", response["parsed"]["error"])

    def test_blank_request_id_returns_400(self):
        response = self.run_handler({"request_id": "   "}, [])
        self.assertEqual(400, response["statusCode"])

    def test_nonexistent_request_id_returns_404(self):
        response = self.run_handler({"request_id": "REQ-does-not-exist"},
                                    [None])
        self.assertEqual(404, response["statusCode"])
        self.assertIn("REQ-does-not-exist", response["parsed"]["error"])

    def test_api_gateway_string_body_is_parsed(self):
        response = self.run_handler(
            {"body": json.dumps({"request_id": "REQ-00-000-000-001"})},
            [make_request(), [make_volunteer()]])
        self.assertEqual(200, response["statusCode"])

    def test_malformed_json_body_is_treated_as_missing(self):
        response = self.run_handler({"body": "{not json"}, [])
        self.assertEqual(400, response["statusCode"])


# --- Skill matching -------------------------------------------------------

class TestSkillMatching(HandlerTestCase):

    def test_multiple_matched_volunteers_are_all_returned(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(),
             [make_volunteer(user_id="SID-1"), make_volunteer(user_id="SID-2"),
              make_volunteer(user_id="SID-3")]])
        self.assertEqual(3, len(response["parsed"]["availableVolunteers"]))

    def test_single_matched_volunteer(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(), [make_volunteer()]])
        self.assertEqual(1, len(response["parsed"]["availableVolunteers"]))

    def test_no_matched_volunteers_returns_200_and_empty_list(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"}, [make_request(), []])
        self.assertEqual(200, response["statusCode"])
        self.assertEqual([], response["parsed"]["availableVolunteers"])

    def test_request_category_is_bound_as_a_parameter(self):
        self.run_handler({"request_id": "REQ-00-000-000-001"},
                         [make_request(cat_id="3.3.1"), []])
        _query, params = self.cursor.statements[-1]
        self.assertEqual("3.3.1", params["req_cat_id"])

    def test_hierarchical_matching_is_off_by_default(self):
        self.run_handler({"request_id": "REQ-00-000-000-001"},
                         [make_request(), []])
        query, _params = self.cursor.statements[-1]
        self.assertNotIn("help_category_map", query)


# --- Volunteer status -----------------------------------------------------

class TestVolunteerStatus(HandlerTestCase):

    def test_status_is_filtered_by_name_not_numeric_id(self):
        self.run_handler({"request_id": "REQ-00-000-000-001"},
                         [make_request(), []])
        query, params = self.cursor.statements[-1]
        self.assertIn("ust.user_status = ANY", query)
        self.assertEqual(["Active"], params["eligible_statuses"])
        self.assertNotIn("user_status_id = 1", query)

    def test_status_is_resolved_through_the_lookup_table(self):
        self.run_handler({"request_id": "REQ-00-000-000-001"},
                         [make_request(), []])
        query, _params = self.cursor.statements[-1]
        self.assertIn("user_status ust", query)

    def test_status_is_surfaced_in_the_response(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(), [make_volunteer(status="Active")]])
        self.assertEqual("Active",
                         response["parsed"]["availableVolunteers"][0]["status"])


# --- Location matching ----------------------------------------------------

class TestLocationMatching(HandlerTestCase):

    def test_in_person_request_applies_the_proximity_filter(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(req_type="In person"), [make_volunteer()]])
        query, params = self.cursor.statements[-1]
        self.assertIn("ST_DWithin", query)
        self.assertEqual(av.IN_PERSON_MATCH_RADIUS_METERS, params["radius_m"])
        self.assertTrue(response["parsed"]["locationFilterApplied"])

    def test_in_person_match_is_case_insensitive(self):
        self.run_handler({"request_id": "REQ-00-000-000-001"},
                         [make_request(req_type="  IN PERSON "), []])
        query, _params = self.cursor.statements[-1]
        self.assertIn("ST_DWithin", query)

    def test_non_in_person_request_is_not_location_filtered(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(req_type="Virtual"), [make_volunteer()]])
        query, _params = self.cursor.statements[-1]
        self.assertNotIn("ST_DWithin", query)
        self.assertFalse(response["parsed"]["locationFilterApplied"])

    def test_unknown_request_type_is_not_location_filtered(self):
        self.run_handler({"request_id": "REQ-00-000-000-001"},
                         [make_request(req_type=None), []])
        query, _params = self.cursor.statements[-1]
        self.assertNotIn("ST_DWithin", query)

    def test_in_person_without_beneficiary_location_skips_the_filter(self):
        # Must still answer rather than fail, but must not claim the
        # remaining volunteers were proximity-checked.
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(req_type="In person", has_location=False),
             [make_volunteer()]])
        self.assertEqual(200, response["statusCode"])
        self.assertFalse(response["parsed"]["locationFilterApplied"])

    def test_volunteer_without_location_does_not_fail_the_call(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(req_type="In person"),
             [make_volunteer(distance=None)]])
        self.assertEqual(200, response["statusCode"])
        self.assertIsNone(
            response["parsed"]["availableVolunteers"][0]["distanceMeters"])

    def test_volunteer_locations_join_is_outer(self):
        self.run_handler({"request_id": "REQ-00-000-000-001"},
                         [make_request(), []])
        query, _params = self.cursor.statements[-1]
        self.assertIn("LEFT JOIN {}.volunteer_locations".format(av.SCHEMA_NAME),
                      query)

    def test_multiple_candidates_are_ordered_by_distance(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(req_type="In person"),
             [make_volunteer(user_id="near", distance=100.0),
              make_volunteer(user_id="far", distance=9000.0)]])
        ids = [v["volunteerId"]
               for v in response["parsed"]["availableVolunteers"]]
        self.assertEqual(["near", "far"], ids)
        query, _params = self.cursor.statements[-1]
        self.assertIn("ORDER BY distance_meters", query)


# --- Existing assignments -------------------------------------------------

class TestExistingAssignments(HandlerTestCase):

    def test_assigned_volunteers_are_excluded_by_default(self):
        self.run_handler({"request_id": "REQ-00-000-000-001"},
                         [make_request(), []])
        query, params = self.cursor.statements[-1]
        self.assertIn("volunteers_assigned", query)
        self.assertIn("NOT EXISTS", query)
        self.assertEqual("REQ-00-000-000-001", params["request_id"])


# --- Failure handling -----------------------------------------------------

class TestFailureHandling(HandlerTestCase):

    def test_database_connection_failure_returns_500(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"}, [],
            raise_on_connect=RuntimeError("connection refused"))
        self.assertEqual(500, response["statusCode"])
        self.assertEqual("Internal server error", response["parsed"]["error"])

    def test_query_execution_failure_returns_500(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"}, [],
            raise_on_execute=RuntimeError("syntax error"))
        self.assertEqual(500, response["statusCode"])

    def test_failure_does_not_leak_internals_to_the_caller(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"}, [],
            raise_on_connect=RuntimeError("password=hunter2 host=db.internal"))
        self.assertNotIn("hunter2", response["body"])


# --- Response contract ----------------------------------------------------

class TestResponseContract(HandlerTestCase):

    def test_response_shape(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(), [make_volunteer()]])
        self.assertEqual("application/json",
                         response["headers"]["Content-Type"])
        volunteer = response["parsed"]["availableVolunteers"][0]
        self.assertEqual(
            {"volunteerId", "name", "skills", "status", "distanceMeters"},
            set(volunteer))

    def test_null_skill_entries_are_dropped(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(), [make_volunteer(skills=[None, "TUTORING"])]])
        self.assertEqual(["TUTORING"],
                         response["parsed"]["availableVolunteers"][0]["skills"])

    def test_missing_optional_fields_do_not_crash(self):
        response = self.run_handler(
            {"request_id": "REQ-00-000-000-001"},
            [make_request(), [{"volunteer_id": "SID-1"}]])
        self.assertEqual(200, response["statusCode"])
        volunteer = response["parsed"]["availableVolunteers"][0]
        self.assertIsNone(volunteer["name"])
        self.assertEqual([], volunteer["skills"])


# --- SQL hygiene ----------------------------------------------------------

class TestSqlHygiene(HandlerTestCase):

    def test_all_user_values_are_bound_not_interpolated(self):
        self.run_handler({"request_id": "REQ-'; DROP TABLE users;--"},
                         [make_request(), []])
        for query, params in self.cursor.statements:
            self.assertNotIn("DROP TABLE", query)
            self.assertIsInstance(params, dict)

    def test_invalid_schema_name_is_rejected(self):
        original = av.SCHEMA_NAME
        av.SCHEMA_NAME = "public; DROP TABLE users;--"
        try:
            with self.assertRaises(ValueError):
                av._schema()
        finally:
            av.SCHEMA_NAME = original

    def test_no_credentials_in_source(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "available_volunteers.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read().lower()
        for needle in ("password=\"", "password='", "secret_key", "aws_access"):
            self.assertNotIn(needle, source)


# --- Configurability ------------------------------------------------------

class TestConfiguration(unittest.TestCase):
    """The issue's open questions must be settings, not literals."""

    @contextlib.contextmanager
    def reloaded_with(self, **env):
        """Reload the module under the given environment, then restore it."""
        original = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            yield importlib.reload(av)
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            importlib.reload(av)

    def test_radius_is_configurable(self):
        with self.reloaded_with(IN_PERSON_MATCH_RADIUS_METERS="2500") as module:
            self.assertEqual(2500.0, module.IN_PERSON_MATCH_RADIUS_METERS)

    def test_eligible_statuses_are_configurable(self):
        with self.reloaded_with(
                ELIGIBLE_VOLUNTEER_STATUSES="Active, Verified") as module:
            self.assertEqual(["Active", "Verified"],
                             module.ELIGIBLE_VOLUNTEER_STATUSES)

    def test_hierarchical_matching_can_be_enabled(self):
        with self.reloaded_with(
                ENABLE_HIERARCHICAL_CATEGORY_MATCH="true") as module:
            self.assertTrue(module.ENABLE_HIERARCHICAL_CATEGORY_MATCH)
            cursor = FakeCursor([[]])
            module.fetch_available_volunteers(cursor, make_request(), False)
            query, _params = cursor.statements[-1]
            self.assertIn("help_category_map", query)

    def test_assignment_exclusion_can_be_disabled(self):
        with self.reloaded_with(EXCLUDE_ASSIGNED_VOLUNTEERS="false") as module:
            self.assertFalse(module.EXCLUDE_ASSIGNED_VOLUNTEERS)
            cursor = FakeCursor([[]])
            module.fetch_available_volunteers(cursor, make_request(), False)
            query, _params = cursor.statements[-1]
            self.assertNotIn("volunteers_assigned", query)

    def test_in_person_type_names_are_configurable(self):
        with self.reloaded_with(
                IN_PERSON_REQUEST_TYPES="Onsite,In person") as module:
            self.assertIn("onsite", module.IN_PERSON_REQUEST_TYPES)
            self.assertTrue(module.is_in_person(make_request(req_type="Onsite")))

    def test_defaults_are_restored_after_reload(self):
        self.assertEqual(50000.0, av.IN_PERSON_MATCH_RADIUS_METERS)
        self.assertEqual(["Active"], av.ELIGIBLE_VOLUNTEER_STATUSES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
