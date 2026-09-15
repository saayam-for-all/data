"""Shared time-range parsing for analytics endpoints (7D/30D/1Y/ALL/CUSTOM)."""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import HTTPException

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}

_WINDOWS = {
    "7D": timedelta(days=7),
    "30D": timedelta(days=30),
    "1Y": timedelta(days=365),
}


def resolve_date_range(
    time_filter: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Resolves a time_filter (+ optional CUSTOM bounds) into a (start, end) UTC range.

    Returns (None, None) for ALL, meaning "no date filter".
    Raises HTTPException(400) on invalid input.
    """
    normalized = (time_filter or "ALL").upper()
    if normalized not in VALID_TIME_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid time_filter '{time_filter}'. Must be one of {sorted(VALID_TIME_FILTERS)}",
        )

    if normalized == "ALL":
        return None, None

    if normalized in _WINDOWS:
        end = datetime.now(timezone.utc)
        start = end - _WINDOWS[normalized]
        return start, end

    # CUSTOM
    if not start_date or not end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date and end_date are required when time_filter=CUSTOM",
        )
    try:
        start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="start_date and end_date must be ISO 8601 dates (YYYY-MM-DD)",
        )
    if start > end:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")
    return start, end


def date_range_clause(column: str, start: Optional[datetime], end: Optional[datetime], params: list) -> str:
    """Builds a ' AND <column> BETWEEN %s AND %s' fragment, appending bind params.

    Returns '' (no-op) when start/end are None (ALL).
    """
    if start is None or end is None:
        return ""
    params.append(start)
    params.append(end)
    return f" AND {column} BETWEEN %s AND %s"


def trend_bucket(time_filter: str) -> str:
    """Picks a date_trunc granularity for registration-trend buckets based on the filter span."""
    normalized = (time_filter or "ALL").upper()
    if normalized == "7D":
        return "day"
    if normalized == "30D":
        return "day"
    if normalized == "1Y":
        return "month"
    return "month"
