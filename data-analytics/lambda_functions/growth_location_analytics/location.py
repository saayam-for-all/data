"""Pure country-distribution calculations for Growth & Location Analytics."""

from __future__ import annotations

from typing import TypedDict

import pandas as pd
from pandas.errors import MergeError

if __package__:
    from .date_ranges import DateWindow
else:
    from date_ranges import DateWindow  # type: ignore[no-redef]


class LocationCalculationError(ValueError):
    """Raised when location lookup data cannot resolve organizations safely."""


class CountryCount(TypedDict):
    """One JSON-compatible country count in a location distribution."""

    country: str
    count: int


def calculate_country_distribution(
    organizations: pd.DataFrame,
    states: pd.DataFrame,
    countries: pd.DataFrame,
    window: DateWindow | None,
) -> list[CountryCount]:
    """Count normalized organization rows by country through state/country lookups.

    None means absent Custom. Count duplicate organization rows separately.
    Duplicate lookup keys or unresolved in-window references raise
    LocationCalculationError; never drop, multiply, or assign fallback rows.
    Return up to four represented countries by count descending, breaking ties
    by country_code ascending.
    """

    if window is None or organizations.empty:
        return []

    created_at = organizations["created_at"]
    if window.is_unbounded:
        in_window = pd.Series(True, index=organizations.index, dtype=bool)
    else:
        in_window = (created_at >= window.start) & (created_at < window.end_exclusive)

    if not bool(in_window.any()):
        return []

    active = organizations.loc[in_window, ["state_id"]]
    try:
        resolved = active.merge(
            states[["state_id", "country_id"]],
            how="left",
            on="state_id",
            validate="many_to_one",
        )
        if resolved["country_id"].isna().any():
            raise LocationCalculationError("Unresolved state references")
        resolved = resolved.merge(
            countries[["country_id", "country_code"]],
            how="left",
            on="country_id",
            validate="many_to_one",
        )
    except MergeError as exc:
        raise LocationCalculationError("Duplicate location lookup keys") from exc
    if resolved["country_code"].isna().any():
        raise LocationCalculationError("Unresolved country references")

    ranked = (
        resolved.groupby("country_code", sort=False)
        .size()
        .rename("count")
        .reset_index()
        .sort_values(
            ["count", "country_code"],
            ascending=[False, True],
            kind="mergesort",
        )
        .head(4)
    )
    return [
        {"country": str(row.country_code), "count": int(row.count)}
        for row in ranked.itertuples(index=False)
    ]
