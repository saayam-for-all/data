"""Focused tests for Growth & Location Analytics date-range helpers."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LAMBDA_ROOT = Path(__file__).resolve().parents[2] / "data-analytics" / "lambda_functions"
sys.path.insert(0, str(LAMBDA_ROOT))

from growth_location_analytics.date_ranges import (
    AnalyticsDateRanges,
    DateRangeError,
    resolve_date_ranges,
)

from tests.growth_location_helpers import utc_window

REFERENCE = datetime(2026, 9, 15, 18, 42, 11, tzinfo=timezone.utc)


def _resolve(**kwargs) -> AnalyticsDateRanges:
    return resolve_date_ranges(reference_time=REFERENCE, **kwargs)


def test_fixed_ranges_use_inclusive_utc_calendar_days():
    ranges = _resolve()

    assert set(ranges.fixed) == {"7D", "30D", "1Y", "All"}
    assert ranges.fixed["7D"].start == datetime(2026, 9, 9, tzinfo=timezone.utc)
    assert ranges.fixed["7D"].end_exclusive == datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert ranges.fixed["30D"].start == datetime(2026, 8, 17, tzinfo=timezone.utc)
    assert ranges.fixed["30D"].end_exclusive == datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert ranges.fixed["1Y"].start == datetime(2025, 9, 15, tzinfo=timezone.utc)
    assert ranges.fixed["1Y"].end_exclusive == datetime(2026, 9, 16, tzinfo=timezone.utc)
    window = ranges.fixed["1Y"]
    assert window.start.strftime("%Y-%m") == "2025-09"
    assert (window.end_exclusive - timedelta(days=1)).strftime("%Y-%m") == "2026-09"


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {
            "start_date": None,
            "end_date": None,
            "location_start_date": None,
            "location_end_date": None,
        },
    ],
)
def test_all_is_explicitly_unbounded_and_custom_absence_is_distinct(kwargs):
    ranges = _resolve(**kwargs)

    assert ranges.fixed["All"].is_unbounded
    assert ranges.fixed["All"].start is None
    assert ranges.fixed["All"].end_exclusive is None
    assert ranges.growth_custom is None
    assert ranges.location_custom is None


@pytest.mark.parametrize("growth,location", [(True, False), (False, True), (True, True)])
def test_custom_pairs_resolve_independently(growth, location):
    kwargs = {}
    if growth:
        kwargs.update(start_date="2026-01-02", end_date="2026-01-04")
    if location:
        kwargs.update(location_start_date="2025-03-10", location_end_date="2025-03-11")
    ranges = _resolve(**kwargs)

    assert ranges.growth_custom == (utc_window("2026-01-02", "2026-01-05") if growth else None)
    assert ranges.location_custom == (utc_window("2025-03-10", "2025-03-12") if location else None)


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"start_date": "01/02/2026", "end_date": "2026-01-03"}, "start_date"),
        ({"start_date": "2026-1-02", "end_date": "2026-01-03"}, "start_date"),
        (
            {
                "location_start_date": "2026-01-02",
                "location_end_date": "2026-01-03T00:00:00Z",
            },
            "location_end_date",
        ),
    ],
)
def test_invalid_date_formats_are_rejected(kwargs, field):
    with pytest.raises(DateRangeError, match=field):
        _resolve(**kwargs)


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"start_date": "2026-02-30", "end_date": "2026-03-01"}, "start_date"),
        (
            {
                "location_start_date": "2025-02-01",
                "location_end_date": "2025-02-29",
            },
            "location_end_date",
        ),
    ],
)
def test_impossible_calendar_dates_are_rejected(kwargs, field):
    with pytest.raises(DateRangeError, match=rf"{field}.*valid calendar date"):
        _resolve(**kwargs)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"start_date": "2026-05-02", "end_date": "2026-05-01"},
            "start_date must be on or before end_date",
        ),
        (
            {
                "location_start_date": "2026-05-02",
                "location_end_date": "2026-05-01",
            },
            "location_start_date must be on or before location_end_date",
        ),
    ],
)
def test_reversed_ranges_are_rejected(kwargs, message):
    with pytest.raises(DateRangeError, match=message):
        _resolve(**kwargs)


def test_same_day_custom_range_covers_the_entire_day():
    ranges = _resolve(start_date="2026-06-30", end_date="2026-06-30")

    assert ranges.growth_custom is not None
    assert ranges.growth_custom.start == datetime(2026, 6, 30, tzinfo=timezone.utc)
    assert ranges.growth_custom.end_exclusive == datetime(2026, 7, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_date": "2026-01-01"},
        {"end_date": "2026-01-01"},
        {"location_start_date": "2026-01-01"},
        {"location_end_date": "2026-01-01"},
    ],
)
def test_partial_custom_pairs_are_rejected(kwargs):
    with pytest.raises(DateRangeError, match="must be provided together"):
        _resolve(**kwargs)


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"start_date": "", "end_date": "2026-01-01"}, "start_date"),
        ({"start_date": "2026-01-01", "end_date": ""}, "end_date"),
        (
            {"location_start_date": "", "location_end_date": "2026-01-01"},
            "location_start_date",
        ),
        (
            {"location_start_date": "2026-01-01", "location_end_date": ""},
            "location_end_date",
        ),
    ],
)
def test_empty_strings_are_invalid_supplied_dates(kwargs, field):
    with pytest.raises(DateRangeError, match=rf"{field}.*YYYY-MM-DD"):
        _resolve(**kwargs)


def test_month_and_year_boundaries_use_exclusive_next_midnight():
    ranges = resolve_date_ranges(
        start_date="2025-12-31",
        end_date="2026-01-31",
        reference_time=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert ranges.fixed["7D"].start == datetime(2025, 12, 26, tzinfo=timezone.utc)
    assert ranges.fixed["7D"].end_exclusive == datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert ranges.fixed["30D"].start == datetime(2025, 12, 3, tzinfo=timezone.utc)
    assert ranges.fixed["1Y"].start == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert ranges.growth_custom is not None
    assert ranges.growth_custom.end_exclusive == datetime(2026, 2, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("reference_time", "expected_start", "expected_end"),
    [
        (
            datetime(2024, 2, 29, 23, 59, tzinfo=timezone.utc),
            datetime(2023, 2, 28, tzinfo=timezone.utc),
            datetime(2024, 3, 1, tzinfo=timezone.utc),
        ),
        (
            datetime(2025, 2, 28, 12, 0, tzinfo=timezone.utc),
            datetime(2024, 2, 28, tzinfo=timezone.utc),
            datetime(2025, 3, 1, tzinfo=timezone.utc),
        ),
    ],
)
def test_one_year_calendar_offset_handles_leap_years(reference_time, expected_start, expected_end):
    ranges = resolve_date_ranges(reference_time=reference_time)

    assert ranges.fixed["1Y"].start == expected_start
    assert ranges.fixed["1Y"].end_exclusive == expected_end
