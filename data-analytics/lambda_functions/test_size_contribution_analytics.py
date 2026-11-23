"""
Automated tests for size_contribution_analytics (Issue #376).

Run:  cd data-analytics/lambda_functions && pytest -q
Each test writes its own tiny CSV fixtures to a temp dir and points
MOCK_DATA_DIR at it, so no shared/committed mock data is required.
"""
import csv
import json
import os

import pytest

import size_contribution_analytics as sca


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _write_csv(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _make_dataset(tmp_path, org_rows, *, with_contributor=True,
                  states=None, countries=None):
    org_fields = ["org_id", "org_size", "is_collaborator", "org_type", "state_id", "created_at"]
    if with_contributor:
        org_fields.insert(3, "is_contributor")
    _write_csv(tmp_path / "organizations.csv", org_fields, org_rows)

    states = states if states is not None else [
        {"state_id": "CA", "country_id": "1", "state_name": "California", "state_code": "US-CA"},
        {"state_id": "MH", "country_id": "2", "state_name": "Maharashtra", "state_code": "IN-MH"},
    ]
    countries = countries if countries is not None else [
        {"country_id": "1", "country_name": "UNITED STATES", "country_code": "USA"},
        {"country_id": "2", "country_name": "INDIA", "country_code": "IND"},
    ]
    _write_csv(tmp_path / "states.csv", ["state_id", "country_id", "state_name", "state_code"], states)
    _write_csv(tmp_path / "countries.csv", ["country_id", "country_name", "country_code"], countries)
    return str(tmp_path)


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    yield


def _call(event):
    res = sca.lambda_handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def _org(i, size, collab, contrib, otype, state, created):
    row = {"org_id": f"O{i}", "org_size": size, "is_collaborator": collab,
           "is_contributor": contrib, "org_type": otype, "state_id": state, "created_at": created}
    return row


# recent-ish + old mix; "All" always sees everything
RECENT = "2026-06-10 00:00:00"
OLDISH = "2024-03-01 00:00:00"


# --------------------------------------------------------------------------- #
# Response shape
# --------------------------------------------------------------------------- #
def test_body_is_json_string(tmp_path, monkeypatch):
    d = _make_dataset(tmp_path, [_org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    res = sca.lambda_handler({}, None)
    assert isinstance(res["body"], str)            # proxy-integration contract
    assert isinstance(json.loads(res["body"]), dict)


def test_no_custom_params_has_five_keys(tmp_path, monkeypatch):
    d = _make_dataset(tmp_path, [_org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({})
    assert code == 200
    assert set(body) == {"7D", "30D", "1Y", "All", "Custom"}
    for k in body:
        assert set(body[k]) == {"organizations_by_size", "collaborator_vs_contributor"}
    assert body["Custom"] == {"organizations_by_size": [], "collaborator_vs_contributor": []}


@pytest.mark.parametrize("payload,size_filled,contrib_filled", [
    ({"size_start_date": "2026-01-01", "size_end_date": "2026-12-31"}, True, False),
    ({"contribution_start_date": "2026-01-01", "contribution_end_date": "2026-12-31"}, False, True),
    ({"size_start_date": "2026-01-01", "size_end_date": "2026-12-31",
      "contribution_start_date": "2026-01-01", "contribution_end_date": "2026-12-31"}, True, True),
])
def test_custom_only_single_key(tmp_path, monkeypatch, payload, size_filled, contrib_filled):
    d = _make_dataset(tmp_path, [_org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({"body": payload})
    assert code == 200
    assert set(body) == {"Custom"}
    assert bool(body["Custom"]["organizations_by_size"]) == size_filled
    assert bool(body["Custom"]["collaborator_vs_contributor"]) == contrib_filled


def test_both_pairs_independent_not_dropped(tmp_path, monkeypatch):
    """The core anti-bug: both date pairs populate their own chart."""
    rows = [
        _org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", "2026-03-01 00:00:00"),
        _org(2, "Large", "FALSE", "TRUE", "Non-Profit", "CA", "2025-03-01 00:00:00"),
    ]
    d = _make_dataset(tmp_path, rows)
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({"body": {
        "size_start_date": "2026-01-01", "size_end_date": "2026-12-31",
        "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31",
    }})
    cust = body["Custom"]
    assert cust["organizations_by_size"] == [{"size": "Small", "count": 1}]      # 2026 window
    assert cust["collaborator_vs_contributor"][1]["count"] == 1                   # 2025 window contributor


# --------------------------------------------------------------------------- #
# Chart correctness
# --------------------------------------------------------------------------- #
def test_independent_counts_not_a_partition(tmp_path, monkeypatch):
    rows = [
        _org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT),   # both
        _org(2, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT),   # both (overlap)
        _org(3, "Large", "FALSE", "FALSE", "Non-Profit", "CA", RECENT), # neither
    ]
    d = _make_dataset(tmp_path, rows)
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    _, body = _call({})
    cvc = {r["type"]: r for r in body["All"]["collaborator_vs_contributor"]}
    assert cvc["Collaborator"]["count"] == 2
    assert cvc["Contributor"]["count"] == 2
    # Overlapping (both) + neither -> counts need not sum to total (3).
    assert cvc["Collaborator"]["count"] + cvc["Contributor"]["count"] == 4
    assert cvc["Collaborator"]["percentage"] == round(2 / 3 * 100, 1)


def test_size_counts_sum_to_window_total(tmp_path, monkeypatch):
    rows = [_org(i, sz, "TRUE", "TRUE", "Non-Profit", "CA", RECENT)
            for i, sz in enumerate(["Small", "Small", "Medium", "Large"], 1)]
    d = _make_dataset(tmp_path, rows)
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    _, body = _call({})
    sizes = body["All"]["organizations_by_size"]
    assert sum(r["count"] for r in sizes) == 4
    assert {r["size"]: r["count"] for r in sizes} == {"Small": 2, "Medium": 1, "Large": 1}


def test_raw_size_values_preserved(tmp_path, monkeypatch):
    d = _make_dataset(tmp_path, [_org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    _, body = _call({})
    assert body["All"]["organizations_by_size"][0]["size"] == "Small"  # not lowercased


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
def test_country_filter_changes_numbers(tmp_path, monkeypatch):
    rows = [
        _org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT),
        _org(2, "Large", "TRUE", "TRUE", "Non-Profit", "MH", RECENT),
    ]
    d = _make_dataset(tmp_path, rows)
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    _, all_body = _call({})
    _, usa_body = _call({"body": {"country": "USA"}})
    _, name_body = _call({"body": {"country": "united states"}})  # name + different casing
    assert sum(r["count"] for r in all_body["All"]["organizations_by_size"]) == 2
    assert sum(r["count"] for r in usa_body["All"]["organizations_by_size"]) == 1
    assert usa_body["All"] == name_body["All"]  # code and name resolve identically


def test_org_type_filter_changes_numbers(tmp_path, monkeypatch):
    rows = [
        _org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT),
        _org(2, "Large", "TRUE", "TRUE", "For-profit", "CA", RECENT),
    ]
    d = _make_dataset(tmp_path, rows)
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    _, np_body = _call({"body": {"organization_type": "non_profit"}})  # underscore vs hyphen/case
    assert sum(r["count"] for r in np_body["All"]["organizations_by_size"]) == 1


# --------------------------------------------------------------------------- #
# Edge cases / error handling
# --------------------------------------------------------------------------- #
def test_empty_dataset_returns_empty_arrays(tmp_path, monkeypatch):
    d = _make_dataset(tmp_path, [])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({})
    assert code == 200
    for k in ["7D", "30D", "1Y", "All"]:
        assert body[k]["organizations_by_size"] == []
        assert body[k]["collaborator_vs_contributor"] == []  # empty -> [] (not two zero rows)


def test_empty_window_returns_empty_arrays(tmp_path, monkeypatch):
    d = _make_dataset(tmp_path, [_org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", OLDISH)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    _, body = _call({})
    # OLDISH org is far older than 7 days
    assert body["7D"]["organizations_by_size"] == []
    assert body["7D"]["collaborator_vs_contributor"] == []
    assert body["All"]["organizations_by_size"]  # but All still sees it


def test_single_row_dataset(tmp_path, monkeypatch):
    d = _make_dataset(tmp_path, [_org(1, "Medium", "TRUE", "FALSE", "Non-Profit", "CA", RECENT)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    _, body = _call({})
    assert body["All"]["organizations_by_size"] == [{"size": "Medium", "count": 1}]
    cvc = {r["type"]: r for r in body["All"]["collaborator_vs_contributor"]}
    assert cvc["Collaborator"]["count"] == 1 and cvc["Contributor"]["count"] == 0


def test_missing_contributor_column_degrades(tmp_path, monkeypatch):
    rows = [{"org_id": "O1", "org_size": "Small", "is_collaborator": "TRUE",
             "org_type": "Non-Profit", "state_id": "CA", "created_at": RECENT}]
    d = _make_dataset(tmp_path, rows, with_contributor=False)
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({})
    assert code == 200
    cvc = {r["type"]: r for r in body["All"]["collaborator_vs_contributor"]}
    assert cvc["Contributor"]["count"] == 0 and cvc["Contributor"]["percentage"] == 0


def test_malformed_missing_half_pair(tmp_path, monkeypatch):
    d = _make_dataset(tmp_path, [_org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({"body": {"size_start_date": "2026-01-01"}})
    assert code == 400 and "error" in body


@pytest.mark.parametrize("bad", ["06/01/2026", "2026-13-01", "not-a-date", "2026/01/01"])
def test_malformed_bad_date_format(tmp_path, monkeypatch, bad):
    d = _make_dataset(tmp_path, [_org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({"body": {"size_start_date": bad, "size_end_date": "2026-06-30"}})
    assert code == 400 and "error" in body


def test_start_after_end(tmp_path, monkeypatch):
    d = _make_dataset(tmp_path, [_org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({"body": {"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"}})
    assert code == 400 and "error" in body


def test_invalid_json_body_returns_400(tmp_path, monkeypatch):
    d = _make_dataset(tmp_path, [_org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({"body": "{not valid json"})
    assert code == 400 and "error" in body


def test_stringified_json_body_supported(tmp_path, monkeypatch):
    d = _make_dataset(tmp_path, [
        _org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT),
        _org(2, "Large", "TRUE", "TRUE", "Non-Profit", "MH", RECENT),
    ])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({"body": json.dumps({"country": "USA"})})
    assert code == 200
    assert sum(r["count"] for r in body["All"]["organizations_by_size"]) == 1


# --------------------------------------------------------------------------- #
# Robustness (hardening beyond the original 5 reviewer items)
# --------------------------------------------------------------------------- #
def test_tz_aware_created_at_does_not_crash(tmp_path, monkeypatch):
    """Timezone-aware ISO timestamps (trailing Z / offset) must not crash."""
    rows = [
        _org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", "2026-06-10T00:00:00Z"),
        _org(2, "Large", "FALSE", "TRUE", "Non-Profit", "CA", "2025-06-10T00:00:00+05:30"),
    ]
    d = _make_dataset(tmp_path, rows)
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({})
    assert code == 200
    assert sum(r["count"] for r in body["All"]["organizations_by_size"]) == 2


@pytest.mark.parametrize("bad", ["2026-1-5", "2026-01-5", "2026-6-30"])
def test_non_zero_padded_dates_rejected(tmp_path, monkeypatch, bad):
    d = _make_dataset(tmp_path, [_org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({"body": {"size_start_date": bad, "size_end_date": "2026-06-30"}})
    assert code == 400 and "error" in body


def test_impossible_calendar_date_rejected(tmp_path, monkeypatch):
    d = _make_dataset(tmp_path, [_org(1, "Small", "TRUE", "TRUE", "Non-Profit", "CA", RECENT)])
    monkeypatch.setenv("MOCK_DATA_DIR", d)
    code, body = _call({"body": {"size_start_date": "2026-02-30", "size_end_date": "2026-06-30"}})
    assert code == 400 and "error" in body
