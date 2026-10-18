"""Tests for the Size & Contribution Analytics Lambda (#376).

Self-contained: builds its own small mock CSVs rather than depending on any
other in-flight PR. Mirrors the fixed-bucket / Custom conventions
established for #336 and #380 -- Custom mode here *replaces* the fixed
buckets instead of riding alongside them, same as #380's contract.

Fixture timestamps are relative to the real `datetime.now()` at test-run
time (not a hardcoded past date), since the handler buckets against real
wall-clock time -- a fixed historical "now" would silently drift out of
the 7D/30D windows as real time passes (this bit the #336 test suite).
"""
import csv
import importlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

IMPL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data-analytics", "lambda_functions",
)


def _write_csvs(tmp_path, countries, states, org_rows, with_is_contributor=True):
    with open(os.path.join(tmp_path, "countries.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country_id", "country_code"])
        w.writerows(countries)

    with open(os.path.join(tmp_path, "states.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state_id", "country_id"])
        w.writerows(states)

    header = ["org_id", "state_id", "org_size", "is_collaborator", "org_type", "created_at"]
    if with_is_contributor:
        header.insert(4, "is_contributor")

    with open(os.path.join(tmp_path, "organizations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(org_rows)


def _write_fixture(tmp_path):
    """6 orgs, 2 countries, mixed sizes/types, one entry inside 7D and one
    just outside it.
    """
    now = datetime.now(timezone.utc)
    countries = [(1, "USA"), (2, "IND")]
    states = [(1, 1), (2, 2)]
    orgs = [
        # org_id, state_id, org_size, is_collaborator, is_contributor, org_type, created_at
        (1, 1, "small", True, False, "non_profit", (now - timedelta(days=200)).strftime("%Y-%m-%d")),
        (2, 1, "medium", False, True, "for_profit", (now - timedelta(days=100)).strftime("%Y-%m-%d")),
        (3, 2, "large", True, True, "non_profit", (now - timedelta(days=20)).strftime("%Y-%m-%d")),
        (4, 1, "small", True, False, "non_profit", (now - timedelta(days=3)).strftime("%Y-%m-%d")),   # inside 7D
        (5, 1, "medium", False, False, "for_profit", (now - timedelta(days=10)).strftime("%Y-%m-%d")),  # outside 7D
        (6, 2, "large", False, True, "for_profit", (now - timedelta(days=1)).strftime("%Y-%m-%d")),   # inside 7D
    ]
    _write_csvs(tmp_path, countries, states, orgs)
    return orgs


@pytest.fixture
def handler(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.syspath_prepend(IMPL_DIR)
    sys.modules.pop("size_contribution_analytics", None)
    module = importlib.import_module("size_contribution_analytics")
    return module.lambda_handler


def test_top_level_keys_no_custom_params(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert set(body.keys()) == {"7D", "30D", "1Y", "All", "Custom"}
    for bucket in body.values():
        assert set(bucket.keys()) == {"organizations_by_size", "collaborator_vs_contributor"}


def test_custom_mode_returns_only_custom_key(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"}, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert set(body.keys()) == {"Custom"}
    assert set(body["Custom"].keys()) == {"organizations_by_size", "collaborator_vs_contributor"}


def test_organizations_by_size_no_zero_fill_and_raw_values(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])

    # Only org #4 (small) and org #6 (large) fall inside 7D -- medium must
    # be absent, not reported with a zero count.
    dist = body["7D"]["organizations_by_size"]
    assert dist == [{"size": "small", "count": 1}, {"size": "large", "count": 1}]


def test_organizations_by_size_display_order(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])
    dist = body["All"]["organizations_by_size"]
    sizes = [x["size"] for x in dist]
    assert sizes == ["small", "medium", "large"]


def test_organizations_by_size_unexpected_category_is_not_dropped(handler, tmp_path):
    now = datetime.now(timezone.utc)
    _write_csvs(
        tmp_path,
        countries=[(1, "USA")],
        states=[(1, 1)],
        org_rows=[
            (1, 1, "small", True, False, "non_profit", (now - timedelta(days=1)).strftime("%Y-%m-%d")),
            (2, 1, "extra_large", True, False, "non_profit", (now - timedelta(days=1)).strftime("%Y-%m-%d")),
        ],
    )
    result = handler({}, None)
    body = json.loads(result["body"])
    sizes = {x["size"] for x in body["All"]["organizations_by_size"]}
    assert sizes == {"small", "extra_large"}


def test_collaborator_vs_contributor_always_two_rows(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])
    cvc = body["All"]["collaborator_vs_contributor"]
    assert [row["type"] for row in cvc] == ["Collaborator", "Contributor"]
    assert all(set(row.keys()) == {"type", "count", "percentage"} for row in cvc)


def test_collaborator_vs_contributor_counts_are_independent_not_partition(handler, tmp_path):
    orgs = _write_fixture(tmp_path)
    result = handler({}, None)
    body = json.loads(result["body"])
    cvc = {row["type"]: row for row in body["All"]["collaborator_vs_contributor"]}

    total = len(orgs)
    collaborators = sum(1 for o in orgs if o[3])
    contributors = sum(1 for o in orgs if o[4])
    assert cvc["Collaborator"]["count"] == collaborators
    assert cvc["Contributor"]["count"] == contributors
    # Both are collaborator AND contributor for org #3 and #6 -- counts
    # should not need to sum to the total.
    assert collaborators + contributors != total or True  # sanity: not asserting equality either way
    assert cvc["Collaborator"]["percentage"] == round(collaborators / total * 100, 1)
    assert cvc["Contributor"]["percentage"] == round(contributors / total * 100, 1)


def test_missing_is_contributor_column_degrades_to_zero(handler, tmp_path):
    now = datetime.now(timezone.utc)
    _write_csvs(
        tmp_path,
        countries=[(1, "USA")],
        states=[(1, 1)],
        org_rows=[(1, 1, "small", True, "non_profit", (now - timedelta(days=1)).strftime("%Y-%m-%d"))],
        with_is_contributor=False,
    )
    result = handler({}, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    contributor_row = next(
        row for row in body["All"]["collaborator_vs_contributor"] if row["type"] == "Contributor"
    )
    assert contributor_row == {"type": "Contributor", "count": 0, "percentage": 0.0}


def test_size_custom_populates_independently_of_contribution_custom(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"}, None)
    body = json.loads(result["body"])
    assert body["Custom"]["organizations_by_size"] != []
    assert body["Custom"]["collaborator_vs_contributor"] == []


def test_contribution_custom_populates_independently_of_size_custom(handler, tmp_path):
    now = datetime.now(timezone.utc)
    _write_fixture(tmp_path)
    result = handler(
        {
            "contribution_start_date": (now - timedelta(days=365)).strftime("%Y-%m-%d"),
            "contribution_end_date": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
        },
        None,
    )
    body = json.loads(result["body"])
    assert body["Custom"]["organizations_by_size"] == []
    assert body["Custom"]["collaborator_vs_contributor"] != []


def test_both_custom_ranges_populate_both_charts(handler, tmp_path):
    """Guards against the exact bug the issue calls out: supplying both
    pairs must populate both sub-charts, not silently drop the second one.
    """
    now = datetime.now(timezone.utc)
    _write_fixture(tmp_path)
    result = handler(
        {
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-06-30",
            "contribution_start_date": (now - timedelta(days=365)).strftime("%Y-%m-%d"),
            "contribution_end_date": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
        },
        None,
    )
    body = json.loads(result["body"])
    assert body["Custom"]["organizations_by_size"] != []
    assert body["Custom"]["collaborator_vs_contributor"] != []


def test_country_filter_applies_to_both_charts(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"country": "IND"}, None)
    body = json.loads(result["body"])
    # Only orgs #3 and #6 are in IND.
    dist = body["All"]["organizations_by_size"]
    assert sum(x["count"] for x in dist) == 2


def test_country_all_is_a_no_op(handler, tmp_path):
    _write_fixture(tmp_path)
    unfiltered = json.loads(handler({}, None)["body"])
    explicit_all = json.loads(handler({"country": "ALL"}, None)["body"])
    assert explicit_all["All"]["organizations_by_size"] == unfiltered["All"]["organizations_by_size"]


def test_organization_type_filter_applies_to_both_charts(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"organization_type": "non_profit"}, None)
    body = json.loads(result["body"])
    # Orgs #1, #3, #4 are non_profit.
    dist = body["All"]["organizations_by_size"]
    assert sum(x["count"] for x in dist) == 3


def test_organization_type_all_is_a_no_op(handler, tmp_path):
    _write_fixture(tmp_path)
    unfiltered = json.loads(handler({}, None)["body"])
    explicit_all = json.loads(handler({"organization_type": "ALL"}, None)["body"])
    assert explicit_all["All"]["organizations_by_size"] == unfiltered["All"]["organizations_by_size"]


def test_lone_size_date_param_is_a_400(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"size_start_date": "2026-01-01"}, None)
    assert result["statusCode"] == 400


def test_lone_contribution_date_param_is_a_400(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"contribution_end_date": "2026-06-30"}, None)
    assert result["statusCode"] == 400


def test_malformed_date_is_a_400(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"size_start_date": "not-a-date", "size_end_date": "2026-06-30"}, None)
    assert result["statusCode"] == 400


def test_start_after_end_is_a_400(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({"contribution_start_date": "2026-06-30", "contribution_end_date": "2026-01-01"}, None)
    assert result["statusCode"] == 400


def test_garbage_org_type_fails_loud(handler, tmp_path):
    _write_csvs(
        tmp_path,
        countries=[(1, "USA")],
        states=[(1, 1)],
        org_rows=[(1, 1, "small", True, "banana", "2026-01-01")],
        with_is_contributor=False,
    )
    result = handler({}, None)
    assert result["statusCode"] == 500


def test_duplicate_state_id_fails_loud_instead_of_double_counting(handler, tmp_path):
    with open(os.path.join(tmp_path, "countries.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country_id", "country_code"])
        w.writerow([1, "USA"])
    with open(os.path.join(tmp_path, "states.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state_id", "country_id"])
        w.writerow([1, 1])
        w.writerow([1, 1])  # duplicate state_id
    with open(os.path.join(tmp_path, "organizations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["org_id", "state_id", "org_size", "is_collaborator", "org_type", "created_at"])
        w.writerow([1, 1, "small", True, "non_profit", "2026-01-01"])

    result = handler({}, None)
    assert result["statusCode"] == 500


def test_empty_organizations_csv_does_not_crash(handler, tmp_path):
    _write_csvs(tmp_path, countries=[(1, "USA")], states=[(1, 1)], org_rows=[])
    result = handler({}, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])

    assert body["Custom"] == {"organizations_by_size": [], "collaborator_vs_contributor": []}
    for bucket_name in ("7D", "30D", "1Y", "All"):
        bucket = body[bucket_name]
        assert bucket["organizations_by_size"] == []
        assert bucket["collaborator_vs_contributor"] == [
            {"type": "Collaborator", "count": 0, "percentage": 0.0},
            {"type": "Contributor", "count": 0, "percentage": 0.0},
        ]


def test_single_row_organizations_csv_does_not_crash(handler, tmp_path):
    _write_csvs(
        tmp_path,
        countries=[(1, "USA")],
        states=[(1, 1)],
        org_rows=[(1, 1, "small", True, False, "non_profit", "2026-01-01")],
    )
    result = handler({}, None)
    assert result["statusCode"] == 200


def test_api_gateway_proxy_event_with_string_body(handler, tmp_path):
    _write_fixture(tmp_path)
    event = {"body": json.dumps({"country": "USA"})}
    result = handler(event, None)
    assert result["statusCode"] == 200


def test_response_body_is_a_json_string(handler, tmp_path):
    _write_fixture(tmp_path)
    result = handler({}, None)
    assert isinstance(result["body"], str)


def test_data_is_loaded_once_per_warm_instance_not_per_call(handler, tmp_path, monkeypatch):
    _write_fixture(tmp_path)

    module = sys.modules["size_contribution_analytics"]
    real_load_data = module.load_data
    call_count = {"n": 0}

    def counting_load_data(*args, **kwargs):
        call_count["n"] += 1
        return real_load_data(*args, **kwargs)

    monkeypatch.setattr(module, "load_data", counting_load_data)

    handler({}, None)
    handler({"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"}, None)
    handler({}, None)

    assert call_count["n"] == 1, "load_data() should run once per warm instance, not per call"


def test_module_imports_without_psycopg2(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.syspath_prepend(IMPL_DIR)
    sys.modules.pop("size_contribution_analytics", None)
    monkeypatch.setitem(sys.modules, "psycopg2", None)

    module = importlib.import_module("size_contribution_analytics")
    assert module.psycopg2 is None

    _write_fixture(tmp_path)
    result = module.lambda_handler({}, None)
    assert result["statusCode"] == 200


def test_postgres_path_without_psycopg2_fails_loud(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.syspath_prepend(IMPL_DIR)
    sys.modules.pop("size_contribution_analytics", None)
    monkeypatch.setitem(sys.modules, "psycopg2", None)

    module = importlib.import_module("size_contribution_analytics")
    result = module.lambda_handler({}, None)
    assert result["statusCode"] == 500
