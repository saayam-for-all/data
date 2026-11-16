# Beneficiary Tab Documentation

> **Issue:** [#603 — Document Application Analytics Flow and Implementation - Beneficiary Dashboard](https://github.com/saayam-for-all/data/issues/603)
>
> **Code documented:** [`data-analytics/lambda_functions/beneficiariesTrendAnalysis.py`](https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/beneficiariesTrendAnalysis.py) at data commit `2602a8897d25b086624e202beb7515d1d31b634a` (handler last changed by commit `11b5f7b`).
>
> **Document history:** Renamed from `issue_603_beneficiary_dashboard_analytics.md`, originally merged through [PR #645](https://github.com/saayam-for-all/data/pull/645). Frontend integration details below are adapted from [PR #672](https://github.com/saayam-for-all/data/pull/672) by [pratyush0824](https://github.com/pratyush0824), documentation commit `b02ea33db5a33ecd65d273340de15e7a6514080e`. Consolidated November 11, 2026.
>
> **Scope of this document:** it records existing behavior and history. It does not change any implementation.

### How to read this document

Findings are labelled with one of the following:

| Label | Meaning |
|---|---|
| **Confirmed** | Verified directly from code currently on `test`, from git history, or from GitHub issue/PR metadata. |
| **Intended / historical** | Described in an issue, PR, or comment, but not necessarily present in the current code. |
| **Known limitation** | A confirmed gap between the current code and the intended behavior. |
| **Open question** | Cannot be resolved from the repository alone; needs live database, AWS, or team confirmation. |

---

## 1. Purpose and Scope

This document covers the following area of the Saayam application:

**Super Admin Dashboard → Application Analytics → Beneficiary tab**

**Intended purpose (from Issues [#70](https://github.com/saayam-for-all/data/issues/70) and [#82](https://github.com/saayam-for-all/data/issues/82)):**

- Track beneficiary trends over time.
- Support views for the last 7 days, last month, last year, and a custom date range.
- Show the geographic distribution of beneficiaries.
- The original design (Issue #82) asks for a breakdown by **country and region**.

**Note on scope:** The backend Lambda that serves this tab, `beneficiariesTrendAnalysis.py`, also calculates **help-request analytics** (trends and country breakdown) in the same function and response. This document focuses on the Beneficiary tab, but describes the help-request portion where it affects the shared implementation (see [Section 5.3](#53-help-request-analytics-in-the-same-lambda)).

---

## 2. User Flow

The intended high-level flow, based on Issues #82, #84, and #138:

1. A Super Admin opens **Application Analytics** in the Super Admin Dashboard.
2. The user selects the **Beneficiary** tab.
3. The user chooses a supported time range (7 days, 1 month, 1 year, or a custom range).
4. The dashboard requests analytics from the beneficiary analytics backend (the `beneficiariesTrendAnalysis` AWS Lambda).
5. The backend queries the analytics databases.
6. Results are aggregated into date-bucketed and country-level counts.
7. The frontend displays beneficiary trend and geographic distribution visualizations.

**Frontend source review:** The UI lives in the separate webapp repository. Section 2.1 records its component, endpoint and payload at a pinned revision. API Gateway mapping, deployed Lambda revision and live integration remain unverified.

---

### 2.1 Frontend behavior and integration contract

The reviewed webapp source is pinned to commit `388534d902110bac4d4a38f7a4fc1cdbba8ac6ad`. [BeneficiariesAnalytics.jsx][beneficiary-frontend] provides a line chart and a country bar/map view, independent 7D/30D/1Y/All/Custom controls, Day/Month grouping for custom dates, and a Top 10 country option. Both dates must be present before a custom request is committed. The UI handles loading, empty and error states; a failed country-specific request can reuse the trend response without a separate country error.

[analyticsServices.js][beneficiary-service] posts the supplied payload to `v1/ml/beneficiariesTrendAnalysis`, as registered in [endpoints.json][beneficiary-endpoints]. The service does not translate the legacy handler contract. [ApplicationAnalytics.jsx][beneficiary-application] initially selects Requests; the user then selects Beneficiaries.

| Request or response | Reviewed frontend | Reviewed backend in this document |
|---|---|---|
| Preset request | `{}` | Requires all four legacy top-level date fields listed in Section 3.2 |
| Custom request | `custom_start_date`, `custom_end_date`, `custom_group_by` | Reads `beneficiaries_start_date`, `beneficiaries_end_date`, `help_requests_start_date`, `help_requests_end_date`; custom grouping is daily |
| Trend keys | `Beneficiaries count 7 days`, `Beneficiaries count 30 days`, `Beneficiaries count 1 year`, `Beneficiaries count all`, `Beneficiaries count custom date range` | `7 days beneficiaries`, `1 month beneficiaries`, `1 year beneficiaries`, `Custom date range beneficiaries`; no All series |
| Country keys | `Beneficiaries count by country <period>`, including `all` and `custom date range` | One all-time `Country beneficiaries` list |

**Known source mismatch:** Connecting these two revisions directly would fail on missing input fields or leave expected chart keys absent. This does not establish a live production failure: the deployed package and Gateway transformations have not been checked. The backend also lacks the UI's country-period and custom-grouping capabilities. Country codes are mapped to display names by the frontend's country-name utility.

The UI source handles map hover but has no country click-to-filter handler for the trend or regional drill-down. The original #672 author also recorded a native date-picker issue discussed in [webapp #1518](https://github.com/saayam-for-all/webapp/issues/1518) and [#1642](https://github.com/saayam-for-all/webapp/pull/1642): date input changes can trigger requests while the user navigates the picker. Browser reproduction remains unverified during consolidation.

---

## 3. Filters

### 3.1 Time ranges (Confirmed)

| Range | How it is applied in the current code |
|---|---|
| Last 7 days | Hard-coded SQL interval `'7 days'` relative to `CURRENT_TIMESTAMP` |
| Last 1 month | Hard-coded SQL interval `'1 month'` relative to `CURRENT_TIMESTAMP` |
| Last 1 year | Hard-coded SQL interval `'1 year'` relative to `CURRENT_TIMESTAMP` |
| Custom date range | `BETWEEN start_date AND end_date` using values from the event |

All four ranges are always calculated on every invocation. The caller does not select a single range; the response contains every range at once.

### 3.2 Custom date inputs (Confirmed)

| Event field | Used for |
|---|---|
| `beneficiaries_start_date` | Start of the custom beneficiary range |
| `beneficiaries_end_date` | End of the custom beneficiary range |
| `help_requests_start_date` | Start of the custom help-request range |
| `help_requests_end_date` | End of the custom help-request range |

The handler reads these fields **directly from the top-level `event` object**, for example `event['beneficiaries_start_date']`. The line that would read an API Gateway request body (`# body = event['body']`) is commented out.

**Known limitation:** The file's own local test block (`if __name__ == "__main__":`) places these fields inside a JSON string under `event["body"]`, which is the shape API Gateway proxy integrations typically send. Because the handler reads top-level keys, the local example does not match what the handler expects. When this was run during research with the database connection mocked to succeed, the handler stopped with `KeyError: 'beneficiaries_start_date'`. No AWS or database access was used for that check.

The fields are required: there is no default when they are missing.

### 3.3 Region filter

**Known limitation:** Issue #82 refers to beneficiary analytics by **country and region**. The current backend implements a country breakdown only. There is no region filter or region grouping anywhere in the current code.

---

## 4. Data Sources

### 4.1 Databases and tables (Confirmed, as written in code)

The Lambda opens two separate PostgreSQL connections, one labelled "Virginia" and one labelled "Ireland".

| Constant in code | Value in code | Points to schema |
|---|---|---|
| `VIRGINIA_REAL_TABLE_REQUEST` | `virginia_dev_saayam_rdbms.request` | Virginia |
| `VIRGINIA_REAL_TABLE_USERS` | `virginia_dev_saayam_rdbms.users` | Virginia |
| `VIRGINIA_REAL_TABLE_COUNTRY` | `virginia_dev_saayam_rdbms.country` | Virginia |
| `IRELAND_REAL_TABLE_REQUEST` | `virginia_dev_saayam_rdbms.request` | **Virginia** |
| `IRELAND_REAL_TABLE_USERS` | `ireland_dev_saayam_rdbms.users` | Ireland |
| `IRELAND_REAL_TABLE_COUNTRY` | `virginia_dev_saayam_rdbms.country` | **Virginia** |

**Intended:** Issue #138 asks for the Ireland `request`, `users`, and `country` tables to be added so that beneficiaries from the Ireland region are counted.

**Known limitation:** In the current code only `IRELAND_REAL_TABLE_USERS` points to the Ireland schema. `IRELAND_REAL_TABLE_REQUEST` and `IRELAND_REAL_TABLE_COUNTRY` point to the Virginia schema. This document does **not** claim that Ireland analytics currently work; see [Section 7](#7-implementation-flow) for how Ireland results are handled.

### 4.2 Credentials (Confirmed)

Credentials are not stored in source code. `get_db_config()` retrieves them at runtime from **AWS Systems Manager (SSM) Parameter Store** with decryption enabled:

| Region label | SSM parameter path |
|---|---|
| Virginia | `/dev/saayam/db/Virginia/Analytics/user` |
| Ireland | `/dev/saayam/db/Ireland/Analytics/user` |

The SSM client is created in region `us-east-1`. `get_db_config()` parses host, port, database name, user, and password out of the parameter value by fixed line positions, so it depends on the parameter value keeping its current text layout. **Open question:** the expected layout of that parameter value is not documented in the repository.

---

## 5. Metrics and Calculations

### 5.1 Beneficiary Trend

**Functions:** `aggregate_beneficiaries()` and `get_beneficiaries_dic()`

**Current logic (Confirmed):**

1. Query the request table:
   - Fixed ranges: `SELECT DISTINCT req_user_id, last_update_date FROM <request table> WHERE last_update_date > CURRENT_TIMESTAMP - INTERVAL '<interval>'`
   - Custom range: the same `SELECT`, with `WHERE last_update_date BETWEEN '<start_date>' AND '<end_date>'`
2. Keep only the `last_update_date` value from each returned row.
3. Load the timestamps into a pandas DataFrame and convert them with `pd.to_datetime`.
4. Group and count with pandas.
5. Return a list of `{"Date": <ISO timestamp>, "Count": <int>}` records.

**Grouping (Confirmed):**

| Range | Grouping |
|---|---|
| 7 days | Daily |
| 1 month | Daily |
| 1 year | Monthly |
| Custom | Daily |

**What the metric represents:** Each counted row is a distinct pair of (`req_user_id`, `last_update_date`) from the request table, bucketed by the date of `last_update_date`. This describes what the code calculates. It is not necessarily the same as a business definition such as "new beneficiaries" or "unique beneficiaries per period". For example, one user with distinct request-update timestamps at 10:00 and 11:00 on the same day contributes two counts that day. Identical user/timestamp pairs collapse; a user can contribute again on later days. **Open question:** the intended business definition of a "beneficiary" count for this tab is not documented in the issues reviewed.

**Empty and failure behavior (Confirmed):** If `cursor.execute` raises an exception, `aggregate_beneficiaries()` returns `[]`; `fetchall` errors occur outside that catch. An empty input produces an empty list of records.

### 5.2 Beneficiaries by Country

**Functions:** `aggregate_beneficiaries_country()` and `get_beneficiaries_country_dic()`

**Current join pattern (Confirmed):**

```
request  →  users  →  country
```

| Join | Condition |
|---|---|
| request → users | `request.req_user_id = users.user_id` |
| users → country | `users.country_id = country.country_id` |

**Calculation (Confirmed):**

1. `SELECT DISTINCT req_user_id, c.country_name` across the join. There is no date filter, so this covers all time.
2. Load the rows into pandas, group by country, and count rows.
3. Return a list of `{"country": <name>, "Count": <int>}` records.

**Notes:**

- Counts only. No percentages or shares are calculated.
- No region-level breakdown exists (see [Section 3.3](#33-region-filter)).
- Ireland rows are fetched but discarded. The returned result uses **Virginia rows only**.
- The country breakdown is not affected by any date range, including the custom range.

### 5.3 Help Request Analytics in the Same Lambda

Although the file is named `beneficiariesTrendAnalysis.py`, the same Lambda also calculates help-request analytics (Confirmed):

| Metric | Function(s) | Date column | Grouping |
|---|---|---|---|
| 7-day help-request trend | `aggregate_help_requests()`, `get_help_requests_dic()` | `submission_date` | Daily |
| 1-month help-request trend | same | `submission_date` | Daily |
| 1-year help-request trend | same | `submission_date` | Monthly |
| Custom help-request trend | same | `submission_date` | Daily |
| Help requests by country | `aggregate_help_requests_country()`, `get_help_requests_country_dic()` | none (all time) | By country |

Differences from the beneficiary metrics:

- Help-request trends are bucketed by `submission_date`. Beneficiary trends use `last_update_date`.
- Help-request trends count every request row returned (no `DISTINCT`).
- Help requests by country count one row per request joined to the requesting user's country.

The help-request metrics follow the same Virginia-only behavior described in [Section 7](#7-implementation-flow).

---

## 6. Current Response Structure

### 6.1 Response keys (Confirmed)

The success response body always contains these 10 keys:

| # | Key | Content |
|---|---|---|
| 1 | `"7 days beneficiaries"` | List of `{Date, Count}` |
| 2 | `"1 month beneficiaries"` | List of `{Date, Count}` |
| 3 | `"1 year beneficiaries"` | List of `{Date, Count}` (monthly) |
| 4 | `"Custom date range beneficiaries"` | List of `{Date, Count}` |
| 5 | `"Country beneficiaries"` | List of `{country, Count}` |
| 6 | `"7 days help requests"` | List of `{Date, Count}` |
| 7 | `"1 month help requests"` | List of `{Date, Count}` |
| 8 | `"1 year help requests"` | List of `{Date, Count}` (monthly) |
| 9 | `"Custom date range help requests"` | List of `{Date, Count}` |
| 10 | `"Country help requests"` | List of `{country, Count}` |

Issue #138 describes "8 analytics statistics". The two custom-date-range keys were added later, in commit `11b5f7b`, which accounts for the current total of 10.

### 6.2 Illustrative response (synthetic values)

```json
{
  "statusCode": 200,
  "body": {
    "7 days beneficiaries": [{"Date": "2026-11-01T00:00:00", "Count": 2}],
    "1 month beneficiaries": [],
    "1 year beneficiaries": [],
    "Custom date range beneficiaries": [],
    "Country beneficiaries": [{"country": "India", "Count": 2}],
    "7 days help requests": [],
    "1 month help requests": [],
    "1 year help requests": [],
    "Custom date range help requests": [],
    "Country help requests": []
  }
}
```

### 6.3 Response format notes (Confirmed)

- The success path uses the key `statusCode`.
- The success `body` is returned as a **Python dictionary**, not as a JSON string produced by `json.dumps(...)`. The first version of the file (commit `04b5fb4`) used `json.dumps(response_body)`.
- Error paths use `status_code` (snake_case) instead of `statusCode`. This affects the database connection failure and the invalid-region branch of `get_db_config()`. The country query functions also return a dictionary containing `status_code` on failure.
- No CORS headers are set in the response.

Connection failure response (Confirmed):

```json
{
  "status_code": 500,
  "body": "{\"error\": \"Could not connect to databases\"}"
}
```

---

## 7. Implementation Flow

**Current flow (Confirmed):**

```
Lambda event
  → get_db_config("Virginia") / get_db_config("Ireland")
      → AWS SSM Parameter Store (decrypted parameters)
  → psycopg2.connect(...) × 2   (Virginia connection, Ireland connection)
      → on failure: return status_code 500
  → read custom date fields from the top-level event
  → aggregation functions
      → beneficiary trends (7 days, 1 month, 1 year, custom)
      → beneficiaries by country
      → help-request trends (7 days, 1 month, 1 year, custom)
      → help requests by country
  → pandas grouping (daily / monthly / by country)
  → response_body (10 keys)
  → close both connections
  → return {"statusCode": 200, "body": response_body}
```

Separate Virginia and Ireland connections and cursors are created. **However, every value in the current response is calculated from Virginia data only:**

- In the trend functions (`get_beneficiaries_dic()`, `get_help_requests_dic()`), the Ireland calls are commented out.
- In the country functions (`get_beneficiaries_country_dic()`, `get_help_requests_country_dic()`), Ireland rows are fetched into `rows_ireland`, then discarded when `rows = rows_virginia` is assigned.

Connections are closed only after `response_body` has been built successfully. There is no `finally` block (see [Section 9](#9-known-limitations-and-open-questions)).

---

## 8. Development History

The following task-by-task review is retained from the merged document. Later frontend details and consolidation checks are attributed separately.

### Issue #70 — Trend Analysis for Beneficiaries

- **Link:** https://github.com/saayam-for-all/data/issues/70
- **Status:** Closed
- **Opened:** 2025-08-01

**Scope (from the issue body):**

1. Count help requests in the past 7 days, month, year, or a custom range.
2. Break down help requests by country and region.
3. Break down help requests by category.
4. Count beneficiaries in the past 7 days, month, year, or a custom range.

**Comments on the issue (Confirmed):**

| Date | Summary |
|---|---|
| 2025-11-10 | A sample script for analyzing all metrics was shared, linked to an `issue#70` branch in the `saayam-for-all/ml` repository. |
| 2025-12-04 | A contributor reported building an API that returns a JSON object for the frontend, linking to an AWS Lambda named `beneficiariesTrendAnalysis` in the AWS console (`us-east-1`). That link needs AWS access and could not be checked for this document. |
| 2026-02-03 | A contributor reported a CSV-based trend analysis (date filters, counts by country, region, and category, plus visualizations) and attached a notebook, `Task_70.ipynb`. |

**Repository evidence (Confirmed):** An unmerged branch, `origin/issue#70`, exists in this repository. It contains `issue_70/beneficiaries.csv`, `issue_70/help_requests.csv`, `issue_70/test.ipynb`, and `issue_70/analytics_dashboard.png`. It is not part of `test`, and none of those files exist on the current branch.

**Linked PR:** None verified.

### Issue #82 — Design of Application Analytics tab under Super Admin Dashboard

- **Link:** https://github.com/saayam-for-all/data/issues/82
- **Status:** Closed
- **Opened:** 2025-11-20

**What it established (Intended):** the six Application Analytics categories (Requests, KPI for resolving requests, Beneficiaries, Volunteers, Organizations, Donors), with two visuals per category.

**Beneficiary analytics as defined by Issue #82:**

1. Track the number of beneficiaries in the past 7 days, month, year, or a custom range.
2. Break down the number of beneficiaries by country and region.

**Comments:** One comment links to a design wiki page in the `ml` repository, [Super-Admin-Dashboard-Analytics-tab-Design](https://github.com/saayam-for-all/ml/wiki/Super-Admin-Dashboard-Analytics-tab-Design), which was not reviewed for this document. The closing comment (2026-03-24) states that the application analytics dashboard implementation under the Super Admin dashboard was completed.

### Issue #84 — Super Admin Dashboard Application Analytics design: creation of Test data

- **Link:** https://github.com/saayam-for-all/data/issues/84
- **Status:** Closed
- **Opened:** 2025-12-08

**Historical MVP approach (Intended / historical, not current confirmed behavior):**

```
Sample CSV files → JSON (backend) → API endpoints → frontend visualizations
```

The issue explains that real data was not yet available in the database, so realistic sample CSVs following the finalized schema would be created. This approach was meant to:

- avoid committing fake data into the shared database,
- let the UI team build dashboards independently, and
- keep the API contract stable, so that the CSV source could later be replaced by database queries without UI changes.

The issue attaches a table/column-name spreadsheet for the `virginia_dev_saayam_rdbms` schema and a "Types of Visualizations for Application Analytics Dashboard" document. The original merged review did not inspect these attachments; the schema and visualization files were subsequently inspected during consolidation.

**Comments:** The closing comment (2026-03-24) states that JSON objects were created and sent to the UI team for integration.

**Repository evidence:** No beneficiary-specific CSV from this effort exists on the current branch.

### Other Super Admin Dashboard Analytics issues reviewed (not tab-specific)

`data-engineering/TASK_TRACKER.md` groups three more closed issues alongside #82 and #84 under the same Super Admin Dashboard Analytics effort. Each was checked individually for Beneficiary-tab content; none contains any:

- **[Issue #81 — Creation of Super Admin Dashboard Analytics](https://github.com/saayam-for-all/data/issues/81).** The umbrella issue for the whole effort ("There are 3 sub categories under Super Admin Analytics tab"), which spawned #82 as a sub-issue. No mention of beneficiaries.
- **[Issue #89 — Application Analytics Dashboard implementation in Python using plotly library](https://github.com/saayam-for-all/data/issues/89).** Empty issue body; its comments report converting mock CSVs into JSON for the frontend team and completion, without a tab-specific contract. No mention of beneficiaries.
- **[Issue #96 — Design of Consolidated metrics of application analytics on the Saayam Home Page](https://github.com/saayam-for-all/data/issues/96).** A different feature (a metrics ticker on the public Home Page, replacing a static tagline). "Total Beneficiaries" appears once, as one of five summary numbers (alongside Total Requests, Requests Resolved, Avg Resolution Time, Total Volunteers) — not a description of the Beneficiary tab itself. Its closing comment references a follow-on issue, #104, for backend implementation; #104 was not reviewed for this document.

### Issue #138 — Implement real API for beneficiary_trend_analysis.py

- **Link:** https://github.com/saayam-for-all/data/issues/138
- **Status:** Closed on GitHub (see the `TASK_TRACKER.md` note in Section 9)
- **Opened:** 2026-04-07
- **Comments:** None

**Requested work (Intended):**

| Phase | Requested |
|---|---|
| 1.1 | Remove fake-data code (`create_fake_table()`, the `create_tables` action block, the unused `sqlite3` import) |
| 1.2 | Add Ireland `Request`, `Users`, and `Country` tables to count Ireland beneficiaries |
| 1.3 | Return `[]` for empty data in all four aggregation functions |
| 1.4 | Wrap the DB connection and all query functions in `try/except`; add a `finally` block to always close the cursor and connection |
| 1.5 | Add an `if __name__ == "__main__"` block for local testing |
| 2 | Test locally; verify each key returns data or `[]`; no crash on empty tables; clean connection closing |
| 3 | Package and deploy to AWS Lambda; test with an empty event `{}`; confirm `statusCode: 200`; check CloudWatch logs |
| 4 | Move DB credentials out of source code |

**Code comparison:** The reviewed handler uses SSM and real queries but does not guarantee cleanup, include Ireland rows, or accept an empty event; see Sections 3, 7 and 9.

Three PRs reference Issue #138. **None of them are merged**, so none of them define current `main`/`test` behavior.

### PR #170 — #138: Implement real PostgreSQL API and db_client abstraction

- **Link:** https://github.com/saayam-for-all/data/pull/170
- **Status:** Open, **unmerged**
- **Branches:** `PR-138-dev` → `dev`
- **Opened:** 2026-05-19

**Described changes (from the PR description and file list):**

- A separate implementation in a **new** file, `data-analytics/lambda_functions/beneficiary_trend_analysis.py` (snake_case, matching the filename used in Issue #138), rather than changes to the existing `beneficiariesTrendAnalysis.py`.
- A new database abstraction, `data-engineering/src/utils/db_client.py`, and a new `data-analytics/lambda_functions/requirements.txt`.
- SQL queries and table references updated to target the Ireland region.
- Empty-data handling (`[]` instead of crashing), `try/except` error handling, and connection closing in a `finally` block.
- Local testing without AWS credentials, which the description reports returned a 500 error response as expected.

Because this PR is unmerged, none of these changes are part of the current implementation.

### PR #172 — #138: Refactor beneficiary trend analysis Lambda for production DB and add test file

- **Link:** https://github.com/saayam-for-all/data/pull/172
- **Status:** Open, **unmerged**
- **Branches:** `Prajakta-101_138_beneficiary_trend_analysis` → `main`
- **Opened:** 2026-05-21

**Verifiable from GitHub metadata:** The PR has no description and no comments. It changes three files (512 additions, 209 deletions):

- modifies `data-analytics/lambda_functions/beneficiariesTrendAnalysis.py`
- adds `data-analytics/lambda_functions/test_beneficiaries.py`
- adds `data-analytics/docs/requests-archival-design.md`, which appears to relate to a different topic (requests archival)

The content of these changes was not reviewed in detail for this document.

### PR #182 — feat(analytics): implement real API for beneficiaries trend analysis lambda

- **Link:** https://github.com/saayam-for-all/data/pull/182
- **Status:** Open, **unmerged**
- **Branches:** `138-implement-real-api-beneficiary-trend-analysis` → `main`
- **Opened:** 2026-06-21

**Described changes (from the PR description):** "Closes #138". Implements regional database connections, empty-data fallbacks, connection handling and closing, and mock tests. It modifies only `beneficiariesTrendAnalysis.py` (333 additions, 287 deletions).

This PR was opened after commit `11b5f7b` was merged. Because it is unmerged, it does not define current behavior.

### Current merged implementation

| Commit | Date | Message | Summary |
|---|---|---|---|
| `04b5fb4` | 2026-04-20 | Create beneficiariesTrendAnalysis.py | First version in this repository. Single database connection configured from environment variables; Virginia tables only; 7-day, 1-month, 1-year, and country metrics; body returned with `json.dumps(...)`. Its local test guard was written as `if name == "main":` and would not run as intended. |
| `11b5f7b` | 2026-05-29 | Update beneficiariesTrendAnalysis.py | **Basis of the current implementation documented here.** Moved credentials to SSM Parameter Store via `get_db_config()`; added separate Virginia and Ireland connections and table constants; added custom date ranges for beneficiaries and help requests; replaced the local test block with the current `__main__` example; changed the success body from a JSON string to a Python dictionary. This commit was made directly, not through PRs #170, #172, or #182. |

**Later unmerged alternative:** Commit `1bc97dc` (2026-06-25) on the branch `origin/vighneshsridhar-beneficiaries_trend_analysis` appears to be a later alternative implementation. Among other changes, it adds an "all time" interval, adds date grouping to the country breakdown, uses `country_code`, and removes help-request logic from this file. It is not merged and does not represent current behavior.

**Open question:** How Issue #138 was closed is not recorded in its comments. None of its three PRs are merged, so the issue was closed without any of them being merged.

---

## 9. Known Limitations and Open Questions

The metric, regional and frontend-contract differences are detailed in Sections 2–5. Additional operational limitations are:

- Country-query failures return an error dictionary that callers pass to pandas without checking it. Trend execute failures return empty lists; `fetchall` failures can escape. Empty responses do not reliably distinguish no activity from failed queries.
- Configuration lookup runs before the connection `try`; missing event keys, fetch errors and processing failures can escape without a formatted response. A failed SQL transaction is not rolled back between queries.
- Connections close only after successful processing, and cursors are never explicitly closed. There is no `finally` block. If Ireland fails after Virginia connects, the Virginia connection can remain open.
- Custom dates are interpolated directly into SQL, without binding or format/order validation. Fixed ranges have no upper bound. A date-only custom end value can exclude later timestamps on that day; database timezone and live timestamp types need confirmation.
- The code uses singular `request`, `req_user_id` and `last_update_date`; the repository mock CSV uses `requests`, `creator_id`/`beneficiary_id` and `last_updated_at`. The historical workbook agrees with the older names, but neither fixture establishes current live DDL.
- Confirm the business definition of a beneficiary, whether identifiers refer to creators or people helped, the serving Lambda revision, Gateway transformations and authorization. The frontend contract inspected in Section 2.1 is known; deployment equivalence remains unverified.

The local task tracker also lists #138 as open despite GitHub's closed status. Historical issue state is not evidence of deployment.

---

## 10. Supporting References

### Issues

- [Issue #70 — Trend Analysis for Beneficiaries](https://github.com/saayam-for-all/data/issues/70)
- [Issue #81 — Creation of Super Admin Dashboard Analytics](https://github.com/saayam-for-all/data/issues/81) (umbrella issue; not tab-specific)
- [Issue #82 — Design of Application Analytics tab under Super Admin Dashboard](https://github.com/saayam-for-all/data/issues/82)
- [Issue #84 — Super Admin Dashboard Application Analytics design: creation of Test data](https://github.com/saayam-for-all/data/issues/84)
- [Issue #89 — Application Analytics Dashboard implementation in Python using plotly library](https://github.com/saayam-for-all/data/issues/89) (general; not tab-specific)
- [Issue #96 — Design of Consolidated metrics of application analytics on the Saayam Home Page](https://github.com/saayam-for-all/data/issues/96) (Home Page ticker, not the dashboard tab)
- [Issue #138 — Implement real API for beneficiary_trend_analysis.py](https://github.com/saayam-for-all/data/issues/138)
- [Issue #603 — Document Application Analytics Flow and Implementation - Beneficiary Dashboard](https://github.com/saayam-for-all/data/issues/603)

### Pull requests (all unmerged)

- [PR #170 — #138: Implement real PostgreSQL API and db_client abstraction](https://github.com/saayam-for-all/data/pull/170)
- [PR #172 — #138: Refactor beneficiary trend analysis Lambda for production DB and add test file](https://github.com/saayam-for-all/data/pull/172)
- [PR #182 — feat(analytics): implement real API for beneficiaries trend analysis lambda](https://github.com/saayam-for-all/data/pull/182)

### Code and repository files

- Current code: [`data-analytics/lambda_functions/beneficiariesTrendAnalysis.py`](https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/beneficiariesTrendAnalysis.py)
- Task tracker: [`data-engineering/TASK_TRACKER.md`](https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-engineering/TASK_TRACKER.md)
- Schema reference (historical column reference): [`data-analytics/sql/Saayam_Table.column.names_data.xlsx`](https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/sql/Saayam_Table.column.names_data.xlsx)
- Conflicting mock dataset (uses different request/identity/timestamp names): [`data-analytics/sql/requests.csv`](https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/sql/requests.csv)
- Commits: `04b5fb4` (file created), `11b5f7b` (current implementation)
- Unmerged branches: `origin/issue#70` (Issue #70 CSVs and notebook), `origin/vighneshsridhar-beneficiaries_trend_analysis` (commit `1bc97dc`)

### External references (not reviewed for this document)

- [Super Admin Dashboard Analytics tab design wiki (`ml` repository)](https://github.com/saayam-for-all/ml/wiki/Super-Admin-Dashboard-Analytics-tab-Design)
- Issue #84 attachments: table/column-name spreadsheet and visualization-types document
- Issue #70 attachment: `Task_70.ipynb`

---

## 11. Verification

The merged document remains the basis for backend calculations and development history. The frontend component at the pinned revision was inspected during consolidation, and its payload fields, chart keys, date controls and country behavior were checked against the backend. Source paths were checked against the webapp Git tree. Frontend details were adapted with attribution from #672; its reported 32 passing tests were not independently repeated. The #84 schema/visualization attachments were inspected during the broader dashboard review; historical tests in the merged document remain attributed to its author. No live API, AWS, SQL or authenticated browser checks were performed.

[beneficiary-frontend]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/components/Analytics/BeneficiariesAnalytics.jsx

[beneficiary-service]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/services/analyticsServices.js

[beneficiary-endpoints]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/services/endpoints.json

[beneficiary-application]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/components/Analytics/ApplicationAnalytics.jsx
