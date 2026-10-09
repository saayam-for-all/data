"""Mock-backed test suite for the Rating & Type Analytics API (Issue #380).

Every assertion runs against the committed mock fixtures in
``data-analytics/sql`` (``organizations.csv``, ``state.csv``, ``country.csv``).
Nothing in this suite reaches a database: the Lambda's mock path is pandas over
CSVs, and the PostgreSQL path is never entered.

Expected values are derived from the CSVs at runtime rather than hard-coded, so
the suite keeps passing when the fixtures are regenerated. The fixed buckets are
computed against a **pinned reference date** so 7D/30D/1Y windows do not drift
as real time passes.

Three things the committed fixture cannot express, covered with synthetic
frames:

* ``7D`` and ``30D`` are empty against it (the newest ``created_at`` is
  2026-01-10), so daily granularity is verified synthetically.
* every ``org_rating`` is populated, so the null-rating path needs its own frame.
* every ``org_type`` is recognized, so the unknown-type path does too.

Run it:

    python data-analytics/tests/test_rating_type_analytics.py

Add ``--emit-results`` to also regenerate ``TEST_RESULTS_380.md`` next to this
file, capturing the pass/fail table and sample API responses.
"""

from __future__ import annotations

import json
import os
import re
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

import rating_type_analytics as rta  # noqa: E402


# A pinned reference date keeps the fixed-bucket windows deterministic.
REFERENCE_DATE = date(2026, 9, 25)

ORGANIZATION_ROWS = rta.load_organizations(str(SQL_DIR))
TOTAL_ORGANIZATIONS = len(ORGANIZATION_ROWS)

BUCKET_KEYS = {"rating_distribution", "organization_mix_trend"}
SERIES_KEYS = {"non_profit", "for_profit"}
FULL_TOP_LEVEL_KEYS = {"7D", "30D", "1Y", "All", "Custom"}

DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")

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
        response = rta.lambda_handler(payload)
    return response["statusCode"], json.loads(response["body"])


def analytics(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the response body directly, with the reference date pinned."""
    filters = rta.extract_filters(payload)
    return rta.build_analytics(ORGANIZATION_ROWS, filters, today=REFERENCE_DATE)


def oracle_frame(country: Optional[str] = None) -> pd.DataFrame:
    """Filter the fixture in pandas, mirroring the Lambda's country filter."""
    frame = ORGANIZATION_ROWS
    if country is not None:
        key = rta._normalize_key(country)
        codes = frame["country_code"].map(rta._normalize_key)
        names = frame["country_name"].map(rta._normalize_key)
        frame = frame[(codes == key) | (names == key)]
    return frame


def synthetic_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a small organizations frame in the shape the charts expect."""
    columns = [
        "org_id", "org_rating", "org_type", "created_at",
        "country_code", "country_name",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(rows)
    frame["created_at"] = pd.to_datetime(frame["created_at"])
    frame["org_rating"] = pd.to_numeric(
        frame["org_rating"], errors="coerce"
    ).astype("Int64")
    return frame


def org(org_id: str, rating: Any, org_type: str, created_at: str) -> dict[str, Any]:
    """Shorthand for one synthetic organization row."""
    return {
        "org_id": org_id,
        "org_rating": rating,
        "org_type": org_type,
        "created_at": created_at,
        "country_code": "AFG",
        "country_name": "AFGHANISTAN",
    }


# --------------------------------------------------------------------------- #
# 1. Fixtures
# --------------------------------------------------------------------------- #
class TestFixtures(unittest.TestCase):
    """The committed CSVs load and carry the columns the charts need."""

    def test_organizations_load(self) -> None:
        """The three CSVs resolve and join into a usable frame."""
        self.assertGreater(TOTAL_ORGANIZATIONS, 0)
        for column in ("org_id", "org_rating", "org_type", "created_at"):
            self.assertIn(column, ORGANIZATION_ROWS.columns)

    def test_singular_filenames_resolve(self) -> None:
        """state.csv/country.csv are found even though the issue says plural."""
        self.assertTrue(rta._resolve_csv("states", str(SQL_DIR)).endswith("state.csv"))
        self.assertTrue(
            rta._resolve_csv("countries", str(SQL_DIR)).endswith("country.csv")
        )

    def test_missing_csv_is_reported_clearly(self) -> None:
        """A directory with no fixtures raises a named error, not a KeyError."""
        with self.assertRaises(rta.MockDataError):
            rta._resolve_csv("organizations", str(TESTS_DIR))

    def test_org_rating_is_a_nullable_integer(self) -> None:
        """org_rating is read as the literal integer, not a float or string."""
        self.assertEqual("Int64", str(ORGANIZATION_ROWS["org_rating"].dtype))

    def test_ratings_are_within_the_expected_scale(self) -> None:
        """Every rating in the fixture falls on the 1-5 scale."""
        ratings = set(ORGANIZATION_ROWS["org_rating"].dropna().astype(int))
        self.assertTrue(ratings.issubset({1, 2, 3, 4, 5}), ratings)

    def test_short_buckets_are_empty_against_this_fixture(self) -> None:
        """Records why daily granularity is verified synthetically."""
        for bucket in ("7D", "30D"):
            start, end = rta.bucket_window(bucket, REFERENCE_DATE)
            self.assertEqual(0, len(rta.window_frame(ORGANIZATION_ROWS, start, end)))


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
        for bucket, charts in analytics({}).items():
            self.assertEqual(BUCKET_KEYS, set(charts), bucket)

    def test_mix_trend_always_has_both_series(self) -> None:
        """Both series keys are present in every bucket, even when empty."""
        for bucket, charts in analytics({}).items():
            self.assertEqual(
                SERIES_KEYS, set(charts["organization_mix_trend"]), bucket
            )

    def test_custom_is_empty_when_no_range_supplied(self) -> None:
        """Custom is present, with an empty chart and two empty series."""
        custom = analytics({})["Custom"]
        self.assertEqual([], custom["rating_distribution"])
        self.assertEqual(
            {"non_profit": [], "for_profit": []}, custom["organization_mix_trend"]
        )

    def test_all_bucket_covers_every_organization(self) -> None:
        """The unbounded All bucket rates every organization in the fixture."""
        ratings = analytics({})["All"]["rating_distribution"]
        self.assertEqual(
            int(ORGANIZATION_ROWS["org_rating"].notna().sum()),
            sum(row["count"] for row in ratings),
        )

    def test_empty_bucket_returns_empty_arrays(self) -> None:
        """A window with no organizations does not crash."""
        self.assertEqual(rta.empty_bucket(), analytics({})["7D"])


# --------------------------------------------------------------------------- #
# 3. Rating distribution - categorical
# --------------------------------------------------------------------------- #
class TestRatingDistribution(unittest.TestCase):
    """rating_distribution is a window-scoped categorical breakdown."""

    def test_counts_match_the_fixture(self) -> None:
        """The All bucket reproduces the fixture's rating counts."""
        expected = (
            ORGANIZATION_ROWS["org_rating"].dropna().astype(int).value_counts()
        )
        actual = {
            row["rating"]: row["count"]
            for row in analytics({})["All"]["rating_distribution"]
        }
        self.assertEqual(dict(sorted(expected.items())), dict(sorted(actual.items())))

    def test_rows_are_ascending_by_rating(self) -> None:
        """Ratings have a natural order, so the chart reads left to right."""
        ratings = [
            row["rating"] for row in analytics({})["All"]["rating_distribution"]
        ]
        self.assertEqual(sorted(ratings), ratings)

    def test_rating_is_a_plain_integer(self) -> None:
        """The literal integer rating is emitted, not a float or string."""
        for row in analytics({})["All"]["rating_distribution"]:
            self.assertIs(int, type(row["rating"]))
            self.assertIs(int, type(row["count"]))

    def test_absent_ratings_are_not_zero_filled(self) -> None:
        """Only ratings present in the window appear."""
        frame = synthetic_frame([
            org("A", 2, "Non-Profit", "2026-01-01"),
            org("B", 5, "For-profit", "2026-01-02"),
        ])
        self.assertEqual(
            [{"rating": 2, "count": 1}, {"rating": 5, "count": 1}],
            rta.build_rating_chart(frame),
        )

    def test_null_ratings_are_excluded(self) -> None:
        """An unrated organization is left out rather than bucketed."""
        frame = synthetic_frame([
            org("A", 3, "Non-Profit", "2026-01-01"),
            org("B", None, "For-profit", "2026-01-02"),
        ])
        self.assertEqual([{"rating": 3, "count": 1}], rta.build_rating_chart(frame))

    def test_all_null_ratings_gives_an_empty_chart(self) -> None:
        """A window where nothing is rated returns [], not a null bucket."""
        frame = synthetic_frame([org("A", None, "Non-Profit", "2026-01-01")])
        self.assertEqual([], rta.build_rating_chart(frame))

    def test_empty_frame_returns_empty_chart(self) -> None:
        """No organizations means an empty array."""
        self.assertEqual([], rta.build_rating_chart(synthetic_frame([])))

    def test_single_row_frame(self) -> None:
        """A one-row dataset produces a single rating row."""
        frame = synthetic_frame([org("A", 4, "Non-Profit", "2026-01-01")])
        self.assertEqual([{"rating": 4, "count": 1}], rta.build_rating_chart(frame))


# --------------------------------------------------------------------------- #
# 4. Organization mix trend - cumulative time series
# --------------------------------------------------------------------------- #
class TestMixTrend(unittest.TestCase):
    """organization_mix_trend is cumulative, sparse and window-scoped."""

    def test_counts_are_non_decreasing(self) -> None:
        """Each series only ever climbs within a bucket."""
        for bucket, charts in analytics({}).items():
            for series, points in charts["organization_mix_trend"].items():
                counts = [point["count"] for point in points]
                self.assertEqual(
                    sorted(counts), counts, f"{bucket}/{series} not cumulative"
                )

    def test_periods_are_strictly_increasing(self) -> None:
        """Periods are ordered oldest first with no repeats."""
        for bucket, charts in analytics({}).items():
            for series, points in charts["organization_mix_trend"].items():
                periods = [point["period"] for point in points]
                self.assertEqual(sorted(set(periods)), periods, f"{bucket}/{series}")

    def test_final_value_equals_the_window_total(self) -> None:
        """The last running total is that type's count inside the window."""
        for bucket in rta.FIXED_BUCKETS:
            start, end = rta.bucket_window(bucket, REFERENCE_DATE)
            windowed = rta.window_frame(ORGANIZATION_ROWS, start, end)
            keys = windowed["org_type"].map(
                lambda value: rta.TYPE_SERIES_KEYS.get(rta._normalize_key(value))
            )
            trend = analytics({})[bucket]["organization_mix_trend"]
            for series in rta.SERIES_ORDER:
                expected = int((keys == series).sum())
                points = trend[series]
                actual = points[-1]["count"] if points else 0
                self.assertEqual(expected, actual, f"{bucket}/{series}")

    def test_accumulation_restarts_per_bucket(self) -> None:
        """A bucket counts only its own window, not all history before it."""
        one_year = analytics({})["1Y"]["organization_mix_trend"]["non_profit"]
        self.assertTrue(one_year)
        # Window-scoped accumulation always opens at the count of that first
        # period alone; carrying history forward would open much higher.
        start, _ = rta.bucket_window("1Y", REFERENCE_DATE)
        before = ORGANIZATION_ROWS[
            ORGANIZATION_ROWS["created_at"] < pd.Timestamp(start)
        ]
        self.assertGreater(len(before), 0)
        self.assertLess(one_year[0]["count"], len(before))

    def test_periods_are_sparse(self) -> None:
        """Periods with no new organizations of that type are omitted."""
        frame = synthetic_frame([
            org("A", 3, "Non-Profit", "2026-01-01"),
            # nothing in February
            org("B", 4, "Non-Profit", "2026-03-01"),
        ])
        points = rta.build_mix_trend(frame, "month")["non_profit"]
        self.assertEqual(["2026-01", "2026-03"], [p["period"] for p in points])
        self.assertEqual([1, 2], [p["count"] for p in points])

    def test_daily_granularity(self) -> None:
        """7D/30D/Custom group by day."""
        frame = synthetic_frame([
            org("A", 3, "Non-Profit", "2026-01-01"),
            org("B", 4, "Non-Profit", "2026-01-02"),
        ])
        points = rta.build_mix_trend(frame, "day")["non_profit"]
        self.assertEqual(["2026-01-01", "2026-01-02"], [p["period"] for p in points])

    def test_bucket_granularity_matches_the_contract(self) -> None:
        """1Y and All emit YYYY-MM; Custom emits YYYY-MM-DD."""
        body = analytics({})
        for bucket in ("1Y", "All"):
            for points in body[bucket]["organization_mix_trend"].values():
                for point in points:
                    self.assertRegex(point["period"], MONTH_PATTERN, bucket)

        custom = analytics({
            "type_start_date": "2023-01-01", "type_end_date": "2026-12-31"
        })["Custom"]["organization_mix_trend"]
        self.assertTrue(custom["non_profit"])
        for points in custom.values():
            for point in points:
                self.assertRegex(point["period"], DAY_PATTERN)

    def test_both_series_present_when_only_one_has_data(self) -> None:
        """A window with one type still reports the other as an empty list."""
        frame = synthetic_frame([org("A", 3, "Non-Profit", "2026-01-01")])
        trend = rta.build_mix_trend(frame, "month")
        self.assertEqual(SERIES_KEYS, set(trend))
        self.assertEqual([], trend["for_profit"])

    def test_stored_labels_map_to_snake_case_series(self) -> None:
        """Non-Profit/For-profit become non_profit/for_profit."""
        frame = synthetic_frame([
            org("A", 3, "Non-Profit", "2026-01-01"),
            org("B", 4, "For-profit", "2026-01-01"),
        ])
        trend = rta.build_mix_trend(frame, "month")
        self.assertEqual(1, trend["non_profit"][0]["count"])
        self.assertEqual(1, trend["for_profit"][0]["count"])

    def test_unknown_type_does_not_create_a_third_series(self) -> None:
        """An unrecognized org_type is skipped, keeping the contract intact."""
        frame = synthetic_frame([
            org("A", 3, "Non-Profit", "2026-01-01"),
            org("B", 4, "Charity", "2026-01-01"),
        ])
        trend = rta.build_mix_trend(frame, "month")
        self.assertEqual(SERIES_KEYS, set(trend))
        self.assertEqual(1, trend["non_profit"][0]["count"])
        self.assertEqual([], trend["for_profit"])

    def test_empty_frame_returns_two_empty_series(self) -> None:
        """No organizations still yields both keys."""
        self.assertEqual(
            {"non_profit": [], "for_profit": []},
            rta.build_mix_trend(synthetic_frame([]), "month"),
        )

    def test_counts_are_plain_ints(self) -> None:
        """No numpy integer leaks into the series."""
        for charts in analytics({}).values():
            for points in charts["organization_mix_trend"].values():
                for point in points:
                    self.assertIs(int, type(point["count"]))
                    self.assertIs(str, type(point["period"]))


# --------------------------------------------------------------------------- #
# 5. Country filter
# --------------------------------------------------------------------------- #
class TestCountryFilter(unittest.TestCase):
    """country narrows both charts, in every response shape."""

    def test_country_code_filter(self) -> None:
        """Filtering by the code the fixture resolves to keeps every row."""
        expected = len(oracle_frame(country=FIXTURE_COUNTRY_CODE))
        ratings = analytics({"country": FIXTURE_COUNTRY_CODE})["All"][
            "rating_distribution"
        ]
        self.assertEqual(expected, sum(row["count"] for row in ratings))

    def test_country_name_filter(self) -> None:
        """The country filter accepts a name as well as a code."""
        self.assertEqual(
            analytics({"country": FIXTURE_COUNTRY_CODE}),
            analytics({"country": FIXTURE_COUNTRY_NAME}),
        )

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
        self.assertEqual(rta.empty_bucket(), analytics({"country": "USA"})["All"])

    def test_all_sentinel_means_no_filter(self) -> None:
        """ALL and an absent filter produce the same response."""
        self.assertEqual(analytics({}), analytics({"country": "ALL"}))

    def test_filter_applies_to_custom_responses(self) -> None:
        """A Custom-only response honours the country filter."""
        payload = {
            "rating_start_date": "2023-01-01",
            "rating_end_date": "2026-12-31",
            "country": "USA",
        }
        self.assertEqual([], analytics(payload)["Custom"]["rating_distribution"])

    def test_no_organization_type_filter_exists(self) -> None:
        """This tab deliberately has no type filter; it is ignored if sent."""
        self.assertEqual(
            analytics({}), analytics({"organization_type": "non_profit"})
        )


# --------------------------------------------------------------------------- #
# 6. Custom-only response shapes
# --------------------------------------------------------------------------- #
class TestCustomResponseShape(unittest.TestCase):
    """Either Custom pair collapses the response to a single Custom key."""

    RATING_RANGE = {"rating_start_date": "2023-01-01", "rating_end_date": "2024-12-31"}
    TYPE_RANGE = {"type_start_date": "2025-01-01", "type_end_date": "2026-12-31"}

    def test_rating_range_only(self) -> None:
        """Only the rating chart is populated, and no fixed buckets appear."""
        status_code, body = invoke(dict(self.RATING_RANGE))
        self.assertEqual(200, status_code)
        self.assertEqual({"Custom"}, set(body))
        self.assertTrue(body["Custom"]["rating_distribution"])
        self.assertEqual(
            {"non_profit": [], "for_profit": []},
            body["Custom"]["organization_mix_trend"],
        )

    def test_type_range_only(self) -> None:
        """The mirror image: only the mix trend is populated."""
        status_code, body = invoke(dict(self.TYPE_RANGE))
        self.assertEqual(200, status_code)
        self.assertEqual({"Custom"}, set(body))
        self.assertEqual([], body["Custom"]["rating_distribution"])
        self.assertTrue(body["Custom"]["organization_mix_trend"]["non_profit"])

    def test_both_ranges_populate_both_charts(self) -> None:
        """Both pairs are evaluated - neither is dropped, neither wins."""
        status_code, body = invoke({**self.RATING_RANGE, **self.TYPE_RANGE})
        self.assertEqual(200, status_code)
        self.assertEqual({"Custom"}, set(body))
        self.assertTrue(body["Custom"]["rating_distribution"])
        self.assertTrue(body["Custom"]["organization_mix_trend"]["non_profit"])

    def test_each_chart_uses_its_own_range(self) -> None:
        """The ranges are deliberately disjoint, so a shared window fails."""
        both = analytics({**self.RATING_RANGE, **self.TYPE_RANGE})["Custom"]
        rating_only = analytics(dict(self.RATING_RANGE))["Custom"]
        type_only = analytics(dict(self.TYPE_RANGE))["Custom"]

        self.assertEqual(
            rating_only["rating_distribution"], both["rating_distribution"]
        )
        self.assertEqual(
            type_only["organization_mix_trend"], both["organization_mix_trend"]
        )

        rating_ids = set(
            rta.window_frame(ORGANIZATION_ROWS, date(2023, 1, 1), date(2024, 12, 31))[
                "org_id"
            ]
        )
        type_ids = set(
            rta.window_frame(ORGANIZATION_ROWS, date(2025, 1, 1), date(2026, 12, 31))[
                "org_id"
            ]
        )
        self.assertTrue(rating_ids)
        self.assertTrue(type_ids)
        self.assertEqual(set(), rating_ids & type_ids)

    def test_custom_bucket_keeps_the_same_shape(self) -> None:
        """The Custom-only body has the two chart keys and both series."""
        custom = analytics(dict(self.RATING_RANGE))["Custom"]
        self.assertEqual(BUCKET_KEYS, set(custom))
        self.assertEqual(SERIES_KEYS, set(custom["organization_mix_trend"]))

    def test_custom_range_with_no_matches_is_empty_not_an_error(self) -> None:
        """A valid range containing no organizations returns empty arrays."""
        status_code, body = invoke(
            {"rating_start_date": "1999-01-01", "rating_end_date": "1999-12-31"}
        )
        self.assertEqual(200, status_code)
        self.assertEqual({"Custom"}, set(body))
        self.assertEqual([], body["Custom"]["rating_distribution"])


# --------------------------------------------------------------------------- #
# 7. Validation and error handling
# --------------------------------------------------------------------------- #
class TestValidation(unittest.TestCase):
    """Malformed input fails with a clear 400, never a partial result."""

    def test_half_a_rating_pair_is_rejected(self) -> None:
        """Only one half of the rating pair is an error, not a silent skip."""
        for payload in (
            {"rating_start_date": "2026-01-01"},
            {"rating_end_date": "2026-01-01"},
        ):
            status_code, body = invoke(payload)
            self.assertEqual(400, status_code, payload)
            self.assertIn("must be provided together", body["error"])

    def test_half_a_type_pair_is_rejected(self) -> None:
        """The type pair is validated the same way."""
        for payload in (
            {"type_start_date": "2026-01-01"},
            {"type_end_date": "2026-01-01"},
        ):
            status_code, body = invoke(payload)
            self.assertEqual(400, status_code, payload)
            self.assertIn("must be provided together", body["error"])

    def test_bad_date_format_is_rejected(self) -> None:
        """Anything that is not YYYY-MM-DD is an error."""
        for value in ("not-a-date", "01-01-2026", "2026/01/01", "2026-1-1", ""):
            status_code, body = invoke(
                {"rating_start_date": value, "rating_end_date": "2026-12-31"}
            )
            self.assertEqual(400, status_code, value)
            self.assertIn("YYYY-MM-DD", body["error"])

    def test_impossible_calendar_date_is_rejected(self) -> None:
        """A well-formed but non-existent date is still an error."""
        status_code, body = invoke(
            {"type_start_date": "2026-02-30", "type_end_date": "2026-12-31"}
        )
        self.assertEqual(400, status_code)
        self.assertIn("valid calendar date", body["error"])

    def test_start_after_end_is_rejected(self) -> None:
        """An inverted range is an error for both pairs."""
        for start_key, end_key in (
            ("rating_start_date", "rating_end_date"),
            ("type_start_date", "type_end_date"),
        ):
            status_code, body = invoke({start_key: "2026-12-31", end_key: "2026-01-01"})
            self.assertEqual(400, status_code, start_key)
            self.assertIn("on or before", body["error"])

    def test_one_bad_pair_fails_the_whole_request(self) -> None:
        """A valid pair beside a broken one returns 400, not partial data."""
        status_code, body = invoke({
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
            "type_start_date": "nonsense",
            "type_end_date": "2026-12-31",
        })
        self.assertEqual(400, status_code)
        self.assertEqual({"error"}, set(body))

    def test_validation_precedes_data_access(self) -> None:
        """A malformed request never reads the CSVs."""
        original = rta.load_data
        rta.load_data = lambda: (_ for _ in ()).throw(
            AssertionError("data must not be loaded for an invalid request")
        )
        try:
            status_code, _ = invoke({"rating_start_date": "bad"})
        finally:
            rta.load_data = original
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
        original = rta.load_data

        def boom() -> Any:
            raise RuntimeError("/secret/path/organizations.csv is unreadable")

        rta.load_data = boom
        try:
            status_code, body = invoke({})
        finally:
            rta.load_data = original
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
            response = rta.lambda_handler({})
        self.assertIsInstance(response["body"], str)
        self.assertEqual(FULL_TOP_LEVEL_KEYS, set(json.loads(response["body"])))

    def test_cors_headers_are_present(self) -> None:
        """Every response carries the shared CORS headers."""
        response = rta.build_response(200, {"ok": True})
        self.assertEqual("application/json", response["headers"]["Content-Type"])
        self.assertEqual("*", response["headers"]["Access-Control-Allow-Origin"])

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

    def test_db_path_requires_configuration(self) -> None:
        """Switching off mock data without DB_HOST is an error, not a fallback."""
        with env(USE_MOCK_DATA="false", DB_HOST=None):
            with self.assertRaises(RuntimeError):
                rta.get_db_connection()

    def test_source_has_no_parameter_store_references(self) -> None:
        """No boto3/SSM call path exists in the module."""
        source = (LAMBDA_DIR / "rating_type_analytics.py").read_text(encoding="utf-8")
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
    "TestRatingDistribution": "Chart 1 - rating distribution",
    "TestMixTrend": "Chart 2 - organization mix trend",
    "TestCountryFilter": "country filter",
    "TestCustomResponseShape": "Custom-only response shapes",
    "TestValidation": "Validation and error handling",
    "TestHandlerContract": "Handler contract",
}


def emit_results(result: _RecordingResult, duration: float) -> Path:
    """Write ``TEST_RESULTS_380.md`` beside this file and return its path."""
    total = len(result.records)
    passed = sum(1 for r in result.records if r[3] == "PASS")
    skipped = sum(1 for r in result.records if r[3] == "SKIP")
    failed = total - passed - skipped

    lines: list[str] = []
    add = lines.append
    add("# Rating & Type Analytics API - Test Results (Issue #380)")
    add("")
    add(f"**{passed}/{total} checks passed**"
        + (f", {failed} failed" if failed else "")
        + (f", {skipped} skipped" if skipped else "")
        + f" in {duration:.2f}s.")
    add("")
    add("| | |")
    add("|---|---|")
    add("| Module under test | `data-analytics/lambda_functions/rating_type_analytics.py` |")
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
    add("| `rating_*` only | `Custom` only - rating populated |")
    add("| `type_*` only | `Custom` only - mix trend populated |")
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
    add("Printed by `python data-analytics/lambda_functions/rating_type_analytics.py`.")
    add("")
    for label, event in rta._sample_events():
        with env(MOCK_DATA_DIR=str(SQL_DIR), USE_MOCK_DATA="true"):
            response = rta.lambda_handler(dict(event))
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
    add("- `organization_mix_trend` is **window-scoped**: every bucket restarts its "
        "running total at zero and counts only organizations created inside its own "
        "window. The issue calls these \"all-time running totals\", but its own worked "
        "example shows `1Y` opening at 8 while `All` has already reached 45 at an "
        "earlier period, which is only possible if each bucket restarts.")
    add("- Series are **sparse**: a period with no new organizations of that type is "
        "omitted rather than repeated. Both series keys are always present, even when "
        "empty.")
    add("- `rating_distribution` emits the literal integer rating, ascending, with no "
        "zero-filling of absent ratings. Unrated organizations are excluded rather "
        "than bucketed.")
    add("- The stored `Non-Profit`/`For-profit` labels are mapped onto the "
        "`non_profit`/`for_profit` series names the issue specifies. This differs "
        "from #376, where the issue asked for the raw enum value.")
    add("- `7D` and `30D` are empty against this fixture: its newest `created_at` is "
        "2026-01-10, well outside both windows from the pinned reference date. Daily "
        "granularity is therefore verified with synthetic frames.")
    add("- A `country` filter of `\"USA\"` matches nothing. Every US state in "
        "`state.csv` carries `country_id=1`, which `country.csv` maps to "
        "`AFGHANISTAN`/`AFG`. That is a mock-data defect; the join itself is correct.")
    add("- There is deliberately no `organization_type` filter on this tab - chart 2 "
        "is the type breakdown, so filtering by type would show one side of its own "
        "stacked bar. An `organization_type` key in the request is ignored.")

    path = TESTS_DIR / "TEST_RESULTS_380.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    """Run the suite, optionally regenerating ``TEST_RESULTS_380.md``."""
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
