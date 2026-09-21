"""
Unit tests for growth_location_analytics.py (issue #336).

These build small CSV fixtures under tmp_path and call the module's
functions directly with a fixed reference_date, so the assertions don't
depend on the wall-clock date. Run with:

    pytest data-analytics/lambda_functions/tests/test_growth_location_analytics.py
"""
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import growth_location_analytics as gla

REFERENCE = pd.Timestamp("2026-06-15")


def _write_csv(path, header, rows):
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(value) for value in row))
    path.write_text("\n".join(lines) + "\n")


def _write_dataset(tmp_path, organizations, states=None, countries=None):
    states = states if states is not None else [
        ("US-TX", "Texas", "1"),
        ("US-FL", "Florida", "1"),
        ("IN-DL", "Delhi", "2"),
        ("GB-LDN", "London", "3"),
        ("CA-ON", "Ontario", "4"),
        ("AU-NSW", "New South Wales", "5"),
    ]
    countries = countries if countries is not None else [
        ("1", "USA"), ("2", "IND"), ("3", "GBR"), ("4", "CAN"), ("5", "AUS"),
    ]
    _write_csv(
        tmp_path / "organizations.csv",
        ["org_id", "state_id", "city_name", "is_collaborator", "created_at"],
        organizations,
    )
    _write_csv(tmp_path / "states.csv", ["state_id", "state_name", "country_id"], states)
    _write_csv(tmp_path / "countries.csv", ["country_id", "country_code"], countries)
    return gla.load_organizations(data_dir=str(tmp_path))


def _days_before(days):
    return (REFERENCE - pd.Timedelta(days=days)).strftime("%Y-%m-%d")


def _months_before(months, day=15):
    return (REFERENCE - pd.DateOffset(months=months)).replace(day=day).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 1. No body -> all 5 keys, buckets with/without activity, Custom fully empty
# ---------------------------------------------------------------------------

def test_no_body_returns_all_five_keys_with_empty_custom(tmp_path):
    organizations = _write_dataset(tmp_path, [
        ("ORG-1", "US-TX", "Austin", "TRUE", _days_before(40)),  # outside 7D/30D, inside 1Y/All
    ])

    response = gla.build_growth_location_response(organizations, {}, reference_date=REFERENCE)

    assert set(response.keys()) == {"7D", "30D", "1Y", "All", "Custom"}

    assert response["7D"]["growth_trend"] == {"total_organizations": [], "collaborators": []}
    assert response["7D"]["organizations_by_location"] == []
    assert response["30D"]["growth_trend"] == {"total_organizations": [], "collaborators": []}
    assert response["30D"]["organizations_by_location"] == []

    assert len(response["1Y"]["growth_trend"]["total_organizations"]) == 1
    assert response["1Y"]["organizations_by_location"] == [{"country": "USA", "count": 1}]
    assert len(response["All"]["growth_trend"]["total_organizations"]) == 1
    assert response["All"]["organizations_by_location"] == [{"country": "USA", "count": 1}]

    assert response["Custom"] == {
        "growth_trend": {"total_organizations": [], "collaborators": []},
        "organizations_by_location": [],
    }


def test_lambda_handler_no_body(tmp_path, monkeypatch):
    _write_dataset(tmp_path, [("ORG-1", "US-TX", "Austin", "TRUE", "2026-01-01")])
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))

    result = gla.lambda_handler({}, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert set(body.keys()) == {"7D", "30D", "1Y", "All", "Custom"}


# ---------------------------------------------------------------------------
# 2 & 3. Only one Custom pair populates only its own section
# ---------------------------------------------------------------------------

def test_only_growth_custom_range_populates_growth_trend_only(tmp_path):
    organizations = _write_dataset(tmp_path, [
        ("ORG-1", "US-TX", "Austin", "TRUE", "2026-03-10"),
    ])

    response = gla.build_growth_location_response(
        organizations,
        {"start_date": "2026-01-01", "end_date": "2026-06-30"},
        reference_date=REFERENCE,
    )

    assert response["Custom"]["growth_trend"]["total_organizations"] == [{"period": "2026-03-10", "count": 1}]
    assert response["Custom"]["organizations_by_location"] == []


def test_only_location_custom_range_populates_location_only(tmp_path):
    organizations = _write_dataset(tmp_path, [
        ("ORG-1", "US-TX", "Austin", "TRUE", "2026-03-10"),
    ])

    response = gla.build_growth_location_response(
        organizations,
        {"location_start_date": "2026-01-01", "location_end_date": "2026-06-30"},
        reference_date=REFERENCE,
    )

    assert response["Custom"]["growth_trend"] == {"total_organizations": [], "collaborators": []}
    assert response["Custom"]["organizations_by_location"] == [{"country": "USA", "count": 1}]


# ---------------------------------------------------------------------------
# 4. Both Custom pairs populate independently, from different windows
# ---------------------------------------------------------------------------

def test_both_custom_ranges_apply_independently(tmp_path):
    organizations = _write_dataset(tmp_path, [
        ("ORG-1", "US-TX", "Austin", "TRUE", "2026-03-10"),   # only in growth range
        ("ORG-2", "IN-DL", "Delhi", "FALSE", "2025-06-01"),   # only in location range
    ])

    response = gla.build_growth_location_response(
        organizations,
        {
            "start_date": "2026-01-01", "end_date": "2026-06-30",
            "location_start_date": "2025-01-01", "location_end_date": "2025-12-31",
        },
        reference_date=REFERENCE,
    )

    assert response["Custom"]["growth_trend"]["total_organizations"] == [{"period": "2026-03-10", "count": 2}]
    assert response["Custom"]["organizations_by_location"] == [{"country": "IND", "count": 1}]


# ---------------------------------------------------------------------------
# 5. Invalid dates / inverted range -> 400
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"start_date": "2026-01-01"},  # end_date missing
    {"end_date": "2026-01-01"},  # start_date missing
    {"start_date": "not-a-date", "end_date": "2026-01-01"},
    {"start_date": "2026-06-30", "end_date": "2026-01-01"},  # start after end
])
def test_invalid_growth_custom_range_raises(tmp_path, body):
    organizations = _write_dataset(tmp_path, [("ORG-1", "US-TX", "Austin", "TRUE", "2026-03-10")])

    with pytest.raises(gla.InvalidDateRangeError):
        gla.build_growth_location_response(organizations, body, reference_date=REFERENCE)


def test_invalid_location_custom_range_raises(tmp_path):
    organizations = _write_dataset(tmp_path, [("ORG-1", "US-TX", "Austin", "TRUE", "2026-03-10")])

    with pytest.raises(gla.InvalidDateRangeError):
        gla.build_growth_location_response(
            organizations,
            {"location_start_date": "2026-06-30", "location_end_date": "2026-01-01"},
            reference_date=REFERENCE,
        )


def test_lambda_handler_returns_400_for_invalid_range(tmp_path, monkeypatch):
    _write_dataset(tmp_path, [("ORG-1", "US-TX", "Austin", "TRUE", "2026-03-10")])
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))

    result = gla.lambda_handler({"start_date": "2026-06-30", "end_date": "2026-01-01"}, None)

    assert result["statusCode"] == 400
    assert "error" in json.loads(result["body"])


# ---------------------------------------------------------------------------
# 6. total_organizations is cumulative/all-time; collaborators is per-period
# ---------------------------------------------------------------------------

def test_total_organizations_is_cumulative_not_reset_per_window():
    organizations = pd.DataFrame([
        {"org_id": "ORG-1", "country_code": "USA", "is_collaborator": True, "created_at": pd.Timestamp("2025-01-01")},
        {"org_id": "ORG-2", "country_code": "USA", "is_collaborator": False, "created_at": pd.Timestamp("2026-06-01")},
        {"org_id": "ORG-3", "country_code": "USA", "is_collaborator": True, "created_at": pd.Timestamp("2026-06-10")},
    ])

    # window = only the last 30 days, but the running total must still count
    # ORG-1 from a year earlier.
    window_start = REFERENCE - pd.Timedelta(days=30)
    result = gla.build_growth_trend(organizations, window_start, REFERENCE, "day")

    counts_by_period = {entry["period"]: entry["count"] for entry in result["total_organizations"]}
    assert counts_by_period["2026-06-01"] == 2  # ORG-1 + ORG-2, not reset to 1
    assert counts_by_period["2026-06-10"] == 3  # + ORG-3

    collab_by_period = {entry["period"]: entry["count"] for entry in result["collaborators"]}
    assert collab_by_period["2026-06-01"] == 0  # ORG-2 is not a collaborator
    assert collab_by_period["2026-06-10"] == 1  # only ORG-3 in this period


# ---------------------------------------------------------------------------
# 7. Grouping granularity: 7D/30D/Custom by day, 1Y/All by month
# ---------------------------------------------------------------------------

def test_grouping_granularity_by_bucket(tmp_path):
    organizations = _write_dataset(tmp_path, [
        ("ORG-1", "US-TX", "Austin", "TRUE", _days_before(3)),
        ("ORG-2", "US-TX", "Austin", "TRUE", _months_before(6)),
    ])

    response = gla.build_growth_location_response(organizations, {}, reference_date=REFERENCE)

    for bucket in ("7D", "30D"):
        for entry in response[bucket]["growth_trend"]["total_organizations"]:
            assert len(entry["period"]) == 10  # YYYY-MM-DD

    for bucket in ("1Y", "All"):
        for entry in response[bucket]["growth_trend"]["total_organizations"]:
            assert len(entry["period"]) == 7  # YYYY-MM


# ---------------------------------------------------------------------------
# 8. Location aggregates by country, never "Other"/percentage, max 4 rows
# ---------------------------------------------------------------------------

def test_location_aggregates_by_country_not_state():
    organizations = pd.DataFrame([
        {"org_id": "ORG-1", "country_code": "USA", "is_collaborator": True, "created_at": pd.Timestamp("2026-01-01")},
        {"org_id": "ORG-2", "country_code": "USA", "is_collaborator": True, "created_at": pd.Timestamp("2026-01-02")},
    ])
    # ORG-1 is TX, ORG-2 is FL in spirit, but both already resolved to USA -
    # the point is they must collapse into a single USA row, not two.
    result = gla.build_organizations_by_location(organizations, None, None)

    assert result == [{"country": "USA", "count": 2}]


def test_location_never_exceeds_four_rows_and_has_no_other_or_percentage():
    countries_with_counts = [("USA", 6), ("IND", 5), ("GBR", 4), ("CAN", 3), ("AUS", 2), ("DEU", 1)]
    organizations = pd.DataFrame([
        {
            "org_id": f"{country}-{n}",
            "country_code": country,
            "is_collaborator": False,
            "created_at": pd.Timestamp("2026-01-01"),
        }
        for country, count in countries_with_counts
        for n in range(count)
    ])

    result = gla.build_organizations_by_location(organizations, None, None)

    assert len(result) == 4
    assert [row["country"] for row in result] == ["USA", "IND", "GBR", "CAN"]
    for row in result:
        assert set(row.keys()) == {"country", "count"}
        assert row["country"] != "Other"


# ---------------------------------------------------------------------------
# 9. Against a single-country states.csv, location returns exactly one row
# ---------------------------------------------------------------------------

def test_single_country_states_csv_returns_one_location_row(tmp_path):
    us_only_states = [
        ("US-TX", "Texas", "1"),
        ("US-FL", "Florida", "1"),
        ("US-CA", "California", "1"),
    ]
    us_only_countries = [("1", "USA")]
    organizations = _write_dataset(
        tmp_path,
        [
            ("ORG-1", "US-TX", "Austin", "TRUE", "2026-01-01"),
            ("ORG-2", "US-FL", "Miami", "FALSE", "2026-01-02"),
            ("ORG-3", "US-CA", "LA", "TRUE", "2026-01-03"),
        ],
        states=us_only_states,
        countries=us_only_countries,
    )

    result = gla.build_organizations_by_location(organizations, None, None)

    assert result == [{"country": "USA", "count": 3}]


# ---------------------------------------------------------------------------
# 10. Empty or 1-row organizations.csv doesn't crash any bucket
# ---------------------------------------------------------------------------

def test_empty_organizations_csv_does_not_crash(tmp_path):
    organizations = _write_dataset(tmp_path, [])

    response = gla.build_growth_location_response(organizations, {}, reference_date=REFERENCE)

    for bucket in ("7D", "30D", "1Y", "All", "Custom"):
        assert response[bucket]["growth_trend"] == {"total_organizations": [], "collaborators": []}
        assert response[bucket]["organizations_by_location"] == []


def test_one_row_organizations_csv_does_not_crash(tmp_path):
    organizations = _write_dataset(tmp_path, [("ORG-1", "US-TX", "Austin", "TRUE", "2026-01-01")])

    response = gla.build_growth_location_response(organizations, {}, reference_date=REFERENCE)

    assert response["All"]["organizations_by_location"] == [{"country": "USA", "count": 1}]


# ---------------------------------------------------------------------------
# Misc: unknown/unmatched state_id doesn't crash and is labeled Unknown
# ---------------------------------------------------------------------------

def test_unmatched_state_id_becomes_unknown_country(tmp_path):
    organizations = _write_dataset(tmp_path, [
        ("ORG-1", "ZZ-NOPE", "Nowhere", "FALSE", "2026-01-01"),
    ])

    result = gla.build_organizations_by_location(organizations, None, None)

    assert result == [{"country": "Unknown", "count": 1}]
