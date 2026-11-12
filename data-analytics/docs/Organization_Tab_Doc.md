# Organization Tab Documentation

**Issue:** [#604](https://github.com/saayam-for-all/data/issues/604)

**Repository:** `saayam-for-all/data`

**Location:** Super Admin Dashboard → Analytics → Application Analytics → Organization

**Document status:** Implementation review; deployment details require confirmation

**Prepared:** November 2026

Adapted from [PR #687](https://github.com/saayam-for-all/data/pull/687) by [akankshab418](https://github.com/akankshab418), documentation commit `79abaee03357954722e908ea8a0a7d39b1378c38`. Consolidation review on November 11, 2026 checked issue #604, the seven main development issue descriptions, implementation PR metadata, and the four handlers linked below. Additional comparison of documentation PRs [#618](https://github.com/saayam-for-all/data/pull/618), [#639](https://github.com/saayam-for-all/data/pull/639), [#640](https://github.com/saayam-for-all/data/pull/640), and [#646](https://github.com/saayam-for-all/data/pull/646) informed the frontend and summary-card notes; those details were then checked against their cited source files. Historical discussions and attachments were not fully re-reviewed; this document does not claim that part of #604 is complete. Code behavior below is pinned to local commit `2602a8897d25b086624e202beb7515d1d31b634a`, not a verified deployment.

## 1. Purpose and Overview

The Organization tab is intended to help Super Admin users understand organization growth, geographic distribution, organization size, contribution activity, ratings, and organization types.

The analytics are organized into three functional areas:

1. Growth & Location Analytics
2. Size & Contribution Analytics
3. Rating & Type Analytics

The backend implementation consists of separate analytics functions. The availability of these functions does not independently confirm that they are connected to the frontend or deployed in production.

## 2. Features and Intended User Flow

### Reviewed UI versus intended API integration

A mock Organization tab is implemented in webapp feature-branch snapshot `f5b940ad3e9075a1743a7e3fae7dd75cd244dd85`. Its [ApplicationAnalytics.jsx][feature-tabs] registers Organization; [OrganizationAnalytics.jsx][feature-ui] renders four summary cards and the three chart views. The newer webapp snapshot `388534d902110bac4d4a38f7a4fc1cdbba8ac6ad` inspected for the other documentation has only Requests, KPI, Beneficiaries and Volunteers. This establishes a source difference, not which build is hosted.

In the feature snapshot:

1. Select Analytics → Application Analytics → Organization. Growth & Location opens by default, with **1 Year** and **Region = All**.
2. Change 7 Days, 30 Days, 1 Year, All, or Custom, and optionally choose North/South/East/West. Custom exposes start/end inputs.
3. The component recomputes local sample data through [organizationData.js][feature-data]; it makes **no analytics API request**. Region selections scale sample values rather than query organization geography. No organization-type selector is exposed.
4. Switch to Size & Contribution or Rating & Type for the other chart pairs. Reset restores 1 Year/All and clears custom dates.

The intended future integration would request each chart handler's supported filters and retain its fixed buckets for period switching. Actual endpoint mapping, loading/error behavior for remote data, authorization and deployment still require confirmation.

### UI/API mismatches to resolve

| Feature-snapshot UI | Reviewed backend contract |
|---|---|
| North/South/East/West region selector | Country codes/names; Growth can return states after country selection. No matching directional-region filter. |
| Growth lines for cumulative Organizations, Collaborators and Contributors | Cumulative organizations and **per-period collaborators** only; no contributor growth series. |
| Collaborator versus “Contributor (Non-Collaborator)” donut | Independent collaborator/contributor flags can overlap. These percentages are not complementary donut slices. |
| Sample state-location rows, Other and shares | Growth returns all country/state groups without a top-four cap, Other or percentage fields. |
| Four summary cards with changes | Chart handlers return no `summary` object or change percentages. The mock average rating is hard-coded to `4.2`, with change `4`. |

### Summary-card backend boundary

[#228](https://github.com/saayam-for-all/data/issues/228) requests Total Organizations, Total Collaborators, Total Contributors and Average Organization Rating. Their final shared source and calculation scope remain unresolved. A retained [FastAPI scaffold][legacy-api] exposes overview/performance summary GET routes, but it counts contributors as `is_collaborator IS NOT TRUE` and uses assumed `rating`/`registered_at` columns. That differs from the chart handlers' independent `is_contributor`, `org_rating` and `created_at`. Neither this scaffold nor the mock UI establishes the final integrated card API.

## 3. Growth & Location Analytics

**Development issue:** [#336](https://github.com/saayam-for-all/data/issues/336)

This area includes:

### Growth Trend

The growth chart tracks organization growth and collaborator activity over time.

The reviewed implementation distinguishes:

- **Total organizations:** Cumulative organization count through a reporting date.
- **Collaborators:** Activity or counts grouped by reporting period, rather than an all-time cumulative total.

Reporting intervals are daily for 7D/30D/Custom and monthly for 1Y/All.

### Organizations by Location

The location chart groups organizations through their state/country mapping. The original top-four-country requirement was superseded: the reviewed code returns all country groups, or state groups when a country is selected, without an Other row or percentage.

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

**Deployment question:** The analytics and engineering variants both exist and differ. Their pinned behavior is documented below; confirm which handler is deployed.

## 5. Rating & Type Analytics

**Development issue:** [#380](https://github.com/saayam-for-all/data/issues/380)

### Rating Distribution

This chart counts integral ratings from 1 through 5; invalid and missing ratings are excluded.

The count for each rating is the number of matching organizations with that rating.

### Organization Type Trend

This chart compares for-profit and nonprofit organizations over time.

The reviewed implementation uses cumulative creation counts for each type, carrying pre-window history and emitting only represented creation periods.

### Implementation history

- [PR #387](https://github.com/saayam-for-all/data/pull/387): Earlier implementation proposal.
- [PR #503](https://github.com/saayam-for-all/data/pull/503): Merged Rating & Type implementation.
- [Issue #506](https://github.com/saayam-for-all/data/issues/506): Requested correction to default and custom response behavior.
- [PR #555](https://github.com/saayam-for-all/data/pull/555): Proposed response-behavior correction.

**Confirmed in the reviewed source:** Rating still returns an empty default `Custom` bucket. PR #555 proposes removing it and remains open and unmerged as of this review.

## 6. Filters and Reporting Periods

All three analytics handlers return `7D`, `30D`, `1Y`, and `All` on a default call. Growth and Size use one shared custom `start_date`/`end_date` pair; Rating still uses separate rating/type pairs and adds an empty default `Custom`. The exact contracts and window boundaries are listed in Section 8. Country filtering is supported by all three; `organization_type` filtering is supported by Size.

## 7. Data Sources and Calculations

The reviewed analytics Growth and Size handlers always read adjacent CSV files; Rating can read PostgreSQL or CSVs. The engineering Size variant also has both modes. The exact source selection is documented below.

The tracked sample CSVs contain **400 unique organization IDs**, size counts small 122 / medium 168 / large 110, **125 collaborators**, **224 contributors**, and type counts non_profit 270 / for_profit 130. There are **323 rated rows and 77 unrated rows**. Creation dates span June 2, 2025 through August 31, 2026, so recent windows can be empty with these fixtures. These counts were independently checked from CSVs during consolidation; they are not live dashboard metrics.

Required CSV fields are `org_id`, `created_at`, `state_id` and the chart-specific size/type/rating/collaboration flags. Geography joins `organizations.state_id` to `states.state_id`, then `states.country_id` to `countries.country_id`. Counts assume one row per organization. Section 8 gives the exact inclusion and calculation rules.

## 8. Implementation Approach

The Python handlers parse inputs, load organization/geographic data, apply filters and aggregate chart results. CSV processing uses pandas; database-capable variants use `psycopg2`. Validation order differs: Growth loads data before country/date checks, so a missing file can mask an input error; Size and Rating validate their date inputs before loading data.

**Code references:**
- [Data Analytics Lambda directory](https://github.com/saayam-for-all/data/tree/test/data-analytics/lambda_functions)
- [Data Engineering source directory](https://github.com/saayam-for-all/data/tree/test/data-engineering/src)
- [Mock data generation directory](https://github.com/saayam-for-all/data/tree/test/data-analytics/mock-data-generation)

These links identify source locations, not confirmed deployed Lambda entry points.

### Reviewed implementation baseline

These source files coexist at the pinned commit; filenames alone do not establish which one is deployed.

| Area | Source | Data source and response contract |
|---|---|---|
| Growth & Location | [growth_trend_analytics.py][growth-source] | Always reads three CSVs from adjacent `mock_data/`. No dates returns `7D`, `30D`, `1Y`, `All`, without `Custom`; `start_date`/`end_date` returns only `Custom` and applies to both charts. Optional `country` filter. |
| Size & Contribution | [size_and_contribution.py][size-source] | Always reads adjacent `mock_data/`; no database/environment switch. Same shared date pair and fixed-versus-Custom response split as Growth. Supports `country` and `organization_type`. |
| Rating & Type | [rating_type_analytics.py][rating-source] | Defaults to PostgreSQL using `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` and optional `DB_PORT`; `USE_MOCK_DATA=true` selects CSVs. Uses separate `rating_start_date`/`rating_end_date` and `type_start_date`/`type_end_date` pairs. Default response includes the four fixed buckets **and an empty `Custom`**. A date pair returns only `Custom`; an unspecified chart stays empty. Optional `country` filter. |
| Engineering Size variant | [lambda_function.py][engineering-size-source] | Separate implementation: `USE_MOCK_DATA` defaults to true and `MOCK_DATA_DIR` defaults to the working directory; false selects PostgreSQL. Retains independent size/contribution date pairs and an empty default `Custom` bucket. Its contract is not interchangeable with the analytics Size file. |

All four handlers return an envelope with `statusCode`, headers and a JSON-string `body`. Growth and analytics Size accept a direct event or a body containing an object/JSON string. Rating additionally combines query-string parameters with body fields. Invalid input generally returns 400 and load/processing failures return 500; the precise parsing and error messages differ between handlers.

The adjacent `data-analytics/lambda_functions/mock_data/` directory is absent in this checkout. Growth and analytics Size require those CSVs to be supplied in the local or Lambda package layout before they can serve data. Repository sample CSVs elsewhere are not automatically loaded by these two handlers.

### Exact calculations and date behavior in the analytics files

- **Growth:** `total_organizations` is a cumulative row count from the full country-filtered dataset, emitted only for periods with creations in the requested window. `collaborators` counts true flags in that window per period, with zero for a represented period having no collaborators. Arrays omit periods with no organization creations. For custom daily windows the cumulative series carries earlier history into the selected dates.
- **Location:** without a country filter, counts all countries, with no top-four cap or Other row. With a country selected, returns state names instead of country codes. Missing joined labels become `Unknown`. Rows sort by descending count, then label.
- **Size:** counts non-null `org_size` values among filtered rows, displaying small/medium/large first. Contribution counts true flags independently and divides by **all filtered organization rows**, rounded to one decimal. Missing `is_contributor` becomes false; empty input returns empty chart arrays. Counts are rows, not deduplicated organization IDs.
- **Rating:** includes only integral ratings 1–5 in the selected creation-date window; missing and invalid ratings are excluded, and absent ratings are not zero-filled. Type series are cumulative counts for normalized `non_profit` and `for_profit` values, carrying history before the window and emitting sparse creation periods. Missing/invalid creation dates are dropped during data cleaning.
- **Growth windows:** 7D starts six days before today, 30D starts 29 days before today, 1Y starts on the first day of the month eleven months earlier, and All has no date restriction. These presets lack an upper bound. Custom includes the whole final day. Grouping is daily for 7D/30D/Custom and monthly for 1Y/All.
- **Size windows:** 7D/30D use today plus the preceding 6/29 days; 1Y begins at the first of the month eleven months earlier. Presets end before tomorrow in UTC; All has no time bounds. Custom includes the whole final day. Size charts are distributions, not time series.
- **Rating windows:** 7D/30D start 6/29 days before today; 1Y starts one day after the same date in the prior year (with leap-day handling); All has no lower bound. All presets end at the handler's current time. Custom ends at the final day's last microsecond. Grouping is daily for 7D/30D/Custom and monthly for 1Y/All. Creation timestamps are normalized to naive UTC, while the current time uses `datetime.now()`; runtime timezone needs confirmation.

Example direct event shared by Growth and analytics Size:

```json
{"start_date":"2026-01-01","end_date":"2026-03-31","country":"USA"}
```

For Size, `organization_type` can additionally restrict both charts to `non_profit` or `for_profit`. Rating requires its chart-specific date fields instead; the generic `start_date`/`end_date` pair does not activate its custom mode.

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

Documentation PR #618 supplies additional task-by-task history. Its historical comment/attachment review is attributed to that author, rather than claimed as a complete new review here:

| Task | Context and consolidation evidence |
|---|---|
| [#81](https://github.com/saayam-for-all/data/issues/81), [#82](https://github.com/saayam-for-all/data/issues/82) | Parent analytics design and original time/profit-type organization counts. These define intent, not a serving endpoint. |
| [#84](https://github.com/saayam-for-all/data/issues/84) | CSV → JSON handoff. The visualization attachment, inspected during the dashboard documentation work, specifies a profit/non-profit donut and country/category bar; it predates the six-chart layout. |
| [#89](https://github.com/saayam-for-all/data/issues/89) | Mock-data visualization handoff. The Plotly title does not establish the rendering library in the React feature UI. |
| [#228](https://github.com/saayam-for-all/data/issues/228) | Four cards, six charts and a consolidated endpoint proposal. Local FastAPI code was checked; its contributor definition and assumed columns differ from the standalone handlers. |
| [#301](https://github.com/saayam-for-all/data/issues/301) | Shared synthetic tables and geographic joins. Consolidation independently counted the tracked organization CSV and checked its field names. |

Historical #618/#639/#646 statements that #583 is still absent describe older baselines. This document follows the local pinned Size file, which already implements its shared-range, CSV-only behavior. The separate engineering Size file still retains the older contract.

## 10. Known Limitations and Open Questions

1. The reviewed feature UI uses sample data without API calls and differs from the four-tab webapp snapshot. An integrated/deployed Organization UI was not verified.
2. Live deployment and API Gateway endpoints are not verified.
3. Authentication and authorization enforcement require confirmation.
4. The feature UI uses local sample summary cards; the three chart handlers do not serve those cards. The older FastAPI scaffold has incompatible contributor/column assumptions. The final integrated source needs confirmation.
5. Multiple historical implementations have different custom-date and filtering contracts.
6. Mock CSV behavior does not establish production database correctness.
7. Some implementation PRs were reverted or superseded.
8. Country-name normalization and missing-field behavior vary by implementation.
9. Handlers use different date boundaries and timezone conventions, as detailed above; product expectations and deployed behavior need confirmation.
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

Before final approval, reviewers should confirm the deployed handlers/endpoints and complete the remaining historical discussion review. Consolidation checked the four backend files, feature UI/data provider, alternate webapp navigation, legacy FastAPI summary code, organization fixture counts and implementation PR metadata. It did not run application tests, SQL, AWS calls or an authenticated frontend. JSON examples, reference definitions and pinned local source paths were checked. Historical test results reported in the compared PRs are not claimed as tests performed here.

[growth-source]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/growth_trend_analytics.py

[size-source]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/size_and_contribution.py

[rating-source]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/rating_type_analytics.py

[engineering-size-source]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-engineering/src/organization_size_contribution_analytics/lambda_function.py

[feature-ui]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/components/Analytics/OrganizationAnalytics.jsx

[feature-data]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/components/Analytics/organizationData.js

[feature-tabs]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/components/Analytics/ApplicationAnalytics.jsx

[legacy-api]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-engineering/src/main.py
