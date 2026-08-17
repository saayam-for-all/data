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
from collections import Counter, defaultdict
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

# A state that actually appears in the fixture, for the region filter tests.
SAMPLE_STATE_ID = Counter(r["state_id"] for r in ORG_ROWS).most_common(1)[0][0]
SAMPLE_STATE_NAME = STATE_NAMES[SAMPLE_STATE_ID]

TOP_LEVEL_KEYS = {
    "summary",
    "growth_trend",
    "organizations_by_location",
    "organizations_by_city",
    "organizations_by_size",
    "collaborator_vs_contributor",
    "rating_distribution",
    "organization_type_distribution",
}
SUMMARY_KEYS = {
    "total_organizations",
    "total_collaborators",
    "total_contributors",
    "average_org_rating",
}


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


def oracle_rows(region: Optional[str] = None, organization_type: Optional[str] = None):
    """Filter the fixture rows in pure Python, mirroring the SQL filters."""
    rows = ORG_ROWS
    if region is not None:
        key = region.strip().lower()
        rows = [
            r for r in rows
            if (STATE_NAMES.get(r["state_id"]) or "").lower() == key
            or (r["state_id"] or "").lower() == key
        ]
    if organization_type is not None:
        key = org._normalize_key(organization_type)
        rows = [r for r in rows if org._normalize_key(r["org_type"]) == key]
    return rows


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

    def dashboard(self, **payload: Any) -> dict[str, Any]:
        """Build the full dashboard payload for a raw request payload."""
        filters = org._extract_filters(payload)
        return org.build_dashboard_response(self.cursor, filters)


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
# 3. KPI cards
# --------------------------------------------------------------------------- #
class TestKpiSummary(MockBackedTestCase):
    """The four KPI cards at the top of the dashboard."""

    def test_summary_has_exactly_the_four_cards(self) -> None:
        """summary carries the four documented keys and nothing else."""
        self.assertEqual(SUMMARY_KEYS, set(self.dashboard()["summary"]))

    def test_total_organizations(self) -> None:
        """total_organizations equals the fixture row count."""
        self.assertEqual(TOTAL_ORGS, self.dashboard()["summary"]["total_organizations"])

    def test_total_collaborators(self) -> None:
        """total_collaborators counts organizations with is_collaborator true."""
        expected = sum(1 for r in ORG_ROWS if r["is_collaborator"] is True)
        self.assertEqual(expected, self.dashboard()["summary"]["total_collaborators"])

    def test_total_contributors(self) -> None:
        """total_contributors counts organizations with is_contributor true."""
        expected = sum(1 for r in ORG_ROWS if r["is_contributor"] is True)
        self.assertEqual(expected, self.dashboard()["summary"]["total_contributors"])

    def test_average_org_rating_ignores_nulls(self) -> None:
        """average_org_rating averages only the rated organizations."""
        ratings = [r["org_rating"] for r in ORG_ROWS if r["org_rating"] is not None]
        expected = round(sum(ratings) / len(ratings), 2)
        self.assertAlmostEqual(
            expected, self.dashboard()["summary"]["average_org_rating"], places=2
        )


# --------------------------------------------------------------------------- #
# 4. Tab 1 - Growth & Location
# --------------------------------------------------------------------------- #
class TestGrowthTrend(MockBackedTestCase):
    """growth_trend reports cumulative organizations and collaborators."""

    def test_row_shape(self) -> None:
        """Each point carries period, total_organizations, total_collaborators."""
        for row in self.dashboard(group_by="yearly")["growth_trend"]:
            self.assertEqual(
                {"period", "total_organizations", "total_collaborators"}, set(row)
            )

    def test_series_are_cumulative(self) -> None:
        """Both series are non-decreasing across periods."""
        rows = self.dashboard(group_by="monthly")["growth_trend"]
        for series in ("total_organizations", "total_collaborators"):
            values = [r[series] for r in rows]
            self.assertEqual(sorted(values), values, f"{series} is not cumulative")

    def test_final_point_matches_summary(self) -> None:
        """The last period equals the KPI totals."""
        payload = self.dashboard(group_by="monthly")
        last = payload["growth_trend"][-1]
        self.assertEqual(
            payload["summary"]["total_organizations"], last["total_organizations"]
        )
        self.assertEqual(
            payload["summary"]["total_collaborators"], last["total_collaborators"]
        )

    def test_periods_ascending_and_unique(self) -> None:
        """Every grouping returns ordered, non-repeating periods."""
        for group_by in ("daily", "weekly", "monthly", "yearly"):
            with self.subTest(group_by=group_by):
                periods = [r["period"] for r in self.dashboard(group_by=group_by)["growth_trend"]]
                self.assertEqual(sorted(periods), periods)
                self.assertEqual(len(set(periods)), len(periods))

    def test_period_formats(self) -> None:
        """Trend period strings use the format tied to each grouping."""
        expected_len = {"daily": 10, "weekly": 10, "monthly": 7, "yearly": 4}
        for group_by, length in expected_len.items():
            with self.subTest(group_by=group_by):
                rows = self.dashboard(group_by=group_by)["growth_trend"]
                self.assertTrue(all(len(r["period"]) == length for r in rows))

    def test_yearly_trend_matches_oracle(self) -> None:
        """Yearly cumulative totals match a running count over created_at."""
        per_year = Counter(str(r["created_at"])[:4] for r in ORG_ROWS)
        running, expected = 0, {}
        for year in sorted(per_year):
            running += per_year[year]
            expected[year] = running
        rows = self.dashboard(group_by="yearly")["growth_trend"]
        self.assertEqual(expected, {r["period"]: r["total_organizations"] for r in rows})


class TestOrganizationsByLocation(MockBackedTestCase):
    """organizations_by_location and organizations_by_city."""

    def test_state_rows_match_oracle(self) -> None:
        """Per-state counts match the fixture."""
        oracle = Counter(r["state_id"] for r in ORG_ROWS)
        rows = self.dashboard()["organizations_by_location"]
        self.assertEqual(dict(oracle), {r["state_id"]: r["organization_count"] for r in rows})

    def test_state_row_shape_and_names(self) -> None:
        """Each row has the documented keys and a resolved state_name."""
        for row in self.dashboard()["organizations_by_location"]:
            self.assertEqual(
                {"state_id", "state_name", "organization_count", "percentage"}, set(row)
            )
            self.assertEqual(STATE_NAMES.get(row["state_id"]), row["state_name"])

    def test_state_percentages_total_100(self) -> None:
        """Percentages are shares of the filtered population."""
        rows = self.dashboard()["organizations_by_location"]
        self.assertAlmostEqual(100.0, sum(r["percentage"] for r in rows), places=0)
        for row in rows:
            self.assertAlmostEqual(
                round(row["organization_count"] * 100.0 / TOTAL_ORGS, 1),
                row["percentage"],
                places=1,
            )

    def test_state_rows_sorted_by_count(self) -> None:
        """Rows are ordered by organization_count descending."""
        counts = [r["organization_count"] for r in self.dashboard()["organizations_by_location"]]
        self.assertEqual(sorted(counts, reverse=True), counts)

    def test_city_rows_match_oracle(self) -> None:
        """Per-city counts match the fixture and total every organization."""
        oracle = Counter(r["city_name"] for r in ORG_ROWS)
        rows = self.dashboard()["organizations_by_city"]
        self.assertEqual(dict(oracle), {r["city_name"]: r["organization_count"] for r in rows})
        self.assertEqual(TOTAL_ORGS, sum(r["organization_count"] for r in rows))

    def test_city_row_shape(self) -> None:
        """City rows carry their owning state for disambiguation."""
        for row in self.dashboard()["organizations_by_city"]:
            self.assertEqual(
                {"city_name", "state_id", "state_name", "organization_count", "percentage"},
                set(row),
            )


# --------------------------------------------------------------------------- #
# 5. Tab 2 - Size & Contribution
# --------------------------------------------------------------------------- #
class TestOrganizationsBySize(MockBackedTestCase):
    """organizations_by_size always reports small/medium/large."""

    def test_canonical_buckets_always_present_in_order(self) -> None:
        """All three buckets are returned, in small-medium-large order."""
        rows = self.dashboard()["organizations_by_size"]
        self.assertEqual(
            list(org.CANONICAL_ORG_SIZES), [r["org_size"] for r in rows[:3]]
        )

    def test_counts_match_oracle(self) -> None:
        """Counts match the fixture, compared case-insensitively."""
        oracle = Counter((r["org_size"] or "").lower() for r in ORG_ROWS)
        rows = self.dashboard()["organizations_by_size"]
        self.assertEqual(dict(oracle), {r["org_size"]: r["organization_count"] for r in rows})

    def test_counts_total_the_population(self) -> None:
        """Every organization lands in exactly one bucket."""
        rows = self.dashboard()["organizations_by_size"]
        self.assertEqual(TOTAL_ORGS, sum(r["organization_count"] for r in rows))

    def test_row_shape(self) -> None:
        """Each row carries org_size and organization_count."""
        for row in self.dashboard()["organizations_by_size"]:
            self.assertEqual({"org_size", "organization_count"}, set(row))


class TestCollaboratorVsContributor(MockBackedTestCase):
    """collaborator_vs_contributor reports both counts and shares."""

    def test_two_rows_in_documented_order(self) -> None:
        """Exactly the collaborator and contributor rows are returned."""
        rows = self.dashboard()["collaborator_vs_contributor"]
        self.assertEqual(["collaborator", "contributor"], [r["type"] for r in rows])

    def test_counts_match_oracle(self) -> None:
        """Counts match the is_collaborator / is_contributor flags."""
        rows = {r["type"]: r for r in self.dashboard()["collaborator_vs_contributor"]}
        self.assertEqual(
            sum(1 for r in ORG_ROWS if r["is_collaborator"] is True),
            rows["collaborator"]["organization_count"],
        )
        self.assertEqual(
            sum(1 for r in ORG_ROWS if r["is_contributor"] is True),
            rows["contributor"]["organization_count"],
        )

    def test_percentages_are_share_of_population(self) -> None:
        """Each percentage is that flag's share of all filtered organizations."""
        for row in self.dashboard()["collaborator_vs_contributor"]:
            self.assertAlmostEqual(
                round(row["organization_count"] * 100.0 / TOTAL_ORGS, 1),
                row["percentage"],
                places=1,
            )

    def test_row_shape(self) -> None:
        """Each row carries type, organization_count and percentage."""
        for row in self.dashboard()["collaborator_vs_contributor"]:
            self.assertEqual({"type", "organization_count", "percentage"}, set(row))


# --------------------------------------------------------------------------- #
# 6. Tab 3 - Ratings & Type
# --------------------------------------------------------------------------- #
class TestRatingDistribution(MockBackedTestCase):
    """rating_distribution always spans the full 1-5 scale."""

    def test_full_scale_always_present(self) -> None:
        """Ratings 1 through 5 are returned in ascending order."""
        rows = self.dashboard()["rating_distribution"]
        self.assertEqual([1, 2, 3, 4, 5], [r["rating"] for r in rows])

    def test_counts_match_oracle(self) -> None:
        """Counts match the rated organizations in the fixture."""
        oracle = Counter(
            r["org_rating"] for r in ORG_ROWS if r["org_rating"] is not None
        )
        rows = self.dashboard()["rating_distribution"]
        self.assertEqual(
            {rating: oracle.get(rating, 0) for rating in (1, 2, 3, 4, 5)},
            {r["rating"]: r["organization_count"] for r in rows},
        )

    def test_null_ratings_are_excluded_not_fatal(self) -> None:
        """Unrated organizations are omitted from the buckets without error."""
        rated = sum(1 for r in ORG_ROWS if r["org_rating"] is not None)
        rows = self.dashboard()["rating_distribution"]
        self.assertEqual(rated, sum(r["organization_count"] for r in rows))

    def test_row_shape(self) -> None:
        """Each row carries rating and organization_count."""
        for row in self.dashboard()["rating_distribution"]:
            self.assertEqual({"rating", "organization_count"}, set(row))


class TestOrganizationTypeDistribution(MockBackedTestCase):
    """organization_type_distribution is a cumulative for/non-profit split."""

    def test_row_shape(self) -> None:
        """Each point carries period, for_profit, non_profit and total."""
        for row in self.dashboard(group_by="yearly")["organization_type_distribution"]:
            self.assertEqual({"period", "for_profit", "non_profit", "total"}, set(row))

    def test_total_is_the_sum_of_both_types(self) -> None:
        """total always equals for_profit + non_profit."""
        for row in self.dashboard(group_by="monthly")["organization_type_distribution"]:
            self.assertEqual(row["for_profit"] + row["non_profit"], row["total"])

    def test_series_are_cumulative(self) -> None:
        """Both series are non-decreasing across periods."""
        rows = self.dashboard(group_by="monthly")["organization_type_distribution"]
        for series in ("for_profit", "non_profit", "total"):
            values = [r[series] for r in rows]
            self.assertEqual(sorted(values), values, f"{series} is not cumulative")

    def test_final_point_matches_oracle(self) -> None:
        """The last period totals every organization, split by type."""
        oracle = Counter(org._normalize_key(r["org_type"]) for r in ORG_ROWS)
        last = self.dashboard(group_by="yearly")["organization_type_distribution"][-1]
        self.assertEqual(oracle["forprofit"], last["for_profit"])
        self.assertEqual(oracle["nonprofit"], last["non_profit"])
        self.assertEqual(TOTAL_ORGS, last["total"])

    def test_yearly_split_matches_oracle(self) -> None:
        """Cumulative per-year splits match a running count over created_at."""
        per_year: dict[str, Counter] = defaultdict(Counter)
        for row in ORG_ROWS:
            per_year[str(row["created_at"])[:4]][org._normalize_key(row["org_type"])] += 1
        running, expected = Counter(), {}
        for year in sorted(per_year):
            running += per_year[year]
            expected[year] = (running["forprofit"], running["nonprofit"])
        rows = self.dashboard(group_by="yearly")["organization_type_distribution"]
        self.assertEqual(
            expected, {r["period"]: (r["for_profit"], r["non_profit"]) for r in rows}
        )


# --------------------------------------------------------------------------- #
# 7. Common filters
# --------------------------------------------------------------------------- #
class TestCommonFilters(MockBackedTestCase):
    """The shared date / region / organization_type filters."""

    def _total(self, **payload: Any) -> int:
        return self.dashboard(**payload)["summary"]["total_organizations"]

    def test_region_by_state_name(self) -> None:
        """region accepts a readable state name."""
        expected = len(oracle_rows(region=SAMPLE_STATE_NAME))
        self.assertGreater(expected, 0)
        self.assertEqual(expected, self._total(region=SAMPLE_STATE_NAME))

    def test_region_by_state_code(self) -> None:
        """region also accepts a state code."""
        self.assertEqual(
            len(oracle_rows(region=SAMPLE_STATE_ID)), self._total(region=SAMPLE_STATE_ID)
        )

    def test_region_is_case_insensitive(self) -> None:
        """region matching ignores case."""
        self.assertEqual(
            self._total(region=SAMPLE_STATE_NAME),
            self._total(region=SAMPLE_STATE_NAME.upper()),
        )

    def test_organization_type_filter(self) -> None:
        """organization_type filters on the snake_case values."""
        for value in ("non_profit", "for_profit"):
            with self.subTest(organization_type=value):
                expected = len(oracle_rows(organization_type=value))
                self.assertGreater(expected, 0)
                self.assertEqual(expected, self._total(organization_type=value))

    def test_all_sentinel_means_unfiltered(self) -> None:
        """'ALL' and null are both treated as no filter."""
        for payload in (
            {"region": "ALL", "organization_type": "ALL", "time_filter": "ALL"},
            {"region": None, "organization_type": None, "time_filter": None},
            {},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(TOTAL_ORGS, self._total(**payload))

    def test_combined_filters_intersect(self) -> None:
        """region and organization_type combine with AND."""
        expected = len(
            oracle_rows(region=SAMPLE_STATE_NAME, organization_type="non_profit")
        )
        self.assertEqual(
            expected,
            self._total(region=SAMPLE_STATE_NAME, organization_type="non_profit"),
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
        expected = sum(1 for r in ORG_ROWS if start <= str(r["created_at"]) <= end)
        self.assertEqual(
            expected,
            self._total(time_filter="CUSTOM", start_date=start, end_date=end),
        )

    def test_filters_apply_to_every_section(self) -> None:
        """A filter narrows every section consistently, not just the summary."""
        payload = self.dashboard(organization_type="non_profit")
        expected = len(oracle_rows(organization_type="non_profit"))
        self.assertEqual(expected, payload["summary"]["total_organizations"])
        self.assertEqual(
            expected, sum(r["organization_count"] for r in payload["organizations_by_size"])
        )
        self.assertEqual(
            expected,
            sum(r["organization_count"] for r in payload["organizations_by_location"]),
        )
        self.assertEqual(0, payload["organization_type_distribution"][-1]["for_profit"])


class TestInvalidFilters(unittest.TestCase):
    """Unsupported filter values are rejected rather than silently ignored."""

    def test_unknown_time_filter_rejected(self) -> None:
        """An unsupported time_filter is a validation error."""
        with self.assertRaises(ValueError):
            org._extract_filters({"time_filter": "LAST_FORTNIGHT"})

    def test_unknown_group_by_rejected(self) -> None:
        """An unsupported group_by is a validation error."""
        with self.assertRaises(ValueError):
            org._extract_filters({"group_by": "fortnightly"})

    def test_unknown_organization_type_rejected(self) -> None:
        """An unsupported organization_type is a validation error."""
        with self.assertRaises(ValueError):
            org._extract_filters({"organization_type": "charity"})

    def test_custom_without_dates_rejected(self) -> None:
        """CUSTOM without both bounds is a validation error."""
        with self.assertRaises(ValueError):
            org._extract_filters({"time_filter": "CUSTOM"})
        with self.assertRaises(ValueError):
            org._extract_filters({"time_filter": "CUSTOM", "start_date": "2026-01-01"})

    def test_supported_values_accepted(self) -> None:
        """Every documented filter value parses without error."""
        for time_filter in ("7D", "30D", "1Y", "ALL"):
            org._extract_filters({"time_filter": time_filter})
        for group_by in ("daily", "weekly", "monthly", "yearly"):
            org._extract_filters({"group_by": group_by})
        org._extract_filters(
            {"time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-06-30"}
        )


class TestEmptyResultSet(MockBackedTestCase):
    """A filter matching nothing returns a complete, zeroed payload."""

    EMPTY = {"region": "Atlantis"}

    def test_matches_nothing(self) -> None:
        """The chosen filter genuinely selects no organizations."""
        self.assertEqual([], oracle_rows(region="Atlantis"))

    def test_structure_is_still_complete(self) -> None:
        """Every documented key is present even with no matching rows."""
        self.assertEqual(TOP_LEVEL_KEYS, set(self.dashboard(**self.EMPTY)))

    def test_summary_is_zeroed(self) -> None:
        """All four KPI cards report zero, including the average."""
        summary = self.dashboard(**self.EMPTY)["summary"]
        self.assertEqual(0, summary["total_organizations"])
        self.assertEqual(0, summary["total_collaborators"])
        self.assertEqual(0, summary["total_contributors"])
        self.assertEqual(0.0, summary["average_org_rating"])

    def test_collections_are_empty_or_zero_filled(self) -> None:
        """Trends empty out while fixed-scale sections stay zero-filled."""
        payload = self.dashboard(**self.EMPTY)
        self.assertEqual([], payload["growth_trend"])
        self.assertEqual([], payload["organizations_by_location"])
        self.assertEqual([], payload["organizations_by_city"])
        self.assertEqual([], payload["organization_type_distribution"])
        self.assertEqual(
            [{"rating": r, "organization_count": 0} for r in (1, 2, 3, 4, 5)],
            payload["rating_distribution"],
        )
        self.assertEqual(
            [{"org_size": s, "organization_count": 0} for s in org.CANONICAL_ORG_SIZES],
            payload["organizations_by_size"],
        )

    def test_percentages_do_not_divide_by_zero(self) -> None:
        """Shares degrade to 0.0 rather than raising on an empty population."""
        for row in self.dashboard(**self.EMPTY)["collaborator_vs_contributor"]:
            self.assertEqual(0, row["organization_count"])
            self.assertEqual(0.0, row["percentage"])


# --------------------------------------------------------------------------- #
# 8. Contributor guard
# --------------------------------------------------------------------------- #
class TestContributorGuard(MockBackedTestCase):
    """ORG_IS_CONTRIBUTOR=false keeps the column out of the SQL entirely."""

    def test_guard_off_zeroes_contributor_figures(self) -> None:
        """Disabled guard reports 0 contributors without dropping keys."""
        with env(ORG_IS_CONTRIBUTOR="false"):
            payload = self.dashboard()
        self.assertEqual(0, payload["summary"]["total_contributors"])
        contributor = [
            r for r in payload["collaborator_vs_contributor"] if r["type"] == "contributor"
        ]
        self.assertEqual(1, len(contributor))
        self.assertEqual(0, contributor[0]["organization_count"])

    def test_guard_off_never_references_the_column(self) -> None:
        """No executed statement mentions is_contributor when disabled."""
        if mock_db.active_backend() != "sqlite":
            self.skipTest("SQL recording is only available on the SQLite backend")
        self.connection.executed_sql.clear()
        with env(ORG_IS_CONTRIBUTOR="false"):
            self.dashboard()
        offenders = [s for s in self.connection.executed_sql if "is_contributor" in s]
        self.assertEqual([], offenders, "is_contributor leaked into SQL while guarded")

    def test_recorder_sees_the_column_when_enabled(self) -> None:
        """Sanity check: the guard really is what suppresses the column."""
        if mock_db.active_backend() != "sqlite":
            self.skipTest("SQL recording is only available on the SQLite backend")
        self.connection.executed_sql.clear()
        with env(ORG_IS_CONTRIBUTOR="true"):
            self.dashboard()
        self.assertTrue(any("is_contributor" in s for s in self.connection.executed_sql))

    def test_response_shape_is_identical_either_way(self) -> None:
        """Toggling the guard adds or drops no JSON keys."""
        with env(ORG_IS_CONTRIBUTOR="true"):
            on = self.dashboard()
        with env(ORG_IS_CONTRIBUTOR="false"):
            off = self.dashboard()
        self.assertEqual(set(on), set(off))
        self.assertEqual(set(on["summary"]), set(off["summary"]))
        self.assertEqual(
            [r["type"] for r in on["collaborator_vs_contributor"]],
            [r["type"] for r in off["collaborator_vs_contributor"]],
        )


# --------------------------------------------------------------------------- #
# 9. Handler contract
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

    def test_returns_200_with_the_full_structure(self) -> None:
        """A standard request returns every documented top-level key."""
        response = org.lambda_handler({"time_filter": "ALL", "group_by": "monthly"})
        self.assertEqual(200, response["statusCode"])
        self.assertEqual(TOP_LEVEL_KEYS, set(self._body(response)))

    def test_accepts_api_gateway_string_body(self) -> None:
        """Filters are read from a JSON string body, as API Gateway sends."""
        event = {"body": json.dumps({"organization_type": "non_profit"})}
        body = self._body(org.lambda_handler(event))
        self.assertEqual(
            len(oracle_rows(organization_type="non_profit")),
            body["summary"]["total_organizations"],
        )

    def test_accepts_dict_body_and_bare_event(self) -> None:
        """A dict body and a bare invocation payload behave identically."""
        expected = len(oracle_rows(organization_type="for_profit"))
        for event in (
            {"body": {"organization_type": "for_profit"}},
            {"organization_type": "for_profit"},
        ):
            with self.subTest(event=event):
                body = self._body(org.lambda_handler(event))
                self.assertEqual(expected, body["summary"]["total_organizations"])

    def test_malformed_body_is_treated_as_no_filters(self) -> None:
        """An unparseable body does not crash the request."""
        response = org.lambda_handler({"body": "{not json"})
        self.assertEqual(200, response["statusCode"])

    def test_missing_and_empty_events(self) -> None:
        """None and {} are valid unfiltered requests."""
        for event in (None, {}):
            with self.subTest(event=event):
                self.assertEqual(200, org.lambda_handler(event)["statusCode"])

    def test_response_envelope(self) -> None:
        """Responses carry JSON content-type and CORS headers."""
        headers = org.lambda_handler({})["headers"]
        self.assertEqual("application/json", headers["Content-Type"])
        self.assertEqual("*", headers["Access-Control-Allow-Origin"])

    def test_invalid_filters_return_400(self) -> None:
        """Every unsupported filter value surfaces as a 400 with a message."""
        for payload in (
            {"time_filter": "CUSTOM"},
            {"time_filter": "LAST_FORTNIGHT"},
            {"group_by": "fortnightly"},
            {"organization_type": "charity"},
        ):
            with self.subTest(payload=payload):
                response = org.lambda_handler(payload)
                self.assertEqual(400, response["statusCode"])
                self.assertIn("error", self._body(response))

    def test_connection_failure_returns_500(self) -> None:
        """A dead database surfaces as a 500 without leaking details."""

        def boom() -> Any:
            raise RuntimeError("connection refused to 10.0.0.5")

        org.get_db_connection = boom
        response = org.lambda_handler({})
        self.assertEqual(500, response["statusCode"])
        self.assertEqual("internal server error", self._body(response)["error"])
        self.assertNotIn("10.0.0.5", response["body"])

    def test_single_query_failure_degrades_to_default(self) -> None:
        """One failing query yields a safe default while the request stays 200."""
        original = org.fetch_summary

        def boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("simulated query failure")

        org.fetch_summary = boom
        self.addCleanup(setattr, org, "fetch_summary", original)

        response = org.lambda_handler({})
        self.assertEqual(200, response["statusCode"])
        body = self._body(response)
        self.assertEqual(0, body["summary"]["total_organizations"])
        # Neighbouring sections still resolve normally.
        self.assertTrue(body["organizations_by_location"])

    def test_body_is_json_encoded_string(self) -> None:
        """The body is a JSON string, as API Gateway proxy integration expects."""
        response = org.lambda_handler({})
        self.assertIsInstance(response["body"], str)
        self.assertIsInstance(json.loads(response["body"]), dict)

    def test_documented_sample_payloads_all_succeed(self) -> None:
        """Every sample payload in the issue returns 200."""
        for payload in SAMPLE_PAYLOADS.values():
            with self.subTest(payload=payload):
                response = org.lambda_handler(dict(payload))
                self.assertEqual(200, response["statusCode"])
                self.assertEqual(TOP_LEVEL_KEYS, set(self._body(response)))


# --------------------------------------------------------------------------- #
# Sample payloads (verbatim from the issue) + results file generation
# --------------------------------------------------------------------------- #
SAMPLE_PAYLOADS: dict[str, dict[str, Any]] = {
    "Standard test": {
        "time_filter": "30D", "start_date": None, "end_date": None,
        "group_by": "daily", "region": "ALL", "organization_type": "ALL",
    },
    "Last 12 months": {
        "time_filter": "1Y", "start_date": None, "end_date": None,
        "group_by": "monthly", "region": "ALL", "organization_type": "ALL",
    },
    "Filter by region": {
        "time_filter": "1Y", "start_date": None, "end_date": None,
        "group_by": "monthly", "region": "California", "organization_type": "ALL",
    },
    "Filter by organization type": {
        "time_filter": "1Y", "start_date": None, "end_date": None,
        "group_by": "monthly", "region": "ALL", "organization_type": "non_profit",
    },
    "Custom date range": {
        "time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-06-30",
        "group_by": "monthly", "region": "ALL", "organization_type": "ALL",
    },
}


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
    "TestNoSharedDatabaseAccess": "No shared-database access (review feedback)",
    "TestFixtures": "Mock fixtures",
    "TestKpiSummary": "KPI cards",
    "TestGrowthTrend": "Tab 1 - Growth trend",
    "TestOrganizationsByLocation": "Tab 1 - Organizations by location",
    "TestOrganizationsBySize": "Tab 2 - Organizations by size",
    "TestCollaboratorVsContributor": "Tab 2 - Collaborator vs contributor",
    "TestRatingDistribution": "Tab 3 - Rating distribution",
    "TestOrganizationTypeDistribution": "Tab 3 - For-profit vs non-profit",
    "TestCommonFilters": "Common filters",
    "TestInvalidFilters": "Invalid filters",
    "TestEmptyResultSet": "Empty result sets",
    "TestContributorGuard": "Contributor guard (ORG_IS_CONTRIBUTOR)",
    "TestLambdaHandler": "Lambda handler contract",
}


def _sample_responses() -> list[tuple[str, Any, dict[str, Any]]]:
    """Produce the sample request/response pairs recorded in the report."""
    original = org.get_db_connection
    org.get_db_connection = mock_db.load_mock_database
    try:
        samples: list[tuple[str, Any, dict[str, Any]]] = []
        for title, payload in SAMPLE_PAYLOADS.items():
            response = org.lambda_handler(dict(payload))
            samples.append((title, payload, {
                "statusCode": response["statusCode"],
                "body": json.loads(response["body"]),
            }))

        # A region that exists in the fixture, so the filtered shape is visible.
        populated = {
            "time_filter": "ALL", "start_date": None, "end_date": None,
            "group_by": "yearly", "region": SAMPLE_STATE_NAME,
            "organization_type": "ALL",
        }
        response = org.lambda_handler(dict(populated))
        samples.append((
            f"Filter by region - {SAMPLE_STATE_NAME} (present in the fixture)",
            populated,
            {"statusCode": response["statusCode"], "body": json.loads(response["body"])},
        ))

        for title, payload in (
            ("Validation error - CUSTOM without dates", {"time_filter": "CUSTOM"}),
            ("Validation error - unsupported organization_type",
             {"organization_type": "charity"}),
        ):
            response = org.lambda_handler(dict(payload))
            samples.append((title, payload, {
                "statusCode": response["statusCode"],
                "body": json.loads(response["body"]),
            }))

        def boom() -> Any:
            raise RuntimeError("simulated database outage")

        org.get_db_connection = boom
        outage = org.lambda_handler({})
        samples.append((
            "Database failure - connection refused",
            {},
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
    add("| Endpoint | `POST /analytics/organizations` |")
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
    add("Generated by invoking `lambda_handler` against the mock fixtures. The "
        "first five payloads are the sample payloads from the issue, verbatim.")
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
    add(f"- `growth_trend` and `organization_type_distribution` are **cumulative** "
        f"running totals, matching the figures in the issue (its stacked-bar sample "
        f"reaches 109 then 111 against a 126 total, which only holds if each period "
        f"reports the total reached rather than the number added).")
    add(f"- The fixture contains {unrated} organizations with a NULL rating. NULL "
        f"handling is still exercised: unrated rows are excluded from the buckets "
        f"and from the average without error, and `rating_distribution` always "
        f"returns the full 1-5 scale zero-filled.")
    add("- `region` resolves through the `state` lookup table and accepts either a "
        "readable state name (`California`) or a state code (`CA`), case-insensitively.")
    add("- The default SQLite backend applies a small compatibility shim "
        "(`%s` placeholders, `INTERVAL` arithmetic, `::numeric`, `DATE_TRUNC`, "
        "`TO_CHAR`). Set `MOCK_DB_BACKEND=postgres` with `DB_*` pointing at a "
        "local PostgreSQL to run the identical assertions against real "
        "PostgreSQL; see `data-analytics/tests/mock_db.py`.")
    add("- `is_contributor` is present in the fixture, so contributor figures "
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
