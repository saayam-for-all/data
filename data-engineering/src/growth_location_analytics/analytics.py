"""Date-window resolution and the growth/location calculations for #336.

Implements the team lead's rulings from the #336 WhatsApp thread
(2026-09-21):
  - "1Y" means trailing 12 calendar months, not a rolling 365 days.
  - Supplying only one of a start/end date pair is an error, not a
    partial or open-ended result.
"""
from datetime import datetime, timedelta, timezone

_DATE_FORMAT = "%Y-%m-%d"


class DateRangeError(ValueError):
    """Raised for invalid or incomplete Custom date-range parameters."""


def _calendar_months_back(now, n):
    """1st of the month that is (n-1) months before `now`'s month."""
    year, month = now.year, now.month - (n - 1)
    while month < 1:
        month += 12
        year -= 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def fixed_windows(now):
    """Returns {bucket: (start, end, granularity)} for the four fixed buckets.

    start is None for "All" (unbounded). end is always `now`.
    """
    return {
        "7D": (now - timedelta(days=7), now, "day"),
        "30D": (now - timedelta(days=30), now, "day"),
        "1Y": (_calendar_months_back(now, 12), now, "month"),
        "All": (None, now, "month"),
    }


def parse_custom_pair(params, start_key, end_key):
    """Parses one Custom date pair.

    Returns (start, end) as UTC-aware datetimes (end is exclusive, i.e. the
    start of the day *after* the supplied end date, since end dates are
    inclusive of the whole calendar day), or None if neither key was
    supplied.

    Raises DateRangeError if only one of the pair was supplied, either
    value fails to parse, or start is after end.
    """
    start_raw = params.get(start_key)
    end_raw = params.get(end_key)

    if start_raw is None and end_raw is None:
        return None
    if start_raw is None or end_raw is None:
        raise DateRangeError(f"{start_key} and {end_key} must be supplied together")

    try:
        start = datetime.strptime(start_raw, _DATE_FORMAT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc:
        raise DateRangeError(f"Invalid date format for {start_key}: {start_raw!r}") from exc
    try:
        end = datetime.strptime(end_raw, _DATE_FORMAT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc:
        raise DateRangeError(f"Invalid date format for {end_key}: {end_raw!r}") from exc

    if start > end:
        raise DateRangeError(f"{start_key} must be on or before {end_key}")

    return start, end + timedelta(days=1)  # end date is inclusive of the whole day


def _period_label(ts, granularity):
    return ts.strftime("%Y-%m-%d") if granularity == "day" else ts.strftime("%Y-%m")


def compute_growth_trend(df, start, end, granularity):
    """total_organizations is an all-time cumulative count as of each period
    (never reset to the window); collaborators is window-scoped per period.
    Both are sparse: a period only appears if it has activity in the window.
    """
    upto_end = df[df["created_at"] < end]
    in_window = upto_end[upto_end["created_at"] >= start] if start is not None else upto_end

    if in_window.empty:
        return {"total_organizations": [], "collaborators": []}

    in_window = in_window.copy()
    in_window["period"] = in_window["created_at"].apply(lambda t: _period_label(t, granularity))
    periods = sorted(in_window["period"].unique())

    upto_end = upto_end.copy()
    upto_end["period"] = upto_end["created_at"].apply(lambda t: _period_label(t, granularity))
    total_series = [
        {"period": p, "count": int((upto_end["period"] <= p).sum())} for p in periods
    ]

    collab_counts = (
        in_window[in_window["is_collaborator"]].groupby("period").size().to_dict()
    )
    collaborators_series = [
        {"period": p, "count": int(collab_counts.get(p, 0))} for p in periods
    ]

    return {"total_organizations": total_series, "collaborators": collaborators_series}


def compute_locations(df, start, end):
    """Top 4 countries by organization count within the window, descending.
    No "Other" entry, no percentage field.
    """
    upto_end = df[df["created_at"] < end]
    in_window = upto_end[upto_end["created_at"] >= start] if start is not None else upto_end

    if in_window.empty:
        return []

    counts = in_window.groupby("country_code").size().sort_values(ascending=False)
    return [{"country": country, "count": int(count)} for country, count in counts.head(4).items()]


def build_bucket(df, start, end, granularity):
    return {
        "growth_trend": compute_growth_trend(df, start, end, granularity),
        "organizations_by_location": compute_locations(df, start, end),
    }
