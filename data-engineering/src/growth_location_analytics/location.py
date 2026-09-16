"""Pure country-distribution calculations for Growth & Location Analytics."""

from __future__ import annotations

from typing import TypedDict

import pandas as pd

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
    """Count in-window organization rows by their resolved country code.

    The caller supplies normalized task-1 tables and a task-2 window selected
    for the requested Location bucket. ``None`` represents an absent Location
    Custom range. Organization rows, including repeated ``org_id`` values, are
    counted independently to stay consistent with the task-3 row-count rule.

    Lookup keys must be unique and every in-window organization must resolve
    through ``organizations.state_id -> states.country_id ->
    countries.country_code``. Invalid mappings raise
    :class:`LocationCalculationError`; rows are never silently dropped,
    deduplicated, or assigned a fallback country. This strict policy is an
    issue #336 implementation assumption pending reviewer confirmation.

    Equal counts are ordered by ``country_code`` ascending for deterministic
    output. Only the four highest-ranked represented countries are returned.

    Args:
        organizations: Normalized organizations table.
        states: Normalized state lookup table.
        countries: Normalized country lookup table.
        window: Resolved Location window, or ``None`` for absent Custom dates.

    Returns:
        Up to four dictionaries containing exactly ``country`` and ``count``.

    Raises:
        LocationCalculationError: If lookup keys are duplicated or an
            in-window organization cannot resolve to exactly one country.
    """

    if window is None or organizations.empty:
        return []

    created_at = organizations["created_at"]
    if window.is_unbounded:
        in_window = pd.Series(True, index=organizations.index, dtype=bool)
    else:
        in_window = (created_at >= window.start) & (
            created_at < window.end_exclusive
        )

    if not bool(in_window.any()):
        return []

    active = organizations.loc[in_window, ["org_id", "state_id"]].copy()
    _raise_for_missing(active, "state_id", "organizations")
    _validate_lookup_keys(states, "state_id", "states")
    _validate_lookup_keys(countries, "country_id", "countries")

    state_lookup = states.loc[:, ["state_id", "country_id"]].copy()
    resolved_states = active.merge(
        state_lookup,
        how="left",
        on="state_id",
        validate="many_to_one",
        indicator="_state_match",
        sort=False,
    )
    unmatched_states = resolved_states["_state_match"].ne("both")
    if bool(unmatched_states.any()):
        state_ids = _display_values(
            resolved_states.loc[unmatched_states, "state_id"]
        )
        raise LocationCalculationError(
            "organizations contain unmatched state_id references: " + state_ids
        )
    _raise_for_missing(resolved_states, "country_id", "states")

    country_lookup = countries.loc[:, ["country_id", "country_code"]].copy()
    resolved_countries = resolved_states.drop(columns="_state_match").merge(
        country_lookup,
        how="left",
        on="country_id",
        validate="many_to_one",
        indicator="_country_match",
        sort=False,
    )
    unmatched_countries = resolved_countries["_country_match"].ne("both")
    if bool(unmatched_countries.any()):
        country_ids = _display_values(
            resolved_countries.loc[unmatched_countries, "country_id"]
        )
        raise LocationCalculationError(
            "states contain unmatched country_id references: " + country_ids
        )
    _raise_for_missing(resolved_countries, "country_code", "countries")

    ranked = (
        resolved_countries.groupby("country_code", sort=False)
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


def _validate_lookup_keys(
    lookup: pd.DataFrame,
    key: str,
    table_name: str,
) -> None:
    """Reject missing or duplicated lookup keys before a many-to-one merge."""

    _raise_for_missing(lookup, key, table_name)
    duplicated = lookup[key].duplicated(keep=False)
    if bool(duplicated.any()):
        values = _display_values(lookup.loc[duplicated, key])
        raise LocationCalculationError(
            f"{table_name}.{key} contains duplicate lookup keys: {values}"
        )


def _raise_for_missing(
    frame: pd.DataFrame,
    column: str,
    table_name: str,
) -> None:
    """Reject null or blank values needed for country resolution."""

    values = frame[column]
    missing = values.isna() | values.astype("string").str.strip().eq("")
    if bool(missing.any()):
        raise LocationCalculationError(
            f"{table_name}.{column} contains missing or blank references"
        )


def _display_values(values: pd.Series) -> str:
    """Return stable, concise lookup values for a data-integrity error."""

    return ", ".join(sorted({str(value) for value in values.tolist()}))
