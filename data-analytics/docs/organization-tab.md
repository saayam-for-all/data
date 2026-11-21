# Organization Tab Documentation — Application Analytics

## 1. Overview

The Organization tab is part of the **Application Analytics** section of the Super Admin Dashboard. It is intended to help administrators understand organization growth, geographic distribution, ratings, organization types, organization size, and collaboration and contribution activity.

The original dashboard design is described in Issue #82 — Design of Application Analytics tab, under Issue #81.

This document describes the intended functionality, API implementation, filters, data sources, metrics, calculations, and known limitations based on the reviewed issues, pull requests, and source code.

**Status note:** Reviewing an issue or pull request does not establish that its implementation has been merged, deployed, or connected to the production dashboard. The implementation details below should be verified against the final merged code.

## 2. Analytics Areas and Related Tasks

The Organization tab includes three main analytics areas. The following issues and pull requests document the requirements and development work associated with each area.

### 2.1 Growth & Trend
- **Issue:** [#539](https://github.com/saayam-for-all/data/issues/539)
- **Related PRs:** [#570](https://github.com/saayam-for-all/data/pull/570), [#572](https://github.com/saayam-for-all/data/pull/572), [#592](https://github.com/saayam-for-all/data/pull/592)

### 2.2 Rating & Type
- **Issue:** [#380](https://github.com/saayam-for-all/data/issues/380)
- **Related PRs:** [#567](https://github.com/saayam-for-all/data/pull/567), [#601](https://github.com/saayam-for-all/data/pull/601)

### 2.3 Size & Contribution
- **Issues:** [#376](https://github.com/saayam-for-all/data/issues/376), [#569](https://github.com/saayam-for-all/data/issues/569), [#583](https://github.com/saayam-for-all/data/issues/583)
- **Related PRs:** [#575](https://github.com/saayam-for-all/data/pull/575), [#576](https://github.com/saayam-for-all/data/pull/576), [#577](https://github.com/saayam-for-all/data/pull/577), [#589](https://github.com/saayam-for-all/data/pull/589), [#595](https://github.com/saayam-for-all/data/pull/595), [#596](https://github.com/saayam-for-all/data/pull/596), [#597](https://github.com/saayam-for-all/data/pull/597), [#598](https://github.com/saayam-for-all/data/pull/598), [#600](https://github.com/saayam-for-all/data/pull/600)

This area provides organization size distribution and collaborator/contributor metrics. The later requirements also introduce shared date-range, country, and organization-type filters.

### 2.4 Differences Across Analytics Areas

Although all three areas belong to the Organization tab, their filters, date-range behavior, metrics, and calculation methods are not identical. These differences are explained in the corresponding sections below.

## 3. User flow

The intended workflow is:

1. A Super Admin opens the dashboard and navigates to Application Analytics.
2. The administrator selects the Organization tab.
3. The administrator selects a reporting period or enters a custom date range where supported.
4. The administrator applies available filters, such as country or organization type.
5. The API validates the inputs and loads organization data from its configured data source.
6. The API filters the records and calculates the relevant metrics.
7. The API returns JSON containing the results for the dashboard to display.

This describes the intended workflow based on the analytics requirements and API implementations. The exact dashboard controls, chart rendering, and production API integration require verification against the frontend and deployment configuration.

## 4. Filters and reporting periods

### 4.1 Standard date ranges

The reviewed Growth & Trend implementation supports these reporting periods:

- **7D:** Today and the previous six days.
- **30D:** Today and the previous 29 days.
- **1Y:** The current calendar month and the preceding 11 calendar months.
- **All:** All available organization history.
- **Custom:** A user-supplied start and end date.

For Growth & Trend, the Custom bucket is returned when both custom dates are valid. Otherwise, the standard response contains `7D`, `30D`, `1Y`, and `All`.

The Rating & Type and Size & Contribution implementations have their own date-range behavior, described below.

### 4.2 Custom date validation

The reviewed Growth & Trend implementation requires dates in `YYYY-MM-DD` format.

- Both `start_date` and `end_date` must be supplied together.
- The start date cannot be later than the end date.
- The end date is inclusive.
- Invalid date formats or invalid date ranges return HTTP 400.

Issue #583 specifies one shared custom date range for both Size & Contribution charts. The Rating & Type implementation reviewed in PR #601 instead uses separate custom date pairs for its rating and organization-type charts.

### 4.3 Country filter

The country filter restricts results to organizations associated with the selected country.

In the reviewed Growth & Trend implementation:

- A blank country or `ALL` means no country filter.
- A country code or country name can be supplied.
- When no country is selected, the location chart groups organizations by country.
- When a country is selected, the location chart groups organizations by state.
- The country filter is applied before the two charts are calculated.

The Rating & Type and Size & Contribution work also specifies country filtering. Their actual behavior depends on the implementation's country/state mappings and data-source configuration.

### 4.4 Organization-type filter

Issue #583 specifies an `organization_type` filter for Size & Contribution. The filter is intended to apply to both charts.

The reviewed Growth & Trend implementation does not use an organization-type filter.

### 4.5 Filter behavior across analytics areas

The filters are not identical across all three analytics APIs:

- **Growth & Trend:** One `start_date` / `end_date` pair applies to both charts. The optional country filter also applies to both charts. A valid custom date pair returns only the `Custom` response key.
- **Rating & Type:** The rating and organization-type charts support separate custom date ranges. Country filtering is also supported.
- **Size & Contribution:** One `start_date` / `end_date` pair applies to both charts. Country and `organization_type` filters apply to both charts. A valid custom date pair returns only `Custom`; without custom dates, the response contains `7D`, `30D`, `1Y`, and `All`.

These differences should be considered when interpreting API requests and responses.

## 5. Metrics and calculations

### 5.1 Growth & Trend

**Implementation:** `data-analytics/lambda_functions/growth_trend_analytics.py`

**Related work:** [Issue #539](https://github.com/saayam-for-all/data/issues/539), [PR #567](https://github.com/saayam-for-all/data/pull/567), [PR #592](https://github.com/saayam-for-all/data/pull/592).

The API returns `growth_trend` and `organizations_by_location`.

**Total organizations**

- Organizations are grouped by day or month, depending on the selected reporting period.
- The API calculates a cumulative organization count over the available filtered history.
- It returns the cumulative value for periods represented in the selected window.

**Collaborators**

- Organizations marked as collaborators are counted within each period.
- This is a per-period count, not a cumulative count.
- Periods with no collaborators are represented with zero when the period otherwise appears in the window.

**Organizations by location**

- Without a selected country, organizations are grouped by country code.
- With a selected country, organizations are grouped by state.
- Results are sorted by descending count and then alphabetically.
- The implementation does not impose a location limit or group remaining locations into an “Other” category.

The implementation groups `7D`, `30D`, and `Custom` by day, and `1Y` and `All` by month.

### 5.2 Rating & Type

**Proposed implementation:** `data-analytics/lambda_functions/organization_rating_type_analytics.py`

**Related work:** [Issue #380](https://github.com/saayam-for-all/data/issues/380), [PR #601](https://github.com/saayam-for-all/data/pull/601).

**Rating distribution**

- Counts organizations with ratings from 1 through 5.
- Ratings with no matching organizations are omitted rather than automatically returned with a zero count.

**Organization-type trend**

- Tracks cumulative counts for `non_profit` and `for_profit` organizations.
- Groups results by day or month, depending on the reporting period.
- The reviewed implementation emits periods containing organizations in the selected display window.
- Cumulative type totals can include organizations created before the visible window.

The proposed implementation supports country filtering and separate custom date ranges for the rating and type charts.

### 5.3 Size & Contribution

**Proposed implementation:** `data-analytics/lambda_functions/size_and_contribution.py`

**Related work:** [Issue #376](https://github.com/saayam-for-all/data/issues/376), [Issue #569](https://github.com/saayam-for-all/data/issues/569), [Issue #583](https://github.com/saayam-for-all/data/issues/583), [PR #600](https://github.com/saayam-for-all/data/pull/600).

**Organization size**

- Counts organizations by the available size categories, such as small, medium, and large.
- Categories without matching records may be omitted.

**Collaborators and contributors**

- Counts organizations marked as collaborators and contributors.
- Calculates each percentage using the total number of organizations in the selected date range as the denominator.
- The collaborator and contributor percentages are independent and do not necessarily add up to 100%.

Issue #583 specifies that the same custom date range, country filter, and organization-type filter apply to both charts. It also specifies that the standard response should contain `7D`, `30D`, `1Y`, and `All`, with `Custom` returned when a valid custom date range is supplied.

## 6. Data Sources and Implementation Approach

The Organization Analytics APIs use organization records and geographic reference data to calculate their metrics.

### 6.1 Growth & Trend

The Growth & Trend API uses:
- `organizations.csv`
- `states.csv`
- `countries.csv`

The geographic relationship is established through `organizations.state_id`, `states.country_id`, and country identifiers or codes.

The sample datasets are maintained under `data-analytics/mock-data-generation/`.

Relevant implementation:
- `data-analytics/lambda_functions/growth_trend_analytics.py`

### 6.2 Rating & Type

The Rating & Type API uses organization rating, organization type, creation date, and geographic reference data.

The country filter relies on the relationship between organizations, states, and countries.

Relevant implementation:
- `data-analytics/lambda_functions/organization_rating_type_analytics.py`

PR #601 documents local testing with temporary mock CSV files. It does not establish successful AWS deployment.

### 6.3 Size & Contribution

The Size & Contribution implementation evolved through Issues #376, #569, and #583.

- The earlier Issue #569 implementation allowed mock-data configuration and optional PostgreSQL access.
- The later Issue #583 / PR #600 changes the approach to CSV-based mock data.
- PR #600 reads `organizations.csv`, `states.csv`, and `countries.csv` from a `mock_data` folder next to the Python file.
- The PR removes PostgreSQL connection code, database environment variables, and the `USE_MOCK_DATA` and `MOCK_DATA_DIR` switches.

Relevant implementation:
- `data-analytics/lambda_functions/size_and_contribution.py`

For local testing, the CSV files are copied from `data-analytics/mock-data-generation/` into the required `mock_data` folder. The copied mock-data folder is not committed as part of the PR.

### 6.4 Important implementation note

The issues and PRs describe different stages of development. Later changes should be distinguished from earlier implementations. The final merged code and deployment configuration must be checked before describing any implementation as production behavior.

## 7. Request validation and error handling

The reviewed Growth & Trend implementation:

- Returns HTTP 200 for successful requests.
- Returns HTTP 400 for invalid JSON, invalid date ranges, invalid country types, and unknown countries.
- Returns HTTP 500 for unexpected errors.
- Includes JSON content-type and CORS headers in its responses.

The Rating & Type and Size & Contribution implementations also include request validation. Their final error behavior should be checked against the merged versions before being treated as a production contract.

### 7.1 API validation differences

The APIs do not have one shared validation contract.

**Growth & Trend:**
- Invalid or incomplete date pairs return HTTP 400.
- Invalid date formats and start dates later than end dates return HTTP 400.
- Non-string or unknown country values return HTTP 400.
- A valid country with no matching organizations returns HTTP 200 with empty charts.

**Rating & Type:**
- PR #601 documents testing of independent date filters, custom date validation, and country-code/name filtering.
- Exact production error responses remain subject to verification against the final merged implementation.

**Size & Contribution:**
- Invalid or incomplete custom date pairs return HTTP 400.
- Blank or null date values behave like dates not supplied.
- Country and organization-type filters retain their existing behavior.

Do not assume that every API returns identical error messages or response structures.

## 8. Known limitations and items to verify

### 8.1 Data-file naming and paths

**Rating & Type:**

PR #601 uses configurable mock-data loading. Its local testing notes use temporary CSV files and identify country/state mapping as something that must be verified against the actual database mappings. The final deployed data-source configuration remains unverified.

**Size & Contribution:**

The earlier Issue #569 implementation supported configurable mock-data and PostgreSQL sources. However, the later Issue #583 / PR #600 implementation removes PostgreSQL access and environment-variable switches. It expects a `mock_data` folder next to `size_and_contribution.py`.

The sample CSVs originate from `data-analytics/mock-data-generation/` and must be copied into that folder for local testing. This is an expected difference between the sample-data source directory and the function's runtime data directory, not necessarily a path mismatch.

Verify that the required CSV files are present in the Lambda deployment package before deployment.

### 8.2 Different metric semantics

Growth & Trend's total organization count is cumulative, whereas its collaborator count is per period. Rating & Type's organization-type trends are cumulative. Size & Contribution calculates counts and percentages within the selected date range.

These differences should be reflected in chart labels and tooltips.

### 8.3 Different date-window rules

The APIs do not necessarily use identical definitions of `1Y`, Custom, or cumulative totals. The final implementation should be checked for consistent behavior where the dashboard requires it.

### 8.4 Missing periods and categories

Some implementations omit categories or periods with no matching records. Verify whether the frontend expects explicit zero values.

### 8.5 Country and state mappings

Country filtering depends on the relationship between organizations, states, and countries. The CSV column names, identifiers, and database mappings must agree with the code.

### 8.6 Deployment and integration

The reviewed code does not establish whether all APIs are deployed, connected to the dashboard, or running against production data. Verify the final merged code, Lambda configuration, database access, and frontend integration.

### 8.7 Testing

Confirm that automated tests cover:

- Default reporting periods.
- Custom date boundaries and invalid date pairs.
- Country and organization-type filters.
- Empty datasets and missing categories.
- Correct data-source paths and column names.
- Error responses and production configuration.

## 9. Related issues and pull requests

### Dashboard design

- [Issue #81 — Application Analytics parent issue](https://github.com/saayam-for-all/data/issues/81)
- [Issue #82 — Design of Application Analytics tab](https://github.com/saayam-for-all/data/issues/82)

### Growth & Trend

- [Issue #539 — Custom date range and country filter](https://github.com/saayam-for-all/data/issues/539)
- [PR #570 — Growth & Trend country filter and custom date range](https://github.com/saayam-for-all/data/pull/570)
- [PR #572 — Related Growth & Trend work](https://github.com/saayam-for-all/data/pull/572)
- [PR #592 — Related Growth & Trend work](https://github.com/saayam-for-all/data/pull/592)

### Rating & Type

- [Issue #380 — Rating & Type Analytics API](https://github.com/saayam-for-all/data/issues/380)
- [PR #567 — Organization Rating & Type Analytics API](https://github.com/saayam-for-all/data/pull/567)
- [PR #601 — Rating & Type implementation](https://github.com/saayam-for-all/data/pull/601)

### Size & Contribution

- [Issue #376 — Original Size & Contribution requirements](https://github.com/saayam-for-all/data/issues/376)
- [Issue #569 — Size & Contribution fixes](https://github.com/saayam-for-all/data/issues/569)
- [Issue #583 — Shared date range and data-source requirements](https://github.com/saayam-for-all/data/issues/583)
- [PR #575](https://github.com/saayam-for-all/data/pull/575), [PR #576](https://github.com/saayam-for-all/data/pull/576), [PR #577](https://github.com/saayam-for-all/data/pull/577), [PR #589](https://github.com/saayam-for-all/data/pull/589), [PR #595](https://github.com/saayam-for-all/data/pull/595), [PR #596](https://github.com/saayam-for-all/data/pull/596), [PR #597](https://github.com/saayam-for-all/data/pull/597), [PR #598](https://github.com/saayam-for-all/data/pull/598), [PR #600](https://github.com/saayam-for-all/data/pull/600)

### Documentation task

- [Issue #604 — Document Application Analytics Flow and Implementation: Organization Dashboard](https://github.com/saayam-for-all/data/issues/604)

## 10. Conclusion

The Organization tab is intended to provide a consolidated view of organization growth, location, ratings, type, size, and contribution activity. Its APIs use date ranges and filters to calculate metrics from organization records.

Before treating this documentation as a complete description of production behavior, verify the final merged implementations, data-file paths, database configuration, and dashboard integration. Update this document when those details are confirmed.
