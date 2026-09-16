"""Pure organization-growth calculations for Growth & Location Analytics."""

from __future__ import annotations

from typing import TypedDict

import pandas as pd

if __package__:
    from .date_ranges import DateWindow, bucket_granularity, period_label
else:
    from date_ranges import (  # type: ignore[no-redef]
        DateWindow,
        bucket_granularity,
        period_label,
    )


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
    """Calculate sparse organization-growth series for one resolved window.

    The input is the normalized organizations table produced by the local data
    loader. Each row remains an organization observation; repeated ``org_id``
    values are intentionally not deduplicated. For bounded windows, rows before
    the start form the all-time baseline and rows within the half-open window
    advance that total. An absent Custom window produces empty series.

    Args:
        organizations: Normalized organizations data with ``created_at`` and
            ``is_collaborator`` columns.
        bucket: Canonical bucket identifier used by the date-range helpers.
        window: Resolved window for the bucket, or ``None`` for an absent
            Growth Custom range.

    Returns:
        Two chronologically aligned, JSON-compatible sparse series.
    """

    # Validate the bucket even when no rows or Custom window are available.
    bucket_granularity(bucket)
    if window is None or organizations.empty:
        return _empty_growth_result()

    created_at = organizations["created_at"]
    if window.is_unbounded:
        in_window = pd.Series(True, index=organizations.index, dtype=bool)
        historical_count = 0
    else:
        in_window = (created_at >= window.start) & (
            created_at < window.end_exclusive
        )
        historical_count = int((created_at < window.start).sum())

    if not bool(in_window.any()):
        return _empty_growth_result()

    active = pd.DataFrame(
        {
            "period": created_at.loc[in_window].map(
                lambda timestamp: period_label(bucket, timestamp)
            ),
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
            {"period": period, "count": int(cumulative_totals.loc[period])}
            for period in periods
        ],
        "collaborators": [
            {"period": period, "count": int(grouped.loc[period, "collaborators"])}
            for period in periods
        ],
    }


def _empty_growth_result() -> GrowthResult:
    """Return a fresh empty growth result."""

    return {"total_organizations": [], "collaborators": []}
