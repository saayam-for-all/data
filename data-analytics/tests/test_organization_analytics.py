"""Mock-backed test suite for the Organization Analytics API (Issue #228).

Every assertion runs against the committed mock fixtures in
``data-analytics/sql`` (``organizations.csv`` and ``state.csv``). Nothing in
this suite can reach the shared Saayam database: the Lambda has no Parameter
Store fallback, and the only connection it is ever handed here is the
disposable one built by :mod:`mock_db`.

Expected values are derived from the CSVs at runtime rather than hard-coded,
so the suite keeps passing when the fixtures are regenerated. A pure-Python
oracle is computed straight from the CSV rows and compared against what the
Lambda's SQL returns, which is what makes the comparison meaningful.

Run it:

    python data-analytics/tests/test_organization_analytics.py

    # against a real local PostgreSQL instead of the SQLite shim
    MOCK_DB_BACKEND=postgres DB_HOST=localhost DB_NAME=saayam_local \\
    DB_USER=postgres DB_PASSWORD=postgres \\
        python data-analytics/tests/test_organization_analytics.py

Add ``--emit-results`` to also regenerate ``TEST_RESULTS.md`` next to this
file, capturing the pass/fail table and sample API responses.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

TESTS_DIR = Path(__file__).resolve().parent
LAMBDA_DIR = TESTS_DIR.parent / "lambda_functions"
for _path in (str(TESTS_DIR), str(LAMBDA_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import mock_db  # noqa: E402
import organization_analytics as org  # noqa: E402


ORG_ROWS = mock_db.load_organizations()
STATE_ROWS = mock_db.load_states()
STATE_NAMES = {row["state_id"]: row["state_name"] for row in STATE_ROWS}
TOTAL_ORGS = len(ORG_ROWS)


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

    def overview(self, **filters: Any) -> dict[str, Any]:
        """Build the overview payload for the given filters."""
        return org.build_overview_response(self.cursor, filters)["organization_overview"]

    def performance(self, **filters: Any) -> dict[str, Any]:
        """Build the performance payload for the given filters."""
        return org.build_performance_response(self.cursor, filters)[
            "organization_performance"
        ]


# --------------------------------------------------------------------------- #
# 1. Security posture - the review feedback that prompted this revision
# --------------------------------------------------------------------------- #
class TestNoSharedDatabaseAccess(unittest.TestCase):
    """The Lambda must have no route to the shared Saayam database."""

    def test_source_has_no_parameter_store_references(self) -> None:
        """No boto3/SSM/Parameter Store call sites remain in the module."""
        source = (LAMBDA_DIR / "organization_analytics.py").read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        # Strip the module docstring, which documents the absence of SSM.
        body = code.split('"""', 2)[-1]
        for forbidden in ("boto3", "ssm", "get_parameter", "WithDecryption"):
            self.assertNotIn(
                forbidden.lower(),
                body.lower(),
                f"{forbidden!r} still appears in organization_analytics.py",
            )

    def test_boto3_is_not_imported(self) -> None:
        """Importing the module must not pull in boto3."""
        self.assertFalse(
            hasattr(org, "boto3"),
            "organization_analytics still binds a boto3 module attribute",
        )

    def test_connection_refuses_to_guess_credentials(self) -> None:
        """With DB_HOST unset the connection raises instead of falling back."""
        with env(DB_HOST=None):
            with self.assertRaises(RuntimeError) as caught:
                org.get_db_connection()
        self.assertIn("DB_HOST", str(caught.exception))

    def test_no_ssm_even_with_aws_environment_present(self) -> None:
        """AWS credentials in the environment do not unlock a fallback path."""
        with env(
            DB_HOST=None,
            AWS_REGION="us-east-1",
            AWS_ACCESS_KEY_ID="AKIAtest",
            AWS_SECRET_ACCESS_KEY="secret",
            AWS_LAMBDA_FUNCTION_NAME="organization_analytics",
        ):
            with self.assertRaises(RuntimeError):
                org.get_db_connection()


# --------------------------------------------------------------------------- #
# 2. Fixtures
# --------------------------------------------------------------------------- #
class TestFixtures(unittest.TestCase):
    """The committed mock CSVs are present and shaped as the issue describes."""

    def test_organizations_fixture_loads(self) -> None:
        """organizations.csv loads with the columns the queries reference."""
        self.assertGreater(TOTAL_ORGS, 0)
        required = {
            "org_id", "org_name", "city_name", "state_id", "org_type",
            "org_size", "org_rating", "is_collaborator", "is_contributor",
            "created_at",
        }
        self.assertTrue(required.issubset(ORG_ROWS[0].keys()))

    def test_state_fixture_loads(self) -> None:
        """state.csv loads and provides state_id -> state_name."""
        self.assertGreater(len(STATE_ROWS), 0)
        self.assertTrue(all(row["state_id"] for row in STATE_ROWS))

    def test_every_org_state_resolves(self) -> None:
        """Every state_id used by an organization exists in state.csv."""
        unknown = {
            row["state_id"] for row in ORG_ROWS
            if row["state_id"] and row["state_id"] not in STATE_NAMES
        }
        self.assertEqual(set(), unknown)

    def test_booleans_are_real_booleans(self) -> None:
        """is_collaborator/is_contributor parse to bools, not strings."""
        for column in ("is_collaborator", "is_contributor"):
            values = {type(row[column]) for row in ORG_ROWS}
            self.assertEqual({bool}, values, f"{column} did not parse to bool")


# --------------------------------------------------------------------------- #
# 3. Overview dashboard
# --------------------------------------------------------------------------- #
class TestOverviewDashboard(MockBackedTestCase):
    """Dashboard 1 metrics match a pure-Python oracle over the fixtures."""

    def test_total_organizations(self) -> None:
        """total_organizations equals the fixture row count."""
        self.assertEqual(TOTAL_ORGS, self.overview()["summary"]["total_organizations"])

    def test_non_profit_and_for_profit_counts(self) -> None:
        """Type summary matches the 'Non-Profit'/'For-profit' fixture labels."""
        oracle = Counter(org._normalize_org_type(r["org_type"]) for r in ORG_ROWS)
        summary = self.overview()["summary"]
        self.assertEqual(oracle["nonprofit"], summary["non_profit_organizations"])
        self.assertEqual(oracle["forprofit"], summary["for_profit_organizations"])
        # Regression guard: this pair silently returned 0/0 before the fix.
        self.assertGreater(summary["non_profit_organizations"], 0)
        self.assertGreater(summary["for_profit_organizations"], 0)

    def test_type_counts_partition_the_total(self) -> None:
        """Non-profit + for-profit accounts for every organization."""
        summary = self.overview()["summary"]
        self.assertEqual(
            summary["total_organizations"],
            summary["non_profit_organizations"] + summary["for_profit_organizations"],
        )

    def test_collaborator_summary(self) -> None:
        """Collaborator / non-collaborator counts match the oracle."""
        expected_true = sum(1 for r in ORG_ROWS if r["is_collaborator"] is True)
        summary = self.overview()["summary"]
        self.assertEqual(expected_true, summary["collaborator_organizations"])
        self.assertEqual(
            TOTAL_ORGS - expected_true, summary["non_collaborator_organizations"]
        )

    def test_contributor_summary_returns_real_values(self) -> None:
        """Contributor counts are real numbers now the fixture has the column."""
        expected_true = sum(1 for r in ORG_ROWS if r["is_contributor"] is True)
        summary = self.overview()["summary"]
        self.assertEqual(expected_true, summary["contributor_organizations"])
        self.assertEqual(
            TOTAL_ORGS - expected_true, summary["non_contributor_organizations"]
        )
        # Previously this was hard-wired to 0 because the column was absent.
        self.assertGreater(summary["contributor_organizations"], 0)

    def test_organizations_by_type(self) -> None:
        """organizations_by_type matches the oracle and is sorted descending."""
        oracle = Counter(r["org_type"] for r in ORG_ROWS)
        rows = self.overview()["organizations_by_type"]
        self.assertEqual(dict(oracle), {r["org_type"]: r["count"] for r in rows})
        counts = [r["count"] for r in rows]
        self.assertEqual(sorted(counts, reverse=True), counts)

    def test_organizations_by_size(self) -> None:
        """organizations_by_size covers Small/Medium/Large per the oracle."""
        oracle = Counter(r["org_size"] for r in ORG_ROWS)
        rows = self.overview()["organizations_by_size"]
        self.assertEqual(dict(oracle), {r["org_size"]: r["count"] for r in rows})

    def test_organizations_by_state(self) -> None:
        """by_state matches the oracle and resolves state_name via the join."""
        oracle = Counter(r["state_id"] for r in ORG_ROWS)
        rows = self.overview()["organizations_by_location"]["by_state"]
        self.assertEqual(dict(oracle), {r["state_id"]: r["count"] for r in rows})
        for row in rows:
            self.assertEqual(
                STATE_NAMES.get(row["state_id"]),
                row["state_name"],
                f"state_name not joined for {row['state_id']}",
            )

    def test_organizations_by_city(self) -> None:
        """by_city matches the oracle and totals every organization."""
        oracle = Counter(r["city_name"] for r in ORG_ROWS)
        rows = self.overview()["organizations_by_location"]["by_city"]
        self.assertEqual(dict(oracle), {r["city_name"]: r["count"] for r in rows})
        self.assertEqual(TOTAL_ORGS, sum(r["count"] for r in rows))

    def test_registration_trend_groupings(self) -> None:
        """Every group_by totals the fixture and is ordered ascending."""
        for group_by in ("daily", "weekly", "monthly", "yearly"):
            with self.subTest(group_by=group_by):
                rows = self.overview(group_by=group_by)["organization_activity_trend"]
                self.assertEqual(TOTAL_ORGS, sum(r["count"] for r in rows))
                periods = [r["period"] for r in rows]
                self.assertEqual(sorted(periods), periods)
                self.assertEqual(len(set(periods)), len(periods))

    def test_trend_period_formats(self) -> None:
        """Trend period strings use the format tied to each grouping."""
        expected_len = {"daily": 10, "weekly": 10, "monthly": 7, "yearly": 4}
        for group_by, length in expected_len.items():
            with self.subTest(group_by=group_by):
                rows = self.overview(group_by=group_by)["organization_activity_trend"]
                self.assertTrue(all(len(r["period"]) == length for r in rows))

    def test_yearly_trend_matches_oracle(self) -> None:
        """Yearly buckets match the years present in created_at."""
        oracle = Counter(str(r["created_at"])[:4] for r in ORG_ROWS)
        rows = self.overview(group_by="yearly")["organization_activity_trend"]
        self.assertEqual(dict(oracle), {r["period"]: r["count"] for r in rows})

    def test_unknown_group_by_falls_back_to_daily(self) -> None:
        """An unrecognized group_by degrades to the daily grouping."""
        self.assertEqual(
            self.overview(group_by="daily")["organization_activity_trend"],
            self.overview(group_by="fortnightly")["organization_activity_trend"],
        )

    def test_distributions_present(self) -> None:
        """Collaborator and contributor distributions total the fixture."""
        payload = self.overview()
        for key, column in (
            ("collaborator_distribution", "is_collaborator"),
            ("contributor_distribution", "is_contributor"),
        ):
            with self.subTest(key=key):
                rows = payload[key]
                self.assertEqual(TOTAL_ORGS, sum(r["count"] for r in rows))
                flags = {r[column] for r in rows}
                self.assertTrue(flags.issubset({True, False}))
                # PostgreSQL booleans must not surface as SQLite 0/1.
                self.assertTrue(all(isinstance(f, bool) for f in flags))
                oracle = Counter(r[column] for r in ORG_ROWS)
                self.assertEqual(dict(oracle), {r[column]: r["count"] for r in rows})

    def test_response_contains_every_required_key(self) -> None:
        """The payload matches the response structure named in the issue."""
        payload = self.overview()
        self.assertEqual(
            {
                "summary", "organization_activity_trend", "organizations_by_type",
                "organizations_by_size", "organizations_by_location",
                "collaborator_distribution", "contributor_distribution",
            },
            set(payload),
        )
        self.assertEqual(
            {
                "total_organizations", "non_profit_organizations",
                "for_profit_organizations", "collaborator_organizations",
                "non_collaborator_organizations", "contributor_organizations",
                "non_contributor_organizations",
            },
            set(payload["summary"]),
        )


# --------------------------------------------------------------------------- #
# 4. Performance dashboard
# --------------------------------------------------------------------------- #
class TestPerformanceDashboard(MockBackedTestCase):
    """Dashboard 2 rating metrics match a pure-Python oracle."""

    @property
    def ratings(self) -> list[int]:
        return [r["org_rating"] for r in ORG_ROWS if r["org_rating"] is not None]

    def test_average_rating(self) -> None:
        """average_rating matches the mean of the fixture ratings."""
        expected = round(sum(self.ratings) / len(self.ratings), 2)
        self.assertAlmostEqual(
            expected, self.performance()["summary"]["average_rating"], places=2
        )

    def test_rated_and_unrated_partition_the_total(self) -> None:
        """rated + unrated equals every organization."""
        summary = self.performance()["summary"]
        self.assertEqual(len(self.ratings), summary["rated_organizations"])
        self.assertEqual(
            TOTAL_ORGS - len(self.ratings), summary["unrated_organizations"]
        )
        self.assertEqual(
            TOTAL_ORGS,
            summary["rated_organizations"] + summary["unrated_organizations"],
        )

    def test_five_star_count(self) -> None:
        """five_star_organizations matches the oracle."""
        expected = sum(1 for r in self.ratings if r == 5)
        self.assertEqual(expected, self.performance()["summary"]["five_star_organizations"])

    def test_rating_distribution(self) -> None:
        """rating_distribution matches the oracle, ascending, ratings 1-5."""
        oracle = Counter(self.ratings)
        rows = self.performance()["rating_distribution"]
        self.assertEqual(dict(oracle), {r["rating"]: r["count"] for r in rows})
        ordered = [r["rating"] for r in rows]
        self.assertEqual(sorted(ordered), ordered)
        self.assertTrue(all(1 <= r["rating"] <= 5 for r in rows))
        self.assertEqual(len(self.ratings), sum(r["count"] for r in rows))

    def test_top_rated_organizations(self) -> None:
        """Leaderboard is capped at TOP_N and ordered by rating descending."""
        rows = self.performance()["top_rated_organizations"]
        self.assertLessEqual(len(rows), org.TOP_N)
        self.assertEqual(min(org.TOP_N, TOTAL_ORGS), len(rows))
        ratings = [r["org_rating"] for r in rows]
        self.assertEqual(sorted(ratings, reverse=True), ratings)
        self.assertEqual(max(self.ratings), ratings[0])

    def test_top_collaborator_organizations(self) -> None:
        """Collaborator leaderboard contains only collaborators."""
        collaborators = {
            r["org_id"] for r in ORG_ROWS if r["is_collaborator"] is True
        }
        rows = self.performance()["top_collaborator_organizations"]
        self.assertTrue(rows)
        self.assertTrue({r["org_id"] for r in rows}.issubset(collaborators))
        self.assertLessEqual(len(rows), org.TOP_N)

    def test_top_contributor_organizations(self) -> None:
        """Contributor leaderboard is populated and contains only contributors."""
        contributors = {r["org_id"] for r in ORG_ROWS if r["is_contributor"] is True}
        rows = self.performance()["top_contributor_organizations"]
        self.assertTrue(rows, "contributor leaderboard should no longer be empty")
        self.assertTrue({r["org_id"] for r in rows}.issubset(contributors))

    def test_ratings_by_organization_type(self) -> None:
        """Average rating per org_type matches the oracle."""
        buckets: dict[str, list[int]] = {}
        for row in ORG_ROWS:
            if row["org_rating"] is not None:
                buckets.setdefault(row["org_type"], []).append(row["org_rating"])
        rows = self.performance()["ratings_by_organization_type"]
        self.assertEqual(set(buckets), {r["org_type"] for r in rows})
        for row in rows:
            expected = round(sum(buckets[row["org_type"]]) / len(buckets[row["org_type"]]), 2)
            self.assertAlmostEqual(expected, row["average_rating"], places=2)
            self.assertEqual(len(buckets[row["org_type"]]), row["rated_count"])

    def test_ratings_by_organization_size(self) -> None:
        """Average rating per org_size matches the oracle."""
        buckets: dict[str, list[int]] = {}
        for row in ORG_ROWS:
            if row["org_rating"] is not None:
                buckets.setdefault(row["org_size"], []).append(row["org_rating"])
        rows = self.performance()["ratings_by_organization_size"]
        self.assertEqual(set(buckets), {r["org_size"] for r in rows})
        for row in rows:
            expected = round(sum(buckets[row["org_size"]]) / len(buckets[row["org_size"]]), 2)
            self.assertAlmostEqual(expected, row["average_rating"], places=2)

    def test_response_contains_every_required_key(self) -> None:
        """The payload matches the response structure named in the issue."""
        payload = self.performance()
        self.assertEqual(
            {
                "summary", "rating_distribution", "top_rated_organizations",
                "top_collaborator_organizations", "top_contributor_organizations",
                "ratings_by_organization_type", "ratings_by_organization_size",
            },
            set(payload),
        )
        self.assertEqual(
            {
                "average_rating", "rated_organizations", "unrated_organizations",
                "five_star_organizations",
            },
            set(payload["summary"]),
        )


# --------------------------------------------------------------------------- #
# 5. Common filters
# --------------------------------------------------------------------------- #
class TestCommonFilters(MockBackedTestCase):
    """Each documented filter narrows the result set correctly."""

    def _total(self, **filters: Any) -> int:
        return self.overview(**filters)["summary"]["total_organizations"]

    def test_org_type_filter(self) -> None:
        """Filtering by org_type returns exactly that type's rows."""
        for value in {r["org_type"] for r in ORG_ROWS}:
            with self.subTest(org_type=value):
                expected = sum(1 for r in ORG_ROWS if r["org_type"] == value)
                self.assertEqual(expected, self._total(org_type=value))

    def test_org_size_filter(self) -> None:
        """Filtering by org_size returns exactly that size's rows."""
        for value in {r["org_size"] for r in ORG_ROWS}:
            with self.subTest(org_size=value):
                expected = sum(1 for r in ORG_ROWS if r["org_size"] == value)
                self.assertEqual(expected, self._total(org_size=value))

    def test_state_and_city_filters(self) -> None:
        """state_id and city_name filters match the oracle."""
        state = ORG_ROWS[0]["state_id"]
        city = ORG_ROWS[0]["city_name"]
        self.assertEqual(
            sum(1 for r in ORG_ROWS if r["state_id"] == state),
            self._total(state_id=state),
        )
        self.assertEqual(
            sum(1 for r in ORG_ROWS if r["city_name"] == city),
            self._total(city_name=city),
        )

    def test_org_rating_filter_accepts_int_and_string(self) -> None:
        """org_rating filters correctly whether passed as int or string."""
        expected = sum(1 for r in ORG_ROWS if r["org_rating"] == 5)
        self.assertEqual(expected, self._total(org_rating=5))
        self.assertEqual(expected, self._total(**org._extract_filters({"org_rating": "5"})))

    def test_boolean_filters(self) -> None:
        """is_collaborator / is_contributor filter on both true and false."""
        for column in ("is_collaborator", "is_contributor"):
            for flag in (True, False):
                with self.subTest(column=column, flag=flag):
                    expected = sum(1 for r in ORG_ROWS if r[column] is flag)
                    self.assertEqual(expected, self._total(**{column: flag}))

    def test_boolean_filter_accepts_strings(self) -> None:
        """String 'true'/'false' are coerced like real booleans."""
        expected = sum(1 for r in ORG_ROWS if r["is_collaborator"] is True)
        self.assertEqual(expected, self._total(is_collaborator="true"))

    def test_combined_filters_intersect(self) -> None:
        """Multiple filters combine with AND."""
        sample = ORG_ROWS[0]
        expected = sum(
            1 for r in ORG_ROWS
            if r["org_type"] == sample["org_type"] and r["org_size"] == sample["org_size"]
        )
        self.assertEqual(
            expected,
            self._total(org_type=sample["org_type"], org_size=sample["org_size"]),
        )

    def test_time_filters_are_monotonic(self) -> None:
        """7D <= 30D <= 1Y <= ALL over the same fixture."""
        counts = {tf: self._total(time_filter=tf) for tf in ("7D", "30D", "1Y", "ALL")}
        self.assertLessEqual(counts["7D"], counts["30D"])
        self.assertLessEqual(counts["30D"], counts["1Y"])
        self.assertLessEqual(counts["1Y"], counts["ALL"])
        self.assertEqual(TOTAL_ORGS, counts["ALL"])

    def test_custom_range_matches_oracle(self) -> None:
        """A CUSTOM window returns exactly the rows created inside it."""
        years = sorted({str(r["created_at"])[:4] for r in ORG_ROWS})
        start, end = f"{years[0]}-01-01", f"{years[0]}-12-31 23:59:59"
        expected = sum(
            1 for r in ORG_ROWS if start <= str(r["created_at"]) <= end
        )
        self.assertEqual(
            expected,
            self._total(time_filter="CUSTOM", start_date=start, end_date=end),
        )

    def test_custom_without_dates_raises(self) -> None:
        """CUSTOM without both bounds is a validation error."""
        with self.assertRaises(ValueError):
            org.build_date_filter("CUSTOM", None, None)

    def test_unknown_time_filter_returns_everything(self) -> None:
        """An unrecognized time_filter applies no date restriction."""
        self.assertEqual(TOTAL_ORGS, self._total(time_filter="LAST_FORTNIGHT"))

    def test_filters_apply_to_performance_dashboard_too(self) -> None:
        """The same filters narrow the performance dashboard."""
        value = ORG_ROWS[0]["org_type"]
        ratings = [
            r["org_rating"] for r in ORG_ROWS
            if r["org_type"] == value and r["org_rating"] is not None
        ]
        summary = self.performance(org_type=value)["summary"]
        self.assertEqual(len(ratings), summary["rated_organizations"])


# --------------------------------------------------------------------------- #
# 6. Contributor guard
# --------------------------------------------------------------------------- #
class TestContributorGuard(MockBackedTestCase):
    """ORG_IS_CONTRIBUTOR=false keeps the column out of the SQL entirely."""

    def test_guard_off_zeroes_contributor_metrics(self) -> None:
        """Disabled guard returns 0 / [] for every contributor metric."""
        with env(ORG_IS_CONTRIBUTOR="false"):
            overview = self.overview()
            performance = self.performance()
        self.assertEqual(0, overview["summary"]["contributor_organizations"])
        self.assertEqual(0, overview["summary"]["non_contributor_organizations"])
        self.assertEqual([], overview["contributor_distribution"])
        self.assertEqual([], performance["top_contributor_organizations"])

    def test_guard_off_never_references_the_column(self) -> None:
        """No executed statement mentions is_contributor when disabled."""
        if mock_db.active_backend() != "sqlite":
            self.skipTest("SQL recording is only available on the SQLite backend")
        self.connection.executed_sql.clear()
        with env(ORG_IS_CONTRIBUTOR="false"):
            self.overview()
            self.performance()
        offenders = [s for s in self.connection.executed_sql if "is_contributor" in s]
        self.assertEqual([], offenders, "is_contributor leaked into SQL while guarded")

    def test_guard_off_still_references_it_when_enabled(self) -> None:
        """Sanity check: the recorder does see the column when enabled."""
        if mock_db.active_backend() != "sqlite":
            self.skipTest("SQL recording is only available on the SQLite backend")
        self.connection.executed_sql.clear()
        with env(ORG_IS_CONTRIBUTOR="true"):
            self.overview()
        self.assertTrue(
            any("is_contributor" in s for s in self.connection.executed_sql)
        )

    def test_response_shape_is_identical_either_way(self) -> None:
        """Toggling the guard adds or drops no JSON keys."""
        with env(ORG_IS_CONTRIBUTOR="true"):
            on_overview, on_performance = self.overview(), self.performance()
        with env(ORG_IS_CONTRIBUTOR="false"):
            off_overview, off_performance = self.overview(), self.performance()
        self.assertEqual(set(on_overview), set(off_overview))
        self.assertEqual(set(on_overview["summary"]), set(off_overview["summary"]))
        self.assertEqual(set(on_performance), set(off_performance))


# --------------------------------------------------------------------------- #
# 7. Handler contract
# --------------------------------------------------------------------------- #
class TestLambdaHandler(unittest.TestCase):
    """End-to-end handler behaviour with the mock connection injected."""

    def setUp(self) -> None:
        self._real_get_connection = org.get_db_connection
        org.get_db_connection = mock_db.load_mock_database
        self.addCleanup(setattr, org, "get_db_connection", self._real_get_connection)

    @staticmethod
    def _body(response: dict[str, Any]) -> dict[str, Any]:
        return json.loads(response["body"])

    def test_overview_returns_200(self) -> None:
        """dashboard_type=overview returns 200 with the overview payload."""
        response = org.lambda_handler({"dashboard_type": "overview"})
        self.assertEqual(200, response["statusCode"])
        self.assertIn("organization_overview", self._body(response))

    def test_performance_returns_200(self) -> None:
        """dashboard_type=performance returns 200 with the performance payload."""
        response = org.lambda_handler({"dashboard_type": "performance"})
        self.assertEqual(200, response["statusCode"])
        self.assertIn("organization_performance", self._body(response))

    def test_response_envelope(self) -> None:
        """Responses carry JSON content-type and CORS headers."""
        headers = org.lambda_handler({})["headers"]
        self.assertEqual("application/json", headers["Content-Type"])
        self.assertEqual("*", headers["Access-Control-Allow-Origin"])

    def test_missing_and_unknown_dashboard_type_default_to_overview(self) -> None:
        """An absent or unrecognized dashboard_type falls back to overview."""
        for event in ({}, None, {"dashboard_type": "nonsense"}):
            with self.subTest(event=event):
                body = self._body(org.lambda_handler(event))
                self.assertIn("organization_overview", body)

    def test_custom_without_dates_returns_400(self) -> None:
        """CUSTOM without start_date/end_date is a 400, not a 500."""
        response = org.lambda_handler(
            {"dashboard_type": "overview", "time_filter": "CUSTOM"}
        )
        self.assertEqual(400, response["statusCode"])
        self.assertIn("error", self._body(response))

    def test_invalid_org_rating_returns_400(self) -> None:
        """A non-integer org_rating is rejected up front."""
        response = org.lambda_handler({"org_rating": "five"})
        self.assertEqual(400, response["statusCode"])
        self.assertIn("org_rating", self._body(response)["error"])

    def test_connection_failure_returns_500(self) -> None:
        """A dead database surfaces as a 500 without leaking details."""

        def boom() -> Any:
            raise RuntimeError("connection refused to 10.0.0.5")

        org.get_db_connection = boom
        response = org.lambda_handler({"dashboard_type": "overview"})
        self.assertEqual(500, response["statusCode"])
        self.assertEqual("internal server error", self._body(response)["error"])
        self.assertNotIn("10.0.0.5", response["body"])

    def test_single_query_failure_degrades_to_default(self) -> None:
        """One failing query yields a safe default while the request stays 200."""
        original = org.fetch_total_organizations

        def boom(*_args: Any, **_kwargs: Any) -> int:
            raise RuntimeError("simulated query failure")

        org.fetch_total_organizations = boom
        self.addCleanup(setattr, org, "fetch_total_organizations", original)

        response = org.lambda_handler({"dashboard_type": "overview"})
        self.assertEqual(200, response["statusCode"])
        payload = self._body(response)["organization_overview"]
        self.assertEqual(0, payload["summary"]["total_organizations"])
        # Neighbouring metrics still resolve normally.
        self.assertTrue(payload["organizations_by_type"])

    def test_body_is_json_encoded_string(self) -> None:
        """The body is a JSON string, as API Gateway proxy integration expects."""
        response = org.lambda_handler({})
        self.assertIsInstance(response["body"], str)
        self.assertIsInstance(json.loads(response["body"]), dict)


# --------------------------------------------------------------------------- #
# Results file generation
# --------------------------------------------------------------------------- #
class _RecordingResult(unittest.TextTestResult):
    """Collects an ordered pass/fail record for the markdown report."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.records: list[tuple[str, str, str, str]] = []

    def _record(self, test: unittest.TestCase, outcome: str) -> None:
        cls = type(test).__name__
        name = test._testMethodName
        doc = (test.shortDescription() or "").strip()
        self.records.append((cls, name, doc, outcome))

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
    "TestNoSharedDatabaseAccess": "No shared-database access (review feedback)",
    "TestFixtures": "Mock fixtures",
    "TestOverviewDashboard": "Dashboard 1 - Organization Overview",
    "TestPerformanceDashboard": "Dashboard 2 - Organization Performance",
    "TestCommonFilters": "Common filters",
    "TestContributorGuard": "Contributor guard (ORG_IS_CONTRIBUTOR)",
    "TestLambdaHandler": "Lambda handler contract",
}


def _sample_responses() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Produce the sample request/response pairs recorded in the report."""
    original = org.get_db_connection
    org.get_db_connection = mock_db.load_mock_database
    try:
        events = [
            ("Overview - all organizations", {"dashboard_type": "overview", "time_filter": "ALL", "group_by": "yearly"}),
            ("Overview - non-profit collaborators only", {"dashboard_type": "overview", "org_type": "Non-Profit", "is_collaborator": True, "group_by": "yearly"}),
            ("Performance - all organizations", {"dashboard_type": "performance", "time_filter": "ALL"}),
            ("Performance - large organizations only", {"dashboard_type": "performance", "org_size": "Large"}),
            ("Validation error - CUSTOM without dates", {"dashboard_type": "overview", "time_filter": "CUSTOM"}),
            ("Validation error - non-integer org_rating", {"dashboard_type": "overview", "org_rating": "five"}),
        ]
        samples = []
        for title, event in events:
            response = org.lambda_handler(event)
            samples.append((title, event, {
                "statusCode": response["statusCode"],
                "body": json.loads(response["body"]),
            }))

        def boom() -> Any:
            raise RuntimeError("simulated database outage")

        org.get_db_connection = boom
        outage = org.lambda_handler({"dashboard_type": "overview"})
        samples.append((
            "Database failure - connection refused",
            {"dashboard_type": "overview"},
            {"statusCode": outage["statusCode"], "body": json.loads(outage["body"])},
        ))
        return samples
    finally:
        org.get_db_connection = original


def emit_results(
    result: _RecordingResult,
    duration: float,
    backend: str,
    coverage: list[tuple[str, str, Optional[_RecordingResult], float]],
) -> Path:
    """Write ``TEST_RESULTS.md`` beside this file and return its path."""
    total = len(result.records)
    passed = sum(1 for r in result.records if r[3] == "PASS")
    skipped = sum(1 for r in result.records if r[3] == "SKIP")
    failed = total - passed - skipped

    lines: list[str] = []
    add = lines.append
    add("# Organization Analytics API - Test Results (Issue #228)")
    add("")
    add(f"**{passed}/{total} checks passed**"
        + (f", {failed} failed" if failed else "")
        + (f", {skipped} skipped" if skipped else "")
        + f" in {duration:.2f}s on the `{backend}` backend.")
    add("")
    add("| | |")
    add("|---|---|")
    add("| Module under test | `data-analytics/lambda_functions/organization_analytics.py` |")
    add("| Data source | mock fixtures only - `data-analytics/sql/organizations.csv`, `data-analytics/sql/state.csv` |")
    add(f"| Organizations in fixture | {TOTAL_ORGS} |")
    add(f"| States in fixture | {len(STATE_ROWS)} |")
    add(f"| Python | {sys.version.split()[0]} |")
    add("| AWS / Parameter Store access | none - no boto3 import, no SSM call path |")
    add("")
    add("### Backend coverage")
    add("")
    add("The identical suite runs against both a real local PostgreSQL and a "
        "zero-dependency SQLite shim, so the SQL is verified on the engine it "
        "will actually run on and the suite stays runnable with no setup.")
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
    add("python data-analytics/tests/test_organization_analytics.py --emit-results")
    add("")
    add("# against a local PostgreSQL")
    add("docker run -d --name saayam-pg -e POSTGRES_PASSWORD=postgres \\")
    add("    -e POSTGRES_DB=saayam_local -p 55432:5432 postgres:16-alpine")
    add("MOCK_DB_BACKEND=postgres DB_HOST=localhost DB_PORT=55432 \\")
    add("DB_NAME=saayam_local DB_USER=postgres DB_PASSWORD=postgres \\")
    add("    python data-analytics/tests/test_organization_analytics.py")
    add("```")
    add("")
    add("---")
    add("")
    add("## Checks")
    add("")

    by_class: dict[str, list[tuple[str, str, str, str]]] = {}
    for record in result.records:
        by_class.setdefault(record[0], []).append(record)

    for cls, records in by_class.items():
        add(f"### {_SECTION_TITLES.get(cls, cls)}")
        add("")
        add("| Result | Check | What it verifies |")
        add("|---|---|---|")
        for _cls, name, doc, outcome in records:
            mark = {"PASS": "PASS", "FAIL": "FAIL", "ERROR": "ERROR", "SKIP": "SKIP"}[outcome]
            add(f"| {mark} | `{name}` | {doc} |")
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
    unrated = sum(1 for r in ORG_ROWS if r["org_rating"] is None)
    add(f"- Every organization in the current fixture carries a rating, so "
        f"`unrated_organizations` is {unrated} here. The metric and its SQL are "
        f"still exercised (`rated + unrated == total`), but a fixture containing "
        f"NULL ratings would give it a non-zero value to assert against.")
    add("- The default SQLite backend applies a small compatibility shim "
        "(`%s` placeholders, `INTERVAL` arithmetic, `::numeric`, `DATE_TRUNC`, "
        "`TO_CHAR`). Set `MOCK_DB_BACKEND=postgres` with `DB_*` pointing at a "
        "local PostgreSQL to run the identical assertions against real "
        "PostgreSQL; see `data-analytics/tests/mock_db.py`.")
    add("- `is_contributor` is present in the fixture, so contributor metrics "
        "return real values. `ORG_IS_CONTRIBUTOR=false` still suppresses them "
        "without referencing the column, for databases where the migration has "
        "not landed.")

    path = TESTS_DIR / "TEST_RESULTS.md"
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
    """Report whether a local PostgreSQL is configured and accepting the fixtures."""
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
    """Run the suite, optionally regenerating ``TEST_RESULTS.md``."""
    emit = "--emit-results" in sys.argv
    verbosity = 2 if "-v" in sys.argv else 1

    if not emit:
        result, _ = _run_suite(verbosity)
        return 0 if result.wasSuccessful() else 1

    # For the report, run every backend we can reach. PostgreSQL is preferred
    # for the detailed table because it is the engine this Lambda deploys to.
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
