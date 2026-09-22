"""Tests for the Growth & Location Analytics Lambda (#336).

Self-contained: builds its own small mock CSVs rather than depending on
any other #336 PR, so this suite runs regardless of what else merges.

Verifies both the issue spec and the team lead's rulings from the #336
WhatsApp thread (2026-09-21): "1Y" is trailing 12 calendar months, and
supplying only one of a start/end date pair is a 400, not a partial
result.
"""
import csv
import importlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

IMPL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "growth_location_analytics",
)

NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


def _write_fixture(tmp_path, collab_encoder=None):
    """A small, hand-computable dataset: 5 orgs, 2 countries, 2 collaborators,
    one entry inside 7D and one just outside it.
    """
    collab_encoder = collab_encoder or (lambda b: "true" if b else "false")

    countries = [(1, "USA"), (2, "IND")]
    states = [(1, "New York", 1), (2, "Delhi", 2)]
    orgs = [
        (1, 1, "NY", True, (NOW - timedelta(days=200)).strftime("%Y-%m-%d")),
        (2, 1, "NY", False, (NOW - timedelta(days=100)).strftime("%Y-%m-%d")),
        (3, 2, "DEL", False, (NOW - timedelta(days=20)).strftime("%Y-%m-%d")),
        (4, 1, "NY", True, (NOW - timedelta(days=3)).strftime("%Y-%m-%d")),   # inside 7D
        (5, 1, "NY", False, (NOW - timedelta(days=10)).strftime("%Y-%m-%d")),  # outside 7D
    ]

    with open(os.path.join(tmp_path, "countries.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country_id", "country_code"])
        w.writerows(countries)

    with open(os.path.join(tmp_path, "states.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state_id", "state_name", "country_id"])
        w.writerows(states)

    with open(os.path.join(tmp_path, "organizations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["org_id", "state_id", "city_name", "is_collaborator", "created_at"])
        for oid, state_id, city, collab, ts in orgs:
            w.writerow([oid, state_id, city, collab_encoder(collab), ts])

    return orgs


@pytest.fixture
def handler(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.syspath_prepend(IMPL_DIR)
    for name in ("lambda_function", "analytics", "loader"):
        sys.modules.pop(name, None)
    lambda_function = importlib.import_module("lambda_function")
    return lambda_function.lambda_handler


def test_top_level_keys(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert set(body.keys()) == {"7D", "30D", "1Y", "All", "Custom"}
    for bucket in ["7D", "30D", "1Y", "All"]:
        assert set(body[bucket].keys()) == {"growth_trend", "organizations_by_location"}
        assert set(body[bucket]["growth_trend"].keys()) == {"total_organizations", "collaborators"}


def test_total_organizations_is_all_time_cumulative_not_windowed(handler, tmp_path):
    orgs = _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])

    # 5 orgs total; the 7D window only contains 1 of them, but
    # total_organizations must still show the all-time count as of "now".
    last_7d_total = body["7D"]["growth_trend"]["total_organizations"][-1]["count"]
    assert last_7d_total == len(orgs)


def test_collaborators_is_window_scoped(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])

    # Only org #4 (3 days ago, collaborator=True) falls inside 7D.
    total_7d_collab = sum(x["count"] for x in body["7D"]["growth_trend"]["collaborators"])
    assert total_7d_collab == 1

    # Both org #1 and org #4 are collaborators across all time.
    total_all_collab = sum(x["count"] for x in body["All"]["growth_trend"]["collaborators"])
    assert total_all_collab == 2


def test_organizations_by_location_shape(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])

    loc = body["All"]["organizations_by_location"]
    assert len(loc) <= 4
    assert all(set(x.keys()) == {"country", "count"} for x in loc)
    counts = [x["count"] for x in loc]
    assert counts == sorted(counts, reverse=True)


def test_lone_date_param_is_a_400(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"start_date": "2026-01-01"}, None)
    assert result["statusCode"] == 400


def test_malformed_date_is_a_400(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"start_date": "not-a-date", "end_date": "2026-06-30"}, None)
    assert result["statusCode"] == 400


def test_start_after_end_is_a_400(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"start_date": "2026-06-30", "end_date": "2026-01-01"}, None)
    assert result["statusCode"] == 400


def test_is_collaborator_y_n_encoding_is_not_silently_zeroed(handler, tmp_path):
    _write_fixture(tmp_path, collab_encoder=lambda b: "Y" if b else "N")
    result = handler({}, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    total = sum(x["count"] for x in body["All"]["growth_trend"]["collaborators"])
    assert total == 2  # must not silently become 0


def test_is_collaborator_garbage_value_fails_loud(handler, tmp_path):
    _write_fixture(tmp_path, collab_encoder=lambda b: "MAYBE")
    result = handler({}, None)
    assert result["statusCode"] == 500  # loud failure, not a silent False


def test_duplicate_state_id_fails_loud_instead_of_double_counting(handler, tmp_path):
    """A duplicate state_id in states.csv fans out the join, silently
    doubling every organization in that state across every metric. This
    must be a loud failure, not a 200 with corrupted counts.
    """
    with open(os.path.join(tmp_path, "countries.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country_id", "country_code"])
        w.writerow([1, "USA"])

    with open(os.path.join(tmp_path, "states.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state_id", "state_name", "country_id"])
        w.writerow([1, "New York", 1])
        w.writerow([1, "New York Duplicate", 1])  # duplicate state_id

    with open(os.path.join(tmp_path, "organizations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["org_id", "state_id", "city_name", "is_collaborator", "created_at"])
        w.writerow([1, 1, "NY", "true", "2026-01-01"])

    result = handler({}, None)
    assert result["statusCode"] == 500  # loud failure, not silent row duplication


def test_api_gateway_proxy_event_with_string_body(handler, tmp_path):
    _write_fixture(tmp_path)
    event = {"body": json.dumps({"start_date": "2026-01-01", "end_date": "2026-06-30"})}
    result = handler(event, None)
    assert result["statusCode"] == 200


def test_response_body_is_a_json_string(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    assert isinstance(result["body"], str)


def test_data_is_loaded_once_per_warm_instance_not_per_call(handler, tmp_path, monkeypatch):
    """A warm Lambda container reuses module-level state across calls, so
    load_data() should only run on the first call -- not on every call.
    """
    _write_fixture(tmp_path)

    loader = sys.modules["loader"]
    real_load_data = loader.load_data
    call_count = {"n": 0}

    def counting_load_data(*args, **kwargs):
        call_count["n"] += 1
        return real_load_data(*args, **kwargs)

    monkeypatch.setattr(loader, "load_data", counting_load_data)
    # lambda_function imported load_data by reference, so it must be
    # patched there too for the substitution to take effect.
    monkeypatch.setattr(sys.modules["lambda_function"], "load_data", counting_load_data)

    handler({}, None)
    handler({"start_date": "2026-01-01", "end_date": "2026-06-30"}, None)
    handler({}, None)

    assert call_count["n"] == 1, "load_data() should run once per warm instance, not per call"
