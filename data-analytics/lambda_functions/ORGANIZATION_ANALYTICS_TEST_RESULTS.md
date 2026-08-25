# Organization Analytics API - Local Test Results

Test date: August 9, 2026

## Environment

- Python: 3.12.13
- PostgreSQL: 17.10, portable local server
- Database: `saayam_local` on localhost only
- Source data: `data-analytics/sql/organizations.csv` and
  `data-analytics/sql/state.csv`
- Rows loaded: 40 organizations and 51 states
- AWS deployment: not performed
- GitHub changes: not performed

## Results

```text
Ran 20 tests in 3.243s

OK
```

All 20 tests passed:

- 10 request parsing, validation, SQL parameterization, and configuration tests
- 10 local PostgreSQL integration tests
- Both overview and performance dashboard response structures
- All common dimension filters
- `7D`, `30D`, `1Y`, `ALL`, and `CUSTOM` time-filter behavior
- Daily, weekly, monthly, and yearly trend grouping
- API Gateway stringified request-body handling
- Contributor analytics when `is_contributor` is present
- Safe fallback and filter rejection when `is_contributor` is absent
- Per-metric failure isolation
- No hard-coded AWS Parameter Store path or client in the API source

## Verified source metrics

```text
total_organizations: 40
non_profit_organizations: 21
for_profit_organizations: 19
collaborator_organizations: 21
non_collaborator_organizations: 19
contributor_organizations: 19
non_contributor_organizations: 21
average_rating: 3.23
rated_organizations: 40
unrated_organizations: 0
five_star_organizations: 12
rating_distribution: 1=5, 2=9, 3=10, 4=4, 5=12
```

## Additional checks

```text
Python AST parse: passed for all four Python implementation/support files
Python line-length check: 0 lines over 99 characters
Git whitespace check: passed
```

The intentional metric-failure test logs two stack traces while forcing the
type and size queries to fail. The test passes because the summary and later
location metrics still return correct data, proving one failed metric does not
blank the dashboard.

