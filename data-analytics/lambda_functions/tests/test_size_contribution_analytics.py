"""
Unit tests for size_contribution_analytics.py (issue #376).

Each test writes small CSV fixtures under tmp_path and uses a fixed
reference date, so results don't depend on the wall-clock date. Run with:

    pytest data-analytics/lambda_functions/tests/test_size_contribution_analytics.py
"""
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import size_contribution_analytics as sca

REFERENCE = pd.Timestamp("2026-06-15")
FIXED_KEYS = {"7D", "30D", "1Y", "All", "Custom"}
EMPTY_BUCKET = {"organizations_by_size": [], "collaborator_vs_contributor": []}

STATES = [
    ("US-TX", "1"),
    ("US-FL", "1"),
    ("IN-DL", "2"),
    ("GB-LDN", "3"),
]
COUNTRIES = [
    ("1", "USA", "UNITED_STATES"),
    ("2", "IND", "INDIA"),
    ("3", "GBR", "UNITED_KINGDOM"),
]
ORG_HEADER = ["org_id", "org_size", "is_collaborator", "is_contributor", "org_type", "state_id", "created_at"]

# (org_id, org_size, is_collaborator, is_contributor, org_type, state_id, created_at)
ORGS = [
    ("O1", "small", "TRUE", "TRUE", "non_profit", "US-TX", "2026-06-15"),   # 7D (both flags)
    ("O2", "small", "FALSE", "TRUE", "for_profit", "IN-DL", "2026-06-12"),  # 7D
    ("O3", "medium", "FALSE", "FALSE", "non_profit", "US-FL", "2026-06-10"),  # 7D (neither)
    ("O4", "large", "TRUE", "FALSE", "for_profit", "GB-LDN", "2026-05-25"),  # 30D
    ("O5", "medium", "TRUE", "TRUE", "non_profit", "US-TX", "2026-01-10"),  # 1Y
    ("O6", "large", "FALSE", "TRUE", "for_profit", "IN-DL", "2025-09-01"),  # 1Y
    ("O7", "small", "TRUE", "FALSE", "non_profit", "US-TX", "2024-03-01"),  # All only
]


def _write_csv(path, header, rows):
    lines = [",".join(header)] + [",".join(str(value) for value in row) for row in rows]
    path.write_text("\n".join(lines) + "\n")


def _write_files(tmp_path, organizations, header=ORG_HEADER, states=STATES, countries=COUNTRIES):
    _write_csv(tmp_path / "organizations.csv", header, organizations)
    _write_csv(tmp_path / "states.csv", ["state_id", "country_id"], states)
    _write_csv(tmp_path / "countries.csv", ["country_id", "country_code", "country_name"], countries)


def _load(tmp_path, organizations, **kwargs):
    _write_files(tmp_path, organizations, **kwargs)
    return sca.prepare_organizations(*sca.load_mock_tables(str(tmp_path)))


def _respond(tmp_path, organizations, payload=None, **kwargs):
    """Runs the full request path (validate -> load -> filter -> build)."""
    orgs, countries = _load(tmp_path, organizations, **kwargs)
    request = sca.parse_request(payload or {})
    orgs = sca.apply_country_filter(orgs, countries, request["country"])
    orgs = sca.apply_organization_type_filter(orgs, request["organization_type"])
    return sca.build_size_contribution_response(orgs, request, reference_date=REFERENCE)


def _sizes(chart):
    return {row["size"]: row["count"] for row in chart}


def _cvc(chart):
    return {row["type"]: (row["count"], row["percentage"]) for row in chart}


@pytest.fixture
def handler_env(tmp_path, monkeypatch):
    """Points the handler at tmp_path CSVs; returns a writer + caller."""
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))

    class Env:
        def write(self, organizations, **kwargs):
            _write_files(tmp_path, organizations, **kwargs)

        def call(self, event):
            result = sca.lambda_handler(event, None, reference_date=REFERENCE)
            return result["statusCode"], json.loads(result["body"])

    env = Env()
    env.write(ORGS)
    return env


# ---------------------------------------------------------------------------
# No Custom params - full 5-bucket response
# ---------------------------------------------------------------------------

def test_no_body_returns_five_keys_and_empty_custom(tmp_path):
    response = _respond(tmp_path, ORGS)
    assert set(response) == FIXED_KEYS
    assert response["Custom"] == EMPTY_BUCKET
    for bucket in response.values():
        assert set(bucket) == {"organizations_by_size", "collaborator_vs_contributor"}

    assert _sizes(response["7D"]["organizations_by_size"]) == {"small": 2, "medium": 1}
    assert _sizes(response["30D"]["organizations_by_size"]) == {"small": 2, "medium": 1, "large": 1}
    assert _sizes(response["1Y"]["organizations_by_size"]) == {"small": 2, "medium": 2, "large": 2}
    assert _sizes(response["All"]["organizations_by_size"]) == {"small": 3, "medium": 2, "large": 2}


def test_buckets_without_in_window_activity_are_empty(tmp_path):
    response = _respond(tmp_path, [("X", "small", "TRUE", "TRUE", "non_profit", "US-TX", "2024-01-01")])
    for bucket in ("7D", "30D", "1Y"):
        assert response[bucket] == EMPTY_BUCKET
    assert _sizes(response["All"]["organizations_by_size"]) == {"small": 1}


def test_handler_no_body_and_api_gateway_body(handler_env):
    for event in ({}, None, {"body": None}, {"body": ""}, {"body": "{}"}, {"body": {}}):
        status, body = handler_env.call(event)
        assert status == 200
        assert set(body) == FIXED_KEYS


def test_unknown_request_fields_are_ignored(tmp_path):
    assert set(_respond(tmp_path, ORGS, {"time_filter": "7D", "foo": 1})) == FIXED_KEYS


# ---------------------------------------------------------------------------
# Collaborator vs Contributor
# ---------------------------------------------------------------------------

def test_collaborator_and_contributor_are_independent_counts(tmp_path):
    response = _respond(tmp_path, ORGS)
    # 7D: O1 (both), O2 (contributor), O3 (neither) -> total 3
    assert response["7D"]["collaborator_vs_contributor"] == [
        {"type": "Collaborator", "count": 1, "percentage": 33.3},
        {"type": "Contributor", "count": 2, "percentage": 66.7},
    ]
    # All: 7 orgs, collaborators O1 O4 O5 O7 = 4, contributors O1 O2 O5 O6 = 4 -> sums to 8 > 7
    assert _cvc(response["All"]["collaborator_vs_contributor"]) == {
        "Collaborator": (4, 57.1),
        "Contributor": (4, 57.1),
    }


def test_collaborator_vs_contributor_has_exactly_two_rows_in_order(tmp_path):
    response = _respond(tmp_path, ORGS)
    for bucket in ("7D", "30D", "1Y", "All"):
        rows = response[bucket]["collaborator_vs_contributor"]
        assert [row["type"] for row in rows] == ["Collaborator", "Contributor"]
        assert all(set(row) == {"type", "count", "percentage"} for row in rows)


def test_counts_need_not_sum_to_total(tmp_path):
    orgs = [
        ("A", "small", "TRUE", "TRUE", "non_profit", "US-TX", "2026-06-14"),
        ("B", "small", "TRUE", "TRUE", "non_profit", "US-TX", "2026-06-14"),
        ("C", "small", "FALSE", "FALSE", "non_profit", "US-TX", "2026-06-14"),
        ("D", "small", "FALSE", "FALSE", "non_profit", "US-TX", "2026-06-14"),
    ]
    assert _cvc(_respond(tmp_path, orgs)["7D"]["collaborator_vs_contributor"]) == {
        "Collaborator": (2, 50.0),
        "Contributor": (2, 50.0),
    }


def test_missing_is_contributor_column_degrades_to_zero(tmp_path):
    header = [column for column in ORG_HEADER if column != "is_contributor"]
    rows = [tuple(value for index, value in enumerate(row) if index != 3) for row in ORGS]
    response = _respond(tmp_path, rows, header=header)
    rows_7d = response["7D"]["collaborator_vs_contributor"]
    assert rows_7d[1] == {"type": "Contributor", "count": 0, "percentage": 0}
    assert rows_7d[0]["count"] == 1


def test_missing_is_contributor_column_via_handler(handler_env):
    header = [column for column in ORG_HEADER if column != "is_contributor"]
    rows = [tuple(value for index, value in enumerate(row) if index != 3) for row in ORGS]
    handler_env.write(rows, header=header)
    status, body = handler_env.call({"contribution_start_date": "2020-01-01", "contribution_end_date": "2026-12-31"})
    assert status == 200
    assert _cvc(body["Custom"]["collaborator_vs_contributor"])["Contributor"] == (0, 0.0)


@pytest.mark.parametrize("truthy", ["TRUE", "true", "True", "t", "1", "yes"])
def test_boolean_flag_variants(tmp_path, truthy):
    orgs = [
        ("A", "small", truthy, truthy, "non_profit", "US-TX", "2026-06-14"),
        ("B", "small", "FALSE", "", "non_profit", "US-TX", "2026-06-14"),
    ]
    assert _cvc(_respond(tmp_path, orgs)["7D"]["collaborator_vs_contributor"]) == {
        "Collaborator": (1, 50.0),
        "Contributor": (1, 50.0),
    }


# ---------------------------------------------------------------------------
# Organizations by Size
# ---------------------------------------------------------------------------

def test_size_counts_sum_to_window_total_and_no_zero_fill(tmp_path):
    response = _respond(tmp_path, ORGS)
    assert "large" not in _sizes(response["7D"]["organizations_by_size"])
    window_totals = {"7D": 3, "30D": 4, "1Y": 6, "All": 7}
    for bucket, total in window_totals.items():
        assert sum(row["count"] for row in response[bucket]["organizations_by_size"]) == total
        assert all(row["count"] <= total for row in response[bucket]["collaborator_vs_contributor"])


def test_size_values_are_not_hardcoded(tmp_path):
    orgs = [
        ("A", "extra_large", "TRUE", "TRUE", "non_profit", "US-TX", "2026-06-14"),
        ("B", "small", "TRUE", "TRUE", "non_profit", "US-TX", "2026-06-14"),
        ("C", "large", "TRUE", "TRUE", "non_profit", "US-TX", "2026-06-14"),
    ]
    rows = _respond(tmp_path, orgs)["7D"]["organizations_by_size"]
    assert rows == [
        {"size": "small", "count": 1},
        {"size": "large", "count": 1},
        {"size": "extra_large", "count": 1},
    ]


def test_blank_org_size_is_excluded_from_size_chart_only(tmp_path):
    orgs = [
        ("A", "", "TRUE", "TRUE", "non_profit", "US-TX", "2026-06-14"),
        ("B", "small", "FALSE", "FALSE", "non_profit", "US-TX", "2026-06-14"),
    ]
    bucket = _respond(tmp_path, orgs)["7D"]
    assert bucket["organizations_by_size"] == [{"size": "small", "count": 1}]
    assert _cvc(bucket["collaborator_vs_contributor"])["Collaborator"] == (1, 50.0)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("country", ["USA", "usa", "UNITED_STATES", "united states"])
def test_country_filter_by_code_or_name_only_counts_that_country(tmp_path, country):
    response = _respond(tmp_path, ORGS, {"country": country})
    # US orgs: O1, O3, O5, O7
    assert _sizes(response["All"]["organizations_by_size"]) == {"small": 2, "medium": 2}
    assert _cvc(response["All"]["collaborator_vs_contributor"]) == {
        "Collaborator": (3, 75.0),
        "Contributor": (2, 50.0),
    }


@pytest.mark.parametrize("country", [None, "ALL", "all"])
def test_country_all_or_missing_counts_every_organization(tmp_path, country):
    payload = {} if country is None else {"country": country}
    assert sum(r["count"] for r in _respond(tmp_path, ORGS, payload)["All"]["organizations_by_size"]) == 7


@pytest.mark.parametrize("org_type, expected", [
    ("non_profit", {"small": 2, "medium": 2}),
    ("for_profit", {"small": 1, "large": 2}),
    ("Non-Profit", {"small": 2, "medium": 2}),
])
def test_organization_type_filter_only_counts_matching(tmp_path, org_type, expected):
    response = _respond(tmp_path, ORGS, {"organization_type": org_type})
    assert _sizes(response["All"]["organizations_by_size"]) == expected


@pytest.mark.parametrize("org_type", ["ALL", "all"])
def test_organization_type_all_counts_every_organization(tmp_path, org_type):
    response = _respond(tmp_path, ORGS, {"organization_type": org_type})
    assert sum(r["count"] for r in response["All"]["organizations_by_size"]) == 7


def test_filters_apply_to_custom_response(tmp_path):
    response = _respond(tmp_path, ORGS, {
        "country": "USA",
        "organization_type": "non_profit",
        "size_start_date": "2020-01-01", "size_end_date": "2026-12-31",
        "contribution_start_date": "2020-01-01", "contribution_end_date": "2026-12-31",
    })
    assert set(response) == {"Custom"}
    assert _sizes(response["Custom"]["organizations_by_size"]) == {"small": 2, "medium": 2}
    assert _cvc(response["Custom"]["collaborator_vs_contributor"])["Collaborator"] == (3, 75.0)


def test_country_with_no_organizations_returns_empty_arrays(tmp_path):
    response = _respond(tmp_path, ORGS, {"country": "GBR", "organization_type": "non_profit"})
    for bucket in ("7D", "30D", "1Y", "All", "Custom"):
        assert response[bucket] == EMPTY_BUCKET


@pytest.mark.parametrize("payload", [
    {"country": "Atlantis"},
    {"country": ""},
    {"country": 5},
    {"organization_type": "government"},
    {"organization_type": ""},
    {"organization_type": 1},
])
def test_invalid_filter_is_a_400(handler_env, payload):
    status, body = handler_env.call(payload)
    assert status == 400
    assert "error" in body


# ---------------------------------------------------------------------------
# Custom ranges
# ---------------------------------------------------------------------------

def test_only_size_range_returns_custom_only_with_size_populated(tmp_path):
    response = _respond(tmp_path, ORGS, {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"})
    assert set(response) == {"Custom"}
    assert _sizes(response["Custom"]["organizations_by_size"]) == {"small": 2, "medium": 2, "large": 1}
    assert response["Custom"]["collaborator_vs_contributor"] == []


def test_only_contribution_range_returns_custom_only_with_cvc_populated(tmp_path):
    response = _respond(tmp_path, ORGS, {
        "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31",
    })
    assert set(response) == {"Custom"}
    assert response["Custom"]["organizations_by_size"] == []
    assert _cvc(response["Custom"]["collaborator_vs_contributor"]) == {
        "Collaborator": (0, 0.0),
        "Contributor": (1, 100.0),
    }


def test_both_ranges_populate_both_charts_each_from_its_own_range(tmp_path):
    response = _respond(tmp_path, ORGS, {
        "size_start_date": "2024-01-01", "size_end_date": "2024-12-31",
        "contribution_start_date": "2026-06-01", "contribution_end_date": "2026-06-30",
    })
    assert set(response) == {"Custom"}
    assert set(response["Custom"]) == {"organizations_by_size", "collaborator_vs_contributor"}
    # size range: only O7
    assert response["Custom"]["organizations_by_size"] == [{"size": "small", "count": 1}]
    # contribution range: O1, O2, O3
    assert _cvc(response["Custom"]["collaborator_vs_contributor"]) == {
        "Collaborator": (1, 33.3),
        "Contributor": (2, 66.7),
    }


def test_both_ranges_via_handler(handler_env):
    status, body = handler_env.call({"body": json.dumps({
        "size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
        "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31",
    })})
    assert status == 200
    assert set(body) == {"Custom"}
    assert body["Custom"]["organizations_by_size"]
    assert body["Custom"]["collaborator_vs_contributor"]


def test_custom_range_is_inclusive_of_both_end_days(tmp_path):
    orgs = [
        ("A", "small", "TRUE", "TRUE", "non_profit", "US-TX", "2026-03-01"),
        ("B", "medium", "TRUE", "TRUE", "non_profit", "US-TX", "2026-03-31T23:30:00"),
        ("C", "large", "TRUE", "TRUE", "non_profit", "US-TX", "2026-04-01"),
        ("D", "large", "TRUE", "TRUE", "non_profit", "US-TX", "2026-02-28T23:59:59"),
    ]
    response = _respond(tmp_path, orgs, {"size_start_date": "2026-03-01", "size_end_date": "2026-03-31"})
    assert _sizes(response["Custom"]["organizations_by_size"]) == {"small": 1, "medium": 1}


def test_single_day_custom_range(tmp_path):
    response = _respond(tmp_path, ORGS, {
        "contribution_start_date": "2026-06-15", "contribution_end_date": "2026-06-15",
    })
    assert _cvc(response["Custom"]["collaborator_vs_contributor"]) == {
        "Collaborator": (1, 100.0),
        "Contributor": (1, 100.0),
    }


def test_custom_range_with_no_organizations_returns_empty_arrays(tmp_path):
    response = _respond(tmp_path, ORGS, {
        "size_start_date": "2000-01-01", "size_end_date": "2000-01-31",
        "contribution_start_date": "2000-01-01", "contribution_end_date": "2000-01-31",
    })
    assert response == {"Custom": EMPTY_BUCKET}


@pytest.mark.parametrize("payload", [
    {"size_start_date": "2026-01-01"},
    {"size_end_date": "2026-01-01"},
    {"contribution_start_date": "2025-01-01"},
    {"contribution_end_date": "2025-12-31"},
    {"size_start_date": "2026/01/01", "size_end_date": "2026-06-30"},
    {"size_start_date": "01-01-2026", "size_end_date": "2026-06-30"},
    {"contribution_start_date": "2025-02-30", "contribution_end_date": "2025-03-01"},
    {"contribution_start_date": "not-a-date", "contribution_end_date": "2025-03-01"},
    {"size_start_date": 20260101, "size_end_date": "2026-06-30"},
    {"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"},
    {"contribution_start_date": "2025-12-31", "contribution_end_date": "2025-01-01"},
    # one pair valid, the other malformed -> whole request fails, no partial result
    {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30", "contribution_start_date": "2025-01-01"},
    {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
     "contribution_start_date": "2025-12-31", "contribution_end_date": "2025-01-01"},
])
def test_malformed_or_incomplete_dates_return_400(handler_env, payload):
    status, body = handler_env.call(payload)
    assert status == 400
    assert set(body) == {"error"}


@pytest.mark.parametrize("event", [{"body": "{not json"}, {"body": "[1, 2]"}, {"body": 5}, "a string"])
def test_malformed_body_returns_400(handler_env, event):
    status, body = handler_env.call(event)
    assert status == 400
    assert "error" in body


def test_blank_date_pair_counts_as_not_supplied(tmp_path):
    response = _respond(tmp_path, ORGS, {"size_start_date": "", "size_end_date": "  "})
    assert set(response) == FIXED_KEYS


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bucket, inside_days, outside_days", [
    ("7D", [0, 6], [7]),
    ("30D", [0, 29], [30]),
])
def test_day_bucket_boundaries(tmp_path, bucket, inside_days, outside_days):
    days = inside_days + outside_days
    orgs = [
        (f"D{day}", "small", "TRUE", "TRUE", "non_profit", "US-TX",
         (REFERENCE - pd.Timedelta(days=day)).strftime("%Y-%m-%d"))
        for day in days
    ]
    rows = _respond(tmp_path, orgs)[bucket]["organizations_by_size"]
    assert rows == [{"size": "small", "count": len(inside_days)}]


def test_1y_bucket_boundary(tmp_path):
    orgs = [
        ("IN", "small", "TRUE", "TRUE", "non_profit", "US-TX", "2025-06-16"),
        ("OUT", "large", "TRUE", "TRUE", "non_profit", "US-TX", "2025-06-15"),
    ]
    assert _sizes(_respond(tmp_path, orgs)["1Y"]["organizations_by_size"]) == {"small": 1}


def test_org_created_later_on_reference_day_is_included(tmp_path):
    orgs = [("A", "small", "TRUE", "TRUE", "non_profit", "US-TX", "2026-06-15T22:00:00")]
    assert _respond(tmp_path, orgs)["7D"]["organizations_by_size"] == [{"size": "small", "count": 1}]


def test_timezone_aware_created_at_is_supported(tmp_path):
    orgs = [("A", "small", "TRUE", "TRUE", "non_profit", "US-TX", "2026-06-14T10:00:00+00:00")]
    assert _respond(tmp_path, orgs)["7D"]["organizations_by_size"] == [{"size": "small", "count": 1}]


def test_windows_are_snapshots_not_cumulative(tmp_path):
    response = _respond(tmp_path, ORGS)
    # O7 (2024) only counts in All, not in 1Y
    assert sum(r["count"] for r in response["1Y"]["organizations_by_size"]) == 6
    assert sum(r["count"] for r in response["All"]["organizations_by_size"]) == 7


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {},
    {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"},
    {"contribution_start_date": "2026-01-01", "contribution_end_date": "2026-06-30"},
    {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
     "contribution_start_date": "2026-01-01", "contribution_end_date": "2026-06-30"},
])
def test_empty_organizations_csv_does_not_crash(handler_env, tmp_path, payload):
    handler_env.write([])
    status, body = handler_env.call(payload)
    assert status == 200
    for bucket in body.values():
        assert bucket == EMPTY_BUCKET

    (tmp_path / "organizations.csv").write_text("")  # completely empty file, no header
    status, body = handler_env.call(payload)
    assert status == 200
    for bucket in body.values():
        assert bucket == EMPTY_BUCKET


@pytest.mark.parametrize("payload", [
    {},
    {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"},
    {"contribution_start_date": "2026-01-01", "contribution_end_date": "2026-06-30"},
])
def test_one_row_organizations_csv_does_not_crash(handler_env, payload):
    handler_env.write([("A", "small", "TRUE", "FALSE", "non_profit", "US-TX", "2026-06-14")])
    status, body = handler_env.call(payload)
    assert status == 200
    for bucket in body.values():
        assert set(bucket) == {"organizations_by_size", "collaborator_vs_contributor"}


def test_unparseable_created_at_is_skipped(tmp_path):
    orgs = [
        ("A", "small", "TRUE", "TRUE", "non_profit", "US-TX", "garbage"),
        ("B", "small", "TRUE", "TRUE", "non_profit", "US-TX", "2026-06-14"),
    ]
    assert _respond(tmp_path, orgs)["All"]["organizations_by_size"] == [{"size": "small", "count": 1}]


def test_org_with_unknown_state_counts_for_all_but_not_a_country(tmp_path):
    orgs = [("A", "small", "TRUE", "TRUE", "non_profit", "ZZ-XX", "2026-06-14")]
    assert _respond(tmp_path, orgs)["All"]["organizations_by_size"] == [{"size": "small", "count": 1}]
    assert _respond(tmp_path, orgs, {"country": "USA"})["All"] == EMPTY_BUCKET


def test_missing_required_column_returns_500(handler_env):
    header = [column for column in ORG_HEADER if column != "org_size"]
    handler_env.write([("A", "TRUE", "TRUE", "non_profit", "US-TX", "2026-06-14")], header=header)
    status, body = handler_env.call({})
    assert status == 500
    assert "error" in body


def test_missing_csv_directory_returns_500(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path / "missing"))
    assert sca.lambda_handler({}, None)["statusCode"] == 500


def test_invalid_request_is_rejected_before_loading_data(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path / "missing"))
    assert sca.lambda_handler({"size_start_date": "2026-01-01"}, None)["statusCode"] == 400


def test_real_db_path_without_psycopg2_returns_500(monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.setattr(sca, "psycopg2", None)
    result = sca.lambda_handler({}, None)
    assert result["statusCode"] == 500


def test_response_headers(handler_env):
    result = sca.lambda_handler({}, None, reference_date=REFERENCE)
    assert result["headers"]["Content-Type"] == "application/json"
    assert result["headers"]["Access-Control-Allow-Origin"] == "*"
