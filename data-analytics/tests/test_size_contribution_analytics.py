"""Contract and regression tests for issue #376; no live services are used."""

import builtins
import importlib.util
import json
import runpy
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "lambda_functions"
    / "size_contribution_analytics.py"
)
SPEC = importlib.util.spec_from_file_location(
    "size_contribution_analytics", MODULE_PATH
)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)
TODAY = date(2026, 10, 4)


@pytest.fixture
def tables():
    """Include exact boundaries, overlapping flags, legacy labels and countries."""
    organizations = pd.DataFrame(
        [
            ("a", "Small", "TRUE", "TRUE", "Non-Profit", "10", "2026-10-04T23:59:59Z"),
            ("b", "Small", "TRUE", "FALSE", "non_profit", "10", "2026-09-28"),
            ("c", "large", "FALSE", "TRUE", "For-profit", "20", "2026-09-27"),
            ("d", "large", "FALSE", "FALSE", "for_profit", "20", "2026-09-05"),
            ("e", "Medium", "TRUE", "TRUE", "Non Profit", "10", "2026-09-04"),
            ("f", "Medium", "FALSE", "FALSE", "non_profit", "10", "2025-10-31"),
            ("g", "unusual-size", "FALSE", "FALSE", "non_profit", "10", "2025-11-01"),
            ("h", "future", "FALSE", "FALSE", "non_profit", "10", "2026-10-05"),
        ],
        columns=[
            "org_id",
            "org_size",
            "is_collaborator",
            "is_contributor",
            "org_type",
            "state_id",
            "created_at",
        ],
    )
    states = pd.DataFrame({"state_id": ["10", "20"], "country_id": ["1", "2"]})
    countries = pd.DataFrame(
        {
            "country_id": ["1", "2"],
            "country_code": ["USA", "IND"],
            "country_name": ["United States", "India"],
        }
    )
    return organizations, states, countries


@pytest.fixture
def csv_dir(tables, tmp_path, monkeypatch):
    """Write ephemeral fixtures; no mock CSVs enter the repository."""
    for frame, name in zip(tables, ("organizations", "states", "countries")):
        frame.to_csv(tmp_path / f"{name}.csv", index=False)
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 4, 12, tzinfo=timezone.utc)

    monkeypatch.setattr(api, "datetime", Clock)
    return tmp_path


def invoke(event=None):
    """Decode the API Gateway response and return status plus body."""
    result = api.lambda_handler({} if event is None else event, None)
    assert result["headers"]["Content-Type"] == "application/json"
    return result["statusCode"], json.loads(result["body"])


def total(bucket):
    """Get the organization total represented by the size chart."""
    return sum(row["count"] for row in bucket["organizations_by_size"])


def test_fixed_contract_and_exact_counts(csv_dir):
    status, body = invoke()
    assert status == 200
    assert list(body) == ["7D", "30D", "1Y", "All", "Custom"]
    assert [total(body[key]) for key in ("7D", "30D", "1Y", "All")] == [2, 4, 6, 8]
    for bucket in body.values():
        assert set(bucket) == set(api.CHARTS)
    assert body["Custom"] == {key: [] for key in api.CHARTS}
    assert body["7D"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 2, "percentage": 100.0},
        {"type": "Contributor", "count": 1, "percentage": 50.0},
    ]
    assert body["All"]["collaborator_vs_contributor"][0]["percentage"] == 37.5
    assert {r["size"] for r in body["All"]["organizations_by_size"]} == {
        "Small",
        "large",
        "Medium",
        "unusual-size",
        "future",
    }


@pytest.mark.parametrize(
    "country,expected",
    [("USA", 6), ("united states", 6), (" IND ", 2), ("unknown", 0), ("ALL", 8)],
)
def test_country_filters(csv_dir, country, expected):
    status, body = invoke({"country": country})
    assert status == 200
    assert total(body["All"]) == expected


@pytest.mark.parametrize(
    "org_type,expected",
    [
        ("non_profit", 6),
        ("Non-Profit", 6),
        ("Non Profit", 6),
        ("for_profit", 2),
        ("all", 8),
    ],
)
def test_type_normalization(csv_dir, org_type, expected):
    status, body = invoke({"organization_type": org_type})
    assert status == 200
    assert total(body["All"]) == expected


@pytest.mark.parametrize("prefix", ["size", "contribution"])
def test_single_custom_range(csv_dir, prefix):
    status, body = invoke(
        {f"{prefix}_start_date": "2026-10-04", f"{prefix}_end_date": "2026-10-04"}
    )
    assert status == 200
    assert list(body) == ["Custom"]
    populated = api.CHARTS[0 if prefix == "size" else 1]
    empty = api.CHARTS[1 if prefix == "size" else 0]
    assert body["Custom"][populated]
    assert body["Custom"][empty] == []


def test_both_custom_ranges_are_independent_and_filtered(csv_dir):
    event = {
        "size_start_date": "2026-09-27",
        "size_end_date": "2026-09-28",
        "contribution_start_date": "2026-10-04",
        "contribution_end_date": "2026-10-04",
    }
    status, body = invoke(event)
    assert status == 200 and list(body) == ["Custom"]
    assert total(body["Custom"]) == 2
    assert [r["percentage"] for r in body["Custom"][api.CHARTS[1]]] == [100.0, 100.0]
    for filters in (
        {"country": "USA"},
        {"organization_type": "non_profit"},
        {"country": "USA", "organization_type": "non_profit"},
    ):
        status, body = invoke({**event, **filters})
        assert status == 200 and total(body["Custom"]) == 1
        assert [r["count"] for r in body["Custom"][api.CHARTS[1]]] == [1, 1]


def test_custom_skips_fixed_windows(csv_dir, monkeypatch):
    def fail(_):
        raise AssertionError("Fixed windows must not be evaluated")

    monkeypatch.setattr(api, "fixed_windows", fail)
    assert invoke({"size_start_date": "2020-01-01", "size_end_date": "2020-01-02"}) == (
        200,
        {"Custom": {key: [] for key in api.CHARTS}},
    )


@pytest.mark.parametrize("prefix", ["size", "contribution"])
@pytest.mark.parametrize(
    "start,end",
    [
        (None, "2026-01-01"),
        ("2026-01-01", None),
        ("", ""),
        (None, None),
        ("2026-02-30", "2026-03-01"),
        ("2026-1-1", "2026-01-02"),
        ("20260101", "2026-01-02"),
        ("2026-01-03", "2026-01-02"),
        (12, "2026-01-02"),
        ([], {}),
        ("2026-01-01T00:00:00", "2026-01-02"),
    ],
)
def test_invalid_ranges_rejected_before_loading(monkeypatch, prefix, start, end):
    def fail():
        pytest.fail("Invalid request accessed the data source")

    monkeypatch.setattr(api, "load_mock_tables", fail)
    monkeypatch.setattr(api, "load_postgres_tables", fail)
    status, body = invoke({f"{prefix}_start_date": start, f"{prefix}_end_date": end})
    assert status == 400 and body["error"]


@pytest.mark.parametrize(
    "event",
    [
        {"size_start_date": "2026-01-01"},
        {"contribution_end_date": "2026-01-01"},
        {"country": []},
        {"country": ""},
        {"organization_type": "invalid"},
        {"organization_type": None},
        {"body": "{bad json"},
        {"body": "[]"},
        {"body": 42},
        [1],
        {"body": "null"},
        {
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-01-02",
            "contribution_start_date": "bad",
        },
    ],
)
def test_invalid_requests(event):
    status, body = invoke(event)
    assert status == 400 and "error" in body


@pytest.mark.parametrize(
    "event", [None, {}, {"body": None}, {"body": ""}, {"body": {}}, {"body": "{}"}]
)
def test_empty_request_forms(csv_dir, event):
    result = api.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert total(json.loads(result["body"])["All"]) == 8


@pytest.mark.parametrize("as_string", [False, True])
def test_gateway_filters(csv_dir, as_string):
    body = {"country": "IND"}
    status, payload = invoke({"body": json.dumps(body) if as_string else body})
    assert status == 200 and total(payload["All"]) == 2


@pytest.mark.parametrize("row_count", [0, 1])
def test_empty_and_single_row_csv(csv_dir, tables, row_count):
    tables[0].iloc[:row_count].to_csv(csv_dir / "organizations.csv", index=False)
    status, body = invoke()
    assert status == 200 and total(body["All"]) == row_count
    if row_count == 0:
        assert all(
            bucket == {key: [] for key in api.CHARTS} for bucket in body.values()
        )


def test_zero_byte_csv(csv_dir):
    (csv_dir / "organizations.csv").write_text("")
    status, body = invoke()
    assert status == 200 and total(body["All"]) == 0


def test_missing_contributor(csv_dir, tables):
    tables[0].drop(columns="is_contributor").to_csv(
        csv_dir / "organizations.csv", index=False
    )
    status, body = invoke()
    assert status == 200
    assert body["All"][api.CHARTS[1]][1] == {
        "type": "Contributor",
        "count": 0,
        "percentage": 0.0,
    }


@pytest.mark.parametrize("drop_column", ["country_name", "country_code"])
def test_country_lookup_accepts_either_field(csv_dir, tables, drop_column):
    tables[2].drop(columns=drop_column).to_csv(csv_dir / "countries.csv", index=False)
    country = "USA" if drop_column == "country_name" else "United States"
    assert total(invoke({"country": country})[1]["All"]) == 6


def test_singular_lookup_names(csv_dir):
    (csv_dir / "states.csv").rename(csv_dir / "state.csv")
    (csv_dir / "countries.csv").rename(csv_dir / "country.csv")
    assert invoke()[0] == 200


def test_unmatched_geography_is_not_invented(csv_dir, tables):
    tables[1]["country_id"] = "missing"
    tables[1].to_csv(csv_dir / "states.csv", index=False)
    assert total(invoke()[1]["All"]) == 8
    assert total(invoke({"country": "USA"})[1]["All"]) == 0


@pytest.mark.parametrize(
    "problem",
    [
        "duplicate_org",
        "duplicate_state",
        "duplicate_country",
        "missing_org_id",
        "bad_date",
        "missing_size",
        "bad_bool",
        "missing_column",
        "no_country_field",
    ],
)
def test_corrupt_source_is_server_error(csv_dir, tables, problem):
    orgs, states, countries = tables
    if problem.startswith("duplicate"):
        index = {"duplicate_org": 0, "duplicate_state": 1, "duplicate_country": 2}[
            problem
        ]
        filename = ("organizations", "states", "countries")[index]
        pd.concat([tables[index], tables[index].iloc[:1]]).to_csv(
            csv_dir / f"{filename}.csv", index=False
        )
    elif problem == "no_country_field":
        countries[["country_id"]].to_csv(csv_dir / "countries.csv", index=False)
    else:
        if problem == "missing_column":
            orgs = orgs.drop(columns="state_id")
        else:
            column, value = {
                "missing_org_id": ("org_id", None),
                "bad_date": ("created_at", "not a date"),
                "missing_size": ("org_size", ""),
                "bad_bool": ("is_collaborator", "maybe"),
            }[problem]
            orgs.loc[0, column] = value
        orgs.to_csv(csv_dir / "organizations.csv", index=False)
    status, body = invoke()
    assert status == 500
    assert str(csv_dir) not in body["error"]


def test_configuration_and_missing_files(csv_dir, monkeypatch):
    monkeypatch.delenv("MOCK_DATA_DIR")
    assert invoke()[0] == 500
    monkeypatch.setenv("MOCK_DATA_DIR", str(csv_dir))
    (csv_dir / "states.csv").write_text("")
    assert invoke()[0] == 500
    (csv_dir / "states.csv").unlink()
    assert invoke()[0] == 500
    monkeypatch.setenv("USE_MOCK_DATA", "typo")
    assert invoke()[0] == 500


def test_calendar_months_and_leap_year():
    assert api.fixed_windows(TODAY)["1Y"] == (date(2025, 11, 1), TODAY)
    assert api.fixed_windows(date(2024, 2, 29))["1Y"][0] == date(2023, 3, 1)
    for key, days in (("7D", 7), ("30D", 30)):
        start, end = api.fixed_windows(TODAY)[key]
        assert (end - start).days + 1 == days


def test_utc_boundary_and_full_custom_end_day(tables):
    tables[0].loc[0, "created_at"] = "2026-10-05T00:30:00+02:00"
    frame = api.prepare_data(*tables)
    selected = api.window(frame, (TODAY, TODAY))
    assert selected["org_id"].tolist() == ["a"]
    assert len(api.window(frame, (date.min, date.max))) == 8


@pytest.mark.parametrize(
    "flags,counts", [([True, False, None, "TRUE", "false", 1, 0, "yes"], 4)]
)
def test_boolean_representations(flags, counts):
    assert int(api.boolean_flags(pd.Series(flags)).sum()) == counts


class FakeCursor:
    """Exercise database loading and SQL selection without a live database."""

    def __init__(self, tables, contributor=True, failure=False):
        self.tables = tables
        self.contributor = contributor
        self.failure = failure
        self.queries = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if self.failure:
            raise RuntimeError("database unavailable")
        if "information_schema" in query:
            self.rows = [
                (c,)
                for c in self.tables[0].columns
                if self.contributor or c != "is_contributor"
            ]
            return
        index = (
            0
            if query.endswith(".organizations")
            else 1 if query.endswith(".state") else 2
        )
        frame = self.tables[index].copy()
        if index == 0 and not self.contributor:
            assert "FALSE AS is_contributor" in query
            frame["is_contributor"] = False
        self.description = [(c,) for c in frame.columns]
        self.rows = list(frame.itertuples(index=False, name=None))

    def fetchall(self):
        return self.rows


class FakeConnection:
    """Track resource cleanup."""

    def __init__(self, cursor):
        self.test_cursor = cursor
        self.closed = False

    def cursor(self):
        return self.test_cursor

    def close(self):
        self.closed = True


@pytest.fixture
def db_setup(monkeypatch, tables):
    for key in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        monkeypatch.setenv(key, "test-only")
    monkeypatch.delenv("DB_SCHEMA", raising=False)
    cursor = FakeCursor(tables)
    connection = FakeConnection(cursor)
    monkeypatch.setattr(
        api, "psycopg2", SimpleNamespace(connect=lambda **kwargs: connection)
    )
    return cursor, connection


def test_database_and_csv_response_parity(csv_dir, db_setup, monkeypatch):
    expected = invoke({"country": "USA", "organization_type": "non_profit"})
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    assert invoke({"country": "USA", "organization_type": "non_profit"}) == expected
    cursor, connection = db_setup
    assert connection.closed and cursor.closed
    assert cursor.queries[0][1] == ("virginia_dev_saayam_rdbms", "organizations")
    assert len(cursor.queries) == 4


def test_database_missing_contributor(csv_dir, db_setup, monkeypatch):
    cursor, connection = db_setup
    cursor.contributor = False
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    status, body = invoke()
    assert status == 200 and body["All"][api.CHARTS[1]][1]["count"] == 0
    assert connection.closed


def test_database_failure_closes_resources(csv_dir, db_setup, monkeypatch):
    cursor, connection = db_setup
    cursor.failure = True
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    assert invoke()[0] == 500
    assert cursor.closed and connection.closed


def test_database_configuration_errors(csv_dir, db_setup, monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.setenv("DB_SCHEMA", "public; DROP TABLE organizations")
    assert invoke()[0] == 500
    monkeypatch.delenv("DB_SCHEMA")
    monkeypatch.delenv("DB_HOST")
    assert invoke()[0] == 500
    monkeypatch.setattr(api, "psycopg2", None)
    assert invoke()[0] == 500


def test_optional_driver_and_sample_runner(csv_dir, monkeypatch, capsys):
    original = builtins.__import__

    def without_driver(name, *args, **kwargs):
        if name == "psycopg2":
            raise ImportError("deliberately unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_driver)
    runpy.run_path(str(MODULE_PATH), run_name="__main__")
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 6
    assert all(row["statusCode"] == 200 for row in rows)
