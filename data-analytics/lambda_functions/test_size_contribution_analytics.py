"""Pytest suite for the Size & Contribution Analytics Lambda (Issue #376).

Covers, against ``size_contribution_analytics.py``:
    * the no-Custom fixed-bucket response shape (exactly 5 top-level keys)
    * ``organizations_by_size()`` grouping/edge-case behavior
    * ``collaborator_vs_contributor()`` independent-count/edge-case behavior
    * ``country`` / ``organization_type`` common filters (by code, by name,
      ``ALL``, and applied before windowing)
    * the ``7D``/``30D``/``1Y``/``All`` fixed-window boundaries
    * the Custom-only response branching (size-only / contribution-only /
      both pairs together)
    * ``validate_date_pair`` error handling, end-to-end through
      ``lambda_handler`` (HTTP 400)
    * ``lambda_handler`` request parsing (direct invocation, API Gateway
      JSON-string body, ``body=None``, malformed JSON) and safe error
      responses (HTTP 500 without leaking paths/credentials/stack traces)
    * ``load_mock_data()`` against small, temporary, never-committed CSVs
    * assorted edge cases (empty data, one row, missing columns, NaN dates,
      string-encoded booleans)

All tests use small in-memory pandas DataFrames or tiny CSVs written to
pytest's ``tmp_path`` fixture -- nothing here reads the real
``data-analytics/mock-data-generation/`` CSVs, touches AWS, or opens a real
database connection. A fixed ``reference_date`` is injected everywhere a
"now" is needed, so every test is deterministic regardless of the day it's
run.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

# Make the sibling module importable regardless of the pytest invocation's
# working directory (this directory has no __init__.py, so it isn't a
# package -- pytest's default "prepend" import mode normally handles this,
# but we make it explicit/robust here).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import size_contribution_analytics as sca  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

REFERENCE_DATE = datetime(2026, 10, 6, 12, 0, 0)


@pytest.fixture
def reference_date() -> datetime:
    """A fixed, deterministic 'now' so every window-boundary test is stable."""
    return REFERENCE_DATE


def make_orgs_df(rows: list) -> pd.DataFrame:
    """Build an organizations-shaped DataFrame, parsing created_at like
    load_mock_data() does (errors="coerce" -> invalid/missing become NaT).
    """
    df = pd.DataFrame(rows)
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    return df


@pytest.fixture
def mixed_window_df(reference_date):
    """Rows spanning every fixed bucket boundary, two countries, two org
    types, and one NaT created_at row -- used for the full-response and
    filter-ordering tests.
    """
    ref = reference_date
    return make_orgs_df(
        [
            # Inside 7D (today - 1 day)
            dict(org_size="small", is_collaborator=True, is_contributor=False,
                 created_at=ref - timedelta(days=1), org_type="non_profit",
                 country_code="USA", country_name="UNITED_STATES"),
            # Exactly at the 7D lower boundary (today - 6 days, midnight)
            dict(org_size="small", is_collaborator=False, is_contributor=True,
                 created_at=datetime.combine((ref - timedelta(days=6)).date(), datetime.min.time()),
                 org_type="non_profit", country_code="USA", country_name="UNITED_STATES"),
            # Exactly at "today" (upper boundary)
            dict(org_size="medium", is_collaborator=True, is_contributor=True,
                 created_at=datetime.combine(ref.date(), datetime.min.time()),
                 org_type="for_profit", country_code="IND", country_name="INDIA"),
            # Inside 30D but outside 7D
            dict(org_size="large", is_collaborator=False, is_contributor=False,
                 created_at=ref - timedelta(days=15), org_type="non_profit",
                 country_code="USA", country_name="UNITED_STATES"),
            # Inside 1Y but outside 30D
            dict(org_size="medium", is_collaborator=True, is_contributor=False,
                 created_at=ref - timedelta(days=200), org_type="non_profit",
                 country_code="USA", country_name="UNITED_STATES"),
            # Outside 1Y, only in "All"
            dict(org_size="small", is_collaborator=False, is_contributor=False,
                 created_at=ref - pd.DateOffset(years=2), org_type="non_profit",
                 country_code="USA", country_name="UNITED_STATES"),
            # Missing/invalid created_at -> NaT; excluded from bounded windows,
            # included only in "All"
            dict(org_size="large", is_collaborator=True, is_contributor=True,
                 created_at=None, org_type="non_profit",
                 country_code="USA", country_name="UNITED_STATES"),
        ]
    )


# ---------------------------------------------------------------------------
# 1. No-Custom response shape
# ---------------------------------------------------------------------------

class TestNoCustomResponseShape:
    def test_exactly_five_top_level_keys(self, mixed_window_df, reference_date):
        response = sca.build_size_contribution_response(mixed_window_df, reference_date=reference_date)
        assert set(response.keys()) == {"7D", "30D", "1Y", "All", "Custom"}

    def test_each_bucket_has_exactly_two_chart_keys(self, mixed_window_df, reference_date):
        response = sca.build_size_contribution_response(mixed_window_df, reference_date=reference_date)
        for bucket in ("7D", "30D", "1Y", "All", "Custom"):
            assert set(response[bucket].keys()) == {"organizations_by_size", "collaborator_vs_contributor"}

    def test_custom_is_empty_when_no_custom_params_given(self, mixed_window_df, reference_date):
        response = sca.build_size_contribution_response(mixed_window_df, reference_date=reference_date)
        assert response["Custom"] == {"organizations_by_size": [], "collaborator_vs_contributor": []}


# ---------------------------------------------------------------------------
# 2. organizations_by_size
# ---------------------------------------------------------------------------

class TestOrganizationsBySize:
    def test_groups_by_org_size(self):
        df = make_orgs_df([
            dict(org_size="small"), dict(org_size="small"),
            dict(org_size="medium"), dict(org_size="large"),
            dict(org_size="large"), dict(org_size="large"),
        ])
        result = sca.organizations_by_size(df)
        as_dict = {row["size"]: row["count"] for row in result}
        assert as_dict == {"small": 2, "medium": 1, "large": 3}

    def test_does_not_hardcode_categories_single_category_present(self):
        """Only 'medium' present -> 'small'/'large' must NOT be zero-filled."""
        df = make_orgs_df([dict(org_size="medium"), dict(org_size="medium")])
        result = sca.organizations_by_size(df)
        assert result == [{"size": "medium", "count": 2}]

    def test_does_not_hardcode_categories_unexpected_category(self):
        """An org_size value outside small/medium/large must still appear
        as-is -- proves the categories aren't a hardcoded allow-list."""
        df = make_orgs_df([dict(org_size="extra_large"), dict(org_size="extra_large")])
        result = sca.organizations_by_size(df)
        assert result == [{"size": "extra_large", "count": 2}]

    def test_empty_dataframe_returns_empty_list(self):
        df = make_orgs_df([])
        if "org_size" not in df.columns:
            df["org_size"] = pd.Series(dtype="object")
        assert sca.organizations_by_size(df) == []

    def test_missing_org_size_column_returns_empty_list(self):
        df = make_orgs_df([dict(org_type="non_profit")])
        assert sca.organizations_by_size(df) == []

    def test_nan_org_size_values_are_dropped_not_counted(self):
        df = make_orgs_df([dict(org_size="small"), dict(org_size=None), dict(org_size="small")])
        result = sca.organizations_by_size(df)
        assert result == [{"size": "small", "count": 2}]

    def test_counts_sum_to_total_rows_in_window(self):
        rows = [dict(org_size=s) for s in ["small", "small", "medium", "large", "large", "large", "large"]]
        df = make_orgs_df(rows)
        result = sca.organizations_by_size(df)
        assert sum(r["count"] for r in result) == len(df)


# ---------------------------------------------------------------------------
# 3. collaborator_vs_contributor
# ---------------------------------------------------------------------------

class TestCollaboratorVsContributor:
    def test_always_returns_exactly_two_rows_in_order(self):
        df = make_orgs_df([dict(is_collaborator=True, is_contributor=False)])
        result = sca.collaborator_vs_contributor(df)
        assert len(result) == 2
        assert result[0]["type"] == "Collaborator"
        assert result[1]["type"] == "Contributor"

    def test_independent_counts_not_a_complement(self):
        """5 orgs: overlapping/neither -- Collaborator and Contributor must
        each be computed independently, not summing to the total or to each
        other's complement."""
        df = make_orgs_df([
            dict(is_collaborator=True, is_contributor=True),   # both
            dict(is_collaborator=True, is_contributor=False),  # collaborator only
            dict(is_collaborator=False, is_contributor=False), # neither
            dict(is_collaborator=True, is_contributor=True),   # both
            dict(is_collaborator=False, is_contributor=True),  # contributor only
        ])
        result = sca.collaborator_vs_contributor(df)
        by_type = {r["type"]: r for r in result}
        assert by_type["Collaborator"]["count"] == 3
        assert by_type["Contributor"]["count"] == 3
        # Not complementary: both counts are 3 out of 5, not summing to 5.
        assert by_type["Collaborator"]["count"] + by_type["Contributor"]["count"] != len(df)

    def test_percentages_use_filtered_window_total_rounded_to_one_decimal(self):
        df = make_orgs_df([
            dict(is_collaborator=True, is_contributor=False),
            dict(is_collaborator=False, is_contributor=False),
            dict(is_collaborator=False, is_contributor=False),
        ])
        result = sca.collaborator_vs_contributor(df)
        by_type = {r["type"]: r for r in result}
        assert by_type["Collaborator"]["count"] == 1
        assert by_type["Collaborator"]["percentage"] == pytest.approx(33.3)
        assert by_type["Contributor"]["count"] == 0
        assert by_type["Contributor"]["percentage"] == 0.0

    def test_missing_is_contributor_column_yields_zero_count_and_percentage(self):
        df = make_orgs_df([dict(is_collaborator=True), dict(is_collaborator=False)])
        assert "is_contributor" not in df.columns
        result = sca.collaborator_vs_contributor(df)
        by_type = {r["type"]: r for r in result}
        assert by_type["Contributor"] == {"type": "Contributor", "count": 0, "percentage": 0.0}
        # Collaborator must still be computed correctly despite the missing column.
        assert by_type["Collaborator"]["count"] == 1

    def test_empty_dataframe_does_not_crash_and_returns_zero_rows(self):
        df = make_orgs_df([])
        result = sca.collaborator_vs_contributor(df)
        assert result == [
            {"type": "Collaborator", "count": 0, "percentage": 0.0},
            {"type": "Contributor", "count": 0, "percentage": 0.0},
        ]

    @pytest.mark.parametrize(
        "collab_values,contrib_values,expected_collab,expected_contrib",
        [
            ([True, False, True], [False, True, True], 2, 2),
            (["True", "false", "TRUE"], ["yes", "no", "YES"], 2, 2),
            (["1", "0", "1"], ["0", "1", "1"], 2, 2),
            (["yes", "no", "Yes"], ["No", "yes", "no"], 2, 1),
        ],
    )
    def test_string_boolean_forms_are_handled_safely(
        self, collab_values, contrib_values, expected_collab, expected_contrib
    ):
        df = make_orgs_df([
            dict(is_collaborator=c, is_contributor=k)
            for c, k in zip(collab_values, contrib_values)
        ])
        result = sca.collaborator_vs_contributor(df)
        by_type = {r["type"]: r for r in result}
        assert by_type["Collaborator"]["count"] == expected_collab
        assert by_type["Contributor"]["count"] == expected_contrib


# ---------------------------------------------------------------------------
# 4. Common filters (country / organization_type)
# ---------------------------------------------------------------------------

class TestCommonFilters:
    @pytest.fixture
    def countries_df(self):
        return make_orgs_df([
            dict(org_size="small", org_type="non_profit", country_code="USA", country_name="UNITED_STATES"),
            dict(org_size="medium", org_type="for_profit", country_code="IND", country_name="INDIA"),
            dict(org_size="large", org_type="non_profit", country_code="usa", country_name="united_states"),
        ])

    def test_filter_by_country_code(self, countries_df):
        result = sca.filter_by_country(countries_df, "USA")
        assert len(result) == 2

    def test_filter_by_country_name(self, countries_df):
        result = sca.filter_by_country(countries_df, "united_states")
        assert len(result) == 2

    def test_filter_by_country_code_and_name_agree(self, countries_df):
        by_code = sca.filter_by_country(countries_df, "IND")
        by_name = sca.filter_by_country(countries_df, "INDIA")
        assert len(by_code) == len(by_name) == 1

    def test_country_all_means_no_filtering(self, countries_df):
        assert len(sca.filter_by_country(countries_df, "ALL")) == len(countries_df)
        assert len(sca.filter_by_country(countries_df, "all")) == len(countries_df)
        assert len(sca.filter_by_country(countries_df, None)) == len(countries_df)

    def test_filter_by_organization_type(self, countries_df):
        assert len(sca.filter_by_organization_type(countries_df, "non_profit")) == 2
        assert len(sca.filter_by_organization_type(countries_df, "FOR_PROFIT")) == 1

    def test_organization_type_all_means_no_filtering(self, countries_df):
        assert len(sca.filter_by_organization_type(countries_df, "ALL")) == len(countries_df)
        assert len(sca.filter_by_organization_type(countries_df, None)) == len(countries_df)

    def test_filters_apply_before_date_window_calculation(self, mixed_window_df, reference_date):
        """A country filter must narrow every bucket's data, including the
        fixed time windows -- proving filtering happens ahead of (or
        together with, but never after/independently of) windowing."""
        response = sca.build_size_contribution_response(
            mixed_window_df, country="IND", reference_date=reference_date
        )
        # Only the single India row (medium, created exactly at "today")
        # should appear in every bucket that includes "today".
        for bucket in ("7D", "30D", "1Y", "All"):
            assert response[bucket]["organizations_by_size"] == [{"size": "medium", "count": 1}]

        response_type = sca.build_size_contribution_response(
            mixed_window_df, organization_type="for_profit", reference_date=reference_date
        )
        for bucket in ("7D", "30D", "1Y", "All"):
            assert response_type[bucket]["organizations_by_size"] == [{"size": "medium", "count": 1}]


# ---------------------------------------------------------------------------
# 5. Fixed date-window boundaries
# ---------------------------------------------------------------------------

class TestFixedWindowBoundaries:
    def test_7d_spans_exactly_seven_calendar_dates_including_today(self, reference_date):
        start, end = sca.get_window_bounds("7D", reference_date)
        assert (end.date() - start.date()).days + 1 == 7
        assert end.date() == reference_date.date()

    def test_30d_spans_exactly_thirty_calendar_dates_including_today(self, reference_date):
        start, end = sca.get_window_bounds("30D", reference_date)
        assert (end.date() - start.date()).days + 1 == 30
        assert end.date() == reference_date.date()

    def test_1y_uses_calendar_year_offset(self, reference_date):
        start, end = sca.get_window_bounds("1Y", reference_date)
        assert start.date() == (reference_date - pd.DateOffset(years=1)).date()
        assert end.date() == reference_date.date()

    def test_all_bucket_is_unbounded(self, reference_date):
        assert sca.get_window_bounds("All", reference_date) is None

    def test_unknown_bucket_raises(self, reference_date):
        with pytest.raises(ValueError):
            sca.get_window_bounds("Bogus", reference_date)

    def test_row_at_exact_lower_boundary_is_included(self, reference_date):
        start, _ = sca.get_window_bounds("7D", reference_date)
        df = make_orgs_df([dict(org_size="medium", created_at=start)])
        windowed = sca.filter_by_created_at_window(df, *sca.get_window_bounds("7D", reference_date))
        assert len(windowed) == 1

    def test_row_just_before_lower_boundary_is_excluded(self, reference_date):
        start, _ = sca.get_window_bounds("7D", reference_date)
        just_before = start - timedelta(microseconds=1)
        df = make_orgs_df([dict(org_size="medium", created_at=just_before)])
        windowed = sca.filter_by_created_at_window(df, *sca.get_window_bounds("7D", reference_date))
        assert len(windowed) == 0

    def test_row_at_exact_upper_boundary_today_is_included(self, reference_date):
        df = make_orgs_df([dict(org_size="medium", created_at=reference_date)])
        windowed = sca.filter_by_created_at_window(df, *sca.get_window_bounds("7D", reference_date))
        assert len(windowed) == 1

    def test_future_dated_record_excluded_from_bounded_windows(self, reference_date):
        tomorrow = reference_date + timedelta(days=1)
        df = make_orgs_df([dict(org_size="medium", created_at=tomorrow)])
        for bucket in ("7D", "30D", "1Y"):
            start, end = sca.get_window_bounds(bucket, reference_date)
            windowed = sca.filter_by_created_at_window(df, start, end)
            assert len(windowed) == 0, f"future-dated row leaked into {bucket}"

    def test_record_outside_7d_excluded_but_inside_30d_included(self, mixed_window_df, reference_date):
        response = sca.build_size_contribution_response(mixed_window_df, reference_date=reference_date)
        sizes_7d = {r["size"]: r["count"] for r in response["7D"]["organizations_by_size"]}
        sizes_30d = {r["size"]: r["count"] for r in response["30D"]["organizations_by_size"]}
        # The -15-day "large" row is outside 7D (only spans 7 days back) ...
        assert "large" not in sizes_7d or sizes_7d.get("large", 0) == 0
        # ... but inside 30D.
        assert sizes_30d.get("large", 0) >= 1

    def test_windows_are_not_cumulative(self, mixed_window_df, reference_date):
        """Each bucket must be a window-scoped snapshot, not cumulative --
        30D's total organization count must differ from (be >=) 7D's, and
        All must differ from 1Y, given rows designed to only appear in one
        or the other."""
        response = sca.build_size_contribution_response(mixed_window_df, reference_date=reference_date)
        total_7d = sum(r["count"] for r in response["7D"]["organizations_by_size"])
        total_30d = sum(r["count"] for r in response["30D"]["organizations_by_size"])
        total_1y = sum(r["count"] for r in response["1Y"]["organizations_by_size"])
        total_all = sum(r["count"] for r in response["All"]["organizations_by_size"])
        assert total_7d < total_30d < total_1y < total_all


# ---------------------------------------------------------------------------
# 6. Custom response behavior
# ---------------------------------------------------------------------------

class TestCustomResponseBehavior:
    def test_size_only_returns_custom_only_with_size_populated(self, mixed_window_df, reference_date):
        response = sca.build_size_contribution_response(
            mixed_window_df, reference_date=reference_date,
            size_start_date="2024-01-01", size_end_date="2026-10-06",
        )
        assert set(response.keys()) == {"Custom"}
        assert len(response["Custom"]["organizations_by_size"]) > 0
        assert response["Custom"]["collaborator_vs_contributor"] == []

    def test_contribution_only_returns_custom_only_with_contribution_populated(self, mixed_window_df, reference_date):
        response = sca.build_size_contribution_response(
            mixed_window_df, reference_date=reference_date,
            contribution_start_date="2024-01-01", contribution_end_date="2026-10-06",
        )
        assert set(response.keys()) == {"Custom"}
        assert response["Custom"]["organizations_by_size"] == []
        assert len(response["Custom"]["collaborator_vs_contributor"]) == 2

    def test_both_pairs_populate_both_charts_independently(self, mixed_window_df, reference_date):
        response = sca.build_size_contribution_response(
            mixed_window_df, reference_date=reference_date,
            size_start_date="2024-01-01", size_end_date="2026-10-06",
            contribution_start_date="2026-09-29", contribution_end_date="2026-10-06",
        )
        assert set(response.keys()) == {"Custom"}
        assert len(response["Custom"]["organizations_by_size"]) > 0
        assert len(response["Custom"]["collaborator_vs_contributor"]) == 2

        # The two ranges are different widths -- confirm they really were
        # evaluated independently, not one dropped/overwritten by the other.
        size_only = sca.build_size_contribution_response(
            mixed_window_df, reference_date=reference_date,
            size_start_date="2024-01-01", size_end_date="2026-10-06",
        )
        assert response["Custom"]["organizations_by_size"] == size_only["Custom"]["organizations_by_size"]

    def test_inclusive_custom_end_date_includes_whole_end_day(self):
        df = make_orgs_df([dict(org_size="small", created_at=datetime(2026, 6, 30, 23, 59, 0))])
        response = sca.build_size_contribution_response(
            df, size_start_date="2026-01-01", size_end_date="2026-06-30",
        )
        assert response["Custom"]["organizations_by_size"] == [{"size": "small", "count": 1}]


# ---------------------------------------------------------------------------
# 7. Date-pair validation
# ---------------------------------------------------------------------------

class TestDatePairValidation:
    def test_neither_date_supplied_returns_none(self):
        assert sca.validate_date_pair(None, None) is None
        assert sca.validate_date_pair("", "") is None

    def test_valid_pair_returns_parsed_tuple(self):
        result = sca.validate_date_pair("2026-01-01", "2026-06-30")
        assert result == (datetime(2026, 1, 1), datetime(2026, 6, 30))

    def test_missing_start_raises(self):
        with pytest.raises(sca.DateRangeError):
            sca.validate_date_pair(None, "2026-06-30")

    def test_missing_end_raises(self):
        with pytest.raises(sca.DateRangeError):
            sca.validate_date_pair("2026-01-01", None)

    def test_malformed_date_raises(self):
        with pytest.raises(sca.DateRangeError):
            sca.validate_date_pair("not-a-date", "2026-06-30")

    def test_start_after_end_raises(self):
        with pytest.raises(sca.DateRangeError):
            sca.validate_date_pair("2026-06-30", "2026-01-01")

    def test_date_range_error_is_a_value_error_subclass(self):
        assert issubclass(sca.DateRangeError, ValueError)

    # --- End-to-end through lambda_handler -> HTTP 400 --------------------

    def test_missing_half_of_pair_returns_400_via_lambda_handler(self, monkeypatch):
        monkeypatch.setattr(sca, "load_mock_data", lambda: make_orgs_df([dict(org_size="small")]))
        result = sca.lambda_handler({"body": json.dumps({"size_start_date": "2026-01-01"})}, None)
        assert result["statusCode"] == 400
        assert "error" in result["body"]

    def test_malformed_date_returns_400_via_lambda_handler(self, monkeypatch):
        monkeypatch.setattr(sca, "load_mock_data", lambda: make_orgs_df([dict(org_size="small")]))
        result = sca.lambda_handler(
            {"body": json.dumps({"contribution_start_date": "2026-13-40", "contribution_end_date": "2026-01-01"})},
            None,
        )
        assert result["statusCode"] == 400

    def test_start_after_end_returns_400_via_lambda_handler(self, monkeypatch):
        monkeypatch.setattr(sca, "load_mock_data", lambda: make_orgs_df([dict(org_size="small")]))
        result = sca.lambda_handler(
            {"body": json.dumps({"size_start_date": "2026-12-31", "size_end_date": "2026-01-01"})},
            None,
        )
        assert result["statusCode"] == 400


# ---------------------------------------------------------------------------
# 8. lambda_handler
# ---------------------------------------------------------------------------

class TestLambdaHandler:
    @pytest.fixture
    def fake_df(self):
        return make_orgs_df([
            dict(org_size="small", is_collaborator=True, is_contributor=False,
                 org_type="non_profit", country_code="USA", country_name="UNITED_STATES",
                 created_at=REFERENCE_DATE),
            dict(org_size="medium", is_collaborator=False, is_contributor=True,
                 org_type="for_profit", country_code="IND", country_name="INDIA",
                 created_at=REFERENCE_DATE),
        ])

    def test_direct_invocation_payload(self, monkeypatch, fake_df):
        monkeypatch.setattr(sca, "load_mock_data", lambda: fake_df)
        result = sca.lambda_handler({"country": "USA"}, None)
        assert result["statusCode"] == 200
        assert set(result["body"].keys()) == {"7D", "30D", "1Y", "All", "Custom"}

    def test_api_gateway_json_string_body(self, monkeypatch, fake_df):
        monkeypatch.setattr(sca, "load_mock_data", lambda: fake_df)
        event = {"body": json.dumps({"organization_type": "non_profit"})}
        result = sca.lambda_handler(event, None)
        assert result["statusCode"] == 200

    def test_body_none_treated_as_no_filters(self, monkeypatch, fake_df):
        monkeypatch.setattr(sca, "load_mock_data", lambda: fake_df)
        result = sca.lambda_handler({"body": None}, None)
        assert result["statusCode"] == 200
        assert set(result["body"].keys()) == {"7D", "30D", "1Y", "All", "Custom"}

    def test_malformed_json_body_returns_400(self):
        result = sca.lambda_handler({"body": "{not valid json!"}, None)
        assert result["statusCode"] == 400
        assert "error" in result["body"]

    def test_response_envelope_matches_existing_convention(self, monkeypatch, fake_df):
        """Mirrors kpi_api_analytics.py's build_response(): statusCode,
        CORS header, Content-Type, plain (not pre-stringified) JSON body."""
        monkeypatch.setattr(sca, "load_mock_data", lambda: fake_df)
        result = sca.lambda_handler({}, None)
        assert result["statusCode"] == 200
        assert result["headers"]["Content-Type"] == "application/json"
        assert result["headers"]["Access-Control-Allow-Origin"] == "*"
        assert isinstance(result["body"], dict)

    def test_data_loading_failure_returns_safe_500(self, monkeypatch):
        sensitive_path = "/Users/realuser/secret/path/organizations.csv"
        monkeypatch.setattr(
            sca, "load_mock_data",
            lambda: (_ for _ in ()).throw(FileNotFoundError(sensitive_path)),
        )
        result = sca.lambda_handler({}, None)
        assert result["statusCode"] == 500
        body_text = json.dumps(result["body"])
        assert sensitive_path not in body_text
        assert "error" in result["body"]

    def test_unexpected_data_loading_exception_returns_safe_500(self, monkeypatch):
        secret_message = "password=SuperSecret123 host=prod-db.internal"
        monkeypatch.setattr(
            sca, "load_mock_data",
            lambda: (_ for _ in ()).throw(RuntimeError(secret_message)),
        )
        result = sca.lambda_handler({}, None)
        assert result["statusCode"] == 500
        body_text = json.dumps(result["body"]).lower()
        assert "password" not in body_text
        assert "supersecret123" not in body_text
        assert "prod-db.internal" not in body_text

    def test_unexpected_calculation_exception_returns_safe_500_no_traceback(self, monkeypatch, fake_df):
        monkeypatch.setattr(sca, "load_mock_data", lambda: fake_df)

        def _boom(*args, **kwargs):
            raise RuntimeError("Traceback (most recent call last): internal stack frame details")

        monkeypatch.setattr(sca, "build_size_contribution_response", _boom)
        result = sca.lambda_handler({}, None)
        assert result["statusCode"] == 500
        body_text = json.dumps(result["body"])
        assert "Traceback" not in body_text
        assert "stack frame" not in body_text

    def test_live_database_path_blocked_returns_safe_500(self, monkeypatch):
        """USE_MOCK_DATA=false: get_db_connection() + load_live_data() are
        exercised; the documented NotImplementedError blocker must still
        produce a safe, generic 500 -- no credentials/connection internals
        leaked."""
        monkeypatch.setattr(sca, "USE_MOCK_DATA", False)
        fake_conn = type("FakeConn", (), {"close": lambda self: None})()
        monkeypatch.setattr(sca, "get_db_connection", lambda: fake_conn)
        result = sca.lambda_handler({}, None)
        assert result["statusCode"] == 500
        body_text = json.dumps(result["body"]).lower()
        assert "password" not in body_text
        assert "credential" not in body_text

    def test_lambda_handler_reuses_build_size_contribution_response(self, monkeypatch, fake_df):
        """Issue requirement: lambda_handler must not duplicate analytics
        logic -- verify it actually calls build_size_contribution_response
        rather than reimplementing the calculation inline."""
        monkeypatch.setattr(sca, "load_mock_data", lambda: fake_df)
        calls = []
        original = sca.build_size_contribution_response

        def _spy(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(sca, "build_size_contribution_response", _spy)
        sca.lambda_handler({"country": "USA"}, None)
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# 9. Data-loading behavior (load_mock_data), without any committed CSVs
# ---------------------------------------------------------------------------

class TestLoadMockData:
    @pytest.fixture
    def tiny_mock_data_dir(self, tmp_path: Path) -> Path:
        """Writes minimal organizations/states/countries CSVs to a pytest
        tmp_path (auto-cleaned after the test; never written into the repo
        or committed) so load_mock_data()'s real join logic can be verified
        without touching the production mock-data-generation CSVs."""
        (tmp_path / "organizations.csv").write_text(
            "org_id,org_size,is_collaborator,is_contributor,org_type,state_id,created_at\n"
            "ORG-1,small,True,False,non_profit,CA,2026-01-15 10:00:00\n"
            "ORG-2,medium,False,True,for_profit,MH,not-a-date\n"
        )
        (tmp_path / "states.csv").write_text(
            "state_id,country_id,state_name\n"
            "CA,1,California\n"
            "MH,2,Maharashtra\n"
        )
        (tmp_path / "countries.csv").write_text(
            "country_id,country_code,country_name\n"
            "1,USA,UNITED_STATES\n"
            "2,IND,INDIA\n"
        )
        return tmp_path

    def test_loads_and_joins_country_columns(self, tiny_mock_data_dir):
        df = sca.load_mock_data(str(tiny_mock_data_dir))
        assert len(df) == 2
        assert set(["country_id", "country_code", "country_name"]).issubset(df.columns)
        row_usa = df[df["org_id"] == "ORG-1"].iloc[0]
        assert row_usa["country_code"] == "USA"
        assert row_usa["country_name"] == "UNITED_STATES"

    def test_invalid_created_at_becomes_nat_not_a_crash(self, tiny_mock_data_dir):
        df = sca.load_mock_data(str(tiny_mock_data_dir))
        row_bad_date = df[df["org_id"] == "ORG-2"].iloc[0]
        assert pd.isna(row_bad_date["created_at"])

    def test_valid_created_at_is_parsed(self, tiny_mock_data_dir):
        df = sca.load_mock_data(str(tiny_mock_data_dir))
        row_good_date = df[df["org_id"] == "ORG-1"].iloc[0]
        assert row_good_date["created_at"] == pd.Timestamp("2026-01-15 10:00:00")

    def test_missing_csv_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            sca.load_mock_data(str(tmp_path))  # empty dir, no CSVs

    def test_can_be_monkeypatched_for_lambda_handler_tests(self, monkeypatch):
        """Confirms the data-loading seam used throughout this suite -- no
        test needs real CSVs, AWS, or a database connection."""
        sentinel_df = make_orgs_df([dict(org_size="small")])
        monkeypatch.setattr(sca, "load_mock_data", lambda: sentinel_df)
        assert sca.load_mock_data() is sentinel_df


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_dataset_full_response_does_not_crash(self, reference_date):
        df = make_orgs_df([])
        for col in ("org_size", "is_collaborator", "is_contributor", "org_type",
                    "country_code", "country_name", "created_at"):
            if col not in df.columns:
                df[col] = pd.Series(dtype="object")
        response = sca.build_size_contribution_response(df, reference_date=reference_date)
        for bucket in ("7D", "30D", "1Y", "All"):
            assert response[bucket]["organizations_by_size"] == []
            assert response[bucket]["collaborator_vs_contributor"] == [
                {"type": "Collaborator", "count": 0, "percentage": 0.0},
                {"type": "Contributor", "count": 0, "percentage": 0.0},
            ]

    def test_one_row_dataset_does_not_crash(self, reference_date):
        df = make_orgs_df([
            dict(org_size="small", is_collaborator=True, is_contributor=False,
                 org_type="non_profit", country_code="USA", country_name="UNITED_STATES",
                 created_at=reference_date),
        ])
        response = sca.build_size_contribution_response(df, reference_date=reference_date)
        assert response["7D"]["organizations_by_size"] == [{"size": "small", "count": 1}]
        assert response["All"]["organizations_by_size"] == [{"size": "small", "count": 1}]

    def test_missing_org_size_column_in_full_response(self, reference_date):
        df = make_orgs_df([dict(is_collaborator=True, created_at=reference_date)])
        response = sca.build_size_contribution_response(df, reference_date=reference_date)
        assert response["7D"]["organizations_by_size"] == []

    def test_missing_is_contributor_column_in_full_response(self, reference_date):
        df = make_orgs_df([dict(org_size="small", is_collaborator=True, created_at=reference_date)])
        response = sca.build_size_contribution_response(df, reference_date=reference_date)
        contributor_row = next(r for r in response["7D"]["collaborator_vs_contributor"] if r["type"] == "Contributor")
        assert contributor_row == {"type": "Contributor", "count": 0, "percentage": 0.0}

    def test_nan_created_at_excluded_from_bounded_but_present_in_all(self, reference_date):
        df = make_orgs_df([
            dict(org_size="large", is_collaborator=True, is_contributor=True, created_at=None),
        ])
        response = sca.build_size_contribution_response(df, reference_date=reference_date)
        assert response["7D"]["organizations_by_size"] == []
        assert response["30D"]["organizations_by_size"] == []
        assert response["1Y"]["organizations_by_size"] == []
        assert response["All"]["organizations_by_size"] == [{"size": "large", "count": 1}]

    @pytest.mark.parametrize("value,expected", [
        (True, True), (False, False),
        ("True", True), ("false", False),
        ("1", True), ("0", False),
        ("yes", True), ("no", False),
        ("YES", True), ("NO", False),
    ])
    def test_coerce_bool_series_handles_all_documented_forms(self, value, expected):
        series = pd.Series([value])
        result = sca._coerce_bool_series(series)
        assert bool(result.iloc[0]) is expected

    def test_coerce_bool_series_treats_missing_as_false(self):
        series = pd.Series([True, None, False])
        result = sca._coerce_bool_series(series)
        assert list(result) == [True, False, False]
