"""Focused tests for pure country-distribution calculations."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

LAMBDA_ROOT = Path(__file__).resolve().parents[2] / "data-analytics" / "lambda_functions"
sys.path.insert(0, str(LAMBDA_ROOT))

from growth_location_analytics.date_ranges import DateWindow, resolve_date_ranges
from growth_location_analytics.location import (
    LocationCalculationError,
    calculate_country_distribution,
)
from tests.growth_location_helpers import utc_window as _window

REFERENCE = datetime(2026, 9, 15, 18, 42, 11, tzinfo=timezone.utc)


def _organizations(*rows: tuple[str, str | None, bool, str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "org_id": pd.Series([row[0] for row in rows], dtype="string"),
            "state_id": pd.Series([row[1] for row in rows], dtype="string"),
            "city_name": pd.Series([f"City {index}" for index in range(len(rows))], dtype="string"),
            "is_collaborator": pd.Series([row[2] for row in rows], dtype="boolean"),
            "created_at": pd.to_datetime([row[3] for row in rows], format="mixed", utc=True),
        }
    )


def _states(*rows: tuple[str | None, str | None]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "state_id": pd.Series([row[0] for row in rows], dtype="string"),
            "state_name": pd.Series(
                [f"State {index}" for index in range(len(rows))], dtype="string"
            ),
            "country_id": pd.Series([row[1] for row in rows], dtype="string"),
        }
    )


def _countries(*rows: tuple[str | None, str | None]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "country_id": pd.Series([row[0] for row in rows], dtype="string"),
            "country_code": pd.Series([row[1] for row in rows], dtype="string"),
        }
    )


def _all_window() -> DateWindow:
    return DateWindow(None, None)


def test_resolves_both_joins_and_combines_multiple_states_in_one_country():
    organizations = _organizations(
        ("org-1", "CA", False, "2026-09-10"),
        ("org-2", "TX", True, "2026-09-11"),
        ("org-3", "KA", False, "2026-09-12"),
    )
    states = _states(("CA", "US"), ("TX", "US"), ("KA", "IN"))
    countries = _countries(("US", "USA"), ("IN", "IND"))

    result = calculate_country_distribution(organizations, states, countries, _all_window())

    assert result == [
        {"country": "USA", "count": 2},
        {"country": "IND", "count": 1},
    ]
    assert sum(row["count"] for row in result) == len(organizations)


def test_ranks_descending_limits_to_four_and_uses_country_code_for_ties():
    counts = {"USA": 4, "IND": 3, "BRA": 2, "CAN": 2, "AUS": 1, "ZAF": 1}
    states = _states(*[(f"S-{code}", f"C-{code}") for code in counts])
    countries = _countries(*[(f"C-{code}", code) for code in counts])
    rows = [
        (f"org-{code}-{index}", f"S-{code}", False, "2026-09-10")
        for code, count in counts.items()
        for index in range(count)
    ]

    result = calculate_country_distribution(_organizations(*rows), states, countries, _all_window())

    assert result == [
        {"country": "USA", "count": 4},
        {"country": "IND", "count": 3},
        {"country": "BRA", "count": 2},
        {"country": "CAN", "count": 2},
    ]
    assert len(result) == 4
    assert sum(row["count"] for row in result) == 11


def test_fewer_than_four_countries_returns_every_represented_country_only():
    organizations = _organizations(
        ("org-1", "IL", False, "2026-09-10"),
        ("org-2", "KA", False, "2026-09-10"),
    )
    states = _states(("IL", "US"), ("KA", "IN"), ("ON", "CA"))
    countries = _countries(("US", "USA"), ("IN", "IND"), ("CA", "CAN"))

    result = calculate_country_distribution(organizations, states, countries, _all_window())

    assert result == [
        {"country": "IND", "count": 1},
        {"country": "USA", "count": 1},
    ]
    assert sum(row["count"] for row in result) == len(organizations)


def test_bounded_window_counts_only_rows_inside_half_open_boundaries():
    organizations = _organizations(
        ("before", "IL", False, "2026-09-08T23:59:59Z"),
        ("start", "IL", True, "2026-09-09T00:00:00Z"),
        ("end", "IL", False, "2026-09-15T23:59:59Z"),
        ("after", "IL", True, "2026-09-16T00:00:00Z"),
    )

    result = calculate_country_distribution(
        organizations,
        _states(("IL", "US")),
        _countries(("US", "USA")),
        _window("2026-09-09", "2026-09-16"),
    )

    assert result == [{"country": "USA", "count": 2}]


def test_all_includes_past_present_and_future_rows():
    organizations = _organizations(
        ("past", "IL", False, "2020-01-01"),
        ("present", "IL", True, "2026-09-15"),
        ("future", "IL", False, "2030-01-01"),
    )

    result = calculate_country_distribution(
        organizations,
        _states(("IL", "US")),
        _countries(("US", "USA")),
        _all_window(),
    )

    assert result == [{"country": "USA", "count": 3}]


@pytest.mark.parametrize(
    ("bucket", "expected_count"),
    [("7D", 1), ("30D", 2), ("1Y", 3), ("All", 4)],
)
def test_fixed_range_helpers_drive_each_location_bucket(bucket, expected_count):
    organizations = _organizations(
        ("seven-day", "IL", False, "2026-09-15"),
        ("thirty-day", "IL", False, "2026-08-20"),
        ("one-year", "IL", False, "2025-10-01"),
        ("older", "IL", False, "2025-01-01"),
    )
    ranges = resolve_date_ranges(reference_time=REFERENCE)

    result = calculate_country_distribution(
        organizations,
        _states(("IL", "US")),
        _countries(("US", "USA")),
        ranges.fixed[bucket],
    )

    assert result == [{"country": "USA", "count": expected_count}]


def test_supplied_custom_window_selects_its_country():
    result = calculate_country_distribution(
        _organizations(
            ("outside", "IL", False, "2026-04-05"),
            ("inside", "KA", True, "2026-06-05"),
        ),
        _states(("IL", "US"), ("KA", "IN")),
        _countries(("US", "USA"), ("IN", "IND")),
        _window("2026-06-01", "2026-07-01"),
    )

    assert result == [{"country": "IND", "count": 1}]


def test_absent_custom_window_returns_empty_location():
    assert (
        calculate_country_distribution(
            _organizations(("org-1", "IL", False, "2026-04-05")),
            _states(("IL", "US")),
            _countries(("US", "USA")),
            None,
        )
        == []
    )


def test_empty_single_and_no_activity_behaviors():
    states = _states(("IL", "US"))
    countries = _countries(("US", "USA"))
    window = _window("2026-09-09", "2026-09-16")

    assert calculate_country_distribution(_organizations(), states, countries, window) == []
    assert calculate_country_distribution(
        _organizations(("org-1", "IL", False, "2026-09-15")),
        states,
        countries,
        window,
    ) == [{"country": "USA", "count": 1}]
    assert (
        calculate_country_distribution(
            _organizations(("org-old", "IL", False, "2020-01-01")),
            states,
            countries,
            window,
        )
        == []
    )


@pytest.mark.parametrize("duplicate_table", ["states", "countries"])
def test_duplicate_lookup_keys_raise_integrity_errors(duplicate_table):
    states = (
        _states(("IL", "US"), ("IL", "US"))
        if duplicate_table == "states"
        else _states(("IL", "US"))
    )
    countries = (
        _countries(("US", "USA"), ("US", "USA"))
        if duplicate_table == "countries"
        else _countries(("US", "USA"))
    )

    with pytest.raises(LocationCalculationError):
        calculate_country_distribution(
            _organizations(("org-1", "IL", False, "2026-09-10")),
            states,
            countries,
            _all_window(),
        )


@pytest.mark.parametrize("state_id,country_id", [("missing", "US"), ("IL", "missing")])
def test_unmatched_references_raise_errors(state_id, country_id):
    with pytest.raises(LocationCalculationError):
        calculate_country_distribution(
            _organizations(("org-1", state_id, False, "2026-09-10")),
            _states(("IL", country_id)),
            _countries(("US", "USA")),
            _all_window(),
        )


def test_duplicate_organization_rows_are_counted_separately():
    organizations = _organizations(
        ("same-org", "IL", False, "2026-09-10"),
        ("same-org", "IL", False, "2026-09-10"),
    )

    result = calculate_country_distribution(
        organizations,
        _states(("IL", "US")),
        _countries(("US", "USA")),
        _all_window(),
    )

    assert result == [{"country": "USA", "count": 2}]
