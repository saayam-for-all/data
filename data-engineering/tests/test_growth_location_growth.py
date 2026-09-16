"""Focused tests for pure organization-growth calculations."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.growth_location_analytics import (
    DateWindow,
    calculate_organization_growth,
    resolve_date_ranges,
)


REFERENCE = datetime(2026, 9, 15, 18, 42, 11, tzinfo=timezone.utc)


def _organizations(*rows: tuple[str, bool, str]) -> pd.DataFrame:
    """Build normalized task-1 organization data from timestamp/bool/state rows."""

    return pd.DataFrame(
        {
            "org_id": [f"org-{index}" for index in range(len(rows))],
            "state_id": [state for _, _, state in rows],
            "city_name": [f"City {index}" for index in range(len(rows))],
            "is_collaborator": pd.Series(
                [is_collaborator for _, is_collaborator, _ in rows],
                dtype="boolean",
            ),
            "created_at": pd.to_datetime(
                [created_at for created_at, _, _ in rows], format="mixed", utc=True
            ),
        }
    )


def _window(start: str, end_exclusive: str) -> DateWindow:
    return DateWindow(
        start=pd.Timestamp(start, tz="UTC").to_pydatetime(),
        end_exclusive=pd.Timestamp(end_exclusive, tz="UTC").to_pydatetime(),
    )


def test_historical_rows_seed_totals_while_collaborators_stay_per_period():
    organizations = _organizations(
        ("2026-01-01", True, "historical-a"),
        ("2026-01-02", False, "historical-b"),
        ("2026-05-10T08:00:00Z", True, "active-a"),
        ("2026-05-10T09:00:00Z", False, "active-b"),
        ("2026-05-12T10:00:00Z", True, "active-c"),
        ("2026-05-12T11:00:00Z", True, "active-d"),
        ("2026-05-12T12:00:00Z", False, "active-e"),
    )

    result = calculate_organization_growth(
        organizations, "Custom", _window("2026-05-10", "2026-05-13")
    )

    assert result == {
        "total_organizations": [
            {"period": "2026-05-10", "count": 4},
            {"period": "2026-05-12", "count": 7},
        ],
        "collaborators": [
            {"period": "2026-05-10", "count": 1},
            {"period": "2026-05-12", "count": 2},
        ],
    }


@pytest.mark.parametrize("bucket", ["7D", "30D", "Custom"])
def test_daily_buckets_are_sparse_sorted_aligned_and_include_zero_collaborators(bucket):
    organizations = _organizations(
        ("2026-09-14T23:00:00Z", True, "TX"),
        ("2026-09-10T12:00:00Z", False, "CA"),
        ("2026-09-10T08:00:00Z", False, "NY"),
    )
    window = _window("2026-09-09", "2026-09-16")

    result = calculate_organization_growth(organizations, bucket, window)

    expected_periods = ["2026-09-10", "2026-09-14"]
    assert [point["period"] for point in result["total_organizations"]] == expected_periods
    assert [point["period"] for point in result["collaborators"]] == expected_periods
    assert result["total_organizations"] == [
        {"period": "2026-09-10", "count": 2},
        {"period": "2026-09-14", "count": 3},
    ]
    assert result["collaborators"] == [
        {"period": "2026-09-10", "count": 0},
        {"period": "2026-09-14", "count": 1},
    ]


@pytest.mark.parametrize("bucket", ["1Y", "All"])
def test_monthly_buckets_group_multiple_rows_independently_of_state(bucket):
    organizations = _organizations(
        ("2026-04-20", True, "one"),
        ("2026-02-03", False, "two"),
        ("2026-04-01", False, "three"),
        ("2026-02-28", True, "four"),
    )
    window = (
        _window("2026-01-15", "2026-05-01")
        if bucket == "1Y"
        else DateWindow(None, None)
    )

    result = calculate_organization_growth(organizations, bucket, window)

    assert result == {
        "total_organizations": [
            {"period": "2026-02", "count": 2},
            {"period": "2026-04", "count": 4},
        ],
        "collaborators": [
            {"period": "2026-02", "count": 1},
            {"period": "2026-04", "count": 1},
        ],
    }


def test_single_organization_and_json_compatible_python_values():
    organizations = _organizations(("2026-09-15T12:34:56Z", False, "IL"))

    result = calculate_organization_growth(
        organizations, "7D", _window("2026-09-09", "2026-09-16")
    )

    assert result == {
        "total_organizations": [{"period": "2026-09-15", "count": 1}],
        "collaborators": [{"period": "2026-09-15", "count": 0}],
    }
    assert type(result["total_organizations"][0]["count"]) is int
    assert type(result["collaborators"][0]["count"]) is int
    assert json.loads(json.dumps(result)) == result


def test_empty_data_and_window_without_activity_return_empty_series():
    empty = _organizations()
    historical_only = _organizations(("2025-01-01", True, "old"))
    window = _window("2026-09-09", "2026-09-16")
    expected = {"total_organizations": [], "collaborators": []}

    assert calculate_organization_growth(empty, "7D", window) == expected
    assert calculate_organization_growth(historical_only, "7D", window) == expected


def test_missing_growth_custom_and_location_only_custom_do_not_activate_growth():
    organizations = _organizations(("2026-04-05", True, "IL"))
    no_custom = resolve_date_ranges(reference_time=REFERENCE)
    location_only = resolve_date_ranges(
        location_start_date="2026-04-01",
        location_end_date="2026-04-30",
        reference_time=REFERENCE,
    )

    assert no_custom.growth_custom is None
    assert location_only.growth_custom is None
    expected = {"total_organizations": [], "collaborators": []}
    assert (
        calculate_organization_growth(
            organizations, "Custom", no_custom.growth_custom
        )
        == expected
    )
    assert (
        calculate_organization_growth(
            organizations, "Custom", location_only.growth_custom
        )
        == expected
    )


def test_growth_and_location_custom_ranges_remain_independent():
    organizations = _organizations(
        ("2026-04-05", True, "growth"),
        ("2026-06-01", True, "location"),
    )
    ranges = resolve_date_ranges(
        start_date="2026-04-01",
        end_date="2026-04-30",
        location_start_date="2026-06-01",
        location_end_date="2026-06-30",
        reference_time=REFERENCE,
    )

    result = calculate_organization_growth(
        organizations, "Custom", ranges.growth_custom
    )

    assert result["total_organizations"] == [
        {"period": "2026-04-05", "count": 1}
    ]


def test_half_open_boundaries_and_partial_month_use_only_in_window_activity():
    organizations = _organizations(
        ("2025-09-14T23:59:59Z", False, "before"),
        ("2025-09-15T00:00:00Z", True, "start"),
        ("2026-09-15T23:59:59Z", False, "end"),
        ("2026-09-16T00:00:00Z", True, "after"),
    )
    window = _window("2025-09-15", "2026-09-16")

    result = calculate_organization_growth(organizations, "1Y", window)

    assert result == {
        "total_organizations": [
            {"period": "2025-09", "count": 2},
            {"period": "2026-09", "count": 3},
        ],
        "collaborators": [
            {"period": "2025-09", "count": 1},
            {"period": "2026-09", "count": 0},
        ],
    }


def test_fixed_window_excludes_later_dates_but_includes_entire_reference_day():
    organizations = _organizations(
        ("2026-09-15T23:59:59Z", False, "today"),
        ("2026-09-16T00:00:00Z", True, "future"),
    )
    ranges = resolve_date_ranges(reference_time=REFERENCE)

    result = calculate_organization_growth(
        organizations, "7D", ranges.fixed["7D"]
    )

    assert result["total_organizations"] == [
        {"period": "2026-09-15", "count": 1}
    ]


def test_all_counts_every_row_including_repeated_ids_and_future_dates():
    organizations = _organizations(
        ("2025-01-01", False, "past"),
        ("2026-01-01", True, "present"),
        ("2027-01-01", False, "future"),
    )
    organizations.loc[1, "org_id"] = organizations.loc[0, "org_id"]

    result = calculate_organization_growth(
        organizations, "All", DateWindow(None, None)
    )

    assert result["total_organizations"][-1]["count"] == len(organizations)
    assert result["total_organizations"] == [
        {"period": "2025-01", "count": 1},
        {"period": "2026-01", "count": 2},
        {"period": "2027-01", "count": 3},
    ]


def test_calculation_does_not_mutate_input_dataframe():
    organizations = _organizations(
        ("2026-04-02", False, "TX"),
        ("2026-04-01", True, "CA"),
    )
    original = organizations.copy(deep=True)

    calculate_organization_growth(
        organizations, "Custom", _window("2026-04-01", "2026-04-03")
    )

    assert_frame_equal(organizations, original)
