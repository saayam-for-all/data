"""Date-window helpers for Growth & Location Analytics.

Issue #336 leaves some boundary details unspecified. This module uses the
reviewed task-2 assumptions: windows follow UTC calendar days, include their
displayed end date, and are represented internally as half-open intervals.
The inclusive 1Y window starts on the same date in the previous year (with
February 29 mapped to February 28), so it can span 366 or 367 calendar dates
and produce 13 calendar-month labels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from types import MappingProxyType
from typing import Literal, Mapping

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
ALL_BUCKETS = (*FIXED_BUCKETS, "Custom")

_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_GRANULARITIES: Mapping[str, Literal["day", "month"]] = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
    "Custom": "day",
}


class DateRangeError(ValueError):
    """Raised when analytics date-range input is incomplete or invalid."""


@dataclass(frozen=True)
class DateWindow:
    """A UTC half-open interval, or an explicit unbounded interval for All.

    ``start`` is inclusive and ``end_exclusive`` is exclusive. Both are
    ``None`` only for the unbounded All window.

    Attributes:
        start: Inclusive UTC boundary, or ``None`` for an unbounded window.
        end_exclusive: Exclusive UTC boundary, or ``None`` for an unbounded
            window.
    """

    start: datetime | None
    end_exclusive: datetime | None

    def __post_init__(self) -> None:
        """Validate that the bounds form a UTC half-open interval.

        Raises:
            ValueError: If bounds are incomplete, naive, non-UTC, or ordered
                incorrectly.
        """

        if (self.start is None) != (self.end_exclusive is None):
            raise ValueError("DateWindow bounds must both be set or both be None")
        for bound in (self.start, self.end_exclusive):
            if bound is not None and (bound.tzinfo is None or bound.utcoffset() is None):
                raise ValueError("DateWindow bounds must be timezone-aware")
            if bound is not None and bound.utcoffset() != timedelta(0):
                raise ValueError("DateWindow bounds must use UTC")
        if (
            self.start is not None
            and self.end_exclusive is not None
            and self.start >= self.end_exclusive
        ):
            raise ValueError("DateWindow start must be before its exclusive end")

    @property
    def is_unbounded(self) -> bool:
        """Return whether this is the explicit unbounded All window."""

        return self.start is None


@dataclass(frozen=True)
class AnalyticsDateRanges:
    """Resolved fixed windows and two independent optional Custom windows.

    Attributes:
        fixed: The shared ``7D``, ``30D``, ``1Y``, and ``All`` windows.
        growth_custom: Custom Growth Trend window, or ``None`` when absent.
        location_custom: Custom Location window, or ``None`` when absent.
    """

    fixed: Mapping[str, DateWindow]
    growth_custom: DateWindow | None
    location_custom: DateWindow | None


def resolve_date_ranges(
    start_date: str | None = None,
    end_date: str | None = None,
    location_start_date: str | None = None,
    location_end_date: str | None = None,
    *,
    reference_time: datetime | None = None,
) -> AnalyticsDateRanges:
    """Parse Custom inputs and resolve every fixed window from one UTC date.

    Missing values must be represented by ``None``. For either Custom pair,
    two ``None`` values mean that chart has no Custom range; exactly one
    ``None`` value is invalid. Empty strings are supplied values and therefore
    fail strict ``YYYY-MM-DD`` validation.

    A naive ``reference_time`` is interpreted as UTC, matching task 1's
    timestamp normalization. An aware reference is converted to UTC before
    selecting the calendar date. If omitted, the current UTC time is read once.

    Args:
        start_date: Inclusive Growth Trend Custom start date.
        end_date: Inclusive Growth Trend Custom end date.
        location_start_date: Inclusive Location Custom start date.
        location_end_date: Inclusive Location Custom end date.
        reference_time: Optional time used to derive one shared UTC ``today``.

    Returns:
        All fixed windows plus the independently resolved Custom windows.

    Raises:
        DateRangeError: If a Custom pair is incomplete, malformed, impossible,
            reversed, or cannot be represented with an exclusive upper bound.
        TypeError: If ``reference_time`` is not a datetime.
    """

    if reference_time is None:
        reference_time = datetime.now(timezone.utc)
    reference_utc = _as_utc(reference_time)
    today = reference_utc.date()
    end_exclusive = _utc_midnight(today + timedelta(days=1))

    fixed = MappingProxyType(
        {
            "7D": DateWindow(
                start=_utc_midnight(today - timedelta(days=6)),
                end_exclusive=end_exclusive,
            ),
            "30D": DateWindow(
                start=_utc_midnight(today - timedelta(days=29)),
                end_exclusive=end_exclusive,
            ),
            "1Y": DateWindow(
                start=_utc_midnight(_same_date_previous_year(today)),
                end_exclusive=end_exclusive,
            ),
            "All": DateWindow(start=None, end_exclusive=None),
        }
    )

    return AnalyticsDateRanges(
        fixed=fixed,
        growth_custom=_parse_custom_pair(start_date, end_date, "start_date", "end_date"),
        location_custom=_parse_custom_pair(
            location_start_date,
            location_end_date,
            "location_start_date",
            "location_end_date",
        ),
    )


def bucket_granularity(bucket: str) -> Literal["day", "month"]:
    """Return the required growth-trend grouping unit for a bucket.

    Args:
        bucket: One of the five canonical analytics bucket identifiers.

    Returns:
        ``"day"`` for ``7D``, ``30D``, and ``Custom``; otherwise ``"month"``.

    Raises:
        ValueError: If ``bucket`` is not a canonical identifier.
    """

    try:
        return _GRANULARITIES[bucket]
    except KeyError as exc:
        expected = ", ".join(ALL_BUCKETS)
        raise ValueError(f"Unknown analytics bucket '{bucket}'; expected: {expected}") from exc


def period_label(bucket: str, value: date | datetime) -> str:
    """Format a date or timestamp as the bucket's growth period label.

    Aware timestamps are converted to UTC before formatting. Naive timestamps
    are interpreted as UTC, consistent with the task-1 loader.

    Args:
        bucket: One of the five canonical analytics bucket identifiers.
        value: Date or timestamp to format.

    Returns:
        A ``YYYY-MM-DD`` day label or ``YYYY-MM`` month label.

    Raises:
        ValueError: If ``bucket`` is not a canonical identifier.
        TypeError: If ``value`` is not a date or datetime.
    """

    granularity = bucket_granularity(bucket)
    if isinstance(value, datetime):
        value = _as_utc(value).date()
    if not isinstance(value, date):
        raise TypeError("value must be a date or datetime")
    return value.strftime("%Y-%m-%d" if granularity == "day" else "%Y-%m")


def _parse_custom_pair(
    start_value: str | None,
    end_value: str | None,
    start_field: str,
    end_field: str,
) -> DateWindow | None:
    """Parse one chart's optional Custom date pair.

    Args:
        start_value: Supplied inclusive start-date value.
        end_value: Supplied inclusive end-date value.
        start_field: Request field name used in validation errors.
        end_field: Request field name used in validation errors.

    Returns:
        A bounded UTC window, or ``None`` when both values are absent.

    Raises:
        DateRangeError: If values are incomplete, invalid, reversed, or exceed
            the representable exclusive boundary.
    """

    if start_value is None and end_value is None:
        return None

    # Empty strings are invalid supplied dates, even if the other endpoint is
    # missing. Check them before reporting an incomplete pair.
    if start_value == "":
        raise DateRangeError(f"{start_field} must use YYYY-MM-DD format")
    if end_value == "":
        raise DateRangeError(f"{end_field} must use YYYY-MM-DD format")
    if start_value is None or end_value is None:
        raise DateRangeError(f"{start_field} and {end_field} must be provided together")

    parsed_start = _parse_date(start_value, start_field)
    parsed_end = _parse_date(end_value, end_field)
    if parsed_start > parsed_end:
        raise DateRangeError(f"{start_field} must be on or before {end_field}")

    try:
        end_exclusive_date = parsed_end + timedelta(days=1)
    except OverflowError as exc:
        raise DateRangeError(f"{end_field} must be earlier than 9999-12-31") from exc

    return DateWindow(
        start=_utc_midnight(parsed_start),
        end_exclusive=_utc_midnight(end_exclusive_date),
    )


def _parse_date(value: str, field: str) -> date:
    """Parse a strict ASCII ``YYYY-MM-DD`` date value.

    Args:
        value: Request value to parse.
        field: Request field name used in validation errors.

    Returns:
        The parsed calendar date.

    Raises:
        DateRangeError: If the format or calendar date is invalid.
    """

    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise DateRangeError(f"{field} must use YYYY-MM-DD format")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DateRangeError(f"{field} must be a valid calendar date in YYYY-MM-DD format") from exc


def _as_utc(value: datetime) -> datetime:
    """Normalize a datetime to UTC, treating naive values as UTC.

    Args:
        value: Reference time or timestamp to normalize.

    Returns:
        A timezone-aware UTC datetime.

    Raises:
        TypeError: If ``value`` is not a datetime.
    """

    if not isinstance(value, datetime):
        raise TypeError("reference_time must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_midnight(value: date) -> datetime:
    """Return midnight UTC at the start of a calendar date.

    Args:
        value: Calendar date to convert.

    Returns:
        A timezone-aware UTC datetime at midnight.
    """

    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _same_date_previous_year(value: date) -> date:
    """Move a date to the prior year, mapping February 29 to February 28.

    Args:
        value: Calendar date to offset.

    Returns:
        The corresponding date in the previous calendar year.
    """

    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        # The only valid date that cannot be moved directly to the prior year
        # is February 29 when the previous year is not a leap year.
        return date(value.year - 1, 2, 28)
