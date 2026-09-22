import json
import sys
from pathlib import Path

import pandas as pd
import pytest

# -------------------------------------------------------------------
# Import the Lambda file from the parent directory
# -------------------------------------------------------------------

LAMBDA_DIR = Path(__file__).resolve().parents[1]

if str(LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(LAMBDA_DIR))

import growth_location_analytics as analytics

TEST_TODAY = pd.Timestamp("2026-09-22", tz="UTC")


# -------------------------------------------------------------------
# Test data
# -------------------------------------------------------------------


@pytest.fixture
def states():
    return pd.DataFrame(
        [
            {"state_id": 1, "state_name": "Texas", "country_id": 1},
            {"state_id": 2, "state_name": "Florida", "country_id": 1},
            {"state_id": 3, "state_name": "Delhi", "country_id": 2},
            {"state_id": 4, "state_name": "Ontario", "country_id": 3},
            {"state_id": 5, "state_name": "England", "country_id": 4},
            {"state_id": 6, "state_name": "NSW", "country_id": 5},
        ]
    )


@pytest.fixture
def countries():
    return pd.DataFrame(
        [
            {"country_id": 1, "country_code": "USA"},
            {"country_id": 2, "country_code": "IND"},
            {"country_id": 3, "country_code": "CAN"},
            {"country_id": 4, "country_code": "GBR"},
            {"country_id": 5, "country_code": "AUS"},
        ]
    )


@pytest.fixture
def organizations():
    df = pd.DataFrame(
        [
            {
                "org_id": 1,
                "state_id": 1,
                "city_name": "Austin",
                "is_collaborator": False,
                "created_at": "2025-01-01T10:00:00Z",
            },
            {
                "org_id": 2,
                "state_id": 1,
                "city_name": "Dallas",
                "is_collaborator": False,
                "created_at": "2026-08-01T10:00:00Z",
            },
            {
                "org_id": 3,
                "state_id": 2,
                "city_name": "Miami",
                "is_collaborator": True,
                "created_at": "2026-09-16T10:00:00Z",
            },
            {
                "org_id": 4,
                "state_id": 1,
                "city_name": "Houston",
                "is_collaborator": False,
                "created_at": "2026-09-18T10:00:00Z",
            },
            {
                "org_id": 5,
                "state_id": 2,
                "city_name": "Orlando",
                "is_collaborator": True,
                "created_at": "2026-09-18T15:00:00Z",
            },
            {
                "org_id": 6,
                "state_id": 3,
                "city_name": "Delhi",
                "is_collaborator": True,
                "created_at": "2026-09-20T10:00:00Z",
            },
            {
                "org_id": 7,
                "state_id": 4,
                "city_name": "Toronto",
                "is_collaborator": False,
                "created_at": "2026-09-21T10:00:00Z",
            },
            {
                "org_id": 8,
                "state_id": 5,
                "city_name": "London",
                "is_collaborator": False,
                "created_at": "2026-09-22T09:00:00Z",
            },
            {
                "org_id": 9,
                "state_id": 6,
                "city_name": "Sydney",
                "is_collaborator": True,
                "created_at": "2026-09-22T12:00:00Z",
            },
            {
                "org_id": 10,
                "state_id": 1,
                "city_name": "Dallas",
                "is_collaborator": False,
                "created_at": "2026-09-22T18:00:00Z",
            },
        ]
    )

    df["created_at"] = pd.to_datetime(
        df["created_at"],
        utc=True,
    )

    return df


# -------------------------------------------------------------------
# Reset warm-instance cache between tests
# -------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_data_cache():
    analytics._DATA_CACHE = None

    yield

    analytics._DATA_CACHE = None


# -------------------------------------------------------------------
# Helper
# -------------------------------------------------------------------


def build_response(
    organizations,
    states,
    countries,
    payload=None,
):
    payload = payload or {}

    growth_range, location_range = analytics.parse_custom_ranges(payload)

    return analytics.build_analytics_response(
        organizations=organizations,
        states=states,
        countries=countries,
        growth_range=growth_range,
        location_range=location_range,
        today=TEST_TODAY,
    )


# -------------------------------------------------------------------
# Response shape
# -------------------------------------------------------------------


def test_all_five_top_level_keys_present(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
    )

    assert list(result.keys()) == [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]


def test_each_bucket_has_exact_required_shape(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
    )

    for bucket in result.values():
        assert set(bucket.keys()) == {
            "growth_trend",
            "organizations_by_location",
        }

        assert set(bucket["growth_trend"].keys()) == {
            "total_organizations",
            "collaborators",
        }


# -------------------------------------------------------------------
# No Custom range
# -------------------------------------------------------------------


def test_no_body_leaves_custom_empty(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
    )

    assert result["Custom"] == {
        "growth_trend": {
            "total_organizations": [],
            "collaborators": [],
        },
        "organizations_by_location": [],
    }

    assert result["7D"]["growth_trend"]["total_organizations"]

    assert result["All"]["growth_trend"]["total_organizations"]


# -------------------------------------------------------------------
# Custom Growth only
# -------------------------------------------------------------------


def test_growth_custom_only(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
        {
            "start_date": "2026-09-18",
            "end_date": "2026-09-20",
        },
    )

    assert result["Custom"]["growth_trend"]["total_organizations"]

    assert result["Custom"]["growth_trend"]["collaborators"]

    assert result["Custom"]["organizations_by_location"] == []


# -------------------------------------------------------------------
# Custom Location only
# -------------------------------------------------------------------


def test_location_custom_only(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
        {
            "location_start_date": "2026-09-18",
            "location_end_date": "2026-09-20",
        },
    )

    assert result["Custom"]["growth_trend"] == {
        "total_organizations": [],
        "collaborators": [],
    }

    assert result["Custom"]["organizations_by_location"]


# -------------------------------------------------------------------
# Both independent Custom ranges
# -------------------------------------------------------------------


def test_both_custom_ranges_are_independent(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
        {
            "start_date": "2026-09-18",
            "end_date": "2026-09-18",
            "location_start_date": "2026-09-20",
            "location_end_date": "2026-09-20",
        },
    )

    growth_periods = [
        item["period"]
        for item in result["Custom"]["growth_trend"]["total_organizations"]
    ]

    assert growth_periods == ["2026-09-18"]

    assert result["Custom"]["organizations_by_location"] == [
        {
            "country": "IND",
            "count": 1,
        }
    ]


# -------------------------------------------------------------------
# Invalid dates
# -------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {
            "start_date": "09/01/2026",
            "end_date": "2026-09-20",
        },
        {
            "start_date": "2026-09-20",
            "end_date": "2026-09-01",
        },
        {
            "location_start_date": "bad-date",
            "location_end_date": "2026-09-20",
        },
        {
            "location_start_date": "2026-09-20",
            "location_end_date": "2026-09-01",
        },
    ],
)
def test_invalid_date_ranges_return_400(
    monkeypatch,
    organizations,
    states,
    countries,
    payload,
):
    monkeypatch.setattr(
        analytics,
        "load_data",
        lambda: (
            organizations,
            states,
            countries,
        ),
    )

    response = analytics.lambda_handler(
        {"body": json.dumps(payload)},
        None,
    )

    assert response["statusCode"] == 400

    body = json.loads(response["body"])

    assert "error" in body


def test_missing_end_date_returns_400(
    monkeypatch,
    organizations,
    states,
    countries,
):
    monkeypatch.setattr(
        analytics,
        "load_data",
        lambda: (
            organizations,
            states,
            countries,
        ),
    )

    response = analytics.lambda_handler(
        {"body": json.dumps({"start_date": "2026-09-01"})},
        None,
    )

    assert response["statusCode"] == 400


# -------------------------------------------------------------------
# Absolute cumulative organization total
# -------------------------------------------------------------------


def test_total_organizations_is_absolute_not_window_reset(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
    )

    totals = result["7D"]["growth_trend"]["total_organizations"]

    assert totals[0] == {
        "period": "2026-09-16",
        "count": 3,
    }

    assert totals[-1] == {
        "period": "2026-09-22",
        "count": 10,
    }


def test_all_last_total_equals_dataset_row_count(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
    )

    totals = result["All"]["growth_trend"]["total_organizations"]

    assert totals[-1]["count"] == len(organizations)


# -------------------------------------------------------------------
# Collaborators are per-period, not cumulative
# -------------------------------------------------------------------


def test_collaborators_are_per_period_not_cumulative(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
    )

    collaborators = result["7D"]["growth_trend"]["collaborators"]

    assert collaborators == [
        {
            "period": "2026-09-16",
            "count": 1,
        },
        {
            "period": "2026-09-18",
            "count": 1,
        },
        {
            "period": "2026-09-20",
            "count": 1,
        },
        {
            "period": "2026-09-21",
            "count": 0,
        },
        {
            "period": "2026-09-22",
            "count": 1,
        },
    ]


def test_growth_series_share_same_periods(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
    )

    totals = result["7D"]["growth_trend"]["total_organizations"]

    collaborators = result["7D"]["growth_trend"]["collaborators"]

    total_periods = [item["period"] for item in totals]

    collaborator_periods = [item["period"] for item in collaborators]

    assert total_periods == collaborator_periods


# -------------------------------------------------------------------
# Day vs month grouping
# -------------------------------------------------------------------


def test_7d_and_30d_group_by_day(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
    )

    for bucket_name in [
        "7D",
        "30D",
    ]:
        periods = [
            item["period"]
            for item in result[bucket_name]["growth_trend"]["total_organizations"]
        ]

        assert periods

        assert all(len(period) == 10 for period in periods)


def test_1y_and_all_group_by_month(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
    )

    for bucket_name in [
        "1Y",
        "All",
    ]:
        periods = [
            item["period"]
            for item in result[bucket_name]["growth_trend"]["total_organizations"]
        ]

        assert periods

        assert all(len(period) == 7 for period in periods)


def test_custom_groups_by_day(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
        {
            "start_date": "2026-09-18",
            "end_date": "2026-09-22",
        },
    )

    periods = [
        item["period"]
        for item in result["Custom"]["growth_trend"]["total_organizations"]
    ]

    assert periods

    assert all(len(period) == 10 for period in periods)


# -------------------------------------------------------------------
# Sparse periods
# -------------------------------------------------------------------


def test_periods_with_no_activity_are_omitted(
    organizations,
    states,
    countries,
):
    result = build_response(
        organizations,
        states,
        countries,
        {
            "start_date": "2026-09-16",
            "end_date": "2026-09-22",
        },
    )

    periods = [
        item["period"]
        for item in result["Custom"]["growth_trend"]["total_organizations"]
    ]

    assert "2026-09-17" not in periods
    assert "2026-09-19" not in periods

    assert periods == [
        "2026-09-16",
        "2026-09-18",
        "2026-09-20",
        "2026-09-21",
        "2026-09-22",
    ]


# -------------------------------------------------------------------
# Location aggregation
# -------------------------------------------------------------------


def test_tx_and_fl_aggregate_into_one_usa_row(
    organizations,
    states,
    countries,
):
    usa_only_window = organizations[organizations["state_id"].isin([1, 2])].copy()

    locations = analytics.build_organizations_by_location(
        window_organizations=usa_only_window,
        states=states,
        countries=countries,
    )

    assert locations == [
        {
            "country": "USA",
            "count": len(usa_only_window),
        }
    ]


def test_location_never_exceeds_four_rows(
    organizations,
    states,
    countries,
):
    locations = analytics.build_organizations_by_location(
        window_organizations=organizations,
        states=states,
        countries=countries,
    )

    assert len(locations) <= 4


def test_location_has_no_other_or_percentage(
    organizations,
    states,
    countries,
):
    locations = analytics.build_organizations_by_location(
        window_organizations=organizations,
        states=states,
        countries=countries,
    )

    for row in locations:
        assert set(row.keys()) == {
            "country",
            "count",
        }

        assert row["country"] != "Other"

        assert "percentage" not in row


def test_location_is_window_scoped(
    organizations,
    states,
    countries,
):
    window = analytics.filter_by_date(
        organizations,
        pd.Timestamp("2026-09-18").date(),
        pd.Timestamp("2026-09-20").date(),
    )

    locations = analytics.build_organizations_by_location(
        window,
        states,
        countries,
    )

    assert sum(row["count"] for row in locations) == len(window)


# -------------------------------------------------------------------
# One-country states data
# -------------------------------------------------------------------


def test_one_country_states_return_one_location_row():
    states = pd.DataFrame(
        [
            {
                "state_id": 1,
                "state_name": "Texas",
                "country_id": 1,
            },
            {
                "state_id": 2,
                "state_name": "Florida",
                "country_id": 1,
            },
        ]
    )

    countries = pd.DataFrame(
        [
            {
                "country_id": 1,
                "country_code": "USA",
            }
        ]
    )

    organizations = pd.DataFrame(
        [
            {
                "org_id": 1,
                "state_id": 1,
                "city_name": "Austin",
                "is_collaborator": False,
                "created_at": pd.Timestamp(
                    "2026-09-20",
                    tz="UTC",
                ),
            },
            {
                "org_id": 2,
                "state_id": 2,
                "city_name": "Miami",
                "is_collaborator": False,
                "created_at": pd.Timestamp(
                    "2026-09-21",
                    tz="UTC",
                ),
            },
        ]
    )

    result = analytics.build_organizations_by_location(
        organizations,
        states,
        countries,
    )

    assert result == [
        {
            "country": "USA",
            "count": 2,
        }
    ]


# -------------------------------------------------------------------
# Empty organizations
# -------------------------------------------------------------------


def test_empty_organizations_does_not_crash(
    states,
    countries,
):
    empty = pd.DataFrame(
        columns=[
            "org_id",
            "state_id",
            "city_name",
            "is_collaborator",
            "created_at",
        ]
    )

    empty["created_at"] = pd.to_datetime(
        empty["created_at"],
        utc=True,
    )

    result = analytics.build_analytics_response(
        organizations=empty,
        states=states,
        countries=countries,
        today=TEST_TODAY,
    )

    for bucket_name in [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]:
        assert result[bucket_name]["growth_trend"] == {
            "total_organizations": [],
            "collaborators": [],
        }

        assert result[bucket_name]["organizations_by_location"] == []


# -------------------------------------------------------------------
# One-row organizations
# -------------------------------------------------------------------


def test_one_row_organizations_does_not_crash(
    states,
    countries,
):
    organizations = pd.DataFrame(
        [
            {
                "org_id": 1,
                "state_id": 1,
                "city_name": "Austin",
                "is_collaborator": True,
                "created_at": pd.Timestamp("2026-09-22T10:00:00Z"),
            }
        ]
    )

    result = analytics.build_analytics_response(
        organizations=organizations,
        states=states,
        countries=countries,
        today=TEST_TODAY,
    )

    assert result["All"]["growth_trend"]["total_organizations"][-1]["count"] == 1

    assert result["7D"]["organizations_by_location"] == [
        {
            "country": "USA",
            "count": 1,
        }
    ]


# -------------------------------------------------------------------
# Empty fixed window
# -------------------------------------------------------------------


def test_bucket_with_no_activity_returns_empty_arrays(
    organizations,
    states,
    countries,
):
    result = analytics.build_analytics_response(
        organizations=organizations,
        states=states,
        countries=countries,
        today=pd.Timestamp(
            "2030-01-01",
            tz="UTC",
        ),
    )

    assert result["7D"]["growth_trend"] == {
        "total_organizations": [],
        "collaborators": [],
    }

    assert result["7D"]["organizations_by_location"] == []


# -------------------------------------------------------------------
# Warm Lambda instance cache
# -------------------------------------------------------------------


def test_handler_three_calls_load_source_only_once(
    monkeypatch,
    organizations,
    states,
    countries,
):
    load_count = 0

    def fake_read_source_data():
        nonlocal load_count

        load_count += 1

        return (
            organizations,
            states,
            countries,
        )

    monkeypatch.setattr(
        analytics,
        "_read_source_data",
        fake_read_source_data,
    )

    analytics._DATA_CACHE = None

    for _ in range(3):
        response = analytics.lambda_handler(
            {"body": "{}"},
            None,
        )

        assert response["statusCode"] == 200

    assert load_count == 1


# -------------------------------------------------------------------
# Handler no-body response
# -------------------------------------------------------------------


def test_handler_no_body_returns_200_and_five_keys(
    monkeypatch,
    organizations,
    states,
    countries,
):
    monkeypatch.setattr(
        analytics,
        "load_data",
        lambda: (
            organizations,
            states,
            countries,
        ),
    )

    response = analytics.lambda_handler(
        {},
        None,
    )

    assert response["statusCode"] == 200

    body = json.loads(response["body"])

    assert list(body.keys()) == [
        "7D",
        "30D",
        "1Y",
        "All",
        "Custom",
    ]

    assert body["Custom"] == {
        "growth_trend": {
            "total_organizations": [],
            "collaborators": [],
        },
        "organizations_by_location": [],
    }


# -------------------------------------------------------------------
# Real local mock CSV integration test
# -------------------------------------------------------------------


def test_local_mock_csv_files_can_be_loaded(
    monkeypatch,
):
    mock_data_dir = Path(analytics.__file__).resolve().parent / "mock_data"

    required_files = [
        mock_data_dir / "organizations.csv",
        mock_data_dir / "states.csv",
        mock_data_dir / "countries.csv",
    ]

    missing = [str(path) for path in required_files if not path.exists()]

    if missing:
        pytest.skip("Local mock CSV files are not present: " + ", ".join(missing))

    monkeypatch.setattr(
        analytics,
        "MOCK_DATA_DIR",
        mock_data_dir,
    )

    analytics._DATA_CACHE = None

    organizations, states, countries = analytics.load_data()

    assert set(analytics.ORGANIZATION_COLUMNS).issubset(organizations.columns)

    assert set(analytics.STATE_COLUMNS).issubset(states.columns)

    assert set(analytics.COUNTRY_COLUMNS).issubset(countries.columns)

    result = analytics.build_analytics_response(
        organizations=organizations,
        states=states,
        countries=countries,
    )

    if not organizations.empty:
        all_totals = result["All"]["growth_trend"]["total_organizations"]

        assert all_totals

        assert all_totals[-1]["count"] == len(organizations)

        # Today's states.csv is expected to map all
        # states to a single country.
        if states["country_id"].nunique() == 1:
            all_locations = result["All"]["organizations_by_location"]

            assert len(all_locations) == 1
