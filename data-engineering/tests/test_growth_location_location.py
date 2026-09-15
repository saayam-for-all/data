"""Focused tests for pure country-distribution calculations."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.growth_location_analytics import (
    DateWindow,
    LocationCalculationError,
    calculate_country_distribution,
    resolve_date_ranges,
)


REFERENCE = datetime(2026, 9, 15, 18, 42, 11, tzinfo=timezone.utc)


def _organizations(*rows: tuple[str, str | None, bool, str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "org_id": pd.Series([row[0] for row in rows], dtype="string"),
            "state_id": pd.Series([row[1] for row in rows], dtype="string"),
            "city_name": pd.Series(
                [f"City {index}" for index in range(len(rows))], dtype="string"
            ),
            "is_collaborator": pd.Series([row[2] for row in rows], dtype="boolean"),
            "created_at": pd.to_datetime(
                [row[3] for row in rows], format="mixed", utc=True
            ),
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


def _window(start: str, end_exclusive: str) -> DateWindow:
    return DateWindow(
        start=pd.Timestamp(start, tz="UTC").to_pydatetime(),
        end_exclusive=pd.Timestamp(end_exclusive, tz="UTC").to_pydatetime(),
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

    result = calculate_country_distribution(
        organizations, states, countries, _all_window()
    )

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

    result = calculate_country_distribution(
        _organizations(*rows), states, countries, _all_window()
    )

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

    result = calculate_country_distribution(
        organizations, states, countries, _all_window()
    )

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


def test_location_custom_uses_only_its_own_range():
    organizations = _organizations(
        ("growth", "IL", False, "2026-04-05"),
        ("location", "KA", True, "2026-06-05"),
    )
    ranges = resolve_date_ranges(
        start_date="2026-04-01",
        end_date="2026-04-30",
        location_start_date="2026-06-01",
        location_end_date="2026-06-30",
        reference_time=REFERENCE,
    )

    result = calculate_country_distribution(
        organizations,
        _states(("IL", "US"), ("KA", "IN")),
        _countries(("US", "USA"), ("IN", "IND")),
        ranges.location_custom,
    )

    assert result == [{"country": "IND", "count": 1}]


def test_growth_custom_alone_leaves_location_custom_empty():
    ranges = resolve_date_ranges(
        start_date="2026-04-01",
        end_date="2026-04-30",
        reference_time=REFERENCE,
    )

    result = calculate_country_distribution(
        _organizations(("org-1", "IL", False, "2026-04-05")),
        _states(("IL", "US")),
        _countries(("US", "USA")),
        ranges.location_custom,
    )

    assert result == []


def test_empty_single_and_no_activity_behaviors():
    states = _states(("IL", "US"))
    countries = _countries(("US", "USA"))
    window = _window("2026-09-09", "2026-09-16")

    assert calculate_country_distribution(
        _organizations(), states, countries, window
    ) == []
    assert calculate_country_distribution(
        _organizations(("org-1", "IL", False, "2026-09-15")),
        states,
        countries,
        window,
    ) == [{"country": "USA", "count": 1}]
    assert calculate_country_distribution(
        _organizations(("org-old", "IL", False, "2020-01-01")),
        states,
        countries,
        window,
    ) == []


def test_collaborator_status_does_not_affect_counts():
    organizations = _organizations(
        ("collaborator", "IL", True, "2026-09-10"),
        ("non-collaborator", "IL", False, "2026-09-11"),
    )

    result = calculate_country_distribution(
        organizations,
        _states(("IL", "US")),
        _countries(("US", "USA")),
        _all_window(),
    )

    assert result == [{"country": "USA", "count": 2}]


@pytest.mark.parametrize(
    ("states", "countries", "message"),
    [
        (
            _states(("IL", "US"), ("IL", "US")),
            _countries(("US", "USA")),
            r"states\.state_id contains duplicate lookup keys: IL",
        ),
        (
            _states(("IL", "US")),
            _countries(("US", "USA"), ("US", "USA")),
            r"countries\.country_id contains duplicate lookup keys: US",
        ),
    ],
)
def test_duplicate_lookup_keys_raise_clear_integrity_errors(
    states, countries, message
):
    organizations = _organizations(("org-1", "IL", False, "2026-09-10"))

    with pytest.raises(LocationCalculationError, match=message):
        calculate_country_distribution(
            organizations, states, countries, _all_window()
        )


@pytest.mark.parametrize(
    ("organizations", "states", "countries", "message"),
    [
        (
            _organizations(("org-1", "missing", False, "2026-09-10")),
            _states(("IL", "US")),
            _countries(("US", "USA")),
            "unmatched state_id references: missing",
        ),
        (
            _organizations(("org-1", None, False, "2026-09-10")),
            _states(("IL", "US")),
            _countries(("US", "USA")),
            r"organizations\.state_id contains missing or blank references",
        ),
        (
            _organizations(("org-1", "IL", False, "2026-09-10")),
            _states(("IL", "missing")),
            _countries(("US", "USA")),
            "unmatched country_id references: missing",
        ),
        (
            _organizations(("org-1", "IL", False, "2026-09-10")),
            _states(("IL", None)),
            _countries(("US", "USA")),
            r"states\.country_id contains missing or blank references",
        ),
        (
            _organizations(("org-1", "IL", False, "2026-09-10")),
            _states(("IL", "US")),
            _countries(("US", None)),
            r"countries\.country_code contains missing or blank references",
        ),
    ],
)
def test_missing_and_unmatched_references_raise_errors(
    organizations, states, countries, message
):
    with pytest.raises(LocationCalculationError, match=message):
        calculate_country_distribution(
            organizations, states, countries, _all_window()
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


def test_output_shape_json_compatibility_and_inputs_are_unchanged():
    organizations = _organizations(
        ("org-1", "IL", True, "2026-09-10"),
        ("org-2", "KA", False, "2026-09-11"),
    )
    states = _states(("IL", "US"), ("KA", "IN"))
    countries = _countries(("US", "USA"), ("IN", "IND"))
    originals = tuple(
        frame.copy(deep=True) for frame in (organizations, states, countries)
    )

    result = calculate_country_distribution(
        organizations, states, countries, _all_window()
    )

    assert all(set(row) == {"country", "count"} for row in result)
    assert all(type(row["country"]) is str for row in result)
    assert all(type(row["count"]) is int for row in result)
    assert all("Other" not in row.values() for row in result)
    assert json.loads(json.dumps(result)) == result
    for actual, original in zip((organizations, states, countries), originals):
        assert_frame_equal(actual, original)
