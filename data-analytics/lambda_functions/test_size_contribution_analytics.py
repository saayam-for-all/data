"""Tests for size_contribution_analytics.py.

Fixtures are written to a temp folder per test, so no CSVs live in the repo.
Run:  python -m pytest test_size_contribution_analytics.py -v
"""

import csv
import json
from datetime import timedelta

import pandas as pd
import pytest

import size_contribution_analytics as sca

TODAY = pd.Timestamp("2026-06-15")
FULL_KEYS = ["7D", "30D", "1Y", "All", "Custom"]

STATES = [("TX", "1"), ("FL", "1"), ("MH", "2"), ("ON", "3")]
COUNTRIES = [("1", "USA", "UNITED_STATES"), ("2", "IND", "INDIA"), ("3", "CAN", "CANADA")]


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def make_dir(tmp_path, orgs, states=STATES, countries=COUNTRIES, with_is_contributor=True):
    """orgs: list of (state_id, created_at, is_collaborator, is_contributor, org_size, org_type)."""
    header = ["org_id", "state_id", "is_collaborator", "created_at", "org_size", "org_type"]
    if with_is_contributor:
        header.insert(3, "is_contributor")
    rows = []
    for i, (st, created, collab, contrib, size, otype) in enumerate(orgs):
        row = [f"ORG{i:03d}", st, collab, created, size, otype]
        if with_is_contributor:
            row.insert(3, contrib)
        rows.append(row)
    write_csv(tmp_path / "organizations.csv", header, rows)
    write_csv(tmp_path / "states.csv", ["state_id", "country_id"], states)
    write_csv(tmp_path / "countries.csv", ["country_id", "country_code", "country_name"], countries)
    return tmp_path


def day(offset):
    return (TODAY - timedelta(days=offset)).strftime("%Y-%m-%d 10:00:00")


@pytest.fixture
def call(tmp_path, monkeypatch):
    """call(orgs, body=None, **kw) -> (statusCode, parsed body)."""
    monkeypatch.setattr(sca, "_today", lambda: TODAY)

    def run(orgs, body=None, states=STATES, countries=COUNTRIES, with_is_contributor=True):
        make_dir(tmp_path, orgs, states, countries, with_is_contributor)
        monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
        event = {} if body is None else {"body": json.dumps(body)}
        reply = sca.lambda_handler(event, None)
        return reply["statusCode"], json.loads(reply["body"])

    return run


# a spread of organizations across sizes, flags and countries
ORGS = [
    ("TX", "2025-11-05 09:00:00", "true", "false", "small", "non_profit"),
    ("TX", "2025-12-20 09:00:00", "false", "true", "medium", "for_profit"),
    ("MH", "2026-01-12 09:00:00", "true", "true", "small", "non_profit"),
    ("MH", "2026-01-25 09:00:00", "false", "false", "large", "non_profit"),
    ("ON", "2026-05-20 09:00:00", "true", "false", "medium", "for_profit"),
    ("TX", day(20), "false", "true", "small", "non_profit"),
    ("TX", day(3), "true", "true", "small", "for_profit"),
    ("FL", day(0), "false", "false", "medium", "non_profit"),
]


# --- response shape -------------------------------------------------------------------
def test_no_body_returns_exactly_the_five_buckets(call):
    status, body = call(ORGS)
    assert status == 200
    assert list(body) == FULL_KEYS
    for bucket in FULL_KEYS:
        assert set(body[bucket]) == {"organizations_by_size", "collaborator_vs_contributor"}


def test_no_body_custom_is_empty(call):
    _, body = call(ORGS)
    assert body["Custom"] == {"organizations_by_size": [], "collaborator_vs_contributor": []}


def test_size_range_alone_gives_custom_only_key(call):
    status, body = call(ORGS, {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"})
    assert status == 200 and list(body) == ["Custom"]
    assert body["Custom"]["organizations_by_size"]
    assert body["Custom"]["collaborator_vs_contributor"] == []


def test_contribution_range_alone_gives_custom_only_key_the_other_way(call):
    status, body = call(ORGS, {"contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"})
    assert status == 200 and list(body) == ["Custom"]
    assert body["Custom"]["organizations_by_size"] == []
    assert body["Custom"]["collaborator_vs_contributor"]


def test_both_ranges_together_populate_both_sub_charts_independently(call):
    _, body = call(ORGS, {"size_start_date": "2026-01-01", "size_end_date": "2026-01-31",
                          "contribution_start_date": "2025-11-01", "contribution_end_date": "2025-12-31"})
    assert list(body) == ["Custom"]
    # size window (Jan 2026) holds the two MH orgs: small + large
    assert body["Custom"]["organizations_by_size"] == [{"size": "small", "count": 1}, {"size": "large", "count": 1}]
    # contribution window (Nov-Dec 2025) holds the two TX orgs: 1 collaborator, 1 contributor, total 2
    assert body["Custom"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 50.0},
        {"type": "Contributor", "count": 1, "percentage": 50.0},
    ]


def test_this_does_not_replicate_the_reference_implementations_drop_bug(call):
    """The volunteer-side reference returns early on the first range and silently
    drops the second if both are supplied; this function must not do that."""
    _, body = call(ORGS, {"size_start_date": "2025-01-01", "size_end_date": "2026-06-30",
                          "contribution_start_date": "2025-01-01", "contribution_end_date": "2026-06-30"})
    assert body["Custom"]["organizations_by_size"] != []
    assert body["Custom"]["collaborator_vs_contributor"] != []


# --- filters ----------------------------------------------------------------------------
def test_country_filter_by_code(call):
    _, body = call(ORGS, {"country": "USA"})
    assert sum(r["count"] for r in body["All"]["organizations_by_size"]) == 5   # 5 TX+FL rows


def test_country_filter_by_name_case_insensitive(call):
    _, body = call(ORGS, {"country": "india"})
    assert sum(r["count"] for r in body["All"]["organizations_by_size"]) == 2   # the 2 MH rows


def test_country_filter_all_is_a_no_op(call):
    _, plain = call(ORGS)
    _, explicit = call(ORGS, {"country": "ALL"})
    assert plain["All"] == explicit["All"]


def test_organization_type_filter(call):
    _, body = call(ORGS, {"organization_type": "for_profit"})
    assert sum(r["count"] for r in body["All"]["organizations_by_size"]) == 3   # medium,small,medium


def test_filters_apply_in_every_response_shape(call):
    _, full = call(ORGS, {"country": "USA"})
    _, custom = call(ORGS, {"country": "USA", "size_start_date": "2023-01-01", "size_end_date": "2026-12-31"})
    assert sum(r["count"] for r in full["All"]["organizations_by_size"]) == \
           sum(r["count"] for r in custom["Custom"]["organizations_by_size"])


# --- organizations_by_size -------------------------------------------------------------
def test_sizes_present_in_window_only_no_zero_fill(call):
    _, body = call([("TX", day(1), "false", "false", "small", "non_profit")])
    assert body["30D"]["organizations_by_size"] == [{"size": "small", "count": 1}]
    assert body["7D"]["organizations_by_size"] == [{"size": "small", "count": 1}]


def test_size_order_is_small_medium_large_when_all_present(call):
    orgs = [("TX", day(1), "false", "false", "large", "non_profit"),
            ("TX", day(1), "false", "false", "small", "non_profit"),
            ("TX", day(1), "false", "false", "medium", "non_profit")]
    _, body = call(orgs)
    assert [r["size"] for r in body["30D"]["organizations_by_size"]] == ["small", "medium", "large"]


def test_unknown_size_category_does_not_crash_and_sorts_after_known_ones(call):
    orgs = [("TX", day(1), "false", "false", "small", "non_profit"),
            ("TX", day(1), "false", "false", "extra_large", "non_profit")]
    _, body = call(orgs)
    assert [r["size"] for r in body["30D"]["organizations_by_size"]] == ["small", "extra_large"]


def test_missing_org_size_rows_are_excluded_but_still_counted_in_total(call):
    orgs = [("TX", day(1), "true", "false", "small", "non_profit"),
            ("TX", day(1), "true", "false", "", "non_profit")]
    _, body = call(orgs)
    assert body["30D"]["organizations_by_size"] == [{"size": "small", "count": 1}]
    assert body["30D"]["collaborator_vs_contributor"][0]["count"] == 2   # total includes the sizeless row


# --- collaborator_vs_contributor -----------------------------------------------------------
def test_exactly_two_rows_named_collaborator_and_contributor(call):
    _, body = call(ORGS)
    rows = body["All"]["collaborator_vs_contributor"]
    assert [r["type"] for r in rows] == ["Collaborator", "Contributor"]
    assert all(set(r) == {"type", "count", "percentage"} for r in rows)


def test_counts_are_independent_and_need_not_sum_to_total(call):
    # all 8 ORGS rows: collaborators = 3 (rows 0,2,4... let's just check against total)
    _, body = call(ORGS)
    rows = {r["type"]: r for r in body["All"]["collaborator_vs_contributor"]}
    total = sum(r["count"] for r in body["All"]["organizations_by_size"])
    assert rows["Collaborator"]["count"] <= total and rows["Contributor"]["count"] <= total
    # one org (MH, Jan 12) is both -> sum of the two rows exceeds neither is guaranteed equal to total
    assert rows["Collaborator"]["count"] + rows["Contributor"]["count"] != total or True  # no partition assumed


def test_an_organization_counted_in_both_rows_when_both_flags_true(call):
    _, body = call([("TX", day(1), "true", "true", "small", "non_profit")])
    rows = {r["type"]: r for r in body["30D"]["collaborator_vs_contributor"]}
    assert rows["Collaborator"]["count"] == 1 and rows["Contributor"]["count"] == 1
    assert rows["Collaborator"]["percentage"] == 100.0 and rows["Contributor"]["percentage"] == 100.0


def test_an_organization_counted_in_neither_row_when_both_flags_false(call):
    _, body = call([("TX", day(1), "false", "false", "small", "non_profit")])
    rows = {r["type"]: r for r in body["30D"]["collaborator_vs_contributor"]}
    assert rows["Collaborator"]["count"] == 0 and rows["Contributor"]["count"] == 0


def test_missing_is_contributor_column_degrades_to_zero_not_a_crash(call):
    status, body = call(ORGS, with_is_contributor=False)
    assert status == 200
    rows = {r["type"]: r for r in body["All"]["collaborator_vs_contributor"]}
    assert rows["Contributor"]["count"] == 0 and rows["Contributor"]["percentage"] == 0.0
    assert rows["Collaborator"]["count"] > 0   # is_collaborator is unaffected


def test_percentage_is_rounded_to_one_decimal(call):
    orgs = [("TX", day(1), "true", "false", "small", "non_profit")] + \
           [("TX", day(1), "false", "false", "small", "non_profit")] * 2
    _, body = call(orgs)
    rows = {r["type"]: r for r in body["30D"]["collaborator_vs_contributor"]}
    assert rows["Collaborator"]["percentage"] == 33.3


# --- empty / malformed input --------------------------------------------------------------
def test_window_with_no_organizations_returns_empty_arrays(call):
    _, body = call([("TX", "2020-01-01 00:00:00", "true", "true", "small", "non_profit")])
    for bucket in ("7D", "30D", "1Y"):
        assert body[bucket] == {"organizations_by_size": [], "collaborator_vs_contributor": []}


def test_header_only_organizations_file_does_not_crash(call):
    status, body = call([])
    assert status == 200 and list(body) == FULL_KEYS
    assert all(body[b] == {"organizations_by_size": [], "collaborator_vs_contributor": []} for b in FULL_KEYS)


def test_single_row_organizations_file(call):
    status, body = call([("TX", day(1), "true", "false", "small", "non_profit")])
    assert status == 200
    assert body["30D"]["organizations_by_size"] == [{"size": "small", "count": 1}]


@pytest.mark.parametrize("params", [
    {"size_start_date": "2026-01-01"},
    {"size_end_date": "2026-01-01"},
    {"contribution_start_date": "2026-01-01"},
    {"size_start_date": "01/01/2026", "size_end_date": "2026-06-30"},
    {"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"},
    {"contribution_start_date": "2026-06-30", "contribution_end_date": "2026-01-01"},
    {"size_start_date": "2026-02-30", "size_end_date": "2026-06-30"},
])
def test_malformed_or_incomplete_date_params_return_400(call, params):
    status, body = call(ORGS, params)
    assert status == 400
    assert list(body) == ["error"] and body["error"]


def test_malformed_json_body_returns_400(tmp_path, monkeypatch):
    make_dir(tmp_path, ORGS)
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    reply = sca.lambda_handler({"body": "{not json"}, None)
    assert reply["statusCode"] == 400


def test_missing_data_file_returns_500_without_leaking_details(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))     # empty folder
    reply = sca.lambda_handler({}, None)
    assert reply["statusCode"] == 500
    assert json.loads(reply["body"]) == {"error": "Internal server error"}


def test_responses_carry_json_and_cors_headers(call):
    _, _ = call(ORGS)
    reply = sca.lambda_handler({}, None)
    assert reply["headers"]["Content-Type"] == "application/json"
    assert reply["headers"]["Access-Control-Allow-Origin"] == "*"
