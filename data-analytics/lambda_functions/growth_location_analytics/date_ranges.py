"""Date-window helpers for Growth & Location Analytics.

Approved boundaries use UTC calendar days: 7D includes today and six prior
days; 30D includes today and twenty-nine prior days. Bounded windows include
their displayed end date via an exclusive next-midnight bound; All is unbounded.
1Y starts on the same date in the previous year (February 29 maps to February
28), so it can span 366 or 367 calendar dates and touch 13 month labels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")

_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class DateRangeError(ValueError):
    """Raised when analytics date-range input is incomplete or invalid."""


@dataclass(frozen=True)
class DateWindow:
    """A UTC interval with inclusive start and exclusive end; both None means All."""

    start: datetime | None
    end_exclusive: datetime | None

    @property
    def is_unbounded(self) -> bool:
        """Return whether this is the explicit unbounded All window."""

        return self.start is None


@dataclass(frozen=True)
class AnalyticsDateRanges:
    """Shared fixed windows and independent optional Growth and Location Custom windows."""

    fixed: dict[str, DateWindow]
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
    """Resolve all windows from one UTC date and validate independent Custom pairs.

    Custom endpoints must be strict YYYY-MM-DD strings: two None values mean
    absent; a partial pair, empty string, impossible date, or reversed range
    raises DateRangeError. An end without a representable next day is invalid.
    Read the clock once if reference_time is omitted; supplied reference times
    are internal UTC datetimes.
    """

    if reference_time is None:
        reference_time = datetime.now(timezone.utc)
    today = reference_time.date()
    end_exclusive = _utc_midnight(today + timedelta(days=1))

    fixed = {
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


def _parse_custom_pair(
    start_value: str | None,
    end_value: str | None,
    start_field: str,
    end_field: str,
) -> DateWindow | None:
    """Return an optional Custom window; raise DateRangeError for invalid bounds."""

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
    """Parse strict ASCII YYYY-MM-DD; raise DateRangeError for invalid dates."""

    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise DateRangeError(f"{field} must use YYYY-MM-DD format")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DateRangeError(f"{field} must be a valid calendar date in YYYY-MM-DD format") from exc


def _utc_midnight(value: date) -> datetime:
    """Return timezone-aware UTC midnight at the start of a calendar date."""

    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _same_date_previous_year(value: date) -> date:
    """Move to the prior year, mapping February 29 to February 28."""

    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        # The only valid date that cannot be moved directly to the prior year
        # is February 29 when the previous year is not a leap year.
        return date(value.year - 1, 2, 28)
