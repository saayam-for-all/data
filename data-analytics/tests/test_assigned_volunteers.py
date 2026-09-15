"""Mock-backed test suite for the Assigned Volunteers API (Issue #295).

Every assertion runs against the committed mock fixtures in
``data-analytics/sql`` (``requests.csv``, ``users.csv`` +
``users_extra_295.csv``, ``user_status.csv`` and ``volunteers_assigned.csv`` +
``volunteers_assigned_extra_295.csv``). Nothing in this suite can reach the
shared Saayam database: the Lambda has no Parameter Store fallback, and the
only connection it is ever handed here is the disposable one built by
:mod:`mock_db`.

Expected values are derived from the CSVs at runtime by a pure-Python oracle
that re-implements the current-assignment rule independently of the SQL, so
the two have to agree for a test to pass.

Most scenarios come from the real committed export: 15 of its 25 requests have
multiple assignees, all six request statuses appear, three cancelled requests
carry assignment rows, and 19 of its 60 assignments name a volunteer with no
``users`` row. Only four things the export cannot express are supplied by the
``*_extra_295`` fixtures - a volunteer with NULL contact details, a non-ACTIVE
volunteer, a NULL ``user_status_id``, and a superseded assignment on a request
that is *not* cancelled (the export's one duplicate pair sits on a cancelled
request, where the rule is masked by suppression). ``user_status.csv`` carries
the one real lookup row (``1 ACTIVE``) plus two mock-only rows, since every
user in the export is ACTIVE.

Run it:

    python data-analytics/tests/test_assigned_volunteers.py

    # against a real local PostgreSQL instead of the SQLite shim
    MOCK_DB_BACKEND=postgres DB_HOST=localhost DB_NAME=saayam_local \\
    DB_USER=postgres DB_PASSWORD=postgres \\
        python data-analytics/tests/test_assigned_volunteers.py

Add ``--emit-results`` to also regenerate ``TEST_RESULTS_295.md`` next to this
file, capturing the pass/fail table and sample API responses.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

TESTS_DIR = Path(__file__).resolve().parent
LAMBDA_DIR = TESTS_DIR.parent / "lambda_functions"
for _path in (str(TESTS_DIR), str(LAMBDA_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import mock_db  # noqa: E402
import assigned_volunteers as av  # noqa: E402


REQUEST_ROWS = mock_db.load_requests()
USER_ROWS = mock_db.load_users()
USER_STATUS_ROWS = mock_db.load_user_statuses()
ASSIGNMENT_ROWS = mock_db.load_volunteers_assigned()

REQUEST_BY_ID = {row["req_id"]: row for row in REQUEST_ROWS}
USER_BY_ID = {row["user_id"]: row for row in USER_ROWS}
STATUS_BY_ID = {
    row["user_status_id"]: row["user_status"] for row in USER_STATUS_ROWS
}

# Scenario request ids. These are fixture landmarks, not expected values -
# every expected payload is still computed by ``oracle_assigned``. All but the
# three marked below come from the real committed export.
REQ_SINGLE = "REQ-000007"            # Completed, exactly one assignment
REQ_MULTIPLE = "REQ-000013"          # New, seven concurrent assignments
REQ_MISSING_PROFILE = "REQ-000020"   # Completed, all 3 volunteers absent from users
REQ_NO_ASSIGNMENT = "REQ-000015"     # Completed, no assignment rows at all
REQ_NEW_UNASSIGNED = "REQ-000022"    # New, no rows in the export
REQ_CANCELLED = "REQ-000005"         # Cancelled, 3 rows incl. a superseded pair
REQ_CANCELLED_EMPTY = "REQ-000010"   # Cancelled, no rows
REQ_COMPLETED = "REQ-000002"         # Completed with 4 rows - must NOT suppress
REQ_ON_HOLD = "REQ-000009"           # On Hold, 4 rows - must NOT suppress
REQ_ESCALATED = "REQ-000008"         # Escalated, 5 rows - must NOT suppress
REQ_LEAD_MATCHES = "REQ-000013"      # the one request whose lead is also assigned
REQ_LEAD_UNMATCHED = "REQ-000003"    # lead_volunteer_id names nobody assigned
REQ_NO_LEAD = "REQ-000016"           # lead_volunteer_id is NULL
REQ_UNKNOWN = "REQ-999999"           # not in the requests fixture

# Scenarios the real export cannot reach, supplied by the *_extra_295 fixtures.
REQ_SPECIAL_PROFILES = "REQ-000022"  # NULL contacts / INACTIVE / NULL status
REQ_REASSIGNED = "REQ-000016"        # superseded row + newer row, not cancelled
REQ_TIED_TIMESTAMP = "REQ-000024"    # two rows, identical last_update_date

RESPONSE_KEYS = {"req_id", "lead_volunteer_id", "assignedVolunteers"}

# Volunteers defined in users_extra_295.csv.
VOL_NULL_CONTACT = "SID-00-000-295-001"
VOL_INACTIVE = "SID-00-000-295-002"
VOL_NULL_STATUS = "SID-00-000-295-003"


@contextmanager
def env(**overrides: Any):
    """Temporarily set (or clear, with ``None``) environment variables."""
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# --------------------------------------------------------------------------- #
# Pure-Python oracle, computed straight from the CSV rows
# --------------------------------------------------------------------------- #
def oracle_current_rows(req_id: str) -> list[dict[str, Any]]:
    """Return the current ``volunteers_assigned`` rows for ``req_id``.

    Re-implements the module's rule in Python: newest ``last_update_date`` per
    volunteer, ties broken by the higher ``vol_assigned_id``, ordered
    newest assignment first then by volunteer id.
    """
    newest: dict[str, dict[str, Any]] = {}
    for row in ASSIGNMENT_ROWS:
        if row["req_id"] != req_id:
            continue
        key = row["volunteer_id"]
        current = newest.get(key)
        if current is None or (
            row["last_update_date"],
            row["vol_assigned_id"],
        ) > (current["last_update_date"], current["vol_assigned_id"]):
            newest[key] = row

    # Stable sorts, applied least-significant first, reproduce
    # ORDER BY last_update_date DESC, volunteer_id ASC.
    ordered = sorted(newest.values(), key=lambda r: r["volunteer_id"])
    ordered.sort(key=lambda r: r["last_update_date"], reverse=True)
    return ordered


def oracle_assigned(req_id: str) -> list[dict[str, Any]]:
    """Return the expected ``assignedVolunteers`` payload for ``req_id``."""
    request_row = REQUEST_BY_ID.get(req_id)
    if request_row is None:
        return []
    if request_row["req_status_id"] in av.TERMINAL_REQUEST_STATUS_IDS:
        return []

    lead = request_row.get("lead_volunteer_id")
    expected: list[dict[str, Any]] = []
    for row in oracle_current_rows(req_id):
        user = USER_BY_ID.get(row["volunteer_id"], {})
        expected.append(
            {
                "user_id": row["volunteer_id"],
                "full_name": user.get("full_name"),
                "primary_email_address": user.get("primary_email_address"),
                "primary_phone_number": user.get("primary_phone_number"),
                "user_status": STATUS_BY_ID.get(user.get("user_status_id")),
                "volunteer_type": row["volunteer_type"],
                "assigned_at": row["last_update_date"],
                "is_lead": lead is not None and row["volunteer_id"] == lead,
            }
        )
    return expected


class MockBackedTestCase(unittest.TestCase):
    """Base case giving each test a freshly seeded mock database."""

    def setUp(self) -> None:
        self.connection = mock_db.load_mock_database()
        try:
            from psycopg2.extras import RealDictCursor

            self.cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        except ImportError:  # SQLite backend does not need psycopg2
            self.cursor = self.connection.cursor()
        self.addCleanup(self.connection.close)
        self.addCleanup(self.cursor.close)

    def assigned(self, req_id: str) -> list[dict[str, Any]]:
        """Return the ``assignedVolunteers`` array the Lambda produces."""
        status_code, body = av.build_assigned_volunteers_response(
            self.cursor, req_id
        )
        self.assertEqual(200, status_code)
        return body["assignedVolunteers"]

    def invoke(self, payload: Any) -> tuple[int, Any]:
        """Invoke ``lambda_handler`` against the mock database."""
        original = av.get_db_connection
        av.get_db_connection = mock_db.load_mock_database
        try:
            response = av.lambda_handler(payload)
        finally:
            av.get_db_connection = original
        return response["statusCode"], json.loads(response["body"])


# --------------------------------------------------------------------------- #
# 1. Security posture - carried over from the issue #228 review feedback
# --------------------------------------------------------------------------- #
class TestNoSharedDatabaseAccess(unittest.TestCase):
    """The Lambda must have no route to the shared Saayam database."""

    def test_source_has_no_parameter_store_references(self) -> None:
        """No boto3/SSM/Parameter Store call sites exist in the module."""
        source = (LAMBDA_DIR / "assigned_volunteers.py").read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        body = code.split('"""', 2)[-1]
        for forbidden in ("boto3", "ssm", "get_parameter", "WithDecryption"):
            self.assertNotIn(
                forbidden.lower(),
                body.lower(),
                f"{forbidden!r} still appears in assigned_volunteers.py",
            )

    def test_boto3_is_not_imported(self) -> None:
        """Importing the module never pulls in an AWS client."""
        self.assertFalse(
            hasattr(av, "boto3"),
            "assigned_volunteers must not import boto3",
        )

    def test_missing_db_host_raises_instead_of_falling_back(self) -> None:
        """An unconfigured environment is an error, not a credential lookup."""
        with env(DB_HOST=None):
            with self.assertRaises(RuntimeError):
                av.get_db_connection()

    def test_credentials_are_not_hardcoded(self) -> None:
        """No literal host, user or password appears in the source."""
        source = (LAMBDA_DIR / "assigned_volunteers.py").read_text(encoding="utf-8")
        for forbidden in ("password=\"", "password='", "amazonaws.com", "rds."):
            self.assertNotIn(forbidden, source)


# --------------------------------------------------------------------------- #
# 2. Fixtures - the scenarios the issue asks for must actually be present
# --------------------------------------------------------------------------- #
class TestFixtures(unittest.TestCase):
    """The mock CSVs cover every scenario the issue lists."""

    def test_every_assignment_points_at_a_known_request(self) -> None:
        """No volunteers_assigned row references a missing request."""
        for row in ASSIGNMENT_ROWS:
            self.assertIn(row["req_id"], REQUEST_BY_ID)

    def test_scenario_requests_all_exist(self) -> None:
        """Each landmark req_id is present in the requests fixture."""
        for req_id in (
            REQ_SINGLE, REQ_MULTIPLE, REQ_MISSING_PROFILE, REQ_NO_ASSIGNMENT,
            REQ_NEW_UNASSIGNED, REQ_CANCELLED, REQ_CANCELLED_EMPTY,
            REQ_COMPLETED, REQ_ON_HOLD, REQ_ESCALATED, REQ_LEAD_MATCHES,
            REQ_LEAD_UNMATCHED, REQ_NO_LEAD, REQ_SPECIAL_PROFILES, REQ_REASSIGNED,
            REQ_TIED_TIMESTAMP,
        ):
            self.assertIn(req_id, REQUEST_BY_ID)
        self.assertNotIn(REQ_UNKNOWN, REQUEST_BY_ID)

    def test_cancelled_request_does_have_assignment_rows(self) -> None:
        """The cancelled landmark carries rows, so suppression is real."""
        self.assertTrue(
            [r for r in ASSIGNMENT_ROWS if r["req_id"] == REQ_CANCELLED],
            "REQ_CANCELLED needs rows for the suppression test to mean anything",
        )
        self.assertIn(
            REQUEST_BY_ID[REQ_CANCELLED]["req_status_id"],
            av.TERMINAL_REQUEST_STATUS_IDS,
        )

    def test_non_terminal_landmarks_are_not_suppressed(self) -> None:
        """Completed/On Hold/Escalated landmarks hold rows and are not terminal."""
        for req_id in (REQ_COMPLETED, REQ_ON_HOLD, REQ_ESCALATED):
            self.assertTrue(
                [r for r in ASSIGNMENT_ROWS if r["req_id"] == req_id], req_id
            )
            self.assertNotIn(
                REQUEST_BY_ID[req_id]["req_status_id"],
                av.TERMINAL_REQUEST_STATUS_IDS,
                req_id,
            )

    def test_historical_rows_exist(self) -> None:
        """Some volunteers have more than one row on the same request."""
        for req_id in (REQ_REASSIGNED, REQ_TIED_TIMESTAMP):
            rows = [r for r in ASSIGNMENT_ROWS if r["req_id"] == req_id]
            self.assertGreater(len(rows), len(oracle_current_rows(req_id)))

    def test_volunteers_missing_from_users_exist(self) -> None:
        """The export really does assign volunteers with no users row."""
        unknown = [
            r for r in ASSIGNMENT_ROWS
            if r["req_id"] == REQ_MISSING_PROFILE
            and r["volunteer_id"] not in USER_BY_ID
        ]
        self.assertTrue(unknown)

    def test_null_values_survive_csv_loading(self) -> None:
        """A literal NULL cell loads as None, not the string 'NULL'."""
        volunteer = USER_BY_ID[VOL_NULL_CONTACT]
        self.assertIsNone(volunteer["primary_phone_number"])
        self.assertIsNone(volunteer["primary_email_address"])
        self.assertIsNone(USER_BY_ID[VOL_NULL_STATUS]["user_status_id"])


# --------------------------------------------------------------------------- #
# 3. Step 1 + 2 - request validation
# --------------------------------------------------------------------------- #
class TestRequestValidation(MockBackedTestCase):
    """req_id is required, and the request behind it must exist."""

    def test_valid_req_id_returns_200(self) -> None:
        """A known req_id returns HTTP 200 with the response envelope."""
        status_code, body = self.invoke({"req_id": REQ_SINGLE})
        self.assertEqual(200, status_code)
        self.assertEqual(RESPONSE_KEYS, set(body))
        self.assertEqual(REQ_SINGLE, body["req_id"])

    def test_missing_req_id_returns_400(self) -> None:
        """An empty payload returns 400 {'error': 'req_id is required'}."""
        status_code, body = self.invoke({})
        self.assertEqual(400, status_code)
        self.assertEqual({"error": "req_id is required"}, body)

    def test_blank_req_id_returns_400(self) -> None:
        """A whitespace-only req_id is rejected the same way."""
        for value in ("", "   ", "\t"):
            status_code, body = self.invoke({"req_id": value})
            self.assertEqual(400, status_code, value)
            self.assertEqual({"error": "req_id is required"}, body)

    def test_non_string_req_id_returns_400(self) -> None:
        """A numeric or null req_id is rejected rather than coerced."""
        for value in (None, 42, [], {"nested": True}):
            status_code, body = self.invoke({"req_id": value})
            self.assertEqual(400, status_code, repr(value))
            self.assertEqual({"error": "req_id is required"}, body)

    def test_unknown_req_id_returns_404(self) -> None:
        """A well-formed but nonexistent req_id returns 404, not 200."""
        status_code, body = self.invoke({"req_id": REQ_UNKNOWN})
        self.assertEqual(404, status_code)
        self.assertIn("error", body)
        self.assertIn(REQ_UNKNOWN, body["error"])

    def test_req_id_is_trimmed(self) -> None:
        """Surrounding whitespace does not turn a valid id into a 404."""
        status_code, body = self.invoke({"req_id": f"  {REQ_SINGLE}  "})
        self.assertEqual(200, status_code)
        self.assertEqual(REQ_SINGLE, body["req_id"])

    def test_no_query_runs_when_validation_fails(self) -> None:
        """A 400 is returned without ever opening a connection."""
        def boom() -> Any:
            raise AssertionError("get_db_connection must not be called")

        original = av.get_db_connection
        av.get_db_connection = boom
        try:
            response = av.lambda_handler({})
        finally:
            av.get_db_connection = original
        self.assertEqual(400, response["statusCode"])


# --------------------------------------------------------------------------- #
# 4. Step 3 - current assignment retrieval
# --------------------------------------------------------------------------- #
class TestAssignmentRetrieval(MockBackedTestCase):
    """Current assignments are found, historical ones are not."""

    def test_single_assigned_volunteer(self) -> None:
        """A request with one current volunteer returns exactly that one."""
        result = self.assigned(REQ_SINGLE)
        self.assertEqual(oracle_assigned(REQ_SINGLE), result)
        self.assertEqual(1, len(result))

    def test_multiple_assigned_volunteers(self) -> None:
        """Seven concurrent assignments are all returned, newest first."""
        result = self.assigned(REQ_MULTIPLE)
        self.assertEqual(oracle_assigned(REQ_MULTIPLE), result)
        self.assertEqual(7, len(result))
        timestamps = [str(entry["assigned_at"]) for entry in result]
        self.assertEqual(sorted(timestamps, reverse=True), timestamps)

    def test_no_assigned_volunteer_returns_empty_list(self) -> None:
        """A valid request with no assignment is 200 with [], not an error."""
        status_code, body = self.invoke({"req_id": REQ_NO_ASSIGNMENT})
        self.assertEqual(200, status_code)
        self.assertEqual(REQ_NO_ASSIGNMENT, body["req_id"])
        self.assertEqual([], body["assignedVolunteers"])

    def test_new_request_with_no_assignment_rows(self) -> None:
        """A New request never matched in the export returns its extras only."""
        self.assertEqual(
            oracle_assigned(REQ_NEW_UNASSIGNED), self.assigned(REQ_NEW_UNASSIGNED)
        )

    def test_reassigned_request_returns_only_the_newest_row(self) -> None:
        """A replaced assignment does not appear alongside its replacement."""
        result = self.assigned(REQ_REASSIGNED)
        self.assertEqual(oracle_assigned(REQ_REASSIGNED), result)
        entry = next(e for e in result if e["user_id"] == VOL_NULL_CONTACT)
        self.assertEqual("Primary", entry["volunteer_type"])

    def test_historical_rows_are_excluded(self) -> None:
        """Superseded rows never reach the response."""
        for req_id in (REQ_REASSIGNED, REQ_TIED_TIMESTAMP):
            all_rows = [r for r in ASSIGNMENT_ROWS if r["req_id"] == req_id]
            result = self.assigned(req_id)
            self.assertEqual(oracle_assigned(req_id), result)
            self.assertLess(len(result), len(all_rows))

    def test_one_entry_per_volunteer(self) -> None:
        """A volunteer with several rows appears at most once."""
        for req_id in sorted({r["req_id"] for r in ASSIGNMENT_ROWS}):
            ids = [entry["user_id"] for entry in self.assigned(req_id)]
            self.assertEqual(len(ids), len(set(ids)), req_id)

    def test_tied_timestamps_break_deterministically(self) -> None:
        """Two rows with the same timestamp resolve to the higher id."""
        rows = [
            r for r in ASSIGNMENT_ROWS
            if r["req_id"] == REQ_TIED_TIMESTAMP
            and r["volunteer_id"] == VOL_INACTIVE
        ]
        self.assertEqual(2, len(rows))
        winner = max(rows, key=lambda r: r["vol_assigned_id"])
        entry = next(
            e for e in self.assigned(REQ_TIED_TIMESTAMP)
            if e["user_id"] == VOL_INACTIVE
        )
        self.assertEqual(winner["volunteer_type"], entry["volunteer_type"])

    def test_cancelled_request_has_no_current_assignment(self) -> None:
        """A Cancelled request returns [] despite holding assignment rows."""
        status_code, body = self.invoke({"req_id": REQ_CANCELLED})
        self.assertEqual(200, status_code)
        self.assertEqual([], body["assignedVolunteers"])

    def test_completed_request_still_reports_its_volunteers(self) -> None:
        """Completed is deliberately not terminal - reviewers need the names."""
        result = self.assigned(REQ_COMPLETED)
        self.assertEqual(oracle_assigned(REQ_COMPLETED), result)
        self.assertTrue(result)

    def test_on_hold_and_escalated_keep_their_volunteers(self) -> None:
        """Paused or raised requests are not ended, so assignments survive."""
        for req_id in (REQ_ON_HOLD, REQ_ESCALATED):
            result = self.assigned(req_id)
            self.assertEqual(oracle_assigned(req_id), result, req_id)
            self.assertTrue(result, req_id)

    def test_assignments_do_not_leak_across_requests(self) -> None:
        """Every returned entry belongs to the requested req_id only."""
        for req_id in {r["req_id"] for r in ASSIGNMENT_ROWS}:
            expected_ids = {r["volunteer_id"] for r in oracle_current_rows(req_id)}
            if REQUEST_BY_ID[req_id]["req_status_id"] in (
                av.TERMINAL_REQUEST_STATUS_IDS
            ):
                expected_ids = set()
            actual_ids = {entry["user_id"] for entry in self.assigned(req_id)}
            self.assertEqual(expected_ids, actual_ids, req_id)

    def test_matches_the_oracle_for_every_request_in_the_fixture(self) -> None:
        """The SQL and the Python rule agree on every request in the export."""
        for req_id in sorted(REQUEST_BY_ID):
            self.assertEqual(oracle_assigned(req_id), self.assigned(req_id), req_id)


# --------------------------------------------------------------------------- #
# 5. Step 4 - volunteer details
# --------------------------------------------------------------------------- #
class TestVolunteerData(MockBackedTestCase):
    """Profile, status and assignment metadata are joined correctly."""

    def test_complete_profile_is_returned(self) -> None:
        """A fully populated volunteer returns every response field."""
        entry = self.assigned(REQ_SINGLE)[0]
        user = USER_BY_ID[entry["user_id"]]
        self.assertEqual(user["full_name"], entry["full_name"])
        self.assertEqual(
            user["primary_email_address"], entry["primary_email_address"]
        )
        self.assertEqual(
            user["primary_phone_number"], entry["primary_phone_number"]
        )
        self.assertIsNone(
            next((v for v in entry.values() if v is None), None),
            "the complete-profile fixture should have no NULL fields",
        )

    def test_every_entry_has_the_full_key_set(self) -> None:
        """The response shape is stable regardless of NULL columns."""
        for req_id in sorted({r["req_id"] for r in ASSIGNMENT_ROWS}):
            for entry in self.assigned(req_id):
                self.assertEqual(set(av.VOLUNTEER_FIELDS), set(entry), req_id)

    def test_null_contact_details_do_not_drop_the_volunteer(self) -> None:
        """NULL email/phone surface as null instead of failing or filtering."""
        entry = next(
            e for e in self.assigned(REQ_SPECIAL_PROFILES)
            if e["user_id"] == VOL_NULL_CONTACT
        )
        self.assertIsNone(entry["primary_email_address"])
        self.assertIsNone(entry["primary_phone_number"])
        self.assertIsNotNone(entry["full_name"])

    def test_missing_user_row_does_not_drop_the_volunteer(self) -> None:
        """An assignment with no users row still reports the volunteer id."""
        result = self.assigned(REQ_MISSING_PROFILE)
        self.assertTrue(result)
        unknown = [e for e in result if e["user_id"] not in USER_BY_ID]
        self.assertTrue(unknown)
        for entry in unknown:
            self.assertIsNone(entry["full_name"])
            self.assertIsNone(entry["user_status"])
            self.assertIsNotNone(entry["volunteer_type"])

    def test_user_status_is_resolved_from_the_lookup(self) -> None:
        """user_status comes from the user_status join, not the raw id."""
        entry = next(
            e for e in self.assigned(REQ_SPECIAL_PROFILES)
            if e["user_id"] == VOL_NULL_CONTACT
        )
        self.assertEqual("ACTIVE", entry["user_status"])

    def test_inactive_volunteer_is_still_returned(self) -> None:
        """A changed user status does not remove a current assignee."""
        entry = next(
            e for e in self.assigned(REQ_SPECIAL_PROFILES)
            if e["user_id"] == VOL_INACTIVE
        )
        self.assertEqual("INACTIVE", entry["user_status"])

    def test_null_user_status_id_yields_null_status(self) -> None:
        """A NULL user_status_id reports null rather than failing the join."""
        entry = next(
            e for e in self.assigned(REQ_SPECIAL_PROFILES)
            if e["user_id"] == VOL_NULL_STATUS
        )
        self.assertIsNone(entry["user_status"])
        self.assertIsNotNone(entry["full_name"])

    def test_assignment_metadata_is_returned(self) -> None:
        """volunteer_type and assigned_at come from volunteers_assigned."""
        expected = oracle_current_rows(REQ_MULTIPLE)
        result = self.assigned(REQ_MULTIPLE)
        self.assertEqual(
            [row["volunteer_type"] for row in expected],
            [entry["volunteer_type"] for entry in result],
        )
        self.assertEqual(
            [str(row["last_update_date"]) for row in expected],
            [str(entry["assigned_at"]) for entry in result],
        )


# --------------------------------------------------------------------------- #
# 5b. The lead volunteer - reported, never reconciled
# --------------------------------------------------------------------------- #
class TestLeadVolunteer(MockBackedTestCase):
    """requests.lead_volunteer_id is echoed and flagged, never used to filter."""

    def test_lead_volunteer_id_is_echoed(self) -> None:
        """The request's own lead_volunteer_id is returned at the top level."""
        status_code, body = self.invoke({"req_id": REQ_LEAD_MATCHES})
        self.assertEqual(200, status_code)
        self.assertEqual(
            REQUEST_BY_ID[REQ_LEAD_MATCHES]["lead_volunteer_id"],
            body["lead_volunteer_id"],
        )

    def test_null_lead_volunteer_id_is_reported_as_null(self) -> None:
        """A request with no lead reports null rather than omitting the key."""
        status_code, body = self.invoke({"req_id": REQ_NO_LEAD})
        self.assertEqual(200, status_code)
        self.assertIn("lead_volunteer_id", body)
        self.assertIsNone(body["lead_volunteer_id"])

    def test_is_lead_marks_the_matching_volunteer(self) -> None:
        """is_lead is true exactly for the request's lead_volunteer_id."""
        lead = REQUEST_BY_ID[REQ_LEAD_MATCHES]["lead_volunteer_id"]
        result = self.assigned(REQ_LEAD_MATCHES)
        flagged = [e["user_id"] for e in result if e["is_lead"]]
        self.assertEqual([lead], flagged)

    def test_is_lead_is_false_when_no_lead_is_set(self) -> None:
        """A NULL lead_volunteer_id never flags anybody."""
        for entry in self.assigned(REQ_NO_LEAD):
            self.assertFalse(entry["is_lead"])

    def test_lead_does_not_filter_the_array(self) -> None:
        """Volunteers who are not the lead are still returned."""
        result = self.assigned(REQ_LEAD_MATCHES)
        self.assertGreater(len(result), len([e for e in result if e["is_lead"]]))

    def test_unmatched_lead_flags_nobody(self) -> None:
        """A lead who holds no assignment row leaves every is_lead false."""
        result = self.assigned(REQ_LEAD_UNMATCHED)
        self.assertTrue(result)
        self.assertFalse([e for e in result if e["is_lead"]])

    def test_lead_without_an_assignment_row_is_not_fabricated(self) -> None:
        """A lead with no volunteers_assigned row is never added to the array."""
        checked = 0
        for req_id, request_row in REQUEST_BY_ID.items():
            lead = request_row["lead_volunteer_id"]
            if not lead:
                continue
            if any(r["volunteer_id"] == lead for r in oracle_current_rows(req_id)):
                continue
            checked += 1
            self.assertNotIn(
                lead, [e["user_id"] for e in self.assigned(req_id)], req_id
            )
        self.assertTrue(checked, "fixture should have unmatched lead ids")


# --------------------------------------------------------------------------- #
# 6. General / failure scenarios
# --------------------------------------------------------------------------- #
class TestFailureScenarios(MockBackedTestCase):
    """Connection and query failures degrade to a clean 500."""

    def test_database_connection_failure_returns_500(self) -> None:
        """A refused connection returns 500 without leaking details."""
        original = av.get_db_connection

        def boom() -> Any:
            raise RuntimeError("connection refused to 10.0.0.5")

        av.get_db_connection = boom
        try:
            response = av.lambda_handler({"req_id": REQ_SINGLE})
        finally:
            av.get_db_connection = original
        self.assertEqual(500, response["statusCode"])
        body = json.loads(response["body"])
        self.assertEqual({"error": "internal server error"}, body)
        self.assertNotIn("10.0.0.5", response["body"])

    def test_query_execution_failure_returns_500(self) -> None:
        """A failing statement returns 500 rather than a partial payload."""
        class FailingCursor:
            def execute(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("simulated query failure")

            def close(self) -> None:
                pass

        class FailingConnection:
            def cursor(self, cursor_factory: Any = None) -> FailingCursor:
                return FailingCursor()

            def close(self) -> None:
                pass

        original = av.get_db_connection
        av.get_db_connection = FailingConnection
        try:
            response = av.lambda_handler({"req_id": REQ_SINGLE})
        finally:
            av.get_db_connection = original
        self.assertEqual(500, response["statusCode"])
        self.assertEqual(
            {"error": "internal server error"}, json.loads(response["body"])
        )

    def test_empty_result_set_is_not_an_error(self) -> None:
        """An empty assignment set is a 200, distinguishable from a failure."""
        status_code, body = self.invoke({"req_id": REQ_NO_ASSIGNMENT})
        self.assertEqual(200, status_code)
        self.assertNotIn("error", body)
        self.assertEqual([], body["assignedVolunteers"])

    @unittest.skipUnless(
        mock_db.active_backend() == "sqlite",
        "executed SQL is only recorded by the SQLite shim",
    )
    def test_req_id_is_bound_never_interpolated(self) -> None:
        """The request id is passed as a parameter, not spliced into SQL."""
        injection = "REQ-1' OR '1'='1"
        av.build_assigned_volunteers_response(self.cursor, injection)
        for statement in self.connection.executed_sql:
            self.assertNotIn(injection, statement)
            self.assertIn("%s", statement)

    @unittest.skipUnless(
        mock_db.active_backend() == "sqlite",
        "executed SQL is only recorded by the SQLite shim",
    )
    def test_no_n_plus_one_queries(self) -> None:
        """Many assigned volunteers still cost the same two statements."""
        self.connection.executed_sql.clear()
        result = av.build_assigned_volunteers_response(self.cursor, REQ_MULTIPLE)
        self.assertGreater(len(result[1]["assignedVolunteers"]), 1)
        self.assertEqual(2, len(self.connection.executed_sql))

    def test_sql_injection_attempt_returns_404(self) -> None:
        """An injected predicate matches no request rather than every one."""
        status_code, body = self.invoke({"req_id": "REQ-1' OR '1'='1"})
        self.assertEqual(404, status_code)
        self.assertIn("error", body)


# --------------------------------------------------------------------------- #
# 7. Handler contract
# --------------------------------------------------------------------------- #
class TestLambdaHandler(MockBackedTestCase):
    """The API Gateway proxy envelope is well formed."""

    def test_body_is_a_json_string(self) -> None:
        """The proxy body is serialized text, not a dict."""
        original = av.get_db_connection
        av.get_db_connection = mock_db.load_mock_database
        try:
            response = av.lambda_handler({"req_id": REQ_SINGLE})
        finally:
            av.get_db_connection = original
        self.assertIsInstance(response["body"], str)
        self.assertEqual(RESPONSE_KEYS, set(json.loads(response["body"])))

    def test_cors_headers_are_present(self) -> None:
        """Every response carries the shared CORS headers."""
        response = av.build_response(200, {"ok": True})
        self.assertEqual("application/json", response["headers"]["Content-Type"])
        self.assertEqual("*", response["headers"]["Access-Control-Allow-Origin"])

    def test_accepts_a_json_string_body(self) -> None:
        """An API Gateway proxy event with a JSON string body is parsed."""
        status_code, body = self.invoke(
            {"body": json.dumps({"req_id": REQ_SINGLE})}
        )
        self.assertEqual(200, status_code)
        self.assertEqual(REQ_SINGLE, body["req_id"])

    def test_accepts_a_dict_body(self) -> None:
        """A dict body is accepted as-is."""
        status_code, body = self.invoke({"body": {"req_id": REQ_SINGLE}})
        self.assertEqual(200, status_code)
        self.assertEqual(REQ_SINGLE, body["req_id"])

    def test_accepts_a_top_level_payload(self) -> None:
        """A direct invocation payload works without a body wrapper."""
        status_code, body = self.invoke({"req_id": REQ_SINGLE})
        self.assertEqual(200, status_code)
        self.assertEqual(REQ_SINGLE, body["req_id"])

    def test_malformed_json_body_is_a_400(self) -> None:
        """An unparseable body degrades to the missing-req_id error."""
        status_code, body = self.invoke({"body": "{not json"})
        self.assertEqual(400, status_code)
        self.assertEqual({"error": "req_id is required"}, body)

    def test_none_event_is_a_400(self) -> None:
        """A null event is rejected rather than raising."""
        status_code, body = self.invoke(None)
        self.assertEqual(400, status_code)
        self.assertEqual({"error": "req_id is required"}, body)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
class _RecordingResult(unittest.TextTestResult):
    """Collects an ordered pass/fail record for the markdown report."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.records: list[tuple[str, str, str, str]] = []

    def _record(self, test: unittest.TestCase, outcome: str) -> None:
        self.records.append(
            (
                type(test).__name__,
                test._testMethodName,
                (test.shortDescription() or "").strip(),
                outcome,
            )
        )

    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        self._record(test, "PASS")

    def addFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addFailure(test, err)
        self._record(test, "FAIL")

    def addError(self, test: unittest.TestCase, err: Any) -> None:
        super().addError(test, err)
        self._record(test, "ERROR")

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        self._record(test, "SKIP")


_SECTION_TITLES = {
    "TestNoSharedDatabaseAccess": "No shared-database access",
    "TestFixtures": "Mock fixtures",
    "TestRequestValidation": "Steps 1-2 - request validation",
    "TestAssignmentRetrieval": "Step 3 - current assignment retrieval",
    "TestVolunteerData": "Step 4 - volunteer details",
    "TestLeadVolunteer": "Lead volunteer (requests.lead_volunteer_id)",
    "TestFailureScenarios": "General / failure scenarios",
    "TestLambdaHandler": "Lambda handler contract",
}

SAMPLE_PAYLOADS = {
    "One assigned volunteer": {"req_id": REQ_SINGLE},
    "Multiple assigned volunteers": {"req_id": REQ_MULTIPLE},
    "Reassigned request - only the current volunteer": {"req_id": REQ_REASSIGNED},
    "NULL contacts, inactive volunteer, NULL status": {
        "req_id": REQ_SPECIAL_PROFILES
    },
    "Volunteers with no users row": {"req_id": REQ_MISSING_PROFILE},
    "Lead volunteer flagged": {"req_id": REQ_LEAD_MATCHES},
    "Completed request - volunteers still reported": {"req_id": REQ_COMPLETED},
    "No current assignment": {"req_id": REQ_NO_ASSIGNMENT},
    "Cancelled request": {"req_id": REQ_CANCELLED},
    "Validation error - missing req_id": {},
    "Unknown req_id": {"req_id": REQ_UNKNOWN},
}


def _sample_responses() -> list[tuple[str, Any, dict[str, Any]]]:
    """Produce the sample request/response pairs recorded in the report."""
    original = av.get_db_connection
    av.get_db_connection = mock_db.load_mock_database
    try:
        samples: list[tuple[str, Any, dict[str, Any]]] = []
        for title, payload in SAMPLE_PAYLOADS.items():
            response = av.lambda_handler(dict(payload))
            samples.append((title, payload, {
                "statusCode": response["statusCode"],
                "body": json.loads(response["body"]),
            }))

        def boom() -> Any:
            raise RuntimeError("simulated database outage")

        av.get_db_connection = boom
        outage = av.lambda_handler({"req_id": REQ_SINGLE})
        samples.append((
            "Database failure - connection refused",
            {"req_id": REQ_SINGLE},
            {"statusCode": outage["statusCode"], "body": json.loads(outage["body"])},
        ))
        return samples
    finally:
        av.get_db_connection = original


def emit_results(
    result: _RecordingResult,
    duration: float,
    backend: str,
    coverage: list[tuple[str, str, Optional[_RecordingResult], float]],
) -> Path:
    """Write ``TEST_RESULTS_295.md`` beside this file and return its path."""
    total = len(result.records)
    passed = sum(1 for r in result.records if r[3] == "PASS")
    skipped = sum(1 for r in result.records if r[3] == "SKIP")
    failed = total - passed - skipped

    lines: list[str] = []
    add = lines.append
    add("# Assigned Volunteers API - Test Results (Issue #295)")
    add("")
    add(f"**{passed}/{total} checks passed**"
        + (f", {failed} failed" if failed else "")
        + (f", {skipped} skipped" if skipped else "")
        + f" in {duration:.2f}s on the `{backend}` backend.")
    add("")
    add("| | |")
    add("|---|---|")
    add("| Endpoint | `POST /volunteers/assigned` |")
    add("| Module under test | `data-analytics/lambda_functions/assigned_volunteers.py` |")
    add("| Data source | mock fixtures only - `requests.csv`, `users.csv`, "
        "`users_extra_295.csv`, `user_status.csv`, `volunteers_assigned.csv`, "
        "`volunteers_assigned_extra_295.csv` |")
    add(f"| Requests in fixture | {len(REQUEST_ROWS)} |")
    add(f"| Terminal statuses | {av.TERMINAL_REQUEST_STATUS_IDS} (Cancelled only) |")
    add(f"| Users in fixture | {len(USER_ROWS)} |")
    add(f"| Assignment rows in fixture | {len(ASSIGNMENT_ROWS)} |")
    add(f"| Python | {sys.version.split()[0]} |")
    add("| AWS / Parameter Store access | none - no boto3 import, no SSM call path |")
    add("")
    add("### Current-assignment rule under test")
    add("")
    add("`volunteers_assigned` has no assignment-status column and no active flag, "
        "so \"current\" is defined by the Lambda: the newest `last_update_date` row "
        "per `(req_id, volunteer_id)` - ties broken by the higher "
        "`vol_assigned_id` - and nothing at all for a Cancelled request "
        "(`req_status_id` 4). The suite re-implements "
        "that rule in Python straight from the CSVs and compares it against what the "
        "SQL returns.")
    add("")
    add("### Backend coverage")
    add("")
    add("| Backend | Engine | Result |")
    add("|---|---|---|")
    for name, engine, run, secs in coverage:
        if run is None:
            add(f"| `{name}` | {engine} | not run |")
            continue
        run_total = len(run.records)
        run_passed = sum(1 for r in run.records if r[3] == "PASS")
        run_skipped = sum(1 for r in run.records if r[3] == "SKIP")
        run_failed = run_total - run_passed - run_skipped
        verdict = f"{run_passed}/{run_total} passed"
        if run_skipped:
            verdict += f", {run_skipped} skipped"
        if run_failed:
            verdict += f", {run_failed} FAILED"
        add(f"| `{name}` | {engine} | {verdict} in {secs:.2f}s |")
    add("")
    add("Reproduce with:")
    add("")
    add("```bash")
    add("# zero-setup run (SQLite shim)")
    add("python data-analytics/tests/test_assigned_volunteers.py --emit-results")
    add("")
    add("# against a local PostgreSQL")
    add("docker run -d --name saayam-pg -e POSTGRES_PASSWORD=postgres \\")
    add("    -e POSTGRES_DB=saayam_local -p 55432:5432 postgres:16-alpine")
    add("MOCK_DB_BACKEND=postgres DB_HOST=localhost DB_PORT=55432 \\")
    add("DB_NAME=saayam_local DB_USER=postgres DB_PASSWORD=postgres \\")
    add("    python data-analytics/tests/test_assigned_volunteers.py")
    add("```")
    add("")
    add("---")
    add("")
    add("## Checks")
    add("")

    by_class: dict[str, list[tuple[str, str, str, str]]] = {}
    for record in result.records:
        by_class.setdefault(record[0], []).append(record)

    for cls in _SECTION_TITLES:
        records = by_class.get(cls)
        if not records:
            continue
        add(f"### {_SECTION_TITLES[cls]}")
        add("")
        add("| Result | Check | What it verifies |")
        add("|---|---|---|")
        for _cls, name, doc, outcome in records:
            add(f"| {outcome} | `{name}` | {doc} |")
        add("")

    add("---")
    add("")
    add("## Sample API responses")
    add("")
    add("Generated by invoking `lambda_handler` against the mock fixtures.")
    add("")
    for title, event, response in _sample_responses():
        add(f"### {title}")
        add("")
        add("Request:")
        add("")
        add("```json")
        add(json.dumps(event, indent=2, default=str))
        add("```")
        add("")
        add(f"Response (HTTP {response['statusCode']}):")
        add("")
        add("```json")
        add(json.dumps(response["body"], indent=2, default=str))
        add("```")
        add("")

    add("---")
    add("")
    add("## Notes")
    add("")
    add("- A valid request with no current assignment is **not** an error: it returns "
        "HTTP 200 with an empty `assignedVolunteers` array. Only a missing `req_id` "
        "(400), an unknown `req_id` (404) and a database failure (500) are errors.")
    add("- Volunteer profile and status are joined with `LEFT JOIN`, so a volunteer "
        "with NULL contact details, a NULL `user_status_id`, or no `users` row at all "
        "is still reported rather than silently dropped.")
    add("- A volunteer is never removed from the response because their user status "
        "changed. `SID-00-000-295-002` is INACTIVE and still returned, with the "
        "status reported as informational data.")
    add("- `user_status.csv` holds the single real lookup row (`1 ACTIVE`) plus two "
        "mock-only rows (`2 INACTIVE`, `3 SUSPENDED`) that exist solely so "
        "non-ACTIVE status handling can be exercised.")
    add("- Only four scenarios the real export cannot express live in the "
        "`*_extra_295` fixtures; they are unioned in rather than appended to the "
        "exports, so regenerating `requests.csv`, `users.csv` or "
        "`volunteers_assigned.csv` cannot silently delete them.")
    add("- `Completed` requests deliberately still report their volunteers - only "
        "`Cancelled` (4) suppresses the array. `requests.lead_volunteer_id` is "
        "echoed and flagged via `is_lead` but never reconciled: in this fixture it "
        "matches an assignment row in only 1 of 20 cases.")
    add("- Suggested indexes for the production tables: "
        "`volunteers_assigned(req_id)` and "
        "`volunteers_assigned(req_id, volunteer_id, last_update_date)` to serve "
        "the lookup and the anti-join, plus the existing `request(req_id)` and "
        "`users(user_id)` primary keys.")

    path = TESTS_DIR / "TEST_RESULTS_295.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run_suite(verbosity: int = 1) -> tuple[_RecordingResult, float]:
    """Run the whole module's suite once and return its result and duration."""
    import time

    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None  # keep declaration order in the report
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    started = time.perf_counter()
    runner = unittest.TextTestRunner(verbosity=verbosity, resultclass=_RecordingResult)
    result = runner.run(suite)
    return result, time.perf_counter() - started


def _postgres_reachable() -> bool:
    """Report whether a local PostgreSQL is configured and accepting fixtures."""
    if not os.environ.get("DB_HOST"):
        return False
    try:
        connection = mock_db._build_postgres()
    except Exception as exc:  # noqa: BLE001 - availability probe only
        print(f"[tests] PostgreSQL backend unavailable: {exc}")
        return False
    connection.close()
    return True


def _describe_engine(backend: str) -> str:
    """Return a human-readable engine label for the report."""
    if backend == "sqlite":
        import sqlite3

        return f"SQLite {sqlite3.sqlite_version} (in-memory, PostgreSQL shim)"
    try:
        connection = mock_db._build_postgres()
        with connection.cursor() as cursor:
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0]
        connection.close()
        return version.split(" on ")[0].strip()
    except Exception:  # noqa: BLE001
        return "PostgreSQL (local)"


def main() -> int:
    """Run the suite, optionally regenerating ``TEST_RESULTS_295.md``."""
    emit = "--emit-results" in sys.argv
    verbosity = 2 if "-v" in sys.argv else 1

    if not emit:
        result, _ = _run_suite(verbosity)
        return 0 if result.wasSuccessful() else 1

    coverage: list[tuple[str, str, Optional[_RecordingResult], float]] = []
    detailed: Optional[tuple[_RecordingResult, float, str]] = None
    ok = True

    for backend in ("sqlite", "postgres"):
        if backend == "postgres" and not _postgres_reachable():
            coverage.append((backend, "PostgreSQL (local)", None, 0.0))
            continue
        with env(MOCK_DB_BACKEND=backend):
            print(f"\n===== backend: {backend} =====")
            engine = _describe_engine(backend)
            result, duration = _run_suite(verbosity)
            coverage.append((backend, engine, result, duration))
            ok = ok and result.wasSuccessful()
            detailed = (result, duration, backend)

    if detailed is None:
        print("No backend could be run.")
        return 1

    result, duration, backend = detailed
    with env(MOCK_DB_BACKEND=backend):
        path = emit_results(result, duration, backend, coverage)
    print(f"\nWrote {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
