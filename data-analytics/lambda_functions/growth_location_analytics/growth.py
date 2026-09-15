"""Pure organization-growth calculations for Growth & Location Analytics."""

from __future__ import annotations

from typing import TypedDict

import pandas as pd

if __package__:
    from .date_ranges import DateWindow
else:
    from date_ranges import DateWindow  # type: ignore[no-redef]


class GrowthPoint(TypedDict):
    """One JSON-compatible point in a growth series."""

    period: str
    count: int


class GrowthResult(TypedDict):
    """Aligned cumulative-organization and per-period collaborator series."""

    total_organizations: list[GrowthPoint]
    collaborators: list[GrowthPoint]


def calculate_organization_growth(
    organizations: pd.DataFrame,
    bucket: str,
    window: DateWindow | None,
) -> GrowthResult:
    """Return aligned sparse cumulative totals and per-period collaborator counts.

    Use normalized loader data and a resolved window; None means absent Custom.
    Count every row, including duplicate IDs. Pre-window rows seed the running
    total, while only in-window rows contribute periods and collaborators.
    """

    if window is None or organizations.empty:
        return _empty_growth_result()

    created_at = organizations["created_at"]
    if window.is_unbounded:
        in_window = pd.Series(True, index=organizations.index, dtype=bool)
        historical_count = 0
    else:
        in_window = (created_at >= window.start) & (created_at < window.end_exclusive)
        historical_count = int((created_at < window.start).sum())

    if not bool(in_window.any()):
        return _empty_growth_result()

    period_format = "%Y-%m" if bucket in {"1Y", "All"} else "%Y-%m-%d"
    active = pd.DataFrame(
        {
            "period": created_at.loc[in_window].dt.strftime(period_format),
            "is_collaborator": organizations.loc[in_window, "is_collaborator"],
        }
    )
    grouped = active.groupby("period", sort=True).agg(
        organizations=("period", "size"),
        collaborators=("is_collaborator", "sum"),
    )
    cumulative_totals = grouped["organizations"].cumsum() + historical_count

    periods = grouped.index.tolist()
    return {
        "total_organizations": [
            {"period": period, "count": int(cumulative_totals.loc[period])} for period in periods
        ],
        "collaborators": [
            {"period": period, "count": int(grouped.loc[period, "collaborators"])}
            for period in periods
        ],
    }


def _empty_growth_result() -> GrowthResult:
    """Return a fresh empty growth result."""

    return {"total_organizations": [], "collaborators": []}
