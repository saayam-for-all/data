"""Calculation tests for issue #376, using the shared filtering layer directly."""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data-analytics" / "lambda_functions"))
import size_contribution_analytics as analytics


TODAY = date(2026, 9, 23)


@pytest.fixture
def organizations():
    rows = [
        # Both flags can be true for the same organization.
        ("small", "non_profit", "USA", "United States", "2026-09-23 23:59:59", True, True),
        ("micro", "non_profit", "USA", "United States", "2026-09-16 00:00:00", False, True),
        ("small", "for_profit", "USA", "United States", "2026-09-15 23:59:59", False, False),
        ("Large", "non_profit", "CAN", "Canada", "2026-08-24 00:00:00", False, False),
        ("tiny", "non_profit", "USA", "United States", "2026-08-23 00:00:00", False, False),
        ("medium", "non_profit", "USA", "United States", "2026-01-01 23:59:59", True, False),
        ("future", "non_profit", "USA", "United States", "2026-09-24 00:00:00", False, False),
    ]
    frame = pd.DataFrame(rows, columns=(
        "org_size", "org_type", "country_code", "country_name", "created_at",
        "is_collaborator", "is_contributor",
    ))
    return analytics._prepare_organizations(frame)


def selected(organizations, window, country="ALL", org_type="ALL", custom_range=None):
    filtered = analytics.filter_organizations(organizations, country, org_type)
    return analytics.filter_by_window(filtered, window, today=TODAY, custom_range=custom_range)


@pytest.mark.parametrize("window,expected_total,expected_sizes", [
    ("7D", 2, {"small": 1, "micro": 1}),
    ("30D", 4, {"small": 2, "micro": 1, "Large": 1}),
    ("1Y", 6, {"small": 2, "micro": 1, "Large": 1, "tiny": 1, "medium": 1}),
    ("All", 7, {"small": 2, "micro": 1, "Large": 1, "tiny": 1, "medium": 1, "future": 1}),
])
def test_size_counts_cover_exact_fixed_window_total(organizations, window, expected_total, expected_sizes):
    frame = selected(organizations, window)
    chart = analytics._size_chart(frame)
    assert len(frame) == expected_total
    assert {row["size"]: row["count"] for row in chart} == expected_sizes
    assert sum(row["count"] for row in chart) == len(frame)


@pytest.mark.parametrize("country,org_type,expected", [
    ("USA", "non_profit", {"small": 1, "micro": 1}),
    ("United States", "for_profit", {"small": 1}),
    ("CAN", "non_profit", {"Large": 1}),
])
def test_size_counts_use_both_shared_filters(organizations, country, org_type, expected):
    frame = selected(organizations, "30D", country, org_type)
    chart = analytics._size_chart(frame)
    assert {row["size"]: row["count"] for row in chart} == expected
    assert sum(row["count"] for row in chart) == len(frame)


def test_size_custom_window_includes_both_date_boundaries(organizations):
    frame = selected(
        organizations, "Custom", "USA", "non_profit",
        custom_range=(date(2026, 9, 16), TODAY),
    )
    assert analytics._size_chart(frame) == [
        {"size": "small", "count": 1}, {"size": "micro", "count": 1},
    ]
    assert sum(row["count"] for row in analytics._size_chart(frame)) == len(frame)

    one_day = selected(
        organizations, "Custom", custom_range=(date(2026, 1, 1), date(2026, 1, 1))
    )
    assert analytics._size_chart(one_day) == [{"size": "medium", "count": 1}]


def test_size_only_emits_observed_raw_categories(organizations):
    frame = selected(organizations, "30D").copy()
    frame["org_size"] = pd.Categorical(
        frame["org_size"], categories=["small", "micro", "Large", "unused"]
    )
    assert {row["size"] for row in analytics._size_chart(frame)} == {"small", "micro", "Large"}


def test_empty_and_one_row_size_inputs(organizations):
    empty = selected(
        organizations, "Custom", custom_range=(date(2020, 1, 1), date(2020, 1, 1))
    )
    assert analytics._size_chart(empty) == []
    one_row = selected(
        organizations, "Custom", custom_range=(date(2026, 9, 23), date(2026, 9, 23))
    )
    assert analytics._size_chart(one_row) == [{"size": "small", "count": 1}]


def test_contribution_counts_are_independent_and_window_scoped(organizations):
    seven_days = selected(organizations, "7D")
    assert analytics._contribution_chart(seven_days) == [
        {"type": "Collaborator", "count": 1, "percentage": 50.0},
        {"type": "Contributor", "count": 2, "percentage": 100.0},
    ]
    thirty_days = selected(organizations, "30D")
    assert analytics._contribution_chart(thirty_days) == [
        {"type": "Collaborator", "count": 1, "percentage": 25.0},
        {"type": "Contributor", "count": 2, "percentage": 50.0},
    ]
    assert all(row["count"] <= len(thirty_days) for row in analytics._contribution_chart(thirty_days))


def test_contribution_custom_window_and_shared_filters(organizations):
    frame = selected(
        organizations, "Custom", "United States", "non_profit",
        custom_range=(date(2026, 9, 16), date(2026, 9, 23)),
    )
    assert analytics._contribution_chart(frame) == [
        {"type": "Collaborator", "count": 1, "percentage": 50.0},
        {"type": "Contributor", "count": 2, "percentage": 100.0},
    ]
    canada = selected(organizations, "30D", "CAN", "non_profit")
    assert analytics._contribution_chart(canada) == [
        {"type": "Collaborator", "count": 0, "percentage": 0.0},
        {"type": "Contributor", "count": 0, "percentage": 0.0},
    ]


def test_contribution_empty_one_row_and_missing_contributor(organizations):
    empty = selected(
        organizations, "Custom", custom_range=(date(2020, 1, 1), date(2020, 1, 1))
    )
    assert analytics._contribution_chart(empty) == []
    one_row = selected(
        organizations, "Custom", custom_range=(date(2026, 9, 23), date(2026, 9, 23))
    )
    assert analytics._contribution_chart(one_row) == [
        {"type": "Collaborator", "count": 1, "percentage": 100.0},
        {"type": "Contributor", "count": 1, "percentage": 100.0},
    ]
    assert analytics._contribution_chart(one_row.drop(columns="is_contributor")) == [
        {"type": "Collaborator", "count": 1, "percentage": 100.0},
        {"type": "Contributor", "count": 0, "percentage": 0.0},
    ]
