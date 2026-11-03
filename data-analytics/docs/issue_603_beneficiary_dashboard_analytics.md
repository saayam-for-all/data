# Beneficiary Dashboard Analytics

> **Issue:** [#603 — Document Application Analytics Flow and Implementation - Beneficiary Dashboard](https://github.com/saayam-for-all/data/issues/603)
>
> **Code documented:** [`data-analytics/lambda_functions/beneficiariesTrendAnalysis.py`](https://github.com/saayam-for-all/data/blob/test/data-analytics/lambda_functions/beneficiariesTrendAnalysis.py) as it exists on the `test` branch (last changed by commit `11b5f7b`).
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

**Open question:** This repository contains no frontend code, API Gateway configuration, or endpoint definition for this tab. The frontend component names, the HTTP route, and how the frontend passes the date range cannot be confirmed from this repository.

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

Lines 254–256 of `beneficiariesTrendAnalysis.py`:

```python
    # body = event['body']
    beneficiaries_start_date = event['beneficiaries_start_date']
    beneficiaries_end_date = event['beneficiaries_end_date']
```

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

Lines 32–38 of `beneficiariesTrendAnalysis.py`:

```python
    VIRGINIA_REAL_TABLE_REQUEST = "virginia_dev_saayam_rdbms.request"
    VIRGINIA_REAL_TABLE_USERS = "virginia_dev_saayam_rdbms.users"
    VIRGINIA_REAL_TABLE_COUNTRY = "virginia_dev_saayam_rdbms.country"

    IRELAND_REAL_TABLE_REQUEST = "virginia_dev_saayam_rdbms.request"
    IRELAND_REAL_TABLE_USERS = "ireland_dev_saayam_rdbms.users"
    IRELAND_REAL_TABLE_COUNTRY = "virginia_dev_saayam_rdbms.country"
```

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

**What the metric represents:** Each counted row is a distinct pair of (`req_user_id`, `last_update_date`) from the request table, bucketed by the date of `last_update_date`. This describes what the code calculates. It is not necessarily the same as a business definition such as "new beneficiaries" or "unique beneficiaries per period". For example, one user with requests updated on several different days is counted once on each of those days. **Open question:** the intended business definition of a "beneficiary" count for this tab is not documented in the issues reviewed.

**Empty and failure behavior (Confirmed):** If the query raises an exception, `aggregate_beneficiaries()` returns `[]`. An empty input produces an empty list of records.

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

### 6.2 Sample structure (structure only, no real values)

```json
{
  "statusCode": 200,
  "body": {
    "7 days beneficiaries": [{"Date": "<ISO-8601 timestamp>", "Count": "<integer>"}],
    "1 month beneficiaries": [],
    "1 year beneficiaries": [],
    "Custom date range beneficiaries": [],
    "Country beneficiaries": [{"country": "<country name>", "Count": "<integer>"}],
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

Lines 131–136 of `beneficiariesTrendAnalysis.py`:

```python
    def get_beneficiaries_country_dic():
        rows_virginia = aggregate_beneficiaries_country(VIRGINIA_REAL_TABLE_REQUEST, VIRGINIA_REAL_TABLE_USERS, VIRGINIA_REAL_TABLE_COUNTRY,
        cursor_V)
        rows_ireland = aggregate_beneficiaries_country(IRELAND_REAL_TABLE_REQUEST, IRELAND_REAL_TABLE_USERS, IRELAND_REAL_TABLE_COUNTRY,
        cursor_I)
        rows = rows_virginia
```

Connections are closed only after `response_body` has been built successfully. There is no `finally` block (see [Section 9](#9-known-limitations-and-open-questions)).

---

## 8. Development History

Each related task was reviewed individually through GitHub issue/PR metadata, issue comments, and local git history.

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

The issue attaches a table/column-name spreadsheet for the `virginia_dev_saayam_rdbms` schema and a "Types of Visualizations for Application Analytics Dashboard" document. Neither attachment was reviewed for this document.

**Comments:** The closing comment (2026-03-24) states that JSON objects were created and sent to the UI team for integration.

**Repository evidence:** No beneficiary-specific CSV from this effort exists on the current branch.

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

**Comparison with the current merged code (Confirmed):**

| Requested item | Present in current code? |
|---|---|
| Fake-data code removed | Yes. No fake-table code, `create_tables` block, or `sqlite3` import remains. |
| Ireland tables added | Partially. Ireland connection and Ireland `users` table exist; Ireland `request` and `country` constants point to Virginia; Ireland results are not used. |
| Empty-data `[]` handling | Partially. The two trend query functions return `[]` on failure; the two country query functions return an error dictionary instead. |
| `try/except` around DB connection | Yes |
| `try/except` around query functions | Yes |
| `finally` block for cleanup | No |
| Cursor closing | No. Cursors are never explicitly closed. |
| Local `__main__` test block | Present, but its event shape does not match what the handler reads. |
| Test with empty event `{}` | Would not succeed against the current code, because the custom date fields are required. Confirmed by code reading only. |
| Credentials out of source code | Yes, via SSM Parameter Store |
| Deployment / CloudWatch verification | **Open question.** Cannot be verified from the repository. |

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

### Confirmed

| # | Area | Status | Details |
|---|---|---|---|
| 1 | Ireland request table | Confirmed | `IRELAND_REAL_TABLE_REQUEST` is set to `virginia_dev_saayam_rdbms.request`. |
| 2 | Ireland country table | Confirmed | `IRELAND_REAL_TABLE_COUNTRY` is set to `virginia_dev_saayam_rdbms.country`. |
| 3 | Ireland results in response | Confirmed | No Ireland data contributes to any returned metric. |
| 4 | Ireland trend calls | Confirmed | Ireland calls in `get_beneficiaries_dic()` and `get_help_requests_dic()` are commented out. |
| 5 | Ireland country rows | Confirmed | `rows_ireland` is fetched in both country functions, then discarded (`rows = rows_virginia`). |
| 6 | Custom-date input location | Confirmed | The handler reads the custom date fields from the top-level `event`. |
| 7 | Local `__main__` sample | Confirmed | The sample wraps the custom date fields in a JSON string under `event["body"]`. |
| 8 | Local example vs handler | Confirmed | The local example does not match the handler's input expectations. With the DB connection mocked, it raises `KeyError: 'beneficiaries_start_date'`. |
| 9 | Country/region requirement | Confirmed | Only partially implemented: country breakdown exists, region breakdown does not. |
| 10 | Country query failure handling | Confirmed | `aggregate_beneficiaries_country()` and `aggregate_help_requests_country()` return an error dictionary instead of `[]` on failure. The caller then builds a DataFrame from that dictionary, so failures are not reported cleanly. Issue #138 asked for `[]`. |
| 11 | Connection cleanup | Confirmed | No `finally` block. If an exception occurs after connecting (for example, the `KeyError` in item 8), the connections are not closed by the handler. |
| 12 | Cursor cleanup | Confirmed | `cursor_V` and `cursor_I` are never explicitly closed. |
| 13 | Response body encoding | Confirmed | The success `body` is a Python dictionary, not `json.dumps(...)` output. |
| 14 | Status key naming | Confirmed | Success uses `statusCode`; error paths use `status_code`. |
| 15 | SQL construction | Confirmed | Custom dates from the event (and fixed intervals) are interpolated into SQL with f-strings. This should be reviewed and parameterized. |
| 16 | `TASK_TRACKER.md` | Confirmed | `data-engineering/TASK_TRACKER.md` lists #138 under "In Progress" as "Open", while GitHub shows the issue as closed. The tracker appears stale for this issue. |

### Requires verification / unclear

| # | Area | Status | Details |
|---|---|---|---|
| 17 | `request` vs `requests` | Open question | The Lambda queries `request` (singular). The repository's mock data uses `requests.csv` (plural), and other recent work in this repository refers to a `requests` table. Which name exists in the deployed databases needs confirmation. |
| 18 | `req_user_id` vs `beneficiary_id` | Open question | The Lambda identifies the beneficiary through `req_user_id`. More recent schema material for the `requests` table uses `beneficiary_id` (and `creator_id`). Which column applies to the table this Lambda queries needs confirmation. |
| 19 | `last_update_date` vs `last_updated_at` | Open question | The Lambda filters on `last_update_date`. More recent schema material uses `last_updated_at`. Needs confirmation against the live schema. |
| 20 | Legacy `request` table | Open question | Whether a singular `request` table still exists in the deployed Virginia and Ireland databases. |
| 21 | Deployed vs committed code | Open question | Whether the deployed `beneficiariesTrendAnalysis` Lambda matches the code in this repository. The Issue #70 comment links to a console-edited Lambda, which cannot be compared from here. |
| 22 | Region-level analytics elsewhere | Open question | Whether region-level beneficiary analytics are implemented outside this repository (for example in the frontend, the `ml` repository, or the JSON delivered under Issue #84). |
| 23 | Beneficiary count definition | Open question | The intended business definition of the beneficiary count (see Section 5.1) is not documented in the reviewed issues. |
| 24 | Frontend integration | Open question | Frontend components, the API route, and how the date range is sent are not in this repository. |

---

## 10. Current vs Intended Behavior

| Capability | Intended | Current repository implementation |
|---|---|---|
| Virginia support | Yes (#138) | Yes. All returned metrics come from Virginia. |
| Ireland support | Yes (#138 Phase 1.2) | Not effective. A connection is opened, but two of three Ireland table constants point to Virginia and Ireland results are not used. |
| 7-day trend | Yes (#70, #82) | Yes, daily grouping |
| 1-month trend | Yes (#70, #82) | Yes, daily grouping |
| 1-year trend | Yes (#70, #82) | Yes, monthly grouping |
| Custom date range | Yes (#70, #82) | Yes, daily grouping. Requires top-level event fields; no defaults. |
| Country breakdown | Yes (#82) | Yes, all time, counts only, Virginia only |
| Region breakdown | Yes (#82) | Not implemented |
| Empty-data handling | `[]` from all four query functions (#138) | Trend functions: yes. Country functions: return an error dictionary instead. |
| Connection cleanup | `finally` closes cursor and connection (#138) | Connections closed on success only; cursors not closed; no `finally` |
| API Gateway body parsing | Not specified in #138; implied by the `__main__` example | Not implemented. `event['body']` parsing is commented out. |
| JSON response body | Original version used `json.dumps` | Returned as a Python dictionary |
| Credentials outside source | Yes (#138 Phase 4) | Yes, via SSM Parameter Store |
| Test with empty event `{}` | Should return 200 (#138 Phase 3) | Would fail due to the required date fields (code reading) |

---

## 11. Supporting References

### Issues

- [Issue #70 — Trend Analysis for Beneficiaries](https://github.com/saayam-for-all/data/issues/70)
- [Issue #82 — Design of Application Analytics tab under Super Admin Dashboard](https://github.com/saayam-for-all/data/issues/82)
- [Issue #84 — Super Admin Dashboard Application Analytics design: creation of Test data](https://github.com/saayam-for-all/data/issues/84)
- [Issue #138 — Implement real API for beneficiary_trend_analysis.py](https://github.com/saayam-for-all/data/issues/138)
- [Issue #603 — Document Application Analytics Flow and Implementation - Beneficiary Dashboard](https://github.com/saayam-for-all/data/issues/603)

### Pull requests (all unmerged)

- [PR #170 — #138: Implement real PostgreSQL API and db_client abstraction](https://github.com/saayam-for-all/data/pull/170)
- [PR #172 — #138: Refactor beneficiary trend analysis Lambda for production DB and add test file](https://github.com/saayam-for-all/data/pull/172)
- [PR #182 — feat(analytics): implement real API for beneficiaries trend analysis lambda](https://github.com/saayam-for-all/data/pull/182)

### Code and repository files

- Current code: [`data-analytics/lambda_functions/beneficiariesTrendAnalysis.py`](https://github.com/saayam-for-all/data/blob/test/data-analytics/lambda_functions/beneficiariesTrendAnalysis.py)
- Task tracker: [`data-engineering/TASK_TRACKER.md`](https://github.com/saayam-for-all/data/blob/test/data-engineering/TASK_TRACKER.md)
- Commits: `04b5fb4` (file created), `11b5f7b` (current implementation)
- Unmerged branches: `origin/issue#70` (Issue #70 CSVs and notebook), `origin/vighneshsridhar-beneficiaries_trend_analysis` (commit `1bc97dc`)

### External references (not reviewed for this document)

- [Super Admin Dashboard Analytics tab design wiki (`ml` repository)](https://github.com/saayam-for-all/ml/wiki/Super-Admin-Dashboard-Analytics-tab-Design)
- Issue #84 attachments: table/column-name spreadsheet and visualization-types document
- Issue #70 attachment: `Task_70.ipynb`

---

## 12. Conclusion

The Beneficiary tab's analytics started as exploratory and mock-data work (Issues #70 and #84), was defined as part of the Application Analytics dashboard design (Issue #82), and moved toward database-backed analytics (Issue #138 and commit `11b5f7b`).

The current repository code establishes the design direction: SSM-managed credentials, separate regional connections, fixed and custom date ranges, and a country breakdown. Several inconsistencies remain. Ireland data does not reach the response, the handler's input shape differs from its own local example, there is no region breakdown, and error handling, cleanup, and response formatting are only partly aligned with Issue #138.

This document records existing behavior and does not change the implementation. The open schema and runtime questions in [Section 9](#9-known-limitations-and-open-questions) (table and column names, the deployed Lambda version, and region analytics outside this repository) should be validated separately against the live databases and AWS environment before implementation work relies on them.
