# Request Tab Documentation

**Task:** [data#602](https://github.com/saayam-for-all/data/issues/602) | **Reviewed:** Nov 3, 2026 | **Location:** Super Admin Dashboard → Analytics → Application Analytics → Requests

**Code reviewed:** `webapp` `test` at [`83f689d`](https://github.com/saayam-for-all/webapp/tree/83f689de72b65a683ab2aa2837a6c684768104c9), `data` `dev` at [`fb30056`](https://github.com/saayam-for-all/data/tree/fb300562d71d86c97f63c4353d5e8b63400968ee), and open PR [data#167](https://github.com/saayam-for-all/data/pull/167) at [`d8ef707`](https://github.com/saayam-for-all/data/tree/d8ef70777bbadd0378290f504080cdc080b4bef0)

> **Important:** The API behind this tab is live, but its source is not merged into `main` or `dev` in the `data` repository. Backend details marked **(PR #167)** describe the closest available implementation evidence, not necessarily the deployed Lambda. The live frontend response includes time-specific category data that is not fully explained by the PR snapshot. Treat deployed behavior and PR-derived behavior separately.

## 1. Purpose

Shows administrators how request volume changes over time and which help categories and countries requests come from. This helps the team notice demand spikes and see which categories and regions may need more volunteers or partner organizations. It reports aggregate counts only.

Requests is the default of four Application Analytics tabs: Requests, KPI, Beneficiaries, and Volunteers.

## 2. Features

- **Request Volume Trend:** line chart of request counts, with the date and count shown on hover.
- **Requests by Category & Region:** horizontal bars by category, stacked by country. Five common countries have fixed colors, and others get a color generated from their name.
- **Top 5 countries:** ranked chips with request counts.
- **Independent charts:** each has its own time range, loading state, empty state, and errors.

## 3. User flow

1. A user with the `SUPER_ADMIN` role ([`rbac.js`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/utils/rbac.js#L43)) opens the dashboard on **Analytics**, switching to the Super Admin view first if another dashboard was last used. Admins see the same component.
2. The view opens on **Infrastructure**, so the user selects **Application Analytics**. **Requests** opens by default.
3. The tab sends one `POST {}` shared by both charts, which show "Loading data..." and then start on **All**.
4. Presets reuse the loaded data. Custom sends a new request for that chart once both dates are valid. Otherwise it shows "Select a start and end date" or "Start date must be on or before end date."
5. Empty results show "No data available for the selected period." API errors show the returned message, and failed requests show "Error:" with the reason.

## 4. Filters

| Filter | Chart | Options | Runs in |
|---|---|---|---|
| Time range | Each chart | 7D, 30D, 1Y, All, Custom | Browser for presets, API for Custom |
| Category | Category | Checkboxes, up to the current limit | Browser |
| Category limit | Category | Top 5, 7, 8 | Browser |
| Country | Category | All Countries or one country | Browser |
| Sort | Category | Total, Name | Browser |

## 5. Data sources

- **Frontend:** [`RequestsAnalytics.jsx`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Dashboard/components/Analytics/RequestsAnalytics.jsx) and [`analyticsServices.js`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/services/analyticsServices.js#L12)
- **API:** `POST v1/ml/requestApplicationAnalytics` ([`endpoints.json`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/services/endpoints.json#L45)), with `{}` or `{ "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD" }`
- **Lambda:** `requestApplicationAnalytics`, live on AWS (deployment recorded in data#167)
- **Database (PR #167):** Virginia RDS PostgreSQL, schema `virginia_dev_saayam_rdbms`, with credentials from AWS Parameter Store. This code has no Ireland connection.
- **Tables (PR #167):** `request` (`submission_date`, `req_user_id`, `req_cat_id`), `users` (`user_id`, `country_id`), `country` (`country_id`, `country_code`), and `help_categories` (`cat_id`, `cat_name`). The relationship is through `users.country_id = country.country_id`; `country_code` is used as the displayed/grouping country identifier. Confirm the deployed schema against the live database before treating this PR-derived schema as authoritative.

| Range | Volume field | Category field |
|---|---|---|
| 7D | `request_volume_7_days` | `requests_by_category_region 7 days` |
| 30D | `request_volume_1_month` | `requests_by_category_region 1 month` |
| 1Y and All | `request_volume_1_year` | `requests_by_category_region 1 year` |
| Custom | `request_volume_custom_range` | `requests_by_category_region_custom_range` |

The frontend also reads `has_errors` and `error_message`. Volume entries use `{date, count}`, and category entries use `{category, country, count}`. The frontend accepts 2- or 3-letter country codes and shows full names. These are frontend-observed response expectations; they should not be assumed to describe every field returned by the unmerged PR #167.

## 6. Metrics and calculations

- **Request volume (PR #167):** `COUNT(*)` of `request` rows, grouped with `DATE_TRUNC` on `submission_date`. 7D and 30D group by day, and 1Y by month. Custom reportedly groups by day under one year, otherwise by month ([webapp#1589](https://github.com/saayam-for-all/webapp/issues/1589)).
- **Category and region (PR #167):** `COUNT(*)` by `cat_name` and `country_code`, joining `request` to `users`, `country`, and `help_categories`. Region is the requester's profile country. The PR query shown in the reviewed implementation counts across all time and accepts optional `category`, `country`, and `sort_by` inputs. The frontend, however, expects separate category results for each selected time range. The reviewed PR code therefore does not, by itself, explain the live API's time-scoped category response. The live query/implementation must be checked before documenting its exact filtering logic.
- **Top 5 countries (browser):** country totals for the selected time range, highest first. PR #167 also returns `top_countries`, but the frontend does not use it ([code](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Dashboard/components/Analytics/RequestsAnalytics.jsx#L226)).
- **Category total (browser):** sum of a category's country counts after filters ([code](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Dashboard/components/Analytics/RequestsAnalytics.jsx#L239)).

## 7. Historical task and PR review

Issue [data#602](https://github.com/saayam-for-all/data/issues/602) asks for the relevant tasks to be reviewed individually, including their comments, attachments, and linked pull requests. The following records summarize the directly relevant history and distinguish what is visible in the issue/PR record from what is not independently verified.

| Record | What the record establishes | Relevance to the Requests tab | Evidence / caveat |
|---|---|---|---|
| [data#82](https://github.com/saayam-for-all/data/issues/82) | Defines Application Analytics visuals, including total help requests over 7 days, month, year, or a custom range, plus requests by category and region. | Establishes the original Requests-tab requirements. | The issue describes the intended visuals; it does not establish the final implementation. |
| [data#84](https://github.com/saayam-for-all/data/issues/84) | Calls for realistic sample CSV files because real data was unavailable, conversion of CSV data to JSON, and API exposure for frontend development. Its description links a database schema spreadsheet and a visualization-types document. A March 24, 2026 comment says the JSON objects were created and sent to the UI team. | Explains the mock-data phase and why the frontend could be developed before live database queries were available. | The linked attachments are listed in the issue: `Table & column names_data-1764970855601.xlsx` and `Types of Visualizations for Application Analytics Dashboard.docx`. Their contents should be checked directly if exact schema or chart specifications are needed; this document does not infer details from filenames alone. |
| [data#89](https://github.com/saayam-for-all/data/issues/89) | Tracks the Python/Plotly Application Analytics implementation work linked as a sub-issue of #84. | Part of the early analytics/mock-data development history. | Treat this as historical analytics work; the current Requests UI is implemented in the webapp and uses Recharts, so the older visualization approach should not be mistaken for the current frontend implementation. |
| [data#146](https://github.com/saayam-for-all/data/issues/146) | Tracks the backend Lambda work for request application analytics. | Connects the original analytics design to the real-data backend implementation. | The implementation history and commits are summarized below; the issue/PR record should be consulted for the full discussion. |
| [data#167](https://github.com/saayam-for-all/data/pull/167) | Contains the real-database Lambda implementation and mock-based tests, plus subsequent changes for Parameter Store, CORS, and SQL grouping. | Main backend implementation reference for the Requests analytics API. | PR remains a separate source of implementation evidence. Its code must not be presented as the exact live implementation where the live response differs. |
| [data#189](https://github.com/saayam-for-all/data/pull/189) | Is titled “Added Date Filters for beneficiariesTrendAnalysis.py.” | Related to the broader Application Analytics/date-filtering work, but its title identifies Beneficiaries rather than the Requests endpoint. | Cross-reference only. Do not use it as evidence for Requests-tab behavior unless a linked change or shared implementation is confirmed. |
| [webapp#1057](https://github.com/saayam-for-all/webapp/issues/1057) | Covers different dashboard views using RBAC. | Provides context for why the Super Admin dashboard view and role gating matter when navigating to Application Analytics. | This is dashboard access/navigation context, not a Requests-chart calculation specification. |
| [webapp#1589](https://github.com/saayam-for-all/webapp/issues/1589) | Tracks work specifically titled Application Analytics – Requests tab and is referenced for custom-range grouping behavior. | Relevant frontend follow-up for Requests date-range behavior. | The exact backend grouping behavior should be confirmed against the linked implementation/PR before treating issue discussion as proof of deployed behavior. |

### Review notes and evidence boundaries

- The issue #84 record explicitly lists two attachments. Their filenames and purpose are visible in the issue; the attachment contents are not reproduced here. Open and inspect those files before relying on them for exact column definitions or visualization specifications.
- The records above establish the development sequence, but not every issue comment or linked PR diff is fully represented in this summary. Where a detail depends on a comment, attachment, deployed Lambda, or live database schema, it is marked as requiring confirmation rather than being stated as fact.
- The PR #167 implementation is useful evidence for backend design, SQL, and tests, but the frontend's observed live response has fields and time-specific results that are not fully explained by that PR snapshot.
- PR [data#649](https://github.com/saayam-for-all/data/pull/649) is a separate documentation PR for issue #602. Its description says it adds a task-by-task review of data issues #82, #84, #89, #146, #167, and #189, plus webapp issues #1057 and #1589 and their PRs. Compare this document with that PR before creating or updating a competing documentation change.

## 8. Implementation approach

| Date | Change | Source |
|---|---|---|
| Nov 2025 – Mar 2026 | Designed the tab's two views: total requests over 7 days, a month, a year, or a custom range, and requests by category and region | [data#82](https://github.com/saayam-for-all/data/issues/82) |
| Dec 2025 – Mar 2026 | With no real data available, created sample CSVs, converted them to JSON, and shared them with the UI team so the frontend could be built independently. SQL queries were planned as a later replacement with no UI changes | [data#84](https://github.com/saayam-for-all/data/issues/84), [data#89](https://github.com/saayam-for-all/data/issues/89) |
| Apr 14–23, 2026 | Backend task opened and first Lambda file added, then overwritten with volunteer logic | [data#146](https://github.com/saayam-for-all/data/issues/146), [`42b959d`](https://github.com/saayam-for-all/data/commit/42b959d) |
| May 7–12, 2026 | Lambda and 13 mock-based tests submitted, original file deleted, Lambda reported deployed | [data#167](https://github.com/saayam-for-all/data/pull/167), [`cfc2ec9`](https://github.com/saayam-for-all/data/commit/cfc2ec9) |
| Jun 2–4, 2026 | Moved to Parameter Store, added CORS, and moved grouping into SQL | [`d467a04`](https://github.com/saayam-for-all/data/commit/d467a04), [`d8ef707`](https://github.com/saayam-for-all/data/commit/d8ef707) |
| Jun 24, 2026 | Frontend connected to the live API, replacing mock JSON | [`a687e6f`](https://github.com/saayam-for-all/webapp/commit/a687e6f) |
| Jul 2, 2026 | Added separate category time range and multi-select | [`e7ce547`](https://github.com/saayam-for-all/webapp/commit/e7ce547) |
| Oct 1, 2026 | Added independent custom ranges and error states, and removed `group_by` | [webapp#1876](https://github.com/saayam-for-all/webapp/pull/1876) |
| Oct 27–30, 2026 | Early dropdown fix reverted, then dropdown and country color fixes merged | [webapp#1941](https://github.com/saayam-for-all/webapp/pull/1941), [webapp#1942](https://github.com/saayam-for-all/webapp/pull/1942) |

The frontend draws both charts with Recharts. Both charts share one default request, and each uses its own `useRequestRange` hook, so a slow response cannot replace a newer selection ([code](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Dashboard/components/Analytics/RequestsAnalytics.jsx#L99)). In PR #167, the Lambda implementation returns status 200 with CORS headers and a JSON-string response body, or status 500 with `Failed to connect to database.` This describes the PR implementation, not a separately verified contract for every live response. The frontend has 19 tests in [`RequestsAnalytics.test.jsx`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Dashboard/components/Analytics/RequestsAnalytics.test.jsx). No separate test-case document for this tab was identified in the reviewed materials.

## 9. Known limitations

- **All** shows one year of data, the same as 1Y ([code](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Dashboard/components/Analytics/RequestsAnalytics.jsx#L64)).
- Stacked bars show only the top 5 countries, although other countries still count toward category totals.
- Top 5 chips do not change with the category or country filter.
- Category and volume totals may differ, because the category query uses inner joins (PR #167).
- Requests are counted regardless of status, including deleted and cancelled requests (PR #167).
- Preset data does not refresh until the tab reloads.
- Periods with no requests are omitted rather than returned as zero, and rolling windows can make the first month in 1Y a partial month (PR #167).


## 10. Items to verify before treating this document as final

1. **Live backend source:** Identify the exact deployed Lambda version and compare it with PR #167. The live API's time-specific category response is not fully explained by the reviewed PR snapshot.
2. **Database schema:** Confirm the live Virginia RDS schema and the `country` table's primary/foreign-key columns. The PR-derived relationship is `users.country_id = country.country_id`, with `country_code` used for grouping/display.
3. **Historical attachments:** Open both attachments listed in [data#84](https://github.com/saayam-for-all/data/issues/84) and compare their schema/chart definitions with the current implementation.
4. **Historical PRs:** Review the linked PRs and comments for [data#89](https://github.com/saayam-for-all/data/issues/89), [data#146](https://github.com/saayam-for-all/data/issues/146), [data#167](https://github.com/saayam-for-all/data/pull/167), [data#189](https://github.com/saayam-for-all/data/pull/189), and the frontend changes associated with [webapp#1057](https://github.com/saayam-for-all/webapp/issues/1057) and [webapp#1589](https://github.com/saayam-for-all/webapp/issues/1589). Do not attribute Beneficiaries-only changes from #189 to Requests without confirming shared code.
5. **Repository delivery:** Confirm the Markdown file is committed under the intended repository path and attached to the PR for review, as required by [data#602](https://github.com/saayam-for-all/data/issues/602).

These are verification tasks, not claims that the implementation is incorrect. They are listed separately so readers can distinguish documented behavior from details that still require access to the deployed backend, database, or historical attachments.
