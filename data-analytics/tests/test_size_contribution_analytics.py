"""Mock-backed test suite for the Size & Contribution Analytics API (Issue #376).

Every assertion runs against the committed mock fixtures in
``data-analytics/sql`` (``organizations.csv``, ``state.csv``, ``country.csv``).
Nothing in this suite reaches a database: the Lambda's mock path is pandas over
CSVs, and the PostgreSQL path is never entered.

Expected values are derived from the CSVs at runtime rather than hard-coded, so
the suite keeps passing when the fixtures are regenerated. The fixed buckets are
computed against a **pinned reference date** so 7D/30D/1Y windows do not drift
as real time passes.

Two things the committed fixture cannot express, covered with synthetic frames:

* ``is_collaborator`` and ``is_contributor`` never overlap in the fixture (21
  and 19 of 40, with zero organizations both or neither), so it cannot show
  that the two counts are independent rather than a partition.
* ``is_contributor`` is always present, so it cannot show the column degrading
  to ``0`` when absent.

Run it:

    python data-analytics/tests/test_size_contribution_analytics.py

Add ``--emit-results`` to also regenerate ``TEST_RESULTS_376.md`` next to this
file, capturing the pass/fail table and sample API responses.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

TESTS_DIR = Path(__file__).resolve().parent
LAMBDA_DIR = TESTS_DIR.parent / "lambda_functions"
SQL_DIR = TESTS_DIR.parent / "sql"
for _path in (str(TESTS_DIR), str(LAMBDA_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import size_contribution_analytics as sca  # noqa: E402


# A pinned reference date keeps the fixed-bucket windows deterministic. It is
# deliberately close to the fixture's newest created_at so 1Y is non-empty.
REFERENCE_DATE = date(2026, 9, 25)

ORGANIZATION_ROWS = sca.load_organizations(str(SQL_DIR))
TOTAL_ORGANIZATIONS = len(ORGANIZATION_ROWS)

BUCKET_KEYS = {"organizations_by_size", "collaborator_vs_contributor"}
FULL_TOP_LEVEL_KEYS = {"7D", "30D", "1Y", "All", "Custom"}

# The fixture's US states all carry country_id=1, which country.csv maps to
# AFGHANISTAN/AFG - so this, not "USA", is the country that actually matches.
FIXTURE_COUNTRY_CODE = "AFG"
FIXTURE_COUNTRY_NAME = "AFGHANISTAN"


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


def invoke(payload: Any) -> tuple[int, Any]:
    """Invoke the handler against the committed fixtures."""
    with env(MOCK_DATA_DIR=str(SQL_DIR), USE_MOCK_DATA="true"):
        response = sca.lambda_handler(payload)
    return response["statusCode"], json.loads(response["body"])


def analytics(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the response body directly, with the reference date pinned."""
    filters = sca.extract_filters(payload)
    return sca.build_analytics(ORGANIZATION_ROWS, filters, today=REFERENCE_DATE)


def oracle_frame(
    country: Optional[str] = None, organization_type: Optional[str] = None
) -> pd.DataFrame:
    """Filter the fixture in pandas, mirroring the Lambda's filters."""
    frame = ORGANIZATION_ROWS
    if country is not None:
        key = sca._normalize_key(country)
        codes = frame["country_code"].map(sca._normalize_key)
        names = frame["country_name"].map(sca._normalize_key)
        frame = frame[(codes == key) | (names == key)]
    if organization_type is not None:
        key = sca._normalize_key(organization_type)
        frame = frame[frame["org_type"].map(sca._normalize_key) == key]
    return frame


def synthetic_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a small organizations frame in the shape the charts expect."""
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "org_id", "org_size", "org_type", "is_collaborator",
                "is_contributor", "created_at", "country_code", "country_name",
            ]
        )
    frame["created_at"] = pd.to_datetime(frame["created_at"])
    return frame


# --------------------------------------------------------------------------- #
# 1. Fixtures - what the committed data can and cannot prove
# --------------------------------------------------------------------------- #
class TestFixtures(unittest.TestCase):
    """The committed CSVs load and carry the columns the charts need."""

    def test_organizations_load(self) -> None:
        """The three CSVs resolve and join into a usable frame."""
        self.assertGreater(TOTAL_ORGANIZATIONS, 0)
        for column in ("org_id", "org_size", "org_type", "created_at"):
            self.assertIn(column, ORGANIZATION_ROWS.columns)

    def test_singular_filenames_resolve(self) -> None:
        """state.csv/country.csv are found even though the issue says plural."""
        self.assertTrue(sca._resolve_csv("states", str(SQL_DIR)).endswith("state.csv"))
        self.assertTrue(
            sca._resolve_csv("countries", str(SQL_DIR)).endswith("country.csv")
        )

    def test_missing_csv_is_reported_clearly(self) -> None:
        """A directory with no fixtures raises a named error, not a KeyError."""
        with self.assertRaises(sca.MockDataError):
            sca._resolve_csv("organizations", str(TESTS_DIR))

    def test_booleans_parsed_from_uppercase_text(self) -> None:
        """The fixture's TRUE/FALSE strings become a real boolean dtype."""
        self.assertEqual("bool", ORGANIZATION_ROWS["is_collaborator"].dtype.name)
        self.assertEqual("bool", ORGANIZATION_ROWS["is_contributor"].dtype.name)

    def test_fixture_cannot_show_flag_overlap(self) -> None:
        """Records why the independence tests use a synthetic frame instead."""
        both = ORGANIZATION_ROWS["is_collaborator"] & ORGANIZATION_ROWS["is_contributor"]
        neither = (
            ~ORGANIZATION_ROWS["is_collaborator"] & ~ORGANIZATION_ROWS["is_contributor"]
        )
        self.assertEqual(0, int(both.sum()))
        self.assertEqual(0, int(neither.sum()))


# --------------------------------------------------------------------------- #
# 2. Response shape - no Custom pair
# --------------------------------------------------------------------------- #
class TestFullResponseShape(unittest.TestCase):
    """With no Custom pair, all four fixed buckets plus an empty Custom."""

    def test_empty_body_has_exactly_five_keys(self) -> None:
        """An empty request returns exactly 7D, 30D, 1Y, All and Custom."""
        status_code, body = invoke({})
        self.assertEqual(200, status_code)
        self.assertEqual(FULL_TOP_LEVEL_KEYS, set(body))

    def test_every_bucket_has_exactly_two_chart_keys(self) -> None:
        """No bucket carries any key beyond the two charts."""
        body = analytics({})
        for bucket, charts in body.items():
            self.assertEqual(BUCKET_KEYS, set(charts), bucket)

    def test_custom_is_empty_when_no_range_supplied(self) -> None:
        """Custom is present but both its arrays are empty."""
        self.assertEqual(sca.empty_bucket(), analytics({})["Custom"])

    def test_all_bucket_counts_every_organization(self) -> None:
        """The unbounded All bucket sees the whole fixture."""
        sizes = analytics({})["All"]["organizations_by_size"]
        self.assertEqual(
            TOTAL_ORGANIZATIONS, sum(row["count"] for row in sizes)
        )

    def test_size_counts_sum_to_the_window_total(self) -> None:
        """Every bucket's size counts sum to that window's organization count."""
        for bucket in sca.FIXED_BUCKETS:
            start, end = sca.bucket_window(bucket, REFERENCE_DATE)
            expected = len(sca.window_frame(ORGANIZATION_ROWS, start, end))
            sizes = analytics({})[bucket]["organizations_by_size"]
            self.assertEqual(expected, sum(row["count"] for row in sizes), bucket)

    def test_raw_enum_values_are_emitted(self) -> None:
        """Size categories use the stored casing, not a normalized form."""
        sizes = {row["size"] for row in analytics({})["All"]["organizations_by_size"]}
        self.assertEqual(set(ORGANIZATION_ROWS["org_size"].dropna()), sizes)

    def test_categories_are_not_zero_filled(self) -> None:
        """Only categories present in the window appear."""
        frame = synthetic_frame([
            {"org_id": "A", "org_size": "Small", "org_type": "Non-Profit",
             "is_collaborator": True, "is_contributor": False,
             "created_at": "2026-01-01", "country_code": "AFG",
             "country_name": "AFGHANISTAN"},
        ])
        self.assertEqual(
            [{"size": "Small", "count": 1}], sca.build_size_chart(frame)
        )


# --------------------------------------------------------------------------- #
# 3. Bucket windows
# --------------------------------------------------------------------------- #
class TestBucketWindows(unittest.TestCase):
    """Fixed windows are inclusive of today and of their first day."""

    def test_windows_are_inclusive_of_today(self) -> None:
        """7D covers today plus the previous six dates."""
        start, end = sca.bucket_window("7D", REFERENCE_DATE)
        self.assertEqual(REFERENCE_DATE, end)
        self.assertEqual(REFERENCE_DATE - timedelta(days=6), start)

    def test_all_bucket_is_unbounded(self) -> None:
        """All has no bounds at all, rather than a very wide range."""
        self.assertEqual((None, None), sca.bucket_window("All", REFERENCE_DATE))

    def test_end_date_is_inclusive_of_the_whole_day(self) -> None:
        """A row timestamped late on the end date is still inside the window."""
        frame = synthetic_frame([
            {"org_id": "A", "org_size": "Small", "org_type": "Non-Profit",
             "is_collaborator": True, "is_contributor": False,
             "created_at": "2026-03-05 23:59:00", "country_code": "AFG",
             "country_name": "AFGHANISTAN"},
        ])
        windowed = sca.window_frame(frame, date(2026, 3, 1), date(2026, 3, 5))
        self.assertEqual(1, len(windowed))

    def test_empty_window_returns_empty_arrays(self) -> None:
        """A bucket with no organizations returns [], and does not crash."""
        bucket = sca.build_bucket(
            ORGANIZATION_ROWS, date(1999, 1, 1), date(1999, 12, 31)
        )
        self.assertEqual(sca.empty_bucket(), bucket)


# --------------------------------------------------------------------------- #
# 4. Filters
# --------------------------------------------------------------------------- #
class TestFilters(unittest.TestCase):
    """country and organization_type narrow both charts identically."""

    def test_country_code_filter(self) -> None:
        """Filtering by the code the fixture resolves to keeps every row."""
        expected = len(oracle_frame(country=FIXTURE_COUNTRY_CODE))
        sizes = analytics({"country": FIXTURE_COUNTRY_CODE})["All"][
            "organizations_by_size"
        ]
        self.assertEqual(expected, sum(row["count"] for row in sizes))

    def test_country_name_filter(self) -> None:
        """The country filter accepts a name as well as a code."""
        by_code = analytics({"country": FIXTURE_COUNTRY_CODE})
        by_name = analytics({"country": FIXTURE_COUNTRY_NAME})
        self.assertEqual(by_code, by_name)

    def test_country_filter_is_case_insensitive(self) -> None:
        """Lowercase input matches the stored uppercase value."""
        self.assertEqual(
            analytics({"country": FIXTURE_COUNTRY_CODE}),
            analytics({"country": FIXTURE_COUNTRY_CODE.lower()}),
        )

    def test_usa_matches_nothing_in_this_fixture(self) -> None:
        """The issue's "USA" example is empty: US states map to country_id 1,
        which country.csv calls AFGHANISTAN. A mock-data defect, not an API one.
        """
        self.assertEqual(
            sca.empty_bucket(), analytics({"country": "USA"})["All"]
        )

    def test_organization_type_filter_normalizes(self) -> None:
        """non_profit matches the stored Non-Profit."""
        expected = len(oracle_frame(organization_type="non_profit"))
        sizes = analytics({"organization_type": "non_profit"})["All"][
            "organizations_by_size"
        ]
        self.assertGreater(expected, 0)
        self.assertEqual(expected, sum(row["count"] for row in sizes))

    def test_for_profit_filter_normalizes(self) -> None:
        """for_profit matches the stored For-profit, despite the casing."""
        expected = len(oracle_frame(organization_type="for_profit"))
        sizes = analytics({"organization_type": "for_profit"})["All"][
            "organizations_by_size"
        ]
        self.assertGreater(expected, 0)
        self.assertEqual(expected, sum(row["count"] for row in sizes))

    def test_filters_partition_the_fixture(self) -> None:
        """The two org types together account for every organization."""
        non_profit = len(oracle_frame(organization_type="non_profit"))
        for_profit = len(oracle_frame(organization_type="for_profit"))
        self.assertEqual(TOTAL_ORGANIZATIONS, non_profit + for_profit)

    def test_all_sentinel_means_no_filter(self) -> None:
        """ALL and an absent filter produce the same response."""
        self.assertEqual(
            analytics({}), analytics({"country": "ALL", "organization_type": "ALL"})
        )

    def test_filters_apply_to_custom_responses_too(self) -> None:
        """A Custom-only response honours country and organization_type."""
        payload = {
            "size_start_date": "2023-01-01",
            "size_end_date": "2026-12-31",
            "organization_type": "non_profit",
        }
        sizes = analytics(payload)["Custom"]["organizations_by_size"]
        self.assertEqual(
            len(oracle_frame(organization_type="non_profit")),
            sum(row["count"] for row in sizes),
        )


# --------------------------------------------------------------------------- #
# 5. Custom-only response shapes
# --------------------------------------------------------------------------- #
class TestCustomResponseShape(unittest.TestCase):
    """Either Custom pair collapses the response to a single Custom key."""

    SIZE_RANGE = {"size_start_date": "2023-01-01", "size_end_date": "2024-12-31"}
    CONTRIBUTION_RANGE = {
        "contribution_start_date": "2025-01-01",
        "contribution_end_date": "2026-12-31",
    }

    def test_size_range_only(self) -> None:
        """Only the size chart is populated, and no fixed buckets appear."""
        status_code, body = invoke(dict(self.SIZE_RANGE))
        self.assertEqual(200, status_code)
        self.assertEqual({"Custom"}, set(body))
        self.assertTrue(body["Custom"]["organizations_by_size"])
        self.assertEqual([], body["Custom"]["collaborator_vs_contributor"])

    def test_contribution_range_only(self) -> None:
        """The mirror image: only the contribution chart is populated."""
        status_code, body = invoke(dict(self.CONTRIBUTION_RANGE))
        self.assertEqual(200, status_code)
        self.assertEqual({"Custom"}, set(body))
        self.assertEqual([], body["Custom"]["organizations_by_size"])
        self.assertTrue(body["Custom"]["collaborator_vs_contributor"])

    def test_both_ranges_populate_both_charts(self) -> None:
        """Both pairs are evaluated - neither is dropped, neither wins."""
        payload = {**self.SIZE_RANGE, **self.CONTRIBUTION_RANGE}
        status_code, body = invoke(payload)
        self.assertEqual(200, status_code)
        self.assertEqual({"Custom"}, set(body))
        self.assertTrue(body["Custom"]["organizations_by_size"])
        self.assertTrue(body["Custom"]["collaborator_vs_contributor"])

    def test_each_chart_uses_its_own_range(self) -> None:
        """The ranges are deliberately different, so a shared window fails."""
        both = analytics({**self.SIZE_RANGE, **self.CONTRIBUTION_RANGE})["Custom"]
        size_only = analytics(dict(self.SIZE_RANGE))["Custom"]
        contribution_only = analytics(dict(self.CONTRIBUTION_RANGE))["Custom"]

        self.assertEqual(
            size_only["organizations_by_size"], both["organizations_by_size"]
        )
        self.assertEqual(
            contribution_only["collaborator_vs_contributor"],
            both["collaborator_vs_contributor"],
        )

        # The two windows really do select different organizations, so the
        # equalities above cannot be satisfied by both charts sharing a window.
        size_ids = set(
            sca.window_frame(ORGANIZATION_ROWS, date(2023, 1, 1), date(2024, 12, 31))[
                "org_id"
            ]
        )
        contribution_ids = set(
            sca.window_frame(ORGANIZATION_ROWS, date(2025, 1, 1), date(2026, 12, 31))[
                "org_id"
            ]
        )
        self.assertTrue(size_ids)
        self.assertTrue(contribution_ids)
        self.assertEqual(set(), size_ids & contribution_ids)

    def test_custom_bucket_still_has_exactly_two_keys(self) -> None:
        """The Custom-only body keeps the same bucket shape."""
        body = analytics(dict(self.SIZE_RANGE))
        self.assertEqual(BUCKET_KEYS, set(body["Custom"]))

    def test_custom_range_with_no_matches_is_empty_not_an_error(self) -> None:
        """A valid range containing no organizations returns empty arrays."""
        status_code, body = invoke(
            {"size_start_date": "1999-01-01", "size_end_date": "1999-12-31"}
        )
        self.assertEqual(200, status_code)
        self.assertEqual({"Custom"}, set(body))
        self.assertEqual([], body["Custom"]["organizations_by_size"])


# --------------------------------------------------------------------------- #
# 6. Collaborator vs contributor - independent, not a partition
# --------------------------------------------------------------------------- #
class TestContributionChart(unittest.TestCase):
    """The two counts are computed independently against the window total."""

    def test_exactly_two_rows_in_order(self) -> None:
        """The chart is always Collaborator then Contributor."""
        rows = analytics({})["All"]["collaborator_vs_contributor"]
        self.assertEqual(["Collaborator", "Contributor"], [r["type"] for r in rows])

    def test_counts_match_the_columns(self) -> None:
        """Each count is its own column's true count."""
        rows = analytics({})["All"]["collaborator_vs_contributor"]
        self.assertEqual(
            int(ORGANIZATION_ROWS["is_collaborator"].sum()), rows[0]["count"]
        )
        self.assertEqual(
            int(ORGANIZATION_ROWS["is_contributor"].sum()), rows[1]["count"]
        )

    def test_each_count_is_within_the_window_total(self) -> None:
        """Neither count can exceed the bucket's organization count."""
        for bucket in sca.FIXED_BUCKETS:
            start, end = sca.bucket_window(bucket, REFERENCE_DATE)
            total = len(sca.window_frame(ORGANIZATION_ROWS, start, end))
            for row in analytics({})[bucket]["collaborator_vs_contributor"]:
                self.assertLessEqual(row["count"], total, bucket)

    def test_percentages_are_shares_of_the_total(self) -> None:
        """Each percentage is its own count over the window total."""
        rows = analytics({})["All"]["collaborator_vs_contributor"]
        for row in rows:
            self.assertEqual(
                round(row["count"] * 100.0 / TOTAL_ORGANIZATIONS, 1),
                row["percentage"],
            )

    def test_counts_need_not_sum_to_the_total(self) -> None:
        """An org can be both or neither, so the rows are not a partition."""
        frame = synthetic_frame([
            # both flags true
            {"org_id": "A", "org_size": "Small", "org_type": "Non-Profit",
             "is_collaborator": True, "is_contributor": True,
             "created_at": "2026-01-01", "country_code": "AFG",
             "country_name": "AFGHANISTAN"},
            # neither flag true
            {"org_id": "B", "org_size": "Large", "org_type": "For-profit",
             "is_collaborator": False, "is_contributor": False,
             "created_at": "2026-01-02", "country_code": "AFG",
             "country_name": "AFGHANISTAN"},
        ])
        rows = sca.build_contribution_chart(frame)
        self.assertEqual(1, rows[0]["count"])
        self.assertEqual(1, rows[1]["count"])
        # Two rows of 1 against a total of 2: they sum to the total here only
        # by coincidence of the overlap, and each is 50%, not 100% between them.
        self.assertEqual(50.0, rows[0]["percentage"])
        self.assertEqual(50.0, rows[1]["percentage"])

    def test_all_both_flags_gives_two_full_counts(self) -> None:
        """When every org is both, both rows report the full total at 100%."""
        frame = synthetic_frame([
            {"org_id": f"O{i}", "org_size": "Small", "org_type": "Non-Profit",
             "is_collaborator": True, "is_contributor": True,
             "created_at": "2026-01-01", "country_code": "AFG",
             "country_name": "AFGHANISTAN"}
            for i in range(3)
        ])
        rows = sca.build_contribution_chart(frame)
        self.assertEqual([3, 3], [row["count"] for row in rows])
        self.assertEqual([100.0, 100.0], [row["percentage"] for row in rows])

    def test_missing_is_contributor_degrades_to_zero(self) -> None:
        """A frame without the column reports Contributor 0, without raising."""
        frame = synthetic_frame([
            {"org_id": "A", "org_size": "Small", "org_type": "Non-Profit",
             "is_collaborator": True, "is_contributor": False,
             "created_at": "2026-01-01", "country_code": "AFG",
             "country_name": "AFGHANISTAN"},
        ]).drop(columns=["is_contributor"])
        rows = sca.build_contribution_chart(frame)
        self.assertEqual(2, len(rows))
        self.assertEqual(0, rows[1]["count"])
        self.assertEqual(0.0, rows[1]["percentage"])

    def test_empty_frame_returns_empty_chart(self) -> None:
        """No organizations means an empty array, not two zero rows."""
        self.assertEqual([], sca.build_contribution_chart(synthetic_frame([])))

    def test_single_row_frame_does_not_crash(self) -> None:
        """A one-row dataset produces valid charts."""
        frame = synthetic_frame([
            {"org_id": "A", "org_size": "Medium", "org_type": "Non-Profit",
             "is_collaborator": True, "is_contributor": True,
             "created_at": "2026-01-01", "country_code": "AFG",
             "country_name": "AFGHANISTAN"},
        ])
        self.assertEqual([{"size": "Medium", "count": 1}], sca.build_size_chart(frame))
        self.assertEqual(2, len(sca.build_contribution_chart(frame)))


# --------------------------------------------------------------------------- #
# 7. Validation and error handling
# --------------------------------------------------------------------------- #
class TestValidation(unittest.TestCase):
    """Malformed input fails with a clear 400, never a partial result."""

    def test_half_a_size_pair_is_rejected(self) -> None:
        """Only one half of the size pair is an error, not a silent skip."""
        for payload in (
            {"size_start_date": "2026-01-01"},
            {"size_end_date": "2026-01-01"},
        ):
            status_code, body = invoke(payload)
            self.assertEqual(400, status_code, payload)
            self.assertIn("must be provided together", body["error"])

    def test_half_a_contribution_pair_is_rejected(self) -> None:
        """The contribution pair is validated the same way."""
        for payload in (
            {"contribution_start_date": "2026-01-01"},
            {"contribution_end_date": "2026-01-01"},
        ):
            status_code, body = invoke(payload)
            self.assertEqual(400, status_code, payload)
            self.assertIn("must be provided together", body["error"])

    def test_bad_date_format_is_rejected(self) -> None:
        """Anything that is not YYYY-MM-DD is an error."""
        for value in ("not-a-date", "01-01-2026", "2026/01/01", "2026-1-1", ""):
            status_code, body = invoke(
                {"size_start_date": value, "size_end_date": "2026-12-31"}
            )
            self.assertEqual(400, status_code, value)
            self.assertIn("YYYY-MM-DD", body["error"])

    def test_impossible_calendar_date_is_rejected(self) -> None:
        """A well-formed but non-existent date is still an error."""
        status_code, body = invoke(
            {"size_start_date": "2026-02-30", "size_end_date": "2026-12-31"}
        )
        self.assertEqual(400, status_code)
        self.assertIn("valid calendar date", body["error"])

    def test_start_after_end_is_rejected(self) -> None:
        """An inverted range is an error for both pairs."""
        for start_key, end_key in (
            ("size_start_date", "size_end_date"),
            ("contribution_start_date", "contribution_end_date"),
        ):
            status_code, body = invoke(
                {start_key: "2026-12-31", end_key: "2026-01-01"}
            )
            self.assertEqual(400, status_code, start_key)
            self.assertIn("on or before", body["error"])

    def test_one_bad_pair_fails_the_whole_request(self) -> None:
        """A valid pair alongside a broken one still returns 400, not partial data."""
        status_code, body = invoke({
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-06-30",
            "contribution_start_date": "nonsense",
            "contribution_end_date": "2026-12-31",
        })
        self.assertEqual(400, status_code)
        self.assertEqual({"error"}, set(body))

    def test_validation_precedes_data_access(self) -> None:
        """A malformed request never reads the CSVs."""
        original = sca.load_data
        sca.load_data = lambda: (_ for _ in ()).throw(
            AssertionError("data must not be loaded for an invalid request")
        )
        try:
            status_code, _ = invoke({"size_start_date": "bad"})
        finally:
            sca.load_data = original
        self.assertEqual(400, status_code)

    def test_malformed_json_body_is_rejected(self) -> None:
        """A body that is not valid JSON returns 400."""
        status_code, body = invoke({"body": "{not json"})
        self.assertEqual(400, status_code)
        self.assertIn("valid JSON", body["error"])

    def test_non_object_json_body_is_rejected(self) -> None:
        """A JSON array body returns 400 rather than being treated as empty."""
        status_code, body = invoke({"body": "[]"})
        self.assertEqual(400, status_code)
        self.assertIn("JSON object", body["error"])

    def test_data_failure_returns_500(self) -> None:
        """A load failure returns a generic 500 without leaking detail."""
        original = sca.load_data

        def boom() -> Any:
            raise RuntimeError("/secret/path/organizations.csv is unreadable")

        sca.load_data = boom
        try:
            status_code, body = invoke({})
        finally:
            sca.load_data = original
        self.assertEqual(500, status_code)
        self.assertEqual({"error": "internal server error"}, body)


# --------------------------------------------------------------------------- #
# 8. Handler contract
# --------------------------------------------------------------------------- #
class TestHandlerContract(unittest.TestCase):
    """The proxy envelope is well formed and the payload is JSON-safe."""

    def test_body_is_a_json_string(self) -> None:
        """The proxy body is serialized text, not a dict."""
        with env(MOCK_DATA_DIR=str(SQL_DIR), USE_MOCK_DATA="true"):
            response = sca.lambda_handler({})
        self.assertIsInstance(response["body"], str)
        self.assertEqual(FULL_TOP_LEVEL_KEYS, set(json.loads(response["body"])))

    def test_cors_headers_are_present(self) -> None:
        """Every response carries the shared CORS headers."""
        response = sca.build_response(200, {"ok": True})
        self.assertEqual("application/json", response["headers"]["Content-Type"])
        self.assertEqual("*", response["headers"]["Access-Control-Allow-Origin"])

    def test_counts_are_plain_ints(self) -> None:
        """No numpy integer leaks into the JSON payload."""
        for charts in analytics({}).values():
            for row in charts["organizations_by_size"]:
                self.assertIs(int, type(row["count"]))
            for row in charts["collaborator_vs_contributor"]:
                self.assertIs(int, type(row["count"]))
                self.assertIs(float, type(row["percentage"]))

    def test_accepts_a_json_string_body(self) -> None:
        """An API Gateway proxy event with a JSON string body is parsed."""
        status_code, body = invoke({"body": json.dumps({"country": "ALL"})})
        self.assertEqual(200, status_code)
        self.assertEqual(FULL_TOP_LEVEL_KEYS, set(body))

    def test_accepts_a_dict_body(self) -> None:
        """A dict body is accepted as-is."""
        status_code, _ = invoke({"body": {"country": "ALL"}})
        self.assertEqual(200, status_code)

    def test_none_event_is_treated_as_empty(self) -> None:
        """A null event returns the full response rather than raising."""
        status_code, body = invoke(None)
        self.assertEqual(200, status_code)
        self.assertEqual(FULL_TOP_LEVEL_KEYS, set(body))

    def test_module_runs_without_psycopg2(self) -> None:
        """The mock path does not need the database driver installed."""
        self.assertTrue(sca.use_mock_data.__module__)
        if sca.psycopg2 is None:
            with self.assertRaises(RuntimeError):
                sca.get_db_connection()

    def test_db_path_requires_configuration(self) -> None:
        """Switching off mock data without DB_HOST is an error, not a fallback."""
        with env(USE_MOCK_DATA="false", DB_HOST=None):
            if sca.psycopg2 is None:
                with self.assertRaises(RuntimeError):
                    sca.get_db_connection()
            else:
                with self.assertRaises(RuntimeError):
                    sca.get_db_connection()

    def test_source_has_no_parameter_store_references(self) -> None:
        """No boto3/SSM call path exists in the module."""
        source = (LAMBDA_DIR / "size_contribution_analytics.py").read_text(
            encoding="utf-8"
        )
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        body = code.split('"""', 2)[-1]
        for forbidden in ("boto3", "get_parameter", "WithDecryption"):
            self.assertNotIn(forbidden.lower(), body.lower())


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
    "TestFixtures": "Mock fixtures",
    "TestFullResponseShape": "Full response (no Custom pair)",
    "TestBucketWindows": "Bucket windows",
    "TestFilters": "country / organization_type filters",
    "TestCustomResponseShape": "Custom-only response shapes",
    "TestContributionChart": "Collaborator vs contributor",
    "TestValidation": "Validation and error handling",
    "TestHandlerContract": "Handler contract",
}


def emit_results(result: _RecordingResult, duration: float) -> Path:
    """Write ``TEST_RESULTS_376.md`` beside this file and return its path."""
    total = len(result.records)
    passed = sum(1 for r in result.records if r[3] == "PASS")
    skipped = sum(1 for r in result.records if r[3] == "SKIP")
    failed = total - passed - skipped

    lines: list[str] = []
    add = lines.append
    add("# Size & Contribution Analytics API - Test Results (Issue #376)")
    add("")
    add(f"**{passed}/{total} checks passed**"
        + (f", {failed} failed" if failed else "")
        + (f", {skipped} skipped" if skipped else "")
        + f" in {duration:.2f}s.")
    add("")
    add("| | |")
    add("|---|---|")
    add("| Module under test | `data-analytics/lambda_functions/size_contribution_analytics.py` |")
    add("| Data source | mock CSVs only - `organizations.csv`, `state.csv`, `country.csv` |")
    add(f"| Organizations in fixture | {TOTAL_ORGANIZATIONS} |")
    add(f"| Reference date for fixed buckets | {REFERENCE_DATE.isoformat()} (pinned) |")
    add(f"| Python | {sys.version.split()[0]} |")
    add(f"| pandas | {pd.__version__} |")
    add("| AWS / Parameter Store access | none |")
    add("")
    add("### Response-shape rules verified")
    add("")
    add("| Request | Top-level keys |")
    add("|---|---|")
    add("| no Custom pair | `7D`, `30D`, `1Y`, `All`, `Custom` (Custom empty) |")
    add("| `size_*` only | `Custom` only - size populated |")
    add("| `contribution_*` only | `Custom` only - contribution populated |")
    add("| both pairs | `Custom` only - **both** populated, each from its own range |")
    add("")
    add("---")
    add("")
    add("## Checks")
    add("")

    by_class: dict[str, list[tuple[str, str, str, str]]] = {}
    for record in result.records:
        by_class.setdefault(record[0], []).append(record)

    for cls, title in _SECTION_TITLES.items():
        records = by_class.get(cls)
        if not records:
            continue
        add(f"### {title}")
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
    add("Printed by `python data-analytics/lambda_functions/size_contribution_analytics.py`.")
    add("")
    for label, event in sca._sample_events():
        with env(MOCK_DATA_DIR=str(SQL_DIR), USE_MOCK_DATA="true"):
            response = sca.lambda_handler(dict(event))
        add(f"### {label}")
        add("")
        add("Request:")
        add("")
        add("```json")
        add(json.dumps(event, indent=2))
        add("```")
        add("")
        add(f"Response (HTTP {response['statusCode']}):")
        add("")
        add("```json")
        add(json.dumps(json.loads(response["body"]), indent=2))
        add("```")
        add("")

    add("---")
    add("")
    add("## Notes")
    add("")
    add("- `organizations_by_size` emits the **raw** stored enum values "
        "(`Small`/`Medium`/`Large`), per the issue's \"use the raw enum value as-is\". "
        "The issue's sample JSON shows `small`/`medium`/`large`, which does not match "
        "the data.")
    add("- `collaborator_vs_contributor` counts each flag independently against the "
        "window total. They are not a partition and need not sum to that total or to "
        "100%. The committed fixture happens to have zero overlap (21 collaborators, "
        "19 contributors, none both or neither), so the independence is proven with "
        "synthetic frames instead.")
    add("- `7D` and `30D` are empty against this fixture: its newest `created_at` is "
        "2026-01-10, well outside both windows from the pinned reference date.")
    add("- A `country` filter of `\"USA\"` matches nothing. Every US state in "
        "`state.csv` carries `country_id=1`, which `country.csv` maps to "
        "`AFGHANISTAN`/`AFG`. That is a mock-data defect; the join itself is correct.")
    add("- No `states.csv`/`countries.csv` exists in this repository, so the loader "
        "prefers those plural names and falls back to the tracked `state.csv`/"
        "`country.csv`.")

    path = TESTS_DIR / "TEST_RESULTS_376.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    """Run the suite, optionally regenerating ``TEST_RESULTS_376.md``."""
    import time

    emit = "--emit-results" in sys.argv
    verbosity = 2 if "-v" in sys.argv else 1

    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None  # keep declaration order in the report
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    started = time.perf_counter()
    runner = unittest.TextTestRunner(verbosity=verbosity, resultclass=_RecordingResult)
    result = runner.run(suite)
    duration = time.perf_counter() - started

    if emit:
        print(f"\nWrote {emit_results(result, duration)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
