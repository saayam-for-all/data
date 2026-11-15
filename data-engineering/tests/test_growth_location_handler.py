"""Integration tests for the Growth & Location Analytics Lambda response."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from pandas.testing import assert_frame_equal

LAMBDA_ROOT = Path(__file__).resolve().parents[2] / "data-analytics" / "lambda_functions"
sys.path.insert(0, str(LAMBDA_ROOT))

from growth_location_analytics import lambda_function as handler
from tests.growth_location_helpers import write_csvs

REFERENCE = datetime(2026, 9, 15, 18, 42, 11, tzinfo=timezone.utc)
EXPECTED_FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
MODULE_DIR = LAMBDA_ROOT / "growth_location_analytics"


def _write_csvs(directory: Path, rows: list[dict[str, object]] | None = None) -> None:
    """Write a tiny valid three-table dataset to a pytest temporary directory."""

    if rows is None:
        rows = [
            {
                "org_id": "old",
                "state_id": "IL",
                "city_name": "Chicago",
                "is_collaborator": False,
                "created_at": "2025-01-01T00:00:00Z",
            },
            {
                "org_id": "year",
                "state_id": "KA",
                "city_name": "Bengaluru",
                "is_collaborator": True,
                "created_at": "2025-10-01T12:00:00Z",
            },
            {
                "org_id": "thirty",
                "state_id": "IL",
                "city_name": "Springfield",
                "is_collaborator": False,
                "created_at": "2026-08-20T08:00:00Z",
            },
            {
                "org_id": "seven",
                "state_id": "KA",
                "city_name": "Mysuru",
                "is_collaborator": True,
                "created_at": "2026-09-10T08:00:00Z",
            },
            {
                "org_id": "today",
                "state_id": "IL",
                "city_name": "Peoria",
                "is_collaborator": False,
                "created_at": "2026-09-15T23:59:59Z",
            },
        ]

    write_csvs(
        directory,
        rows,
        states=[("IL", "Illinois", "US"), ("KA", "Karnataka", "IN")],
        countries=[("US", "USA"), ("IN", "IND")],
    )


@pytest.fixture
def invoke(tmp_path, monkeypatch):
    """Invoke the real loader, range helpers, and calculations at a fixed time."""

    _write_csvs(tmp_path)
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(handler, "_current_utc_time", lambda: REFERENCE)

    def call(event: object) -> tuple[dict[str, object], dict[str, object]]:
        response = handler.lambda_handler(event, None)
        return response, json.loads(response["body"])

    return call


def _assert_exact_payload_shape(payload: dict[str, object]) -> None:
    """Check the literal issue contract independently of production constants."""

    assert set(payload) == {"7D", "30D", "1Y", "All", "Custom"}
    for bucket in payload:
        assert set(payload[bucket]) == {"growth_trend", "organizations_by_location"}
        assert set(payload[bucket]["growth_trend"]) == {
            "total_organizations",
            "collaborators",
        }
        for series_name in ("total_organizations", "collaborators"):
            for point in payload[bucket]["growth_trend"][series_name]:
                assert set(point) == {"period", "count"}
                assert type(point["count"]) is int
        for point in payload[bucket]["organizations_by_location"]:
            assert set(point) == {"country", "count"}
            assert type(point["count"]) is int
            assert isinstance(point["country"], str)
        assert len(payload[bucket]["organizations_by_location"]) <= 4


def test_lambda_entry_point_imports_from_packaged_zip_root():
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from lambda_function import lambda_handler; assert callable(lambda_handler)",
        ],
        cwd=MODULE_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_local_runner_uses_real_handler_for_all_required_scenarios(tmp_path, monkeypatch, capsys):
    _write_csvs(tmp_path)
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(handler, "_current_utc_time", lambda: REFERENCE)
    real_handler = handler.lambda_handler
    responses = []

    def record_response(event, context):
        response = real_handler(event, context)
        responses.append(response)
        return response

    monkeypatch.setattr(handler, "lambda_handler", record_response)
    handler._run_local_samples()

    assert len(responses) == 4
    for response, (has_growth, has_location) in zip(
        responses, [(False, False), (True, False), (False, True), (True, True)]
    ):
        assert response["statusCode"] == 200
        payload = json.loads(response["body"])
        assert payload["All"]["growth_trend"]["total_organizations"][-1]["count"] == 5
        custom = payload["Custom"]
        assert bool(custom["growth_trend"]["total_organizations"]) == has_growth
        assert bool(custom["organizations_by_location"]) == has_location
    assert capsys.readouterr().out.count('"statusCode": 200') == 4


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"body": None},
        {"body": "{}"},
        {
            "start_date": None,
            "end_date": None,
            "location_start_date": None,
            "location_end_date": None,
        },
    ],
)
def test_no_body_returns_all_fixed_buckets_and_empty_custom(invoke, event):
    response, payload = invoke(event)

    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "application/json"
    assert isinstance(response["body"], str)
    assert json.loads(json.dumps(response, allow_nan=False)) == response
    _assert_exact_payload_shape(payload)
    for bucket, periods, totals, collaborators, countries in [
        ("7D", ["2026-09-10", "2026-09-15"], [4, 5], [1, 0], {"IND": 1, "USA": 1}),
        (
            "30D",
            ["2026-08-20", "2026-09-10", "2026-09-15"],
            [3, 4, 5],
            [0, 1, 0],
            {"IND": 1, "USA": 2},
        ),
        ("1Y", ["2025-10", "2026-08", "2026-09"], [2, 3, 5], [1, 0, 1], {"IND": 2, "USA": 2}),
        (
            "All",
            ["2025-01", "2025-10", "2026-08", "2026-09"],
            [1, 2, 3, 5],
            [0, 1, 0, 1],
            {"IND": 2, "USA": 3},
        ),
    ]:
        growth = payload[bucket]["growth_trend"]
        assert growth["total_organizations"] == [
            {"period": period, "count": count} for period, count in zip(periods, totals)
        ]
        assert growth["collaborators"] == [
            {"period": period, "count": count} for period, count in zip(periods, collaborators)
        ]
        assert {
            row["country"]: row["count"] for row in payload[bucket]["organizations_by_location"]
        } == countries
    assert payload["Custom"] == {
        "growth_trend": {"total_organizations": [], "collaborators": []},
        "organizations_by_location": [],
    }


def test_growth_custom_only_populates_growth_and_keeps_fixed_results(invoke):
    _, baseline = invoke({})
    _, payload = invoke(
        {"body": json.dumps({"start_date": "2026-08-20", "end_date": "2026-08-20"})}
    )

    assert payload["Custom"]["growth_trend"] == {
        "total_organizations": [{"period": "2026-08-20", "count": 3}],
        "collaborators": [{"period": "2026-08-20", "count": 0}],
    }
    assert payload["Custom"]["organizations_by_location"] == []
    assert {bucket: payload[bucket] for bucket in EXPECTED_FIXED_BUCKETS} == {
        bucket: baseline[bucket] for bucket in EXPECTED_FIXED_BUCKETS
    }


def test_location_custom_only_populates_location_and_keeps_growth_empty(invoke):
    _, payload = invoke(
        {
            "location_start_date": "2026-09-10",
            "location_end_date": "2026-09-10",
        }
    )

    assert payload["Custom"]["growth_trend"] == {
        "total_organizations": [],
        "collaborators": [],
    }
    assert payload["Custom"]["organizations_by_location"] == [{"country": "IND", "count": 1}]


def test_both_custom_pairs_use_different_ranges_without_early_return(invoke):
    _, payload = invoke(
        {
            "body": json.dumps(
                {
                    "start_date": "2026-08-20",
                    "end_date": "2026-08-20",
                    "location_start_date": "2026-09-15",
                    "location_end_date": "2026-09-15",
                }
            )
        }
    )

    assert payload["Custom"]["growth_trend"]["total_organizations"] == [
        {"period": "2026-08-20", "count": 3}
    ]
    assert payload["Custom"]["organizations_by_location"] == [{"country": "USA", "count": 1}]
    assert all(bucket in payload for bucket in EXPECTED_FIXED_BUCKETS)


@pytest.mark.parametrize(
    "request_data",
    [
        {"start_date": "09/10/2026", "end_date": "2026-09-10"},
        {"start_date": "2026-09-11", "end_date": "2026-09-10"},
        {"location_start_date": "09/10/2026", "location_end_date": "2026-09-10"},
        {"location_start_date": "2026-09-11", "location_end_date": "2026-09-10"},
        {"start_date": "2026-09-10"},
        {"location_end_date": "2026-09-10"},
        {"start_date": "", "end_date": None},
    ],
)
def test_invalid_custom_dates_fail_whole_request(invoke, request_data):
    response, payload = invoke(request_data)

    assert response["statusCode"] == 400
    assert set(payload) == {"error"}
    assert payload["error"]


@pytest.mark.parametrize("invalid_chart", ["growth", "location"])
def test_one_invalid_chart_range_prevents_partial_success(invoke, invalid_chart):
    event = {
        "start_date": "2026-08-20",
        "end_date": "2026-08-20",
        "location_start_date": "2026-09-10",
        "location_end_date": "2026-09-10",
    }
    event["start_date" if invalid_chart == "growth" else "location_start_date"] = "2026-09-12"

    response, payload = invoke(event)

    assert response["statusCode"] == 400
    assert set(payload) == {"error"}
    assert payload["error"]


@pytest.mark.parametrize("event", [{"body": "{"}, {"body": "[]"}, {"body": 42}, None])
def test_malformed_json_and_unsupported_event_forms_are_400(invoke, event):
    response, payload = invoke(event)

    assert response["statusCode"] == 400
    assert set(payload) == {"error"}
    assert payload["error"]


def test_unknown_fields_are_ignored(invoke):
    _, baseline = invoke({})
    _, payload = invoke({"time_filter": "7D", "unexpected": [1, 2, 3]})

    assert payload == baseline


def test_shared_input_tables_are_unchanged_across_all_bucket_calculations(tmp_path, monkeypatch):
    _write_csvs(tmp_path)
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    tables = handler.load_local_data()
    originals = [frame.copy(deep=True) for frame in tables.__dict__.values()]
    ranges = handler.resolve_date_ranges(
        start_date="2026-08-20",
        end_date="2026-08-20",
        location_start_date="2026-09-10",
        location_end_date="2026-09-10",
        reference_time=REFERENCE,
    )

    handler.assemble_analytics(tables, ranges)

    for frame, original in zip(tables.__dict__.values(), originals):
        assert_frame_equal(frame, original)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [
            {
                "org_id": "one",
                "state_id": "IL",
                "city_name": "Chicago",
                "is_collaborator": True,
                "created_at": "2026-09-15T12:00:00Z",
            }
        ],
        [
            {
                "org_id": "inactive",
                "state_id": "IL",
                "city_name": "Chicago",
                "is_collaborator": False,
                "created_at": "2020-01-01T00:00:00Z",
            }
        ],
    ],
    ids=["empty", "single-row", "inactive-fixed-windows"],
)
def test_empty_single_row_and_inactive_datasets(tmp_path, monkeypatch, rows):
    _write_csvs(tmp_path, rows)
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(handler, "_current_utc_time", lambda: REFERENCE)

    response = handler.lambda_handler({}, None)
    payload = json.loads(response["body"])

    assert response["statusCode"] == 200
    _assert_exact_payload_shape(payload)
    if not rows or rows[0]["org_id"] == "inactive":
        assert payload["7D"]["growth_trend"]["total_organizations"] == []
        assert payload["7D"]["organizations_by_location"] == []
    if rows:
        assert payload["All"]["growth_trend"]["total_organizations"][-1]["count"] == 1


def test_server_error_returns_safe_500(monkeypatch):
    monkeypatch.setattr(
        handler,
        "load_local_data",
        Mock(side_effect=RuntimeError("secret row at /private/data.csv")),
    )

    response = handler.lambda_handler({}, None)

    assert response["statusCode"] == 500
    assert json.loads(response["body"]) == {"error": "Internal server error"}
