"""
Unit tests for rating_type_analytics.py (issue #380).

Each test writes small CSV fixtures under tmp_path and uses a fixed
reference date, so results don't depend on the wall-clock date. Run with:

    pytest data-analytics/lambda_functions/tests/test_rating_type_analytics.py
"""
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import rating_type_analytics as rta

REFERENCE = pd.Timestamp("2026-06-15")
FIXED_KEYS = {"7D", "30D", "1Y", "All", "Custom"}
EMPTY_BUCKET = {"rating_distribution": [], "organization_mix_trend": {"non_profit": [], "for_profit": []}}

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
ORG_HEADER = ["org_id", "org_rating", "org_type", "state_id", "created_at"]


def _write_csv(path, header, rows):
    lines = [",".join(header)] + [",".join(str(value) for value in row) for row in rows]
    path.write_text("\n".join(lines) + "\n")


def _write_files(tmp_path, organizations, states=STATES, countries=COUNTRIES):
    _write_csv(tmp_path / "organizations.csv", ORG_HEADER, organizations)
    _write_csv(tmp_path / "states.csv", ["state_id", "country_id"], states)
    _write_csv(tmp_path / "countries.csv", ["country_id", "country_code", "country_name"], countries)


def _load(tmp_path, organizations, **kwargs):
    _write_files(tmp_path, organizations, **kwargs)
    return rta.prepare_organizations(*rta.load_mock_tables(str(tmp_path)))


def _respond(tmp_path, organizations, payload=None, **kwargs):
    """Runs the full request path (validate -> load -> filter -> build)."""
    orgs, countries = _load(tmp_path, organizations, **kwargs)
    request = rta.parse_request(payload or {})
    orgs = rta.apply_country_filter(orgs, countries, request["country"])
    return rta.build_rating_type_response(orgs, request, reference_date=REFERENCE)


def _days_before(days):
    return (REFERENCE - pd.Timedelta(days=days)).strftime("%Y-%m-%d")


@pytest.fixture
def handler_env(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path))
    return tmp_path


def _call_handler(event):
    result = rta.lambda_handler(event, None, reference_date=REFERENCE)
    return result["statusCode"], json.loads(result["body"])


def _assert_bucket_shape(bucket):
    assert set(bucket) == {"rating_distribution", "organization_mix_trend"}
    assert set(bucket["organization_mix_trend"]) == {"non_profit", "for_profit"}


# ---------------------------------------------------------------------------
# No body -> exactly 5 keys, active buckets populated, Custom fully empty
# ---------------------------------------------------------------------------

def test_no_body_returns_five_keys_and_empty_custom(tmp_path):
    response = _respond(tmp_path, [
        ("ORG-1", 4, "non_profit", "US-TX", _days_before(40)),   # 1Y / All only
        ("ORG-2", 5, "for_profit", "IN-DL", _days_before(10)),   # 30D / 1Y / All
    ])

    assert set(response) == FIXED_KEYS
    for bucket in response.values():
        _assert_bucket_shape(bucket)

    assert response["7D"] == EMPTY_BUCKET
    assert response["30D"]["rating_distribution"] == [{"rating": 5, "count": 1}]
    assert response["30D"]["organization_mix_trend"] == {
        "non_profit": [],
        "for_profit": [{"period": _days_before(10), "count": 1}],
    }
    assert response["1Y"]["rating_distribution"] == [{"rating": 4, "count": 1}, {"rating": 5, "count": 1}]
    assert response["All"]["rating_distribution"] == [{"rating": 4, "count": 1}, {"rating": 5, "count": 1}]
    assert response["Custom"] == EMPTY_BUCKET


def test_handler_no_body_and_api_gateway_body(handler_env):
    _write_files(handler_env, [("ORG-1", 3, "non_profit", "US-TX", "2026-06-01")])

    for event in ({}, None, {"body": None}, {"body": ""}, {"body": "{}"}, {"body": {}}):
        status, body = _call_handler(event)
        assert status == 200
        assert set(body) == FIXED_KEYS

    status, body = _call_handler({"body": json.dumps({"rating_start_date": "2026-06-01",
                                                      "rating_end_date": "2026-06-01"})})
    assert status == 200
    assert body == {"Custom": {"rating_distribution": [{"rating": 3, "count": 1}],
                               "organization_mix_trend": {"non_profit": [], "for_profit": []}}}


def test_unknown_request_fields_are_ignored(tmp_path):
    response = _respond(tmp_path, [("ORG-1", 3, "non_profit", "US-TX", "2026-06-01")],
                        {"time_filter": "7D"})
    assert set(response) == FIXED_KEYS


# ---------------------------------------------------------------------------
# Country filter
# ---------------------------------------------------------------------------

COUNTRY_ORGS = [
    ("ORG-1", 5, "non_profit", "US-TX", "2026-06-01"),
    ("ORG-2", 4, "for_profit", "US-FL", "2026-06-02"),
    ("ORG-3", 2, "non_profit", "IN-DL", "2026-06-03"),
    ("ORG-4", 1, "for_profit", "GB-LDN", "2026-06-04"),
]


@pytest.mark.parametrize("country", ["USA", "usa", " USA ", "United_States", "united states", "United-States"])
def test_country_filter_by_code_or_name_only_counts_that_country(tmp_path, country):
    response = _respond(tmp_path, COUNTRY_ORGS, {"country": country})

    assert response["All"]["rating_distribution"] == [{"rating": 4, "count": 1}, {"rating": 5, "count": 1}]
    assert response["All"]["organization_mix_trend"] == {
        "non_profit": [{"period": "2026-06", "count": 1}],
        "for_profit": [{"period": "2026-06", "count": 1}],
    }


def test_country_filter_applies_to_custom_response(tmp_path):
    response = _respond(tmp_path, COUNTRY_ORGS, {
        "country": "IND",
        "rating_start_date": "2026-06-01", "rating_end_date": "2026-06-30",
        "type_start_date": "2026-06-01", "type_end_date": "2026-06-30",
    })

    assert response == {"Custom": {
        "rating_distribution": [{"rating": 2, "count": 1}],
        "organization_mix_trend": {"non_profit": [{"period": "2026-06-03", "count": 1}], "for_profit": []},
    }}


@pytest.mark.parametrize("country", ["ALL", "all", None])
def test_country_all_or_missing_counts_every_organization(tmp_path, country):
    payload = {} if country is None else {"country": country}
    response = _respond(tmp_path, COUNTRY_ORGS, payload)
    assert sum(row["count"] for row in response["All"]["rating_distribution"]) == 4


def test_country_with_no_organizations_returns_empty_arrays(tmp_path):
    response = _respond(tmp_path, [("ORG-1", 5, "non_profit", "US-TX", "2026-06-01")], {"country": "GBR"})
    assert set(response) == FIXED_KEYS
    for bucket in response.values():
        assert bucket == EMPTY_BUCKET


def test_org_with_unknown_state_counts_for_all_but_not_a_country(tmp_path):
    orgs = [("ORG-1", 5, "non_profit", "ZZ-XX", "2026-06-01")]
    assert _respond(tmp_path, orgs)["All"]["rating_distribution"] == [{"rating": 5, "count": 1}]
    assert _respond(tmp_path, orgs, {"country": "USA"})["All"]["rating_distribution"] == []


@pytest.mark.parametrize("country", ["Atlantis", "", "   ", 123, ["USA"]])
def test_invalid_country_is_a_400(handler_env, country):
    _write_files(handler_env, COUNTRY_ORGS)
    status, body = _call_handler({"country": country})
    assert status == 400
    assert "country" in body["error"].lower()


# ---------------------------------------------------------------------------
# Custom ranges: rating only / type only / both
# ---------------------------------------------------------------------------

CUSTOM_ORGS = [
    ("ORG-1", 3, "non_profit", "US-TX", "2025-03-10"),
    ("ORG-2", 4, "for_profit", "US-TX", "2025-03-10"),
    ("ORG-3", 5, "non_profit", "US-TX", "2026-02-01"),
    ("ORG-4", 5, "non_profit", "US-TX", "2026-04-15"),
]


def test_only_rating_range_returns_custom_only_with_rating_populated(tmp_path):
    response = _respond(tmp_path, CUSTOM_ORGS, {"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"})

    assert list(response) == ["Custom"]
    assert response["Custom"] == {
        "rating_distribution": [{"rating": 5, "count": 2}],
        "organization_mix_trend": {"non_profit": [], "for_profit": []},
    }


def test_only_type_range_returns_custom_only_with_mix_populated(tmp_path):
    response = _respond(tmp_path, CUSTOM_ORGS, {"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"})

    assert list(response) == ["Custom"]
    assert response["Custom"] == {
        "rating_distribution": [],
        "organization_mix_trend": {
            "non_profit": [{"period": "2025-03-10", "count": 1}],
            "for_profit": [{"period": "2025-03-10", "count": 1}],
        },
    }


def test_both_ranges_populate_both_charts_each_from_its_own_range(tmp_path):
    response = _respond(tmp_path, CUSTOM_ORGS, {
        "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
        "type_start_date": "2025-01-01", "type_end_date": "2025-12-31",
    })

    assert list(response) == ["Custom"]
    # rating range 2026 H1 -> only ORG-3 and ORG-4; type range 2025 -> only ORG-1 and ORG-2.
    assert response["Custom"]["rating_distribution"] == [{"rating": 5, "count": 2}]
    assert response["Custom"]["organization_mix_trend"] == {
        "non_profit": [{"period": "2025-03-10", "count": 1}],
        "for_profit": [{"period": "2025-03-10", "count": 1}],
    }


def test_custom_range_is_inclusive_of_both_end_days(tmp_path):
    orgs = [
        ("ORG-1", 1, "non_profit", "US-TX", "2026-01-01 00:00:00"),
        ("ORG-2", 2, "non_profit", "US-TX", "2026-01-31 23:59:59"),
        ("ORG-3", 3, "non_profit", "US-TX", "2026-02-01 00:00:00"),
        ("ORG-4", 4, "non_profit", "US-TX", "2025-12-31 23:59:59"),
    ]
    response = _respond(tmp_path, orgs, {"rating_start_date": "2026-01-01", "rating_end_date": "2026-01-31"})
    assert response["Custom"]["rating_distribution"] == [{"rating": 1, "count": 1}, {"rating": 2, "count": 1}]


def test_single_day_custom_range(tmp_path):
    response = _respond(tmp_path, CUSTOM_ORGS, {"type_start_date": "2026-04-15", "type_end_date": "2026-04-15"})
    assert response["Custom"]["organization_mix_trend"] == {
        "non_profit": [{"period": "2026-04-15", "count": 3}],
        "for_profit": [],
    }


def test_custom_range_with_no_organizations_returns_empty_arrays(tmp_path):
    response = _respond(tmp_path, CUSTOM_ORGS, {
        "rating_start_date": "2000-01-01", "rating_end_date": "2000-12-31",
        "type_start_date": "2000-01-01", "type_end_date": "2000-12-31",
    })
    assert response == {"Custom": EMPTY_BUCKET}


# ---------------------------------------------------------------------------
# Malformed / incomplete input -> 400, never a partial result or a crash
# ---------------------------------------------------------------------------

BAD_PAYLOADS = [
    {"rating_start_date": "2026-01-01"},
    {"rating_end_date": "2026-01-01"},
    {"type_start_date": "2026-01-01"},
    {"type_end_date": "2026-01-01"},
    {"rating_start_date": "2026-01-01", "rating_end_date": ""},
    {"rating_start_date": "2026/01/01", "rating_end_date": "2026-01-31"},
    {"type_start_date": "01-01-2025", "type_end_date": "2025-12-31"},
    {"type_start_date": "2025-01-01", "type_end_date": "not-a-date"},
    {"rating_start_date": "2026-02-30", "rating_end_date": "2026-03-01"},
    {"rating_start_date": "2026-01-01T00:00:00", "rating_end_date": "2026-01-31"},
    {"rating_start_date": 20260101, "rating_end_date": "2026-01-31"},
    {"rating_start_date": "2026-06-30", "rating_end_date": "2026-01-01"},
    {"type_start_date": "2025-12-31", "type_end_date": "2025-01-01"},
    # a valid pair must not rescue an invalid one - no partial result
    {"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30", "type_start_date": "2025-01-01"},
    {"rating_start_date": "2026-06-30", "rating_end_date": "2026-01-01",
     "type_start_date": "2025-01-01", "type_end_date": "2025-12-31"},
]


@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_malformed_or_incomplete_dates_return_400(handler_env, payload):
    _write_files(handler_env, CUSTOM_ORGS)
    status, body = _call_handler(payload)
    assert status == 400
    assert set(body) == {"error"}
    assert body["error"]


@pytest.mark.parametrize("event", [{"body": "{not json"}, {"body": "[1, 2]"}, {"body": 42}, "not-a-dict"])
def test_malformed_body_returns_400(handler_env, event):
    _write_files(handler_env, CUSTOM_ORGS)
    status, body = _call_handler(event)
    assert status == 400
    assert "error" in body


def test_blank_date_pair_counts_as_not_supplied(tmp_path):
    response = _respond(tmp_path, CUSTOM_ORGS, {"rating_start_date": "", "rating_end_date": None})
    assert set(response) == FIXED_KEYS


# ---------------------------------------------------------------------------
# organization_mix_trend semantics: cumulative, all-time, sparse, per type
# ---------------------------------------------------------------------------

def test_mix_trend_is_all_time_cumulative_and_sparse(tmp_path):
    orgs = [
        ("ORG-1", 5, "non_profit", "US-TX", "2020-01-01"),   # before every window except All
        ("ORG-2", 5, "non_profit", "US-TX", "2020-01-02"),
        ("ORG-3", 4, "non_profit", "US-TX", _days_before(20)),
        ("ORG-4", 4, "non_profit", "US-TX", _days_before(20)),
        ("ORG-5", 3, "non_profit", "US-TX", _days_before(5)),
        ("ORG-6", 3, "for_profit", "US-TX", _days_before(3)),
    ]
    response = _respond(tmp_path, orgs)

    # 30D starts from the all-time total (2 older orgs), and quiet days are omitted.
    assert response["30D"]["organization_mix_trend"] == {
        "non_profit": [{"period": _days_before(20), "count": 4}, {"period": _days_before(5), "count": 5}],
        "for_profit": [{"period": _days_before(3), "count": 1}],
    }
    assert response["7D"]["organization_mix_trend"] == {
        "non_profit": [{"period": _days_before(5), "count": 5}],
        "for_profit": [{"period": _days_before(3), "count": 1}],
    }
    # rating_distribution stays window-scoped (not cumulative).
    assert response["7D"]["rating_distribution"] == [{"rating": 3, "count": 2}]


def test_mix_trend_counts_are_non_decreasing_in_every_bucket(tmp_path):
    orgs = [
        (f"ORG-{i}", (i % 5) + 1, "non_profit" if i % 3 else "for_profit", "US-TX", _days_before(i * 11))
        for i in range(60)
    ]
    response = _respond(tmp_path, orgs)
    for bucket in response.values():
        for series in bucket["organization_mix_trend"].values():
            counts = [point["count"] for point in series]
            assert counts == sorted(counts)
            periods = [point["period"] for point in series]
            assert periods == sorted(periods) and len(periods) == len(set(periods))


def test_period_formats_per_bucket(tmp_path):
    response = _respond(tmp_path, [("ORG-1", 5, "for_profit", "US-TX", _days_before(2))])
    assert response["7D"]["organization_mix_trend"]["for_profit"][0]["period"] == _days_before(2)
    assert response["30D"]["organization_mix_trend"]["for_profit"][0]["period"] == _days_before(2)
    assert response["1Y"]["organization_mix_trend"]["for_profit"][0]["period"] == _days_before(2)[:7]
    assert response["All"]["organization_mix_trend"]["for_profit"][0]["period"] == _days_before(2)[:7]

    custom = _respond(tmp_path, [("ORG-1", 5, "for_profit", "US-TX", "2025-03-09")],
                      {"type_start_date": "2025-03-01", "type_end_date": "2025-03-31"})
    assert custom["Custom"]["organization_mix_trend"]["for_profit"] == [{"period": "2025-03-09", "count": 1}]


def test_monthly_running_total_includes_the_whole_month(tmp_path):
    orgs = [
        ("ORG-1", 5, "non_profit", "US-TX", "2026-05-02"),
        ("ORG-2", 5, "non_profit", "US-TX", "2026-05-31 18:00:00"),
    ]
    response = _respond(tmp_path, orgs)
    assert response["All"]["organization_mix_trend"]["non_profit"] == [{"period": "2026-05", "count": 2}]


def test_org_type_variants_are_normalized_and_others_excluded_from_mix(tmp_path):
    orgs = [
        ("ORG-1", 5, "Non-Profit", "US-TX", "2026-06-01"),
        ("ORG-2", 4, "For-profit", "US-TX", "2026-06-02"),
        ("ORG-3", 3, "Community Group", "US-TX", "2026-06-03"),
        ("ORG-4", 2, "", "US-TX", "2026-06-04"),
    ]
    response = _respond(tmp_path, orgs)
    assert response["All"]["organization_mix_trend"] == {
        "non_profit": [{"period": "2026-06", "count": 1}],
        "for_profit": [{"period": "2026-06", "count": 1}],
    }
    # Every org still has a valid rating, so all four count in the rating chart.
    assert sum(row["count"] for row in response["All"]["rating_distribution"]) == 4


# ---------------------------------------------------------------------------
# rating_distribution semantics
# ---------------------------------------------------------------------------

def test_rating_distribution_uses_literal_integer_and_no_zero_fill(tmp_path):
    orgs = [
        ("ORG-1", "5", "non_profit", "US-TX", "2026-06-01"),
        ("ORG-2", "5.0", "non_profit", "US-TX", "2026-06-01"),
        ("ORG-3", "2", "for_profit", "US-TX", "2026-06-01"),
        ("ORG-4", "4.5", "for_profit", "US-TX", "2026-06-01"),   # not an integer - not rounded
        ("ORG-5", "0", "for_profit", "US-TX", "2026-06-01"),     # out of range
        ("ORG-6", "6", "for_profit", "US-TX", "2026-06-01"),     # out of range
        ("ORG-7", "", "for_profit", "US-TX", "2026-06-01"),      # missing
        ("ORG-8", "abc", "for_profit", "US-TX", "2026-06-01"),   # garbage
    ]
    response = _respond(tmp_path, orgs)

    assert response["All"]["rating_distribution"] == [{"rating": 2, "count": 1}, {"rating": 5, "count": 2}]
    # Orgs with an unusable rating still count toward the type chart.
    assert response["All"]["organization_mix_trend"]["for_profit"] == [{"period": "2026-06", "count": 6}]


def test_rating_distribution_is_sorted_by_rating(tmp_path):
    orgs = [(f"ORG-{r}", r, "non_profit", "US-TX", "2026-06-01") for r in (5, 1, 3, 4, 2)]
    ratings = [row["rating"] for row in _respond(tmp_path, orgs)["All"]["rating_distribution"]]
    assert ratings == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# Fixed-bucket window boundaries (exactly 7 / 30 days, exactly 1 year)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bucket, inside_days, outside_days", [
    ("7D", 6, 7),
    ("30D", 29, 30),
])
def test_day_bucket_boundaries(tmp_path, bucket, inside_days, outside_days):
    orgs = [
        ("ORG-IN", 5, "non_profit", "US-TX", _days_before(inside_days)),
        ("ORG-OUT", 1, "non_profit", "US-TX", _days_before(outside_days)),
    ]
    assert _respond(tmp_path, orgs)[bucket]["rating_distribution"] == [{"rating": 5, "count": 1}]


def test_1y_bucket_boundary(tmp_path):
    orgs = [
        ("ORG-IN", 5, "non_profit", "US-TX", "2025-06-16"),
        ("ORG-OUT", 1, "non_profit", "US-TX", "2025-06-15"),
    ]
    assert _respond(tmp_path, orgs)["1Y"]["rating_distribution"] == [{"rating": 5, "count": 1}]


def test_org_created_later_on_reference_day_is_included(tmp_path):
    orgs = [("ORG-1", 5, "non_profit", "US-TX", "2026-06-15 21:30:00")]
    assert _respond(tmp_path, orgs)["7D"]["rating_distribution"] == [{"rating": 5, "count": 1}]


def test_timezone_aware_created_at_is_supported(tmp_path):
    orgs = [("ORG-1", 5, "non_profit", "US-TX", "2026-06-14T10:00:00+00:00")]
    response = _respond(tmp_path, orgs)
    assert response["7D"]["organization_mix_trend"]["non_profit"] == [{"period": "2026-06-14", "count": 1}]


# ---------------------------------------------------------------------------
# Empty / 1-row data and data-source failures
# ---------------------------------------------------------------------------

ALL_REQUEST_SHAPES = [
    {},
    {"country": "USA"},
    {"rating_start_date": "2026-01-01", "rating_end_date": "2026-12-31"},
    {"type_start_date": "2026-01-01", "type_end_date": "2026-12-31"},
    {"rating_start_date": "2026-01-01", "rating_end_date": "2026-12-31",
     "type_start_date": "2026-01-01", "type_end_date": "2026-12-31"},
]


@pytest.mark.parametrize("payload", ALL_REQUEST_SHAPES)
def test_empty_organizations_csv_does_not_crash(handler_env, payload):
    _write_files(handler_env, [])
    status, body = _call_handler(payload)
    assert status == 200
    for bucket in body.values():
        assert bucket == EMPTY_BUCKET


@pytest.mark.parametrize("payload", ALL_REQUEST_SHAPES)
def test_one_row_organizations_csv_does_not_crash(handler_env, payload):
    _write_files(handler_env, [("ORG-1", 4, "for_profit", "US-TX", "2026-06-10")])
    status, body = _call_handler(payload)
    assert status == 200
    for bucket in body.values():
        _assert_bucket_shape(bucket)


def test_unparseable_created_at_is_skipped(tmp_path):
    orgs = [
        ("ORG-1", 5, "non_profit", "US-TX", "not-a-date"),
        ("ORG-2", 4, "non_profit", "US-TX", "2026-06-01"),
    ]
    assert _respond(tmp_path, orgs)["All"]["rating_distribution"] == [{"rating": 4, "count": 1}]


def test_missing_required_column_returns_500(handler_env):
    _write_csv(handler_env / "organizations.csv", ["org_id", "org_type", "state_id", "created_at"],
               [("ORG-1", "non_profit", "US-TX", "2026-06-01")])
    _write_csv(handler_env / "states.csv", ["state_id", "country_id"], STATES)
    _write_csv(handler_env / "countries.csv", ["country_id", "country_code"], [("1", "USA")])
    status, body = _call_handler({})
    assert status == 500
    assert body == {"error": "Failed to load organization data"}


def test_missing_csv_directory_returns_500(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path / "does-not-exist"))
    status, _ = _call_handler({})
    assert status == 500


def test_invalid_request_is_rejected_before_loading_data(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path / "does-not-exist"))
    status, _ = _call_handler({"rating_start_date": "2026-01-01"})
    assert status == 400


def test_real_db_path_without_psycopg2_returns_500(monkeypatch):
    monkeypatch.setenv("USE_MOCK_DATA", "false")
    monkeypatch.setattr(rta, "psycopg2", None)
    status, body = _call_handler({})
    assert status == 500
    assert body == {"error": "Failed to load organization data"}


def test_response_headers(handler_env):
    _write_files(handler_env, [])
    result = rta.lambda_handler({}, None, reference_date=REFERENCE)
    assert result["headers"] == {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
