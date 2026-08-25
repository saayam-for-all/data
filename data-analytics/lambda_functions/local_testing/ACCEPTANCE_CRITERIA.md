# Organization Analytics API — Acceptance Criteria Checklist (#228)

Maps directly to the Development & Testing Requirements / Acceptance Criteria
given for this task. Each line notes which test(s) prove it and where.

## Development & Testing Requirements

- [x] **Use a local PostgreSQL connection** — `local_testing/local_setup_schema.sql`
      + `organizations.csv`/`state.csv`; both test suites run against it.
- [x] **Do not use AWS Parameter Store** — verified by
      `test_organization_analytics_unit_mock.py` (`no functional SSM/boto3 usage`
      style check) and by manual code review (`get_db_connection` uses only
      `os.environ`).
- [x] **Do not deploy directly to AWS** — nothing in this PR touches AWS;
      all testing is local.
- [x] **Follow the coding pattern used in existing analytics APIs** —
      `RealDictCursor`, `build_response()` with CORS headers, per-metric
      try/except degradation, matching `kpi_api_analytics.py` /
      `volunteer_application_analytics.py` (SSM omitted intentionally, per the
      explicit instruction above).
- [x] **Use parameterized SQL queries** — every filter value (`region`,
      `organization_type`, `start_date`, `end_date`) is passed via `%s` +
      a `params` list, never string-interpolated. Verified by
      `test_region_filter_produces_parameterized_condition` and
      `test_organization_type_filter_normalizes_and_parameterizes` (mock suite),
      which assert the raw filter value never appears inside the SQL text.
- [x] **Handle NULL values safely** — `rating_distribution` excludes NULL
      ratings from its buckets rather than erroring; verified against the real
      CSV with two injected NULL-rating rows (integration suite) and via mocked
      `average_org_rating: None` (unit suite).
- [x] **Add cursor-based/mock database unit tests** —
      `local_testing/test_organization_analytics_unit_mock.py`, 18 tests,
      runs with zero DB configuration (mocks `get_db_connection` entirely).
- [x] **Test valid filters** — `TestValidFilters` (mock) +
      region/organization_type filter tests (integration).
- [x] **Test invalid filters** — `TestInvalidFilters`: garbage `time_filter`
      and `group_by` fall back to safe defaults; a nonsense `region` or
      `organization_type` matches zero rows rather than crashing.
- [x] **Test custom date ranges** — `TestCustomDateRanges` (both dates present,
      one missing, both missing) + integration `CUSTOM` test.
- [x] **Test empty result sets** — `TestEmptyResultSets` (mock, all-empty
      cursor results) + integration zero-match-region test.
- [x] **Test database/query exceptions** — `TestDatabaseAndQueryExceptions`:
      connection failure → 500 + default body; single query failure →
      that field degrades, others unaffected, 200; cursor/connection always
      closed (via `finally`), even when a query raises.
- [x] **Validate the response structure against the Organization Dashboard
      requirements** — `TestResponseStructureValidation` checks every field
      name across summary, growth trend, location, size, collaborator/
      contributor, rating distribution, and type distribution.
- [x] **Include sample request and response payloads in the PR** —
      `sample_response_standard_30D.json`, `sample_response_last_12_months.json`,
      `sample_response_region_california.json`, `sample_response_type_nonprofit.json`,
      `sample_response_custom_range.json` — one per payload given in the issue.

## Acceptance Criteria

- [x] **Organization Analytics API is implemented** — `organization_analytics.py`.
- [x] **All four KPI cards are returned correctly** — `total_organizations`,
      `total_collaborators`, `total_contributors`, `average_org_rating` in
      `summary`.
- [x] **Growth Trend returns Total Organizations and Total Collaborators** —
      `growth_trend` rows: `{period, total_organizations, total_collaborators}`.
- [x] **Organizations by Location supports state/city data** —
      `organizations_by_location` rows: `{state_id, state_name, city_name,
      organization_count, percentage}`.
- [x] **Organizations by Size returns Small, Medium, and Large distributions** —
      always exactly 3 rows, zero-filled if empty.
- [x] **Collaborator vs Contributor data is returned correctly** —
      `collaborator_vs_contributor`, two independent (not mutually exclusive)
      counts + percentages.
- [x] **Rating Distribution returns ratings from 1 to 5** — always 5 rows,
      zero-filled, NULL-safe.
- [x] **For-Profit vs Non-Profit trend is returned correctly** —
      `organization_type_distribution`, one row per period with
      `for_profit`/`non_profit`/`total`.
- [x] **Existing common dashboard filters are reused** — `time_filter`,
      `start_date`, `end_date`, `group_by` match the pattern used by the other
      analytics dashboards; no separate filtering mechanism introduced.
- [x] **Local unit tests pass** — 18/18 mock + 24/24 integration = 42/42.
- [x] **No AWS deployment is performed** — local only.
- [x] **PR contains test results and sample API responses** — see PR
      description; results and 5 sample payload/response pairs included.

## Open items for reviewer (not blocking, flagged for confirmation)

- Table name `states` (plural, per issue text) vs. `state` (singular, actual
  CSV filename in the repo / earlier `ddl_state.sql`) — built as `states`;
  please confirm against the real Aurora schema.
- `growth_trend` / `organization_type_distribution` count **new
  registrations per period**, not a cumulative running total — flagging the
  assumption in case cumulative was intended.
