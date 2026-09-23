"""Local CSV tests for issue #376's standalone analytics Lambda."""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data-analytics" / "lambda_functions"))
import size_contribution_analytics as analytics


def write_data(directory, organizations):
    """Create only temporary CSV fixtures, never repository datasets."""
    pd.DataFrame(organizations).to_csv(directory / "organizations.csv", index=False)
    pd.DataFrame(
        [
            {"state_id": "CA", "country_id": "1"},
            {"state_id": "NY", "country_id": "1"},
            {"state_id": "ON", "country_id": "2"},
        ]
    ).to_csv(directory / "states.csv", index=False)
    pd.DataFrame(
        [
            {"country_id": "1", "country_code": "USA", "country_name": "United States"},
            {"country_id": "2", "country_code": "CAN", "country_name": "Canada"},
        ]
    ).to_csv(directory / "countries.csv", index=False)


def call(event):
    """Unwrap a Lambda response for assertions."""
    response = analytics.lambda_handler(event, None)
    return response["statusCode"], json.loads(response["body"])


@pytest.fixture
def sample_data(tmp_path, monkeypatch):
    """Provide organizations with overlapping flags and distinct country joins."""
    today = datetime.now(timezone.utc).date()
    rows = [
        {"org_id": "1", "org_size": "small", "org_type": "non_profit", "state_id": "CA",
         "created_at": str(today), "is_collaborator": True, "is_contributor": True},
        {"org_id": "2", "org_size": "medium", "org_type": "for_profit", "state_id": "NY",
         "created_at": str(today - timedelta(days=7)), "is_collaborator": False, "is_contributor": True},
        {"org_id": "3", "org_size": "large", "org_type": "non_profit", "state_id": "ON",
         "created_at": str(today - timedelta(days=8)), "is_collaborator": True, "is_contributor": False},
        {"org_id": "4", "org_size": "small", "org_type": "non_profit", "state_id": "NY",
         "created_at": f"{today - timedelta(days=30)} 23:59:59", "is_collaborator": False,
         "is_contributor": False},
        {"org_id": "5", "org_size": "small", "org_type": "non_profit", "state_id": "CA",
         "created_at": str(today - timedelta(days=31)), "is_collaborator": False, "is_contributor": False},
    ]
    write_data(tmp_path, rows)
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    return rows


def test_csv_loading_joins_and_defaults(sample_data):
    """All rows join through state and country and the default filters are ALL."""
    frame = analytics.load_mock_organizations()
    assert len(frame) == 5
    assert frame.loc[frame.org_id == 1, "country_code"].iloc[0] == "USA"
    status, body = call({})
    assert status == 200
    assert list(body) == ["7D", "30D", "1Y", "All", "Custom"]
    assert sum(row["count"] for row in body["All"]["organizations_by_size"]) == 5
    assert body["Custom"] == {"organizations_by_size": [], "collaborator_vs_contributor": []}


def test_unmatched_lookup_keys_fail_without_partial_counts(sample_data, tmp_path):
    """A broken state or country reference must not silently remove an organization."""
    write_data(tmp_path, [dict(sample_data[0], state_id="UNKNOWN")])
    status, body = call({})
    assert status == 500
    assert list(body) == ["error"]
    assert "state_id" in body["error"]

    write_data(tmp_path, [sample_data[0]])
    states = pd.read_csv(tmp_path / "states.csv")
    states.loc[states.state_id == "CA", "country_id"] = 999
    states.to_csv(tmp_path / "states.csv", index=False)
    status, body = call({"country": "USA"})
    assert status == 500
    assert list(body) == ["error"]
    assert "country_id" in body["error"]


@pytest.mark.parametrize("column,bad_value", [
    ("created_at", "not-a-date"),
    ("created_at", None),
    ("org_size", None),
    ("org_size", ""),
    ("is_collaborator", "maybe"),
    ("is_contributor", "maybe"),
    ("is_contributor", None),
])
def test_invalid_source_values_fail_without_partial_charts(
    sample_data, tmp_path, column, bad_value
):
    """Malformed source fields cannot turn into misleading analytics."""
    write_data(tmp_path, [dict(sample_data[0], **{column: bad_value})])
    today = str(datetime.now(timezone.utc).date())
    status, body = call({
        "size_start_date": today, "size_end_date": today,
        "contribution_start_date": today, "contribution_end_date": today,
    })
    assert status == 500
    assert list(body) == ["error"]
    assert column in body["error"]


@pytest.mark.parametrize("country,expected", [("USA", 4), ("united states", 4), ("CAN", 1)])
def test_country_name_and_code_filter(sample_data, country, expected):
    """Country filters use the joined country rather than state text."""
    status, body = call({"body": json.dumps({"country": country})})
    assert status == 200
    assert sum(row["count"] for row in body["All"]["organizations_by_size"]) == expected


def test_organization_type_maps_to_org_type(sample_data):
    """The public organization_type parameter filters the org_type column."""
    status, body = call({"organization_type": "for_profit", "country": "USA"})
    assert status == 200
    assert body["All"]["organizations_by_size"] == [{"size": "medium", "count": 1}]


def test_fixed_window_boundaries_and_independent_counts(sample_data):
    """Boundary dates are included and the two flags may overlap."""
    status, body = call({})
    assert status == 200
    assert sum(row["count"] for row in body["7D"]["organizations_by_size"]) == 2
    assert sum(row["count"] for row in body["30D"]["organizations_by_size"]) == 4
    assert body["7D"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 50.0},
        {"type": "Contributor", "count": 2, "percentage": 100.0},
    ]


def test_one_year_cutoff_and_future_exclusion():
    """The 1Y boundary is calendar based and fixed windows stop tonight."""
    today = date(2026, 9, 23)
    frame = pd.DataFrame({"created_at": pd.to_datetime([
        "2025-09-22", "2025-09-23 00:00:00", "2026-09-23 23:59:59", "2026-09-24",
    ], format="mixed")})
    selected = analytics.filter_by_window(frame, "1Y", today=today)
    assert len(selected) == 2
    assert list(selected.index) == [1, 2]


def test_custom_ranges_are_independent_and_end_day_is_inclusive(sample_data):
    """Each chart uses its own Custom dates, including the entire end day."""
    today = datetime.now(timezone.utc).date()
    size_day = str(today - timedelta(days=30))
    contribution_day = str(today)
    status, body = call({
        "size_start_date": size_day, "size_end_date": size_day,
        "contribution_start_date": contribution_day, "contribution_end_date": contribution_day,
    })
    assert status == 200
    assert list(body) == ["Custom"]
    assert body["Custom"]["organizations_by_size"] == [{"size": "small", "count": 1}]
    assert body["Custom"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 100.0},
        {"type": "Contributor", "count": 1, "percentage": 100.0},
    ]


@pytest.mark.parametrize("prefix,other", [("size", "contribution"), ("contribution", "size")])
def test_single_custom_pair_leaves_other_chart_empty(sample_data, prefix, other):
    """A single valid pair creates a Custom-only response."""
    today = str(datetime.now(timezone.utc).date())
    status, body = call({f"{prefix}_start_date": today, f"{prefix}_end_date": today})
    assert status == 200
    assert list(body) == ["Custom"]
    other_chart = "collaborator_vs_contributor" if other == "contribution" else "organizations_by_size"
    assert body["Custom"][other_chart] == []


@pytest.mark.parametrize("bad_values,expected", [
    ({"size_start_date": "2026-01-01"}, "size_start_date and size_end_date"),
    ({"contribution_end_date": "2026-01-01"}, "contribution_start_date and contribution_end_date"),
    ({"size_start_date": "2026-02-30", "size_end_date": "2026-03-01"}, "size_start_date"),
    ({"contribution_start_date": "2026/01/01", "contribution_end_date": "2026-02-01"}, "contribution_start_date"),
    ({"size_start_date": "2026-02-02", "size_end_date": "2026-02-01"}, "on or before"),
    ({"size_start_date": "2026-01-01", "size_end_date": "2026-01-31",
      "contribution_start_date": "bad", "contribution_end_date": "2026-01-31"}, "contribution_start_date"),
])
def test_invalid_pairs_fail_before_results(sample_data, bad_values, expected):
    """Both pairs are checked before any partial Custom data is returned."""
    status, body = call(bad_values)
    assert status == 400
    assert expected in body["error"]
    assert "Custom" not in body


def test_missing_is_contributor_is_zero(tmp_path, monkeypatch, sample_data):
    """Older CSVs without the contributor column still produce two rows."""
    rows = [{key: value for key, value in sample_data[0].items() if key != "is_contributor"}]
    write_data(tmp_path, rows)
    status, body = call({})
    assert status == 200
    assert body["All"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 100.0},
        {"type": "Contributor", "count": 0, "percentage": 0.0},
    ]


def test_all_filters_accept_surrounding_spaces(sample_data):
    """The ALL sentinel behaves as a default even when padded."""
    assert call({"country": " ALL ", "organization_type": " ALL "}) == call({})


@pytest.mark.parametrize("organization_type", ["unsupported", "non-profit", "small"])
def test_unsupported_organization_type_is_rejected(sample_data, organization_type):
    """Invalid enum values produce an error instead of misleading empty charts."""
    status, body = call({"organization_type": organization_type})
    assert status == 400
    assert "organization_type" in body["error"]
    assert "All" not in body


def test_timezone_aware_creation_date_is_filtered(sample_data, tmp_path):
    """Offsets are normalized before comparison with UTC date boundaries."""
    rows = [dict(sample_data[0], created_at="2026-01-02T00:30:00+01:00")]
    write_data(tmp_path, rows)
    status, body = call({"size_start_date": "2026-01-01", "size_end_date": "2026-01-01"})
    assert status == 200
    assert body["Custom"]["organizations_by_size"] == [{"size": "small", "count": 1}]


def test_empty_csv_and_no_matching_window(tmp_path, monkeypatch, sample_data):
    """Zero organizations and empty date windows produce empty chart arrays."""
    frame = pd.read_csv(tmp_path / "organizations.csv")
    frame.iloc[:0].to_csv(tmp_path / "organizations.csv", index=False)
    status, body = call({})
    assert status == 200
    assert body["All"] == {"organizations_by_size": [], "collaborator_vs_contributor": []}

    write_data(tmp_path, [sample_data[0]])
    status, body = call({"size_start_date": "2020-01-01", "size_end_date": "2020-01-01"})
    assert status == 200
    assert body["Custom"] == {"organizations_by_size": [], "collaborator_vs_contributor": []}


def test_mock_mode_needs_no_psycopg2(sample_data, monkeypatch):
    """Optional driver absence cannot affect the CSV path."""
    monkeypatch.setattr(analytics, "psycopg2", None)
    assert call({})[0] == 200


def test_database_loader_uses_state_and_country_joins(monkeypatch):
    """The optional database path reads the same joined columns and closes it."""
    class FakeCursor:
        description = [(name,) for name in (
            "org_id", "org_size", "org_type", "created_at", "is_collaborator",
            "is_contributor", "country_code", "country_name",
        )]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, params=None):
            self.query = query
            self.metadata_query = params is not None

        def fetchall(self):
            if self.metadata_query:
                return [
                    ("organizations", name) for name in (
                        "org_id", "org_size", "org_type", "state_id", "created_at",
                        "is_collaborator", "is_contributor",
                    )
                ] + [
                    ("states", name) for name in ("state_id", "country_id")
                ] + [
                    ("countries", name) for name in ("country_id", "country_code", "country_name")
                ]
            return [("1", "small", "non_profit", "2026-01-01", True, False, "USA", "United States")]

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()
            self.closed = False

        def cursor(self):
            return self.fake_cursor

        def close(self):
            self.closed = True

    connection = FakeConnection()

    class FakeDriver:
        def connect(self, **_kwargs):
            return connection

    monkeypatch.setattr(analytics, "psycopg2", FakeDriver())
    frame = analytics.load_database_organizations()
    assert len(frame) == 1
    assert frame["country_code"].iloc[0] == "USA"
    assert "JOIN virginia_dev_saayam_rdbms.states s ON o.state_id = s.state_id" in connection.fake_cursor.query
    assert "JOIN virginia_dev_saayam_rdbms.countries c ON s.country_id = c.country_id" in connection.fake_cursor.query
    assert connection.closed


def test_database_loader_handles_singular_tables_and_missing_contributor(monkeypatch):
    """Documented singular lookup names and size/state_code aliases work."""
    class FakeCursor:
        description = [(name,) for name in (
            "org_id", "org_size", "org_type", "created_at", "is_collaborator",
            "is_contributor", "country_code", "country_name",
        )]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, params=None):
            self.query = query
            self.metadata_query = params is not None

        def fetchall(self):
            if self.metadata_query:
                return [
                    ("organizations", name) for name in (
                        "org_id", "size", "org_type", "state_code", "created_at", "is_collaborator",
                    )
                ] + [
                    ("state", name) for name in ("state_code", "country_id")
                ] + [
                    ("country", name) for name in ("country_id", "country_code", "country_name")
                ]
            return [("1", "small", "non_profit", "2026-01-01", True, False, "USA", "United States")]

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()

        def cursor(self):
            return self.fake_cursor

        def close(self):
            pass

    connection = FakeConnection()

    class FakeDriver:
        def connect(self, **_kwargs):
            return connection

    monkeypatch.setattr(analytics, "psycopg2", FakeDriver())
    frame = analytics.load_database_organizations()
    assert "o.size AS org_size" in connection.fake_cursor.query
    assert "FALSE AS is_contributor" in connection.fake_cursor.query
    assert "JOIN virginia_dev_saayam_rdbms.state s ON o.state_code = s.state_code" in connection.fake_cursor.query
    assert "JOIN virginia_dev_saayam_rdbms.country c ON s.country_id = c.country_id" in connection.fake_cursor.query
    assert not frame["is_contributor"].iloc[0]
