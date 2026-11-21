# KPI Tab Documentation — Application Analytics (Super Admin Dashboard)

Issue: [#599](https://github.com/saayam-for-all/data/issues/599)

> **Scope and sources.** Written from the code and git history in this repository and from a review of
> the issue list at <https://github.com/saayam-for-all/data/issues> (136 issues, 6 pages, reviewed as of
> 2026-11-02; see [Issue review](#8-issue-review)). Issue/PR text was read from the public GitHub pages;
> attachments (images, .xlsx, .docx) could not be opened. I could not see the Super Admin Dashboard
> front-end code or the deployed AWS configuration. Anything that depends on those is listed under
> [Open questions](#7-missing-or-unclear-information) rather than guessed.

---

## 1. Purpose and features

The KPI tab is part of the **Application Analytics** section of the Super Admin Dashboard. It gives
admins a view of how help **requests** are flowing through the platform:

| Feature | What it shows |
|---|---|
| Request status distribution | Number of requests per status, optionally broken down per time bucket |
| Total requests | Number of requests submitted, optionally per time bucket |
| Average resolution time by category | Mean hours from submission to service, per help category, for completed requests |
| SLA reference | Target and warning thresholds returned with every response so the UI can flag slow categories |
| Time range selector | 7D, 30D, 1Y, All, Custom (start/end date) and a Snapshot (unfiltered totals) |

The backend is a single AWS Lambda: [`data-analytics/lambda_functions/kpi_api_analytics.py`](../lambda_functions/kpi_api_analytics.py).

## 2. User flow

1. A Super Admin opens **Application Analytics → KPI**.
2. On load, the UI calls the Lambda with an empty event (`{}`) and receives **all preset ranges in one
   response** (`7D`, `30D`, `1Y`, `All`, `Snapshot`). Switching between presets therefore needs no
   further API call.
3. If the admin picks **Custom**, the UI calls the Lambda again with
   `{"time_range": "Custom", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}` and receives a
   single, flat result for that range.
4. The UI renders the status distribution, total requests and per-category resolution time, and uses
   the `sla` block to highlight categories over the warning/target threshold.

*(Steps 1 and 4 are inferred from the response shape; the front-end is not in this repo.)*

## 3. Data sources

Database: PostgreSQL, schema `virginia_dev_saayam_rdbms` (hard-coded as `SCHEMA_NAME`).

| Table | Columns used | Used for |
|---|---|---|
| `request` | `req_id`, `submission_date`, `serviced_date`, `req_status_id`, `req_cat_id` | all three KPIs |
| `request_status` | `req_status_id`, `req_status` | status names; filtering completed requests |
| `help_categories` | `cat_id`, `cat_name` | category names |

Credentials come from AWS Systems Manager Parameter Store
(`/dev/saayam/db/Virginia/Analytics/user`, decrypted, JSON with `HOST`, `PORT`, `DATABASE NAME`,
`USERNAME`, `PASSWORD`), region `us-east-1`. Connection uses `sslmode=require`.

## 4. KPI definitions and calculations

### 4.1 Request status distribution
Count of `request.req_id` grouped by `request_status.req_status`, within the selected date range.
For time-bucketed ranges it is additionally grouped by period.

### 4.2 Total requests
`COUNT(req_id)` within the selected range, per period for bucketed ranges, a single integer for
`Snapshot`.

### 4.3 Average resolution time by category
```
AVG( (serviced_date - submission_date) in hours )   -- rounded to 2 decimals
```
grouped by `help_categories.cat_name` (and period for bucketed ranges), sorted by `avg_hours`
descending. Only rows that satisfy **all** of:
- `submission_date` and `serviced_date` are not null
- `serviced_date >= submission_date`
- status (upper-cased) is `COMPLETED` or `RESOLVED`

### 4.4 SLA constants
Returned verbatim in every response; not computed from data.

| Field | Value |
|---|---|
| `target_days` / `target_hours` | 10 / 240 |
| `warning_days` / `warning_hours` | 8.33 / 200 |

### 4.5 Time ranges and grouping

| `time_range` | Date filter on `submission_date` | Bucket |
|---|---|---|
| `7D` | last 7 days | day (`YYYY-MM-DD`) |
| `30D` | last 30 days | day |
| `1Y` | last 1 year | month (`YYYY-MM`) |
| `All` | **last 2 years** (see limitations) | month |
| `Custom` | `BETWEEN start_date AND end_date` | day |
| `Snapshot` | none | none (flat totals) |

Date values are passed as bound query parameters (`%s`). The period/format strings are interpolated
into SQL but come only from the fixed mapping above, not from user input.

## 5. Implementation approach

- **One Lambda, one handler** (`lambda_handler`). Empty event → consolidated response keyed by range;
  `time_range == "Custom"` → single flat response.
- **Per-query isolation.** Each KPI query is wrapped in its own `try/except`; a failing query leaves
  its field at the safe default (`[]` / `0`) so one broken query does not blank the tab. A failed DB
  connection returns HTTP 500 with the default body.
- **Safe defaults.** `get_default_response()` guarantees the response shape even on failure.
- **CORS** `Access-Control-Allow-Origin: *` on all responses.
- **Local testing:** `python kpi_api_analytics.py` runs the handler with `{}` (needs AWS creds and DB
  access).

### Response shape

Consolidated (`{}`):
```json
{
  "7D":  {"request_status_distribution": [{"period": "2026-10-01", "status": "OPEN", "count": 3}],
          "total_requests": [{"period": "2026-10-01", "total_requests": 5}],
          "average_resolution_time_by_category": [{"period": "2026-10-01", "category": "Food", "avg_hours": 41.5}]},
  "30D": {}, "1Y": {}, "All": {},
  "Snapshot": {"request_status_distribution": [{"status": "OPEN", "count": 12}],
               "total_requests": 40,
               "average_resolution_time_by_category": [{"category": "Food", "avg_hours": 41.5}]},
  "sla": {"target_days": 10, "target_hours": 240, "warning_days": 8.33, "warning_hours": 200}
}
```
Custom: `{"request_status_distribution": [...], "total_requests": [...], "average_resolution_time_by_category": [...], "sla": {...}}`.

### Development history (from git log)

| Phase | Issue / PR | Summary | Contributors |
|---|---|---|---|
| Design / mock data | [#81](https://github.com/saayam-for-all/data/issues/81), [#82](https://github.com/saayam-for-all/data/issues/82), [#84](https://github.com/saayam-for-all/data/issues/84), [#89](https://github.com/saayam-for-all/data/issues/89) (closed Mar 24 2026) | Defined the Application Analytics tab (requests, resolution KPIs, beneficiaries, volunteers, orgs, donors); mock CSV→JSON served to the UI team | prachi080588 (author) |
| Initial API | [#160](https://github.com/saayam-for-all/data/issues/160) (opened Apr 27 2026; closed Sep 22 2026), PR [#173](https://github.com/saayam-for-all/data/pull/173) (merged Jun 1 2026 by sana-desai) | Lambda skeleton, schema/table fixes, `COMPLETED`/`RESOLVED` filter, invalid-date filtering, Parameter Store credentials, local entry point | soniya487, anupbpote02, others |
| "Real API" implementation | #160, PR [#223](https://github.com/saayam-for-all/data/pull/223) | Nidhi1202's implementation. **PR #223 was still open/unmerged when reviewed** (2 approvals required; reviewers sana-desai, saquibb8), although its commits appear in the local git history | Nidhi1202 |
| Date filters | [#181](https://github.com/saayam-for-all/data/issues/181) (opened Jun 16 2026; closed Sep 22 2026), PRs [#192](https://github.com/saayam-for-all/data/pull/192) (merged Jun 28, rajthakkar18), [#195](https://github.com/saayam-for-all/data/pull/195) (revert, Jun 30), [#190](https://github.com/saayam-for-all/data/pull/190) (v2, merged Jul 2 by bakugou123-ai, KTB2110) | 7D/30D/1Y/All/Custom filters via `build_date_filter()`; merged, reverted, re-applied | KTB2110, rajthakkar18, bakugou123-ai; later commits by other contributors |

Related but separate: `data-engineering/src/kpi_api_analytics.py` is an **earlier, unfiltered** version
(no date ranges, uses `aws_lambda_powertools` for credentials, JSON-encodes the body). Sibling
analytics lambdas: `volunteer_application_analytics.py`, `beneficiariesTrendAnalysis.py`. Acceptance
tests are in `data-analytics/lambda_functions/Test Cases and Acceptance Criteria.docx` (not reviewed —
binary file).

## 6. Known limitations

1. **Response body is not JSON-serialised.** `build_response` in the `data-analytics` version puts a
   Python dict in `"body"`; API Gateway proxy integrations require a string. The `data-engineering`
   version uses `json.dumps(body, default=str)`. Confirm how the deployed API consumes this.
2. **`All` is not all time.** It is filtered to the last 2 years. Use `Snapshot` for true totals.
3. **Inconsistent value types for `total_requests`:** a list of `{period, total_requests}` for bucketed
   ranges, an integer for `Snapshot`. The consolidated default is `0`, so the UI must handle both.
4. **Filter is on `submission_date` only**, so resolution time for a request is attributed to the
   period it was submitted, not the period it was resolved.
5. **Snapshot has no date filter and the avg-resolution query only counts `COMPLETED`/`RESOLVED`**;
   status names are matched case-insensitively against two hard-coded strings and will miss any other
   "done" status.
6. **Custom range is not validated.** Missing `start_date`/`end_date` yields no date filter (all data);
   malformed dates make the query fail silently (logged, returns empty).
7. **Hard-coded environment:** schema `virginia_dev_saayam_rdbms`, SSM path `/dev/...`, region
   `us-east-1`. Promoting to another environment needs code changes.
8. **Failures are swallowed.** Errors are only `print`ed; the UI cannot distinguish "no data" from
   "query failed" except for a full 500.
9. **No automated tests** are checked in (`data-analytics/lambda_functions/tests/` holds only a
   virtualenv); `Access-Control-Allow-Origin: *` is open to any origin.
10. The consolidated call runs 15 queries per invocation (5 ranges × 3 KPIs), sequentially.
11. **Status distribution is not limited to CREATED / IN_PROGRESS / RESOLVED**, which #160 specified;
    the query returns every status (flagged by adarshjadhav17 on #160, Jun 18 2026).
12. **`COMPLETED` is probably dead code.** Per the same comment, `request_status` has no `COMPLETED`
    value, only `RESOLVED`; the filter still lists both.
13. **Min / max / median resolution time are not provided.** #74 and #76 asked for min, max, average,
    improvement trend, and median by category/location (heatmaps/boxplots); the API only returns the
    average by category.
14. **Home-page metrics are separate.** #96/#103/#104 (Total Requests, Requests Resolved, Avg Resolution
    Time, volunteers, beneficiaries from S3) are a different pipeline and are not computed by this Lambda.

## 7. Missing or unclear information

- Attachments could not be opened: the table/column `.xlsx` and visualization-types `.docx` on #84, the
  four images on #76, and the tracking-columns image on #593.
- Files changed / review comments of PRs #173, #190, #192, #195 and #223 were not visible. PRs for
  several commits in the local history (e.g. Manvija Cherukuri, Syeda Sanobar Asna, Mahaveer, Rupendra
  Shata) were not identified; they may be fork PRs or unmerged.
- Whether PR #223 was ever merged, and which code is actually deployed.
- #181's title mentions "Request Volume Trend" and "Requests by Category & Region", but its body covers
  only the three existing KPI functions. The region breakdown does not exist in the Lambda.
- #160 says the formula is `submission_date - serviced_date` (negative); the code uses
  `serviced_date - submission_date`, as noted by the #223 author. The issue text should be corrected.
- #160 names the test script `kpi_analytics.py`; the file is `kpi_api_analytics.py`.
- #160 and #181 show a "Data Analysis" label and large, shifting assignee lists; the people who
  actually delivered the final code are best identified from git history, not assignees.
- #593 (Lambda inventory, PR #619) is in progress; its Lambda names/counts are provisional until AWS
  access is granted. This Lambda's deployed name and console link should be taken from there.
- Front-end implementation, API Gateway route/URL, and how the UI consumes `sla` — not in this repo.
- Deployment: Lambda name, runtime, layers (`psycopg2`, `boto3`), VPC/IAM settings — not documented.
- Whether the `data-engineering/src` copy is still in use or should be removed.
- Intended meaning of "Snapshot" (inferred as "current totals, no date filter").
- `#160` is still listed as "Open" in `data-engineering/TASK_TRACKER.md` although the work was merged.

## 8. Issue review

All 136 issues (6 list pages) were scanned by title; those touching the KPI tab were opened one by one.
Links: `https://github.com/saayam-for-all/data/issues/<n>`.

### Directly about the KPI tab

| # | Title | State | Findings |
|---|---|---|---|
| 160 | Implement real API for KPI_API_Analytics.py | Closed Sep 22 2026 | Defines the 3 KPIs, SLA (10 d / 8.33 d), response shape, error handling. Comments: soniya487 (May 5) asked for RDS credentials; adarshjadhav17 (Jun 18) flagged all-status distribution and missing `COMPLETED`. Linked PR #223 (open). |
| 181 | Add Date Filters for KPI … | Closed Sep 22 2026 (reopened Jul 2) | Adds 7D/30D/1Y/All/Custom. PRs #190 (merged), #192 (merged then reverted by #195). Title/body mismatch (see §7). |
| 599 | Document … KPI Dashboard | Open | This document. |

### Related context

| # | Title | State | Relevance |
|---|---|---|---|
| 74 | Trend Analysis using Key Performance Indicators | Closed | Asked for min/max/avg resolution time and improvement trend; comment defines resolution time as created→closed. No PRs. |
| 76 | Request Resolution Time Analysis | Closed | Resolution time = `submission_date` → `serviced_date`; median by category/location, heatmaps; DB `virginia_dev_saayam_rdbms`. Draft with 4 images posted by shendu-95; no PR. |
| 16 | Trend Analysis for Saayam Functionality | Open | Original umbrella for usage / resolution-time trends; no linked work. |
| 81, 82, 83, 84, 85, 88, 89 | Super Admin Dashboard analytics design / test data / Plotly implementation | Closed Mar 24 2026 | Origin of the Application Analytics tab and its KPI visuals (resolution KPIs: average resolution time by category; resolved/unresolved/in-progress counts). Mock JSON delivered to the UI team. |
| 96 | Consolidated metrics on the Saayam home page | Closed | Home-page metrics (separate S3 pipeline); follow-ups #103, #104. |
| 301 | Create Mock Data for Dashboard Implementation | Closed Sep 22 2026 | Synthetic CSVs under `data-analytics/mock-data-generation/` (PRs #314, #331, #357); useful for testing, but the KPI tables `request`, `request_status` are not in its table list. |
| 593 | Identify and Document Lambda Functions | Open | Lambda inventory (draft PR #619); source for deployed name/links. |
| 602–605 | Document Application Analytics Flow: Request / Beneficiary / Organization / Volunteer dashboards | Open | Sibling documentation tasks. |
| 543 | System Design Documentation for Data Engineering & Analytics | Open | Broader design doc. |
| 138, 146, 151 | "Implement real API" for beneficiary, request, volunteer analytics | Closed | Sibling Lambdas built on the same pattern as #160. |
| 179 | Date filter for Volunteer Application Analytics | Closed | Same date-filter pattern as #181. |

### Reviewed by title, no KPI-tab relevance

Organization dashboard APIs (#228, #336, #376, #380, #506, #539, #569, #583), request archival to S3
(#175, #177, #416, #573–#587), emergency contacts (#11, #37, #49, #333, #334, #482), organization
aggregation / data collection (#10, #28, #31–#34, #42–#47, #55–#69, #80, #92, #93, #98, #99, #113),
volunteer APIs (#273, #289, #295), fraud / content filtering / ML (#1–#15, #86, #87, #100, #422), CI/CD
and dependencies (#328, #329, #579, #580), synthetic-data tasks (#114, #117–#121), onboarding
(#78, #102, #264), infrastructure (#620, #622, #302, #203, #276, #29, #23, #39, #41, #38, #35, #33,
#30). #30/#33/#35 ("Analytics for Requestors and Volunteers" and its subtasks) are open, generic
analytics API/query tasks with no linked work; they were not opened individually.
