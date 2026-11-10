# Organization Tab — Application Analytics Documentation

**Issue:** [#604](https://github.com/saayam-for-all/data/issues/604)  
**Repository:** `saayam-for-all/data`  
**Location:** Super Admin Dashboard → Analytics → Application Analytics → Organization  
**Document status:** Implementation review; deployment details require confirmation  
**Prepared:** November 2026

## 1. Purpose and Overview

The Organization tab is intended to help Super Admin users understand organization growth, geographic distribution, organization size, contribution activity, ratings, and organization types.

The analytics are organized into three functional areas:

1. Growth & Location Analytics
2. Size & Contribution Analytics
3. Rating & Type Analytics

The backend implementation consists of separate analytics functions. The availability of these functions does not independently confirm that they are connected to the frontend or deployed in production.

## 2. Features and Intended User Flow

The intended workflow is:

1. A Super Admin opens the dashboard.
2. The user navigates to Application Analytics and selects Organization.
3. The dashboard presents organization analytics charts.
4. The user selects a reporting period such as 7D, 30D, 1Y, or All.
5. Where supported, the user applies custom date ranges and other filters.
6. The corresponding analytics data is requested and displayed.

**Verification required:** The exact frontend-to-backend integration, API endpoints, authorization, loading states, and error presentation must be confirmed against the deployed application.

## 3. Growth & Location Analytics

**Development issue:** [#336](https://github.com/saayam-for-all/data/issues/336)

This area includes:

### Growth Trend

The growth chart tracks organization growth and collaborator activity over time.

The original implementation distinguishes:

- **Total organizations:** Cumulative organization count through a reporting date.
- **Collaborators:** Activity or counts grouped by reporting period, rather than an all-time cumulative total.

Reporting intervals are daily for shorter windows and monthly for longer windows in the earlier implementation.

### Organizations by Location

The location chart groups organizations geographically using country information associated with their registered state.
The original requirement focused on the four countries with the highest organization counts. Later development work changed the location aggregation behavior, so the current implementation must be checked against the selected code baseline.

**Implementation references:**
- [PR #347 — Growth & Location implementation](https://github.com/saayam-for-all/data/pull/347)
- [PR #424 — Test cleanup](https://github.com/saayam-for-all/data/pull/424)
- [PR #538 — Later Growth & Location changes](https://github.com/saayam-for-all/data/pull/538)
- [PR #541 — Subsequent update](https://github.com/saayam-for-all/data/pull/541)

## 4. Size & Contribution Analytics

**Development issue:** [#376](https://github.com/saayam-for-all/data/issues/376)

### Organizations by Size

Organizations are grouped by their size category. Each category's count represents the number of organizations matching the applicable reporting window and filters.

### Collaborators vs Contributors

The chart compares organizations marked as collaborators with those marked as contributors.

The two classifications are counted independently. An organization may belong to both groups.

Percentage calculation:

`percentage = (matching category count / total organizations in the filtered window) × 100`

If the `is_contributor` field is missing, some implementations return zero for the contributor category.

### Implementation history

- [PR #379](https://github.com/saayam-for-all/data/pull/379): Earlier standalone implementation, left open in the reviewed history.
- [PR #419](https://github.com/saayam-for-all/data/pull/419): Merged implementation using `data-engineering/src/organization_size_contribution_analytics/lambda_function.py`.
- [PR #471](https://github.com/saayam-for-all/data/pull/471): Alternative implementation supporting independent custom ranges and SQL-level filtering.
- [PR #490](https://github.com/saayam-for-all/data/pull/490): Reverted PR #471.
- [PR #568](https://github.com/saayam-for-all/data/pull/568): Later implementation referenced in the documentation review.

**Verification required:** The repository contains multiple historical implementations. Confirm the active handler and its behavior from the current `test` branch before treating one implementation as authoritative.

## 5. Rating & Type Analytics

**Development issue:** [#380](https://github.com/saayam-for-all/data/issues/380)

### Rating Distribution

This chart groups organizations by their rating, generally across rating values 1 through 5.

The count for each rating is the number of matching organizations with that rating.

### Organization Type Trend

This chart compares for-profit and nonprofit organizations over time.

The earlier implementation uses cumulative counts to show how the organization mix changes.

### Implementation history

- [PR #387](https://github.com/saayam-for-all/data/pull/387): Earlier implementation proposal.
- [PR #503](https://github.com/saayam-for-all/data/pull/503): Merged Rating & Type implementation.
- [Issue #506](https://github.com/saayam-for-all/data/issues/506): Requested correction to default and custom response behavior.
- [PR #555](https://github.com/saayam-for-all/data/pull/555): Proposed response-behavior correction.

**Verification required:** The original API specification and later correction differ in whether an empty `Custom` bucket appears by default.

## 6. Filters and Reporting Periods

The analytics APIs support combinations of:

- Reporting periods: `7D`, `30D`, `1Y`, and `All`.
- Custom date ranges where implemented.
- Country filtering.
- Organization-type filtering for applicable charts.

Earlier Size & Contribution implementations accepted `size_start_date`, `size_end_date`, `contribution_start_date`, and `contribution_end_date`.

Earlier Rating & Type implementations accepted `rating_start_date`, `rating_end_date`, `type_start_date`, and `type_end_date`.

Growth & Location originally supported separate date pairs for growth and location charts. Later implementations revised the custom-range behavior.

**Important:** These are historical API contracts. Parameter names, default buckets, and custom-range behavior must be verified against the active handler before integration.

## 7. Data Sources and Calculations

The development tasks describe CSV-based mock data for local testing and PostgreSQL access in some Lambda implementations.

Relevant organization fields include:

- Organization identifier and creation date.
- Organization size and type.
- Organization rating.
- Collaborator and contributor indicators.
- State identifier, linked to country information.

Country information is derived through the relationship:

`organizations.state_id → states.country_id → countries.country_code`

### Metric definitions

| Metric | Calculation |
|---|---|
| Organizations by size | Count organizations grouped by size |
| Rating distribution | Count organizations grouped by rating |
| Organizations by location | Count organizations grouped by geographic area |
| Total organizations | Cumulative count through the reporting date |
| Collaborators | Count matching collaborator records or flags according to the handler |
| Contributors | Count matching contributor records or flags according to the handler |
| Contributor percentage | Contributor count divided by filtered organization total, multiplied by 100 |
| Organization type trend | Cumulative counts grouped by for-profit/nonprofit classification |

Exact denominator selection, null handling, date boundaries, and grouping frequency should be confirmed in the active code.

## 8. Implementation Approach

The backend work uses Python analytics functions, including pandas for local CSV processing and optional `psycopg2` access for PostgreSQL in certain implementations.

The Lambda handlers generally:

1. Read request parameters.
2. Validate date ranges and supported filters.
3. Load organization and geographic data.
4. Apply filters.
5. Aggregate metrics by chart and reporting period.
6. Return structured JSON or an error response.

**Code references:**
- [Data Analytics Lambda directory](https://github.com/saayam-for-all/data/tree/test/data-analytics/lambda_functions)
- [Data Engineering source directory](https://github.com/saayam-for-all/data/tree/test/data-engineering/src)
- [Mock data generation directory](https://github.com/saayam-for-all/data/tree/test/data-analytics/mock-data-generation)

These links identify source locations, not confirmed deployed Lambda entry points.

## 9. Development Task Review

The following issues and related changes were identified during the documentation investigation.

| Issue | Area | Review finding |
|---|---|---|
| [#336](https://github.com/saayam-for-all/data/issues/336) | Growth & Location | Initial chart contracts, time buckets, and geographic joins |
| [#376](https://github.com/saayam-for-all/data/issues/376) | Size & Contribution | Size distribution and independently counted collaborator/contributor categories |
| [#380](https://github.com/saayam-for-all/data/issues/380) | Rating & Type | Rating distribution and organization-type trend |
| [#506](https://github.com/saayam-for-all/data/issues/506) | Rating & Type update | Default response and custom-range correction |
| [#539](https://github.com/saayam-for-all/data/issues/539) | Growth update | Later changes requiring current-code verification |
| [#569](https://github.com/saayam-for-all/data/issues/569) | Size update | Later change request |
| [#583](https://github.com/saayam-for-all/data/issues/583) | Size update | Revised date-range and implementation requirements |

Additional historical tasks identified by other documentation contributors include [#81](https://github.com/saayam-for-all/data/issues/81), [#82](https://github.com/saayam-for-all/data/issues/82), [#84](https://github.com/saayam-for-all/data/issues/84), [#89](https://github.com/saayam-for-all/data/issues/89), [#228](https://github.com/saayam-for-all/data/issues/228), and [#301](https://github.com/saayam-for-all/data/issues/301).

These additional tasks require individual evidence review before their specific implementation details can be presented as independently verified.

## 10. Known Limitations and Open Questions

1. Frontend integration with the three analytics handlers is not independently confirmed.
2. Live deployment and API Gateway endpoints are not verified.
3. Authentication and authorization enforcement require confirmation.
4. The source of the dashboard's summary KPI cards is unclear.
5. Multiple historical implementations have different custom-date and filtering contracts.
6. Mock CSV behavior does not establish production database correctness.
7. Some implementation PRs were reverted or superseded.
8. Country-name normalization and missing-field behavior vary by implementation.
9. Date boundaries, timezone handling, and empty-period behavior need active-code verification.
10. The latest frontend behavior and deployed backend version may differ from the reviewed branches.

## 11. Supporting References

**Documentation task:** [Issue #604](https://github.com/saayam-for-all/data/issues/604)

**Existing documentation submissions:**
- [PR #618](https://github.com/saayam-for-all/data/pull/618)
- [PR #639](https://github.com/saayam-for-all/data/pull/639)
- [PR #640](https://github.com/saayam-for-all/data/pull/640)
- [PR #646](https://github.com/saayam-for-all/data/pull/646)

**Implementation references:**
- [PR #347](https://github.com/saayam-for-all/data/pull/347)
- [PR #419](https://github.com/saayam-for-all/data/pull/419)
- [PR #471](https://github.com/saayam-for-all/data/pull/471)
- [PR #490](https://github.com/saayam-for-all/data/pull/490)
- [PR #503](https://github.com/saayam-for-all/data/pull/503)
- [PR #538](https://github.com/saayam-for-all/data/pull/538)
- [PR #541](https://github.com/saayam-for-all/data/pull/541)
- [PR #555](https://github.com/saayam-for-all/data/pull/555)
- [PR #568](https://github.com/saayam-for-all/data/pull/568)

## 12. Documentation Review Notes

This document summarizes the reviewed development history and separates historical requirements from implementation behavior that still needs confirmation.

It does not claim that the frontend integration, production deployment, or latest database behavior has been independently tested.

Before final approval, reviewers should confirm the active code baseline, reconcile superseded implementations, and identify the deployed analytics endpoints.
