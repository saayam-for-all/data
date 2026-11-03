# Application Analytics — KPI Tab Documentation

## 1. Purpose

The KPI tab is part of the **Application Analytics** section of the Saayam For All Super Admin Dashboard.

Its purpose is to help administrators understand how help requests are progressing through the platform and how efficiently requests are being resolved.

The KPI tab currently focuses on three related measurements:

| KPI | Purpose |
|---|---|
| Request Status Distribution | Shows how many requests exist in each request status |
| Total Requests | Shows the total number of requests for the selected period |
| Average Resolution Time by Category | Measures how long resolved requests take to complete, grouped by help category |

The backend also returns SLA reference values that can be used by the dashboard to compare actual resolution times against expected service levels.

---

# 2. Historical Task Review

This section documents the tasks and implementation work that led to the current KPI tab.

## 2.1 Issue #81 — Creation of Super Admin Dashboard Analytics

[Issue #81](/saayam-for-all/data/issues/81)

Issue #81 was the higher-level dashboard analytics task under which Application Analytics work was organized.

The Application Analytics design work was later broken into more focused tasks, including Issue #82 for defining the dashboard visuals.

The issue established the overall Super Admin analytics direction rather than implementing the KPI API itself.

---

## 2.2 Issue #82 — Design of Application Analytics Tab

[Issue #82](/saayam-for-all/data/issues/82)

Issue #82 defined the original Application Analytics dashboard structure.

For the KPI section, it specified two main visuals:

| Original KPI visual | Description |
|---|---|
| Average Resolution Time by Category | Measure how long requests take to resolve for different help categories |
| Request Resolution Status | Show the number of requests that are resolved, unresolved, or in progress |

The same Application Analytics design also included Requests, Beneficiaries, Volunteers, Organizations, and Donors.

This task established the dashboard requirements but did not provide the production database implementation.

---

## 2.3 Issue #160 — Real KPI Analytics API

[Issue #160](/saayam-for-all/data/issues/160)

Issue #160 converted the KPI concept into a real backend API.

The task required an AWS Lambda function called `kpi_api_analytics.py` that connects to the Virginia PostgreSQL RDS database and returns chart-ready data.

The required database tables were:

| Table | Purpose |
|---|---|
| `request` | Stores help request data |
| `request_status` | Provides request status lookup values |
| `help_categories` | Provides help category information |

The task required the API to avoid mock CSV data and use the Virginia database.

### Request Status Distribution

The original #160 requirement expected the KPI API to report request counts for:

`CREATED`

`IN_PROGRESS`

`RESOLVED`

The expected relationship was:

`request.req_status_id = request_status.req_status_id`

The API was also required to return the total number of requests.

### Average Resolution Time

Issue #160 required resolution time to be calculated using:

`request.submission_date`

and

`request.serviced_date`

The final implementation calculates elapsed resolution time in hours as:

`serviced_date - submission_date`

and averages the result for each help category.

Only records where both dates are present and `serviced_date >= submission_date` are included.

### SLA Metadata

The dashboard SLA reference values defined by #160 are:

| SLA level | Days | Hours |
|---|---:|---:|
| Target | 10 | 240 |
| Warning | 8.33 | 200 |

The SLA object is returned even when no resolution-time records are available.

### Error Handling

Issue #160 also required the Lambda to fail safely.

When a database connection cannot be established, the Lambda returns HTTP `500`.

When an individual KPI query fails, the implementation attempts to preserve the rest of the response by returning safe values such as an empty array or zero.

Database cursor and connection resources are closed in the `finally` block.

### Implementation History

The Git history shows several stages of development for #160.

PR #169 introduced KPI analytics work and was subsequently reverted.

[PR #169](/saayam-for-all/data/pull/169)

PR #173 later merged additional KPI implementation work.

[PR #173](/saayam-for-all/data/pull/173)

Additional #160 commits added database connectivity, status distribution, resolution-time calculations, safe response defaults, local testing, and configuration/error-handling improvements.

One implementation comment reported that the Lambda could be tested locally with safe default responses but that Virginia RDS credentials were not yet available for live local testing.

Another review comment identified two differences between the task requirements and the code:

1. The implementation returned every status present in `request_status`, while the issue specifically listed `CREATED`, `IN_PROGRESS`, and `RESOLVED`.

2. The implementation checked both `COMPLETED` and `RESOLVED`, while the reviewer reported that the request-status lookup contained `RESOLVED` but not `COMPLETED`.

These differences remain important when interpreting the current implementation.

---

## 2.4 Issue #181 — KPI Date Filter Support

[Issue #181](/saayam-for-all/data/issues/181)

After the original KPI API was implemented, additional work added dashboard date filters.

Repository history and team meeting records show that Issue #181 was used for KPI time-filter development and testing.

The work introduced or refined:

| Time option | Current backend behavior |
|---|---|
| `7D` | Requests submitted during the previous 7 days |
| `30D` | Requests submitted during the previous 30 days |
| `1Y` | Requests submitted during the previous year |
| `All` | Requests submitted during the previous two years in the current implementation |
| `Custom` | Uses caller-provided `start_date` and `end_date` |
| `Snapshot` | Returns an ungrouped current aggregate |

For 7-day and 30-day ranges, the current implementation groups results by day.

For 1-year and All ranges, it groups results by month.

The custom range is grouped by day.

Several branches and PRs were created while #181 was being developed.

Relevant PR history includes:

[PR #190](/saayam-for-all/data/pull/190)

[PR #192](/saayam-for-all/data/pull/192)

[PR #195](/saayam-for-all/data/pull/195)

The Git history shows that date-filter code was added, merged, reverted, and subsequently restored/fixed before later commits continued refining the implementation.

The exact Issue #181 description and all attachments were not available during this documentation review. Therefore, the Issue #181 behavior in this document is reconstructed from repository history, current code, and team meeting records.

---

# 3. Current Code Locations

Two KPI implementations currently exist in the repository.

### Data Analytics Lambda

[Current Data Analytics KPI Lambda](../lambda_functions/kpi_api_analytics.py)

Path:

`data-analytics/lambda_functions/kpi_api_analytics.py`

This version contains the more extensive time-range implementation.

It supports:

`7D`

`30D`

`1Y`

`All`

`Custom`

`Snapshot`

It also performs period-based grouping and custom date filtering.

### Data Engineering Copy

[Data Engineering KPI implementation](../../data-engineering/src/kpi_api_analytics.py)

Path:

`data-engineering/src/kpi_api_analytics.py`

This version provides a simpler aggregate response without the newer date-range functionality.

It also uses a different AWS Parameter Store access mechanism.

The repository does not currently contain an explicit statement identifying which of these two files is the canonical source of truth.

Based on the Git history and #181 date-filter work, the `data-analytics/lambda_functions` implementation appears to represent the more evolved dashboard API.

This should be confirmed with the Data Analytics/Data Engineering leads before future development consolidates or removes either copy.

---

# 4. User Flow

The intended user flow is:

Super Admin Dashboard
→ Application Analytics
→ KPI tab
→ Select or load a time period
→ Dashboard requests KPI analytics
→ Lambda queries PostgreSQL
→ Aggregated metrics are returned
→ KPI charts are rendered

The default backend call can return multiple predefined periods together.

A custom date range uses a dedicated `Custom` request with start and end dates.

The exact frontend component and API invocation logic are outside the `data` repository and therefore were not verified as part of this documentation task.

---

# 5. Backend Data Flow

The backend flow is:

Dashboard / API consumer
→ AWS Lambda
→ `kpi_api_analytics.py`
→ AWS Systems Manager Parameter Store
→ Virginia PostgreSQL RDS
→ SQL aggregation queries
→ JSON response
→ Dashboard charts

The current analytics Lambda reads database credentials from:

`/dev/saayam/db/Virginia/Analytics/user`

in AWS region:

`us-east-1`

The PostgreSQL connection uses SSL with:

`sslmode="require"`

No credentials are stored directly in the source file.

---

# 6. Data Sources

## 6.1 Request Table

The `request` table provides the main KPI records.

Important fields used by the KPI implementation include:

| Field | Use |
|---|---|
| `req_id` | Count requests |
| `req_status_id` | Join request status |
| `req_cat_id` | Join help category |
| `submission_date` | Determine request creation time and time filter |
| `serviced_date` | Determine when a request was serviced/resolved |

---

## 6.2 Request Status Table

The `request_status` table is joined using:

`request.req_status_id = request_status.req_status_id`

The status name is returned using:

`request_status.req_status`

The current implementation groups by every status returned from this table.

---

## 6.3 Help Categories Table

The `help_categories` table is joined using:

`request.req_cat_id = help_categories.cat_id`

The category name used in the KPI response is:

`help_categories.cat_name`

This allows average resolution times to be displayed by help category.

---

# 7. KPI Definitions and Calculations

## 7.1 Request Status Distribution

Request Status Distribution counts requests by their current request status.

Conceptually:

`COUNT(request.req_id) GROUP BY request_status.req_status`

For date-grouped results, the backend additionally groups requests by submission period.

An example response item is:

```json
{
  "period": "2026-09-01",
  "status": "RESOLVED",
  "count": 25
}
```

For Snapshot mode, the period field is omitted.

---

## 7.2 Total Requests

Total Requests counts request records for the selected time range.

Conceptually:

`COUNT(request.req_id)`

For grouped date ranges, results contain a period and corresponding request count.

Example:

```json
{
  "period": "2026-09",
  "total_requests": 140
}
```

Snapshot returns a single integer.

---

## 7.3 Average Resolution Time by Category

Average Resolution Time measures the average elapsed time between request submission and servicing.

The implemented SQL calculation is:

`EXTRACT(EPOCH FROM (serviced_date - submission_date)) / 3600`

This converts the PostgreSQL interval into hours.

The result is then averaged:

`AVG(resolution_time_hours)`

and grouped by:

`help_categories.cat_name`

The value is rounded to two decimal places.

Example:

```json
{
  "category": "Shelter",
  "avg_hours": 218.75
}
```

For time-grouped queries, a `period` field is also included.

Records are excluded when:

`submission_date` is null

`serviced_date` is null

or

`serviced_date < submission_date`

---

# 8. SLA Definitions

The API always includes SLA metadata:

```json
{
  "target_days": 10,
  "target_hours": 240,
  "warning_days": 8.33,
  "warning_hours": 200
}
```

These values are reference thresholds for interpreting average resolution times.

The backend currently returns these thresholds but does not itself classify each category as good, warning, or over-SLA.

That interpretation may be performed by the dashboard UI.

---

# 9. Time Filter Implementation

The date filter is applied to:

`request.submission_date`

Current filters are:

| Filter | SQL behavior |
|---|---|
| 7D | `submission_date >= CURRENT_DATE - INTERVAL '7 days'` |
| 30D | `submission_date >= CURRENT_DATE - INTERVAL '30 days'` |
| 1Y | `submission_date >= CURRENT_DATE - INTERVAL '1 year'` |
| All | `submission_date >= CURRENT_DATE - INTERVAL '2 years'` |
| Custom | `submission_date BETWEEN start_date AND end_date` |
| Snapshot | No time grouping |

The name `All` is potentially misleading because the current implementation limits this range to two years rather than querying all historical records.

---

# 10. API Response Behavior

## Default / Consolidated Request

When no custom time range is supplied, the current Data Analytics Lambda builds data for:

`7D`

`30D`

`1Y`

`All`

`Snapshot`

The default response also contains an empty `Custom` entry and the SLA object.

Each time-range entry contains:

```json
{
  "request_status_distribution": [],
  "total_requests": 0,
  "average_resolution_time_by_category": []
}
```

---

## Custom Request

For a custom request, the event is expected to provide:

```json
{
  "time_range": "Custom",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD"
}
```

The API returns a custom KPI result containing:

```json
{
  "request_status_distribution": [],
  "total_requests": 0,
  "average_resolution_time_by_category": [],
  "sla": {}
}
```

The current code does not perform extensive explicit validation of custom date format or confirm that `start_date <= end_date` before executing the database query.

---

# 11. Error Handling

The implementation uses separate exception handling around the database connection and individual analytics queries.

If the database connection fails, the Lambda returns status code `500` with the safe/default response structure.

If only one KPI query fails, the Lambda logs the error and attempts to return the remaining KPI values.

Safe defaults are:

| Metric | Safe value |
|---|---|
| Status distribution | `[]` |
| Total requests | `0` |
| Average resolution time | `[]` |

Cursor and database connection objects are closed in the `finally` block when they were successfully created.

---

# 12. Implementation Evolution

Repository history shows the KPI backend evolved through multiple development stages.

| Period | Main change |
|---|---|
| May 2026 | Initial KPI database connection and status-distribution implementation |
| May 2026 | Average resolution time and SLA metadata added |
| May–June 2026 | Error handling, local test behavior, and database configuration improved |
| June 2026 | Real API implementation revised and merged through #160 work |
| June–July 2026 | #181 introduced date-range filters |
| June–July 2026 | Multiple date-filter PRs were merged/reverted/refined |
| August 2026 | Additional KPI date-range filtering fixes were committed |

Notable implementation commits include work associated with #160 and #181.

The history indicates that KPI development was iterative and that several contributors implemented overlapping solutions before the current version emerged.

---

# 13. Known Limitations and Open Questions

### Duplicate implementations

There are currently two KPI API implementations:

`data-analytics/lambda_functions/kpi_api_analytics.py`

and

`data-engineering/src/kpi_api_analytics.py`

They are not identical.

The canonical production source should be confirmed.

### Request status mismatch

Issue #160 specifically lists:

`CREATED`

`IN_PROGRESS`

`RESOLVED`

The current status-distribution query does not restrict results to those three values. It groups every status present in the database.

### COMPLETED vs RESOLVED

The resolution-time query currently accepts:

`COMPLETED`

or

`RESOLVED`

A review comment on #160 reported that the request-status lookup contained `RESOLVED` but did not contain `COMPLETED`.

This should be verified against the current Virginia database.

### Resolution formula wording

Issue #160 described the formula as:

`submission_date - serviced_date`

The implementation instead calculates:

`serviced_date - submission_date`

The implemented version represents positive elapsed resolution time and is also protected by the condition:

`serviced_date >= submission_date`

The discrepancy between issue wording and implementation should be considered a documentation inconsistency.

### `All` does not mean all history

The current implementation treats `All` as the previous two years.

This may differ from what users expect from a filter labeled "All."

### Custom date validation

The implementation accepts `start_date` and `end_date`, but explicit format validation and reversed-range validation are not clearly implemented before the SQL query runs.

### Frontend integration

This repository contains the analytics backend but not the complete frontend implementation of the KPI tab.

Therefore, exact frontend rendering behavior, API URL, refresh behavior, and user-facing error states were not verified here.

### Current frontend issue

A separate issue currently exists in the web application repository titled **Application Analytics-KPI bug**.

[webapp Issue #1953](/saayam-for-all/webapp/issues/1953)

The exact bug details should be reviewed separately when updating or troubleshooting the KPI UI.

### Live environment verification

Historical #160 comments show that at least one early implementation was tested locally without access to the Virginia RDS credentials.

This document does not independently verify the current production Lambda deployment, API Gateway configuration, or current live RDS results.

---

# 14. Supporting References

| Type | Reference |
|---|---|
| Parent analytics task | [Issue #81](/saayam-for-all/data/issues/81) |
| Application Analytics design | [Issue #82](/saayam-for-all/data/issues/82) |
| Real KPI API implementation | [Issue #160](/saayam-for-all/data/issues/160) |
| KPI date-filter development | [Issue #181](/saayam-for-all/data/issues/181) |
| Current documentation task | [Issue #599](/saayam-for-all/data/issues/599) |
| KPI implementation PR | [PR #169](/saayam-for-all/data/pull/169) |
| KPI implementation PR | [PR #173](/saayam-for-all/data/pull/173) |
| KPI date-filter PR | [PR #190](/saayam-for-all/data/pull/190) |
| KPI date-filter PR | [PR #192](/saayam-for-all/data/pull/192) |
| KPI date-filter/revert work | [PR #195](/saayam-for-all/data/pull/195) |
| Current analytics Lambda | [kpi_api_analytics.py](../lambda_functions/kpi_api_analytics.py) |
| Alternate data-engineering implementation | [kpi_api_analytics.py](../../data-engineering/src/kpi_api_analytics.py) |

---

# 15. Summary

The KPI tab began as part of the Application Analytics dashboard design and evolved into a PostgreSQL-backed AWS Lambda API.

Its primary purpose is to provide Super Admin users with visibility into request volume, request status, and request-resolution performance.

The backend currently calculates request status distribution, total requests, average resolution time by help category, and SLA reference values.

Later work added predefined and custom date ranges so KPI behavior could be analyzed over time.

The implementation is functional but has several areas that require clarification, particularly duplicate KPI source files, request-status filtering, the meaning of the `All` range, `COMPLETED` versus `RESOLVED`, custom-date validation, and identification of the canonical production Lambda.

These ambiguities should be resolved before future KPI backend changes are consolidated.
