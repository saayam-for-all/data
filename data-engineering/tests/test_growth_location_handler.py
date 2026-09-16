"""Integration tests for the Growth & Location Analytics Lambda response."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.growth_location_analytics import ALL_BUCKETS, FIXED_BUCKETS, LocalDataTables
from src.growth_location_analytics import lambda_function as handler


REFERENCE = datetime(2026, 9, 15, 18, 42, 11, tzinfo=timezone.utc)
MODULE_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "growth_location_analytics"
)


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

    pd.DataFrame(
        rows,
        columns=[
            "org_id",
            "state_id",
            "city_name",
            "is_collaborator",
            "created_at",
        ],
    ).to_csv(directory / "organizations.csv", index=False)
    pd.DataFrame(
        [
            {"state_id": "IL", "state_name": "Illinois", "country_id": "US"},
            {"state_id": "KA", "state_name": "Karnataka", "country_id": "IN"},
        ]
    ).to_csv(directory / "states.csv", index=False)
    pd.DataFrame(
        [
            {"country_id": "US", "country_code": "USA"},
            {"country_id": "IN", "country_code": "IND"},
        ]
    ).to_csv(directory / "countries.csv", index=False)


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
    assert tuple(payload) == ALL_BUCKETS
    for bucket in ALL_BUCKETS:
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


@pytest.mark.parametrize("event", [{}, {"body": None}, {"body": "{}"}])
def test_no_body_returns_all_fixed_buckets_and_empty_custom(invoke, event):
    response, payload = invoke(event)

    assert response["statusCode"] == 200
    _assert_exact_payload_shape(payload)
    assert payload["7D"]["growth_trend"]["total_organizations"][-1]["count"] == 5
    assert payload["7D"]["organizations_by_location"] == [
        {"country": "IND", "count": 1},
        {"country": "USA", "count": 1},
    ]
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
    assert {bucket: payload[bucket] for bucket in FIXED_BUCKETS} == {
        bucket: baseline[bucket] for bucket in FIXED_BUCKETS
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
    assert payload["Custom"]["organizations_by_location"] == [
        {"country": "IND", "count": 1}
    ]


def test_explicit_null_pairs_leave_custom_empty(invoke):
    _, payload = invoke(
        {
            "start_date": None,
            "end_date": None,
            "location_start_date": None,
            "location_end_date": None,
        }
    )

    assert payload["Custom"] == {
        "growth_trend": {"total_organizations": [], "collaborators": []},
        "organizations_by_location": [],
    }


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
    assert payload["Custom"]["organizations_by_location"] == [
        {"country": "USA", "count": 1}
    ]
    assert all(bucket in payload for bucket in FIXED_BUCKETS)


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
def test_invalid_custom_dates_fail_whole_request_before_loading(
    monkeypatch, request_data
):
    load = Mock(side_effect=AssertionError("loader must not run"))
    monkeypatch.setattr(handler, "load_local_data", load)

    response = handler.lambda_handler(request_data, None)

    assert response["statusCode"] == 400
    assert set(json.loads(response["body"])) == {"error"}
    load.assert_not_called()


def test_one_invalid_chart_range_prevents_partial_success(monkeypatch):
    monkeypatch.setattr(handler, "load_local_data", Mock())
    event = {
        "start_date": "2026-08-20",
        "end_date": "2026-08-20",
        "location_start_date": "2026-09-12",
        "location_end_date": "2026-09-10",
    }

    response = handler.lambda_handler(event, None)

    assert response["statusCode"] == 400
    assert json.loads(response["body"]) == {
        "error": "location_start_date must be on or before location_end_date"
    }
    handler.load_local_data.assert_not_called()


@pytest.mark.parametrize(
    ("event", "message"),
    [
        ({"body": "{"}, "Request body must contain valid JSON"),
        ({"body": "[]"}, "Request body must decode to a JSON object"),
        ({"body": 42}, "Request body must be a JSON object encoded as a string"),
        ({"body": {}}, "Request body must be a JSON object encoded as a string"),
        (None, "Request event must be a JSON object"),
    ],
)
def test_malformed_json_and_unsupported_event_forms_are_400(
    monkeypatch, event, message
):
    load = Mock()
    monkeypatch.setattr(handler, "load_local_data", load)

    response = handler.lambda_handler(event, None)

    assert response["statusCode"] == 400
    assert json.loads(response["body"]) == {"error": message}
    load.assert_not_called()


def test_unknown_fields_are_ignored(invoke):
    _, baseline = invoke({})
    _, payload = invoke({"time_filter": "7D", "unexpected": [1, 2, 3]})

    assert payload == baseline


def test_loader_runs_once_per_invocation(tmp_path, monkeypatch):
    _write_csvs(tmp_path)
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    current_time = Mock(return_value=REFERENCE)
    monkeypatch.setattr(handler, "_current_utc_time", current_time)
    real_loader = handler.load_local_data
    tracked_loader = Mock(side_effect=real_loader)
    monkeypatch.setattr(handler, "load_local_data", tracked_loader)

    response = handler.lambda_handler({}, None)

    assert response["statusCode"] == 200
    tracked_loader.assert_called_once_with()
    current_time.assert_called_once_with()


def test_fixed_charts_receive_the_identical_window_objects(monkeypatch):
    empty_organizations = pd.DataFrame(
        columns=["org_id", "state_id", "city_name", "is_collaborator", "created_at"]
    )
    tables = LocalDataTables(
        organizations=empty_organizations,
        states=pd.DataFrame(columns=["state_id", "state_name", "country_id"]),
        countries=pd.DataFrame(columns=["country_id", "country_code"]),
    )
    growth_windows: dict[str, object] = {}
    location_windows: list[object] = []

    def growth(_organizations, bucket, window):
        growth_windows[bucket] = window
        return {"total_organizations": [], "collaborators": []}

    def location(_organizations, _states, _countries, window):
        location_windows.append(window)
        return []

    monkeypatch.setattr(handler, "calculate_organization_growth", growth)
    monkeypatch.setattr(handler, "calculate_country_distribution", location)
    ranges = handler.resolve_date_ranges(reference_time=REFERENCE)

    handler.assemble_analytics(tables, ranges)

    for index, bucket in enumerate(FIXED_BUCKETS):
        assert growth_windows[bucket] is location_windows[index]


def test_shared_input_tables_are_unchanged_across_all_bucket_calculations(
    tmp_path, monkeypatch
):
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


def test_actual_transport_response_is_json_serializable_without_double_encoding(invoke):
    response, payload = invoke({})

    round_trip = json.loads(json.dumps(response, allow_nan=False))

    assert round_trip == response
    assert isinstance(response["body"], str)
    assert json.loads(response["body"]) == payload
    assert response["headers"] == {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
    }


@pytest.mark.parametrize(
    "failure_target", ["load_local_data", "calculate_organization_growth"]
)
def test_loader_and_calculation_errors_return_safe_500(monkeypatch, failure_target):
    monkeypatch.setattr(handler, "_current_utc_time", lambda: REFERENCE)
    if failure_target == "load_local_data":
        monkeypatch.setattr(
            handler,
            failure_target,
            Mock(side_effect=RuntimeError("secret row at /private/data.csv")),
        )
    else:
        tables = Mock()
        monkeypatch.setattr(handler, "load_local_data", Mock(return_value=tables))
        monkeypatch.setattr(
            handler,
            failure_target,
            Mock(side_effect=RuntimeError("secret row at /private/data.csv")),
        )

    response = handler.lambda_handler({}, None)

    assert response["statusCode"] == 500
    assert json.loads(response["body"]) == {"error": "Internal server error"}
    assert "/private" not in response["body"]
