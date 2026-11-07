# Application Analytics KPI Tab

This document addresses [issue #599](https://github.com/saayam-for-all/data/issues/599). It describes the intended KPI experience, the implementations present in this repository, their development history, and questions that remain open.

Reviewed against `dev` commit [`fb300562d71d86c97f63c4353d5e8b63400968ee`](https://github.com/saayam-for-all/data/commit/fb300562d71d86c97f63c4353d5e8b63400968ee) on November 7, 2026. Repository code and task comments do not establish which version is deployed. No authenticated frontend, live AWS, or live database verification was performed.

## Purpose and intended experience

The KPI tab is part of **Super Admin Dashboard → Application Analytics**. It is intended to help administrators understand the current state of help requests and how long resolved requests take to service.

The design identifies two KPI visuals:

| Visual | Intended measure | Design |
| --- | --- | --- |
| Request status distribution | Requests grouped as resolved, pending/unresolved, or in progress | Donut chart |
| Average resolution time by category | Average time to service requests, grouped by help category | Column chart |

The backend also returns total request counts and fixed SLA reference values. It returns database status labels directly; mapping those values to the three presentation groups is not implemented in the inspected handlers. Other Application Analytics visuals (requests by region, beneficiaries, volunteers, organizations, and donors) are outside this KPI document's scope.

## Related task history

The following tasks were reviewed individually, including their descriptions and available comments. Issue #84 has two attachments, both reviewed below. No attachment was present in the issue data reviewed for #74, #81, #82, #160, or #181. A PR description records a proposal or reported test; it does not by itself prove deployment.

### Resolution-time analysis — [#74](https://github.com/saayam-for-all/data/issues/74)

This earlier task asks for minimum, maximum, and average request-resolution times, plus a way to show improvement over time. Its [comment](https://github.com/saayam-for-all/data/issues/74#issuecomment-3683368923) defines resolution time as the interval from request creation to closure. The inspected KPI handlers calculate category averages only; minimum, maximum, and an improvement trend are not present. No implementation PR is cross-referenced by this issue.

### Super Admin analytics design — [#81](https://github.com/saayam-for-all/data/issues/81) and [#82](https://github.com/saayam-for-all/data/issues/82)

Issue #81 is the umbrella task for Super Admin Dashboard Analytics. Its [completion comment](https://github.com/saayam-for-all/data/issues/81#issuecomment-4120148423) reports that the dashboard implementation was complemented, but does not identify a frontend revision or deployment.

Its child issue #82 specifies Application Analytics, including average resolution time by category and counts of resolved, unresolved, and in-progress requests. A [comment on #82](https://github.com/saayam-for-all/data/issues/82#issuecomment-3579143385) points to the [ML dashboard design wiki](https://github.com/saayam-for-all/ml/wiki/Super-Admin-Dashboard-Analytics-tab-Design); the wiki's current contents were not independently verified. A later [completion comment](https://github.com/saayam-for-all/data/issues/82#issuecomment-4120156989) also does not identify a deployed UI version.

### Sample-data and visualization design — [#84](https://github.com/saayam-for-all/data/issues/84)

Issue #84 proposed a temporary CSV → backend JSON → frontend workflow so UI development could proceed before real database data was available. Its [handoff comment](https://github.com/saayam-for-all/data/issues/84#issuecomment-4120185370) says JSON objects were sent to the UI team.

The two issue attachments were inspected:

- [Schema workbook](https://github.com/user-attachments/files/24040548/Table.column.names_data-1764970855601.xlsx): lists the `virginia_dev_saayam_rdbms` schema and the `request`, `request_status`, and `help_categories` fields used by the current queries. The request dates are timestamp-without-time-zone columns.
- [Visualization specification](https://github.com/user-attachments/files/24040571/Types.of.Visualizations.for.Application.Analytics.Dashboard.docx): specifies a column chart for average resolution time by category and a donut chart for requests by status.

These are historical design artifacts. The current KPI handlers query PostgreSQL directly; they do not read the sample CSVs.

### Real database KPI API — [#160](https://github.com/saayam-for-all/data/issues/160)

Issue #160 replaces the sample-data approach with Virginia PostgreSQL queries and defines the status, total-request, average-resolution-time, and SLA response data. The issue's initial [testing comment](https://github.com/saayam-for-all/data/issues/160#issuecomment-4381598337) reports safe defaults when credentials are unavailable locally. A later [review comment](https://github.com/saayam-for-all/data/issues/160#issuecomment-4743648744) identifies duplicate KPI source files and discrepancies between the requested status values and the database lookup.

Relevant implementation PRs:

| PR | State and contribution |
| --- | --- |
| [#169](https://github.com/saayam-for-all/data/pull/169) | Merged May 18, 2026. Introduced status counts, total requests, category resolution averages, SLA metadata, and local CSV-based checks. |
| [#173](https://github.com/saayam-for-all/data/pull/173) | Merged June 1, 2026. Corrected schema/table references and excluded invalid negative resolution durations. |
| [#180](https://github.com/saayam-for-all/data/pull/180) | Open and unmerged at review; an alternative database implementation. |
| [#223](https://github.com/saayam-for-all/data/pull/223) | Open and unmerged at review; proposes restricting statuses and resolution averages to `RESOLVED`, and notes that `COMPLETED` may not exist in the status lookup. |

The currently inspected code still allows both `COMPLETED` and `RESOLVED` in the resolution-time query and returns every status found by the status query. Confirm the live lookup vocabulary and intended status grouping before changing that behavior.

### Date-filter support — [#181](https://github.com/saayam-for-all/data/issues/181)

Issue #181 requests request-submission-date filters, custom-date handling, and preservation of the KPI and SLA response data. The issue's only retrieved [comment](https://github.com/saayam-for-all/data/issues/181#issuecomment-4868041037) says “Opened” and adds no implementation detail.

The [merged PR #190](https://github.com/saayam-for-all/data/pull/190) describes support for preset and custom date ranges. The date-filter history also includes the [merged revert PR #195](https://github.com/saayam-for-all/data/pull/195), which reverts PR #192. Other open proposals, such as [#211](https://github.com/saayam-for-all/data/pull/211), are alternatives rather than evidence of the final contract. The two KPI source files on the reviewed `dev` commit differ: the `data-analytics` implementation has filters, while the `data-engineering` implementation does not.

## Data flow and implementation

The intended path is dashboard → KPI request → Lambda handler → PostgreSQL → chart-ready response. The repository does not establish the frontend call site, API Gateway mapping, authorization, deployed Lambda, or which of the two source files is canonical.

### Available source files

- [`data-analytics/lambda_functions/kpi_api_analytics.py`](../lambda_functions/kpi_api_analytics.py) ([pinned source](https://github.com/saayam-for-all/data/blob/fb300562d71d86c97f63c4353d5e8b63400968ee/data-analytics/lambda_functions/kpi_api_analytics.py)): returns grouped date buckets for preset filters and a separate response for custom dates. It obtains decrypted credentials through boto3 SSM in `us-east-1`.
- [`data-engineering/src/kpi_api_analytics.py`](../../data-engineering/src/kpi_api_analytics.py) ([pinned source](https://github.com/saayam-for-all/data/blob/fb300562d71d86c97f63c4353d5e8b63400968ee/data-engineering/src/kpi_api_analytics.py)): returns a flat, unfiltered KPI response and uses AWS Lambda Powertools parameter retrieval.

Both use `psycopg2`, the `virginia_dev_saayam_rdbms` schema, and the SSM parameter `/dev/saayam/db/Virginia/Analytics/user`. The analytics implementation builds a Python dictionary in the outer response's `body`; the engineering implementation serializes the body to JSON. Confirm the actual deployment and API integration before relying on either response shape.

The database relationships used by both implementations are:

| Table | Relevant columns | Use |
| --- | --- | --- |
| `request` | `req_id`, `req_status_id`, `req_cat_id`, `submission_date`, `serviced_date` | Request records, current status/category references, and elapsed-time dates |
| `request_status` | `req_status_id`, `req_status` | Status lookup joined by `req_status_id` |
| `help_categories` | `cat_id`, `cat_name` | Category lookup joined by `req_cat_id` |

No credential values are documented here.

## KPI definitions and calculations

The following describes the SQL behavior in the `data-analytics` implementation. The `data-engineering` implementation uses the same core measures but does not support the date buckets.

| Response field | Calculation |
| --- | --- |
| `request_status_distribution` | Count of `request.req_id`, grouped by the current `request_status.req_status`; the analytics implementation additionally groups by submission-date period for bucketed ranges. The inner join omits requests without a matching status row. |
| `total_requests` | Count of `request.req_id`, filtered by the selected range where supported. This query does not join the status lookup, so it can differ from the sum of the status distribution if lookup references are missing. |
| `average_resolution_time_by_category` | Average of `(serviced_date - submission_date)` converted to hours, rounded to two decimals and grouped by category (and submission-date period for bucketed ranges). Rows require both dates, a nonnegative duration, matching category/status rows, and a status of `COMPLETED` or `RESOLVED`. |
| `sla` | Fixed reference values: target 10 days / 240 hours and warning 8.33 days / 200 hours. The handler does not calculate an SLA compliance rate or breach count. |

Status counts use current state, not status-transition history. Resolution cohorts are filtered/grouped by request submission date, not service date. The category average excludes open requests and rows with missing or invalid dates.

### Date-range behavior in `data-analytics`

| Range | Current predicate on `submission_date` | Grouping |
| --- | --- | --- |
| `7D` | At or after `CURRENT_DATE - INTERVAL '7 days'` | Daily |
| `30D` | At or after `CURRENT_DATE - INTERVAL '30 days'` | Daily |
| `1Y` | At or after `CURRENT_DATE - INTERVAL '1 year'` | Monthly |
| `All` | At or after `CURRENT_DATE - INTERVAL '2 years'` | Monthly |
| `Custom` | `BETWEEN` the supplied start and end values when both are present | Daily |
| `Snapshot` | No date predicate | Unbucketed |

The `All` range is therefore limited to two years, not unlimited history. Preset predicates have no explicit upper bound. Custom dates are bound SQL parameters, but missing values result in no date predicate and the handler does not validate date format or ordering. Since the source columns are timestamps without time zones, timezone interpretation and inclusive end-date behavior need confirmation.

For the analytics handler, an empty event returns the preset buckets (`7D`, `30D`, `1Y`, `All`, `Snapshot`) together; the `Custom` key remains an empty placeholder. An event with `time_range: "Custom"` returns a flat KPI object instead of a `Custom` bucket. This is code behavior, not a verified frontend request flow. The engineering handler returns one flat response and does not accept a date range.

## Error behavior and limitations

- A connection/setup failure returns status 500 with default KPI values. Individual query failures are logged and leave that metric at its default while the analytics handler can still return status 200. No per-metric error indicator distinguishes failed queries from genuinely empty results.
- Both handlers close their cursor and connection in `finally`. Full live RDS behavior and deployed error handling were not verified.
- The backend does not map raw statuses to the design's resolved/pending/in-progress categories.
- The API response shapes differ between the source files and between preset and custom requests. The frontend integration contract remains unverified.
- Which handler is deployed, the endpoint and gateway mapping, authorization, frontend revision, and current database status vocabulary remain unknown.
- The custom-date requirements, `All` semantics, timezone, and whether resolution time should be grouped by submission or service date need agreement.
- Minimum/maximum resolution times, improvement trends, and SLA compliance metrics are design asks not implemented by the inspected handlers.

Before treating this document as a production integration contract, confirm the deployed source and frontend call site, compare the live response shapes, validate the status lookup and timezone policy, and agree on `All` and custom-date semantics.
