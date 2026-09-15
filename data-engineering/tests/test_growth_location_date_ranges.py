"""Focused tests for Growth & Location Analytics date-range helpers."""

from datetime import date, datetime, timedelta, timezone

import pytest
from src.growth_location_analytics.date_ranges import (
    FIXED_BUCKETS,
    AnalyticsDateRanges,
    DateRangeError,
    bucket_granularity,
    period_label,
    resolve_date_ranges,
)

REFERENCE = datetime(2026, 9, 15, 18, 42, 11, tzinfo=timezone.utc)


def _resolve(**kwargs) -> AnalyticsDateRanges:
    return resolve_date_ranges(reference_time=REFERENCE, **kwargs)


def test_fixed_ranges_use_inclusive_utc_calendar_days():
    ranges = _resolve()

    assert tuple(ranges.fixed) == FIXED_BUCKETS
    assert ranges.fixed["7D"].start == datetime(2026, 9, 9, tzinfo=timezone.utc)
    assert ranges.fixed["7D"].end_exclusive == datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert ranges.fixed["30D"].start == datetime(2026, 8, 17, tzinfo=timezone.utc)
    assert ranges.fixed["30D"].end_exclusive == datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert ranges.fixed["1Y"].start == datetime(2025, 9, 15, tzinfo=timezone.utc)
    assert ranges.fixed["1Y"].end_exclusive == datetime(2026, 9, 16, tzinfo=timezone.utc)


def test_all_is_explicitly_unbounded_and_custom_absence_is_distinct():
    ranges = _resolve()

    assert ranges.fixed["All"].is_unbounded
    assert ranges.fixed["All"].start is None
    assert ranges.fixed["All"].end_exclusive is None
    assert ranges.growth_custom is None
    assert ranges.location_custom is None


def test_growth_custom_pair_does_not_populate_location_custom():
    ranges = _resolve(start_date="2026-01-02", end_date="2026-01-04")

    assert ranges.growth_custom is not None
    assert ranges.growth_custom.start == datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert ranges.growth_custom.end_exclusive == datetime(2026, 1, 5, tzinfo=timezone.utc)
    assert ranges.location_custom is None


def test_location_custom_pair_does_not_populate_growth_custom():
    ranges = _resolve(location_start_date="2025-03-10", location_end_date="2025-03-11")

    assert ranges.growth_custom is None
    assert ranges.location_custom is not None
    assert ranges.location_custom.start == datetime(2025, 3, 10, tzinfo=timezone.utc)
    assert ranges.location_custom.end_exclusive == datetime(2025, 3, 12, tzinfo=timezone.utc)


def test_both_custom_pairs_remain_independent():
    ranges = _resolve(
        start_date="2026-01-01",
        end_date="2026-06-30",
        location_start_date="2025-01-01",
        location_end_date="2025-12-31",
    )

    assert ranges.growth_custom is not None
    assert ranges.location_custom is not None
    assert ranges.growth_custom.start == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert ranges.growth_custom.end_exclusive == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert ranges.location_custom.start == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert ranges.location_custom.end_exclusive == datetime(2026, 1, 1, tzinfo=timezone.utc)


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


def test_maximum_date_has_a_clear_exclusive_boundary_error():
    with pytest.raises(DateRangeError, match="end_date must be earlier"):
        _resolve(start_date="9999-12-31", end_date="9999-12-31")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_date": "2026-01-01"},
        {"end_date": "2026-01-01"},
        {"location_start_date": "2026-01-01"},
        {"location_end_date": "2026-01-01"},
        {"start_date": "2026-01-01", "end_date": None},
        {"location_start_date": None, "location_end_date": "2026-01-01"},
    ],
)
def test_partial_custom_pairs_are_rejected(kwargs):
    with pytest.raises(DateRangeError, match="must be provided together"):
        _resolve(**kwargs)


def test_explicit_null_pairs_are_absent():
    ranges = _resolve(
        start_date=None,
        end_date=None,
        location_start_date=None,
        location_end_date=None,
    )

    assert ranges.growth_custom is None
    assert ranges.location_custom is None


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"start_date": "", "end_date": "2026-01-01"}, "start_date"),
        ({"start_date": "2026-01-01", "end_date": ""}, "end_date"),
        ({"start_date": "", "end_date": None}, "start_date"),
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


def test_inclusive_one_year_window_can_touch_thirteen_month_labels():
    ranges = resolve_date_ranges(reference_time=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))
    window = ranges.fixed["1Y"]

    assert window.start is not None
    assert window.end_exclusive is not None
    assert period_label("1Y", window.start) == "2025-01"
    assert period_label("1Y", window.end_exclusive - timedelta(microseconds=1)) == "2026-01"


def test_reference_time_is_converted_to_utc_before_selecting_today():
    ranges = resolve_date_ranges(reference_time=datetime.fromisoformat("2026-09-15T23:30:00-05:00"))

    assert ranges.fixed["7D"].start == datetime(2026, 9, 10, tzinfo=timezone.utc)
    assert ranges.fixed["7D"].end_exclusive == datetime(2026, 9, 17, tzinfo=timezone.utc)


def test_naive_reference_time_is_interpreted_as_utc():
    ranges = resolve_date_ranges(reference_time=datetime(2026, 9, 15, 23, 59))

    assert ranges.fixed["7D"].end_exclusive == datetime(2026, 9, 16, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("bucket", "granularity", "label"),
    [
        ("7D", "day", "2026-04-05"),
        ("30D", "day", "2026-04-05"),
        ("1Y", "month", "2026-04"),
        ("All", "month", "2026-04"),
        ("Custom", "day", "2026-04-05"),
    ],
)
def test_bucket_granularity_and_period_labels(bucket, granularity, label):
    value = datetime(2026, 4, 5, 10, 30, tzinfo=timezone.utc)

    assert bucket_granularity(bucket) == granularity
    assert period_label(bucket, value) == label


def test_period_label_uses_utc_date_for_offset_timestamp():
    value = datetime.fromisoformat("2026-04-05T23:30:00-05:00")

    assert period_label("7D", value) == "2026-04-06"
    assert period_label("1Y", value) == "2026-04"


def test_period_label_accepts_a_date_and_rejects_unknown_bucket():
    assert period_label("Custom", date(2024, 2, 29)) == "2024-02-29"

    with pytest.raises(ValueError, match="Unknown analytics bucket"):
        period_label("ALL", date(2026, 1, 1))
