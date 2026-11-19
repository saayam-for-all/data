# Volunteer Tab Documentation

The **Super Admin Dashboard → Analytics → Application Analytics → Volunteers** tab shows volunteer registration trends and volunteer counts by country. It helps administrators compare the size and geographic distribution of the volunteer population over time. It does not measure completed volunteering work, hours, or request resolution.

Selected from [PR #631](https://github.com/saayam-for-all/data/pull/631) by [virajparmaj](https://github.com/virajparmaj), after comparing [PR #636](https://github.com/saayam-for-all/data/pull/636) and [PR #663](https://github.com/saayam-for-all/data/pull/663). Consolidated on November 11, 2026 with updated frontend references and additional local verification.

This document addresses [data issue #605](https://github.com/saayam-for-all/data/issues/605). It explains the checked-in implementation, reviews its development tasks individually, and identifies differences between historical requirements, branch contents, and reported deployment behavior.

## Reviewed implementation

Consolidation reviewed on **November 11, 2026**, using these fixed source revisions. The original #631 review used October 30 snapshots; its historical review and test reports are distinguished below.

| Source | Revision and relevant code |
| --- | --- |
| Analytics backend | `data`, local documentation branch at `2602a8897d25b086624e202beb7515d1d31b634a`: [volunteer Lambda][handler] |
| Dashboard frontend | `webapp`, pinned source at `388534d902110bac4d4a38f7a4fc1cdbba8ac6ad`: [VolunteerAnalytics][volunteer-ui], [ApplicationAnalytics][application-ui], [SuperAdminDashboard][superadmin-ui] |
| Frontend API integration | Same webapp revision: [analytics service][service], [endpoint definitions][endpoints], [shared HTTP client][http-client] |
| Schema references | Same data revision: [database workbook][schema] and [ACTIVE status lookup][status-lookup] |

**Evidence labels:** “Confirmed from code” describes these revisions or inspected repository artifacts. “Reported in task discussion” describes a contributor's account. “Unverified” identifies information that was not established by source inspection or local checks. A closed issue or a successful test reported in a PR does not establish which code is deployed.

**Frontend update:** The reviewed frontend now shows only Active and Total Volunteers. [Webapp #1680](https://github.com/saayam-for-all/webapp/issues/1680) requests removal of New Volunteers and reports a changed API contract. [PR #1838](https://github.com/saayam-for-all/webapp/pull/1838) merged the removal into `features/dashboard-analytics`; [PR #1944](https://github.com/saayam-for-all/webapp/pull/1944) merged the subtitle/legend follow-up into `test` on November 3. Those changes are present in the pinned frontend, but the checked-in backend still returns `new_volunteers`. The deployed UI/API revision remains **unverified**.

## User flow and visible features

1. Open the Super Admin Dashboard, select **Analytics**, then **Application Analytics**. The dashboard initially selects Infrastructure; Application Analytics initially selects Requests, so select **Volunteers** to mount this tab. See the [dashboard state][dashboard-state] and [nested tab components][superadmin-ui].
2. The component sends an empty POST payload, `{}`, and initially selects **All** for both widgets.
3. Use **7D**, **30D**, **1Y**, **All**, or **Custom** separately for each widget. Preset buttons select a bucket from the response already loaded; they do not send a new request. Custom selection exposes two date inputs, and a request is sent once both dates are populated.
4. Inspect chart values through tooltips and legends. Use **Expand chart** to open the same chart content in a modal; close it with the close button or by clicking the backdrop. Expansion itself does not fetch data. See [ChartContainer][chart-container].

| Widget | Confirmed display and transformation |
| --- | --- |
| Volunteer Activity Trend | Line chart with Active and Total series; `new_volunteers` is not read or displayed. The frontend joins the two arrays by `period`, sorts ascending, and displays missing series values as unavailable in the tooltip. It does not create missing time buckets or fill absent series counts with zero. |
| Volunteers by Location | Horizontal bar chart of the **top 10** returned countries by count. ISO alpha-3 codes are converted to English names where recognized; other values are displayed unchanged. The backend returns the full country aggregation before this frontend limit. |

These transformations are in [VolunteerAnalytics][volunteer-ui] and the [country-name helper][country-names]. Country, skill, chart-type, state, and city selectors shown in some earlier mock screens are absent from this reviewed UI. Country and skill filtering remain backend inputs, described below.

### Loading, empty, error, and refresh behavior

**Confirmed from code:** The trend widget shows a loading message during the initial fetch and custom trend requests. A rejected initial/trend request sets an error banner. An empty selected dataset displays an empty-state message. The location widget displays its empty state during initial loading and shows an updating indicator during a custom location request. A failed custom location request clears its custom response without a dedicated location error banner. Existing trend data can remain visible after a failed custom trend request.

The current component does not import the old static JSON fallback files. There is no retry button or periodic refresh. Leaving and re-entering Volunteers remounts the component and fetches defaults again. Custom requests and switching back to presets have a cache limitation described under [Known defects](#known-defects-in-the-reviewed-sources). See the [request effects and selected data][ui-requests].

## API contract and processing

**Confirmed from code:** The frontend posts to the relative route **`v1/ml/volunteerApplicationAnalytics`** through `getVolunteerApplicationAnalytics(payload)`. The shared HTTP client uses `VITE_BASE_API_URL` and adds the authenticated session's ID token when available. The route definition does not establish the deployed Gateway integration, authorizer, or exact Lambda version. See the [service][service], [endpoint][endpoints], and [HTTP client][http-client].

The Lambda accepts a direct event dictionary, a dictionary in `event.body`, or JSON text in `event.body`. Malformed JSON text falls back to an empty dictionary. The handler's response has `statusCode`, JSON/CORS headers, and a JSON-encoded `body`. The frontend selects `data.body ?? data` as an object; it does not decode a JSON string there. Whether API Gateway unwraps the Lambda response into the expected HTTP JSON body is **unverified** by this review. See [event parsing and handler responses][handler].

### Supported inputs

| Input | Current behavior |
| --- | --- |
| `{}` | Computes both widgets for `7D`, `30D`, `1Y`, and `All`; includes an empty `Custom` bucket. |
| `start_date`, `end_date` | With both values present, returns **only `Custom`**, populating the trend and leaving location empty. |
| `location_start_date`, `location_end_date` | With both values present and no complete activity date pair, returns **only `Custom`**, populating location and leaving the three trend arrays empty. |
| Both complete date pairs | The activity branch returns first; location custom dates are not processed. The reviewed frontend sends separate calls for the two widgets. |
| `country` | Location only. Default is the exact sentinel `All Countries`. Other values are bound to `UPPER(country.country_code) = %s`; callers must supply the expected uppercase code. The handler does not normalize it. |
| `skill` | Location only. Default is the exact sentinel `All Skills`. Otherwise matches `help_categories.cat_name` through `user_skills.cat_id` using `EXISTS`; an empty string is a filter value, not the all-skills sentinel. |
| `chart_type` | Defaults to `Bar Chart`; passed through to the location helper but does not change the query or response. |
| `time_range`, `time_range_location` | Not read by this handler. Preset selection happens in the frontend using the consolidated response. |

The handler requires both dates in a pair to enter a custom branch. A single supplied date does not select that branch. The old aliases `start_date_location` / `end_date_location` in the [test-case DOCX][historical-tests] are not read; use **`location_start_date` / `location_end_date`**. There is no handler-level date-format or reversed-range validation. See [routing][handler] and [country/skill SQL][location-query].

### Time windows

All date filtering uses `volunteer_details.created_at` (`vd.created_at`), not a request date, last login, skill update, or current-location timestamp.

| Response key | SQL selection | Trend grouping and `period` |
| --- | --- | --- |
| `7D` | `created_at >= CURRENT_DATE - INTERVAL '7 days'` | Daily, `YYYY-MM-DD` |
| `30D` | `created_at >= CURRENT_DATE - INTERVAL '30 days'` | Daily, `YYYY-MM-DD` |
| `1Y` | `created_at >= CURRENT_DATE - INTERVAL '1 year'` | Monthly, `YYYY-MM` |
| `All` | No date predicate | Monthly, `YYYY-MM` |
| `Custom` | New/active/location use timestamp `BETWEEN` with the supplied endpoints; total uses date-cast boundaries and a pre-start baseline | Daily, `YYYY-MM-DD` |

`CURRENT_DATE` uses the database session's date. Fixed windows have a lower bound but no upper bound and do not mean exactly seven or thirty complete calendar dates. The code does not apply the viewer's timezone. Custom end-date behavior differs between total and the other counts; see [Known defects](#known-defects-in-the-reviewed-sources). These predicates and grouping rules are [confirmed in the helpers][date-helpers].

### Request and response examples

Default request:

```json
{}
```

Its parsed response body contains five top-level keys: `7D`, `30D`, `1Y`, `All`, and `Custom`. Every bucket contains `volunteer_activity_trend` with `new_volunteers`, `active_volunteers`, and `total_volunteers` arrays, plus `volunteers_by_location`. The default `Custom` arrays are empty.

Custom trend request:

```json
{
  "start_date": "2026-05-01",
  "end_date": "2026-05-03"
}
```

Example **parsed body using synthetic cursor results**, not observed live counts:

```json
{
  "Custom": {
    "volunteer_activity_trend": {
      "new_volunteers": [{"period": "2026-05-01", "count": 3}],
      "active_volunteers": [{"period": "2026-05-01", "count": 2}],
      "total_volunteers": [{"period": "2026-05-01", "count": 11}]
    },
    "volunteers_by_location": []
  }
}
```

Custom location request:

```json
{
  "location_start_date": "2026-05-01",
  "location_end_date": "2026-05-03"
}
```

This returns `Custom.volunteers_by_location` as country/count objects, for example `{"country":"USA","count":5}`, and empty trend arrays. It does not return preset buckets. Country and skill inputs can be added to a location request; they do not filter the activity trend.

## Data sources, joins, and calculations

### Sources and execution

The handler opens two PostgreSQL connections and queries these schema-qualified tables separately in **`virginia_dev_saayam_rdbms`** and **`ireland_dev_saayam_rdbms`**:

| Tables and columns | Use |
| --- | --- |
| `users.user_id` → `volunteer_details.user_id` | Base inner join that defines which users are included as volunteers. No additional `user_category` predicate is applied. |
| `volunteer_details.created_at` | Registration/onboarding timestamp proxy for trend buckets and location date filters. |
| `users.user_status_id` | Active trend predicate, currently `= 1`. The checked-in [lookup CSV][status-lookup] maps `1` to `ACTIVE`; the deployed lookup remains unverified. |
| `users.country_id` → `country.country_id` | Location attribution, using `country.country_code`. A left join preserves volunteers without a country match as `Unknown`. |
| `user_skills.user_id`, `user_skills.cat_id` → `help_categories.cat_id` | Optional skill membership filter by category name. `EXISTS` avoids multiplying the volunteer count for multiple skill rows. |

State, city, volunteer-location, and user-location table constants are declared but not queried by these widgets. Location therefore means the user's country mapping, not current volunteer proximity or GPS. The current [schema workbook][schema] includes `created_at` and `user_skills.cat_id`; the older [#84 attachment][old-schema] has different fields, including `skill_id`, and lacks that volunteer creation column. Use the current workbook as a repository reference, while validating actual deployed schemas separately.

`get_db_config()` retrieves encrypted SSM parameters for Virginia and Ireland from the `us-east-1` SSM client and parses the returned configuration text. It then passes the values to `psycopg2.connect`. Credentials are not embedded in this file. The region names are data-source labels, not country filters. See [table constants][table-sources] and [configuration loading][configuration].

### Metric definitions

The calculations below are **confirmed from the [trend queries][trend-query] and [location query][location-query]**. Counts are distinct by `users.user_id` within each regional query.

| Metric | Calculation and interpretation |
| --- | --- |
| New Volunteers | Distinct joined users whose non-null volunteer creation timestamp falls in the period and selected window. |
| Active Volunteers | The same creation-period cohort, additionally requiring the user's **current** status ID to equal `1`. This is not a count of volunteers who performed work or were active during that historical period. |
| Total Volunteers, fixed windows | Running sum of registration counts **within the filtered window**. `7D`, `30D`, and `1Y` omit registrations before their lower bound. `All` runs over the full non-null creation history. |
| Total Volunteers, Custom | Count created before the custom start date, plus the running sum of registrations whose creation **date** is within the range. Thus its baseline differs from fixed-window totals. A baseline alone does not generate a row on a day without registrations. |
| Volunteers by Location | Distinct joined users per country, optionally restricted by creation date, country, and skill. It includes all statuses. Under `All`, it does not require a non-null creation timestamp. |

For example, in one region, ten volunteers registered before a selected window and two plus three registered in its first two buckets produce fixed-window totals **2, 5**, while a Custom range with that baseline produces **12, 15**. New counts remain **2, 3**. These examples explain query scope; they are not production measurements.

Each region's results are merged by matching `period` or country and **adding counts**, then sorted by key. The merge does not deduplicate identities across databases or fill missing periods. A merged total can fall when a region has no row for a period because its earlier cumulative value is not carried forward. It is not a globally deduplicated daily census. See the [merge helpers][merge-code].

### Errors and operational boundaries

The normal consolidated request executes three trend queries and one location query per window per database: **32 query executions** across four preset windows and two databases. Custom trend uses six; custom location uses two. There is no CSV-loading path in this Lambda.

Query helpers catch exceptions and return empty arrays, so empty or partial results may still be returned with HTTP 200. Exceptions reaching the outer handler, including configuration/connection failures, return HTTP 500 with the five-bucket empty response. The `finally` block attempts to close both cursors and connections. See the [handler][handler], [trend error path][trend-query], and [location error path][location-query].

The repository's [automatic deployment workflow][deployment] targets `data-engineering/src/saayam-org-*` changes, not this `data-analytics/lambda_functions` file. Neither that workflow nor the route name proves deployment of the reviewed Lambda. Team leads handle deployment under [CONTRIBUTING.md](../../data-engineering/CONTRIBUTING.md); this documentation review made no AWS or live-database calls.

## Development history and individual task reviews

The original #631 author recorded the following separate task reviews, including returned comments, attachments and linked PR material. Consolidation independently rechecked the principal tasks and sources; remaining review boundaries are listed under Validation. Requirements, contributor reports, and current code are distinguished so that historical mock screens and reverted implementations are not presented as current features.

| Task | Reviewed evidence and contribution to this tab |
| --- | --- |
| [data #71](https://github.com/saayam-for-all/data/issues/71), early volunteer trends | Body and three comments cover temporal/geographic analysis, ratings, and users. Reviewed the two-page [volunteer prototype PDF](https://github.com/user-attachments/files/21701394/Volunteer_trend_analysis.pdf), [user-analysis notebook](https://github.com/user-attachments/files/22061197/Trend.Analysis.for.Users.71.ipynb), and [analysis script](https://github.com/user-attachments/files/23724833/saayam-trend-analysis.py). These demonstrate exploratory CSV joins, country counts, and visualizations. The script synthesizes dates/ratings; it does not establish current Lambda calculations. No linked PR appeared in its reviewed timeline. |
| [data #81](https://github.com/saayam-for-all/data/issues/81), Super Admin Analytics | Body and one completion comment establish the dashboard umbrella. No volunteer-specific contract, attachment, or linked PR was provided there. |
| [data #82](https://github.com/saayam-for-all/data/issues/82), Application Analytics design | Body, two comments, and the linked [analytics design wiki](https://github.com/saayam-for-all/ml/wiki/Super-Admin-Dashboard-Analytics-tab-Design) establish volunteer counts over time and by geography. Its linked infrastructure subtask is outside this tab's implementation. No volunteer implementation PR appeared in the reviewed timeline. |
| [data #84](https://github.com/saayam-for-all/data/issues/84), initial mock data | Body, two comments, [schema XLSX][old-schema], and [visualization DOCX](https://github.com/user-attachments/files/24040571/Types.of.Visualizations.for.Application.Analytics.Dashboard.docx) specify CSV → JSON → API development and line/bar volunteer visuals. The completion comment reports JSON delivery to the frontend team. The attached schema is historical. Its child is #89. |
| [data #89](https://github.com/saayam-for-all/data/issues/89), Python/Plotly implementation | No body; two comments report mock CSV conversion, delivery, and completion. Its timeline links it to parent #84. No implementation attachment or linked PR was provided there. The current frontend uses Recharts, so the issue title is not evidence of the current rendering library. |
| [data #151](https://github.com/saayam-for-all/data/issues/151), real volunteer API | Body, no comments, and linked schema reference cover Virginia/Ireland, the two widgets, joins, monthly trend metrics, filters, safe responses, and credential handling. Reviewed [PR #199](https://github.com/saayam-for-all/data/pull/199), its diff and discussion: it remains open, unmerged, targeting `dev`. Its proposed code is not the selected implementation. |
| [data #179](https://github.com/saayam-for-all/data/issues/179), date filters | Body, no comments, timeline, [test-case DOCX][historical-tests], and PRs listed below cover independent dates, daily/monthly grouping, and `period` replacing `month`. The DOCX still describes selector payloads and an older location-date alias that do not match the current handler. |
| [webapp #1057](https://github.com/saayam-for-all/webapp/issues/1057), dashboard views | Body and 19 comments reviewed for analytics navigation and dashboard context. The thread establishes Analytics, Infrastructure, Application Analytics, and Google Analytics placement. Its All Requests table/filter changes and date-format screenshot are outside the Volunteer analytics flow. Initial analytics UI is also recorded in [commit `55f175a`](https://github.com/saayam-for-all/webapp/commit/55f175a634663efae73af3972d2676bc2353dca7). |
| [webapp #1680](https://github.com/saayam-for-all/webapp/issues/1680), Volunteers integration and updates | Original author reviewed the then-available discussion and screenshots; consolidation read the updated discussion, all three screenshots, and PRs #1838/#1944. The discussion reports database resets, subsequent API mock data, and removal of New Volunteers. Those reports do not establish the currently deployed field set. Reviewed the actual integration [PR #1681](https://github.com/saayam-for-all/webapp/pull/1681), despite its title referencing Requests issue #1589. |

### PR and code evolution

| Evidence | Disposition and relevance |
| --- | --- |
| [#179 PR #200](https://github.com/saayam-for-all/data/pull/200) | Open. Its revised body proposes consolidated windows and describes a shared date helper, but says presets remain present during custom requests. The checked-in handler instead returns early with Custom only. |
| [PR #202](https://github.com/saayam-for-all/data/pull/202) → [revert #204](https://github.com/saayam-for-all/data/pull/204) | Both merged. The date-filter implementation was reverted; it is not the final contract. |
| [PR #218](https://github.com/saayam-for-all/data/pull/218) → [revert #219](https://github.com/saayam-for-all/data/pull/219) | Both merged; that implementation was reverted. |
| [PR #229](https://github.com/saayam-for-all/data/pull/229) → [revert #238](https://github.com/saayam-for-all/data/pull/238) | Both merged; that implementation was reverted. Its [attached Python proposal](https://github.com/user-attachments/files/30390428/volunteer_application_analytics.1.py) was inspected during consolidation: it uses a flat selected-range response and a local SQLite mode, unlike the pinned consolidated handler. |
| Other #179 proposals | [#208](https://github.com/saayam-for-all/data/pull/208), [#209](https://github.com/saayam-for-all/data/pull/209), [#217](https://github.com/saayam-for-all/data/pull/217), [#221](https://github.com/saayam-for-all/data/pull/221), [#224](https://github.com/saayam-for-all/data/pull/224), and [#243](https://github.com/saayam-for-all/data/pull/243) are open/unmerged. [#226](https://github.com/saayam-for-all/data/pull/226) is closed/unmerged. Reviewed their diffs/discussions, #208's [Python attachment](https://github.com/user-attachments/files/29760793/179.Date.filters.py), and #243's test screenshot. Their local validation reports apply to those proposed versions. |
| [PR #232](https://github.com/saayam-for-all/data/pull/232) | Appears in #179's cross-references but changes KPI analytics. Reviewed and excluded from this tab's implementation history. |
| [Backend upload `8b640fc`](https://github.com/saayam-for-all/data/commit/8b640fc093abbb64cbadd7d06820958f4aefde57) | The last change to this Lambda in the selected base, after the revert sequence. Its actual contents establish the consolidated preset response and separate Custom-only calls described above. |
| [Webapp PR #1681](https://github.com/saayam-for-all/webapp/pull/1681) | Merged into `test`; introduced the live POST integration and independent range controls. Its body describes static fallback behavior that was subsequently removed in [commit `9accf9c`](https://github.com/saayam-for-all/webapp/commit/9accf9c1da0b641b23eb4dbb13fca8af1b714e2e). The reviewed source has empty states instead of a mock fallback. |
| [Webapp PR #1838](https://github.com/saayam-for-all/webapp/pull/1838), [#1944](https://github.com/saayam-for-all/webapp/pull/1944) | #1838 removes the New series but merged into `features/dashboard-analytics`. #1944 merged the subtitle/legend changes into `test` on November 3. The updated pinned frontend now omits New from the plotted series and tooltip, while the backend retains the field. |

## Known defects in the reviewed sources

These source findings affect interpretation and integration; this documentation does not modify the implementation.

| Trigger | Confirmed behavior | Practical implication |
| --- | --- | --- |
| Complete a custom trend request, then select a preset or view a preset location chart. | `setApiData(data)` replaces the shared preset response with Custom-only data. Preset selection does not refetch defaults. | Either chart can lose its preset data until remount/refetch. See [custom state][ui-custom-cache]. |
| Select a daily range with several points in one month. | `formatPeriod` ignores the day and labels every point with month/year. | Distinct daily counts have indistinguishable date labels/tooltips. See [formatter][ui-period-format]. |
| Use custom dates with registrations later on the final day. | New/active/location compare timestamps to the end date's midnight; Custom total casts to date and includes the whole day. | Counts can cover different end-day records. See [date helpers][date-helpers] and [total SQL][trend-query]. |

## Missing or unclear information

| Question | Evidence and remaining confirmation |
| --- | --- |
| Which version and fields are deployed? | #1680 reports removing `new_volunteers`, while the pinned backend retains it and the frontend no longer reads it. Confirm the deployed Lambda, Gateway route mapping, frontend build revision, and the final metric set with the responsible teams. |
| Are displayed counts real, synthetic, or empty? | #1680 reports a DB reset and later added API mock data. The checked-in Lambda reads databases, not CSVs. Confirm current table provenance before interpreting the charts as real volunteer growth. |
| What is the approved meaning of Active and Total? | Code uses current status grouped by creation period and different total baselines for fixed/custom windows. Confirm these business definitions before using the figures as historical activity or overall population metrics. |
| Are the regional populations disjoint and time settings aligned? | Merging adds regional results without identity deduplication or gap filling. No deployed cross-region identity or timezone guarantee was verified. |
| Does the Gateway return the body shape the component expects? | The Lambda encodes `body` as text, while the component expects a parsed object. The exact deployed proxy/response mapping was not exercised. |
| Is the deployed database schema the same as the workbook? | The old and current workbooks differ. Current code assumes `created_at`, `cat_id`, and the documented country/status joins; live schema access was not part of this review. |

## Validation of this documentation

The original #631 author reports nine mocked-backend checks and three frontend transformation checks. Those results are attributed to that author; they were not rerun as a frontend suite during consolidation.

The original author also read [VolunteerAnalytics tests][ui-tests]; historical suite pass counts remain contributor reports. Consolidation independently inspected the #71 PDF (both rendered pages), notebook and exploratory script; #84 schema/visualization attachments; #179 test-case DOCX; #229 Python attachment; and all three #1680 screenshots. Attached code was not executed. The #208 attachment and #243 test screenshot were reviewed by the original author, not independently rechecked here. GitHub API rate limits prevented an exhaustive new inline-comment review; visible public PR discussions were used as a fallback.

Consolidation added **16 passing mocked source-behavior checks**, covering the five default buckets, 32/6/2 query-call paths, success cleanup, bound country/skill/dates, custom total baseline SQL, activity precedence for simultaneous date pairs, partial-pair and malformed-JSON fallback, ignored range selectors, active-status SQL, missing preset baseline, regional cumulative merge without carry-forward, query-error empty defaults, and connection-failure 500 shape. These used the actual Python function definitions with imports/service access replaced by doubles; no PostgreSQL, AWS or live API calls occurred. The backend syntax tree matches the original #631 baseline. Updated frontend fields, endpoint/service code, source paths and JSON examples were rechecked. The frontend test suite was not rerun.

[handler]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/volunteer_application_analytics.py
[table-sources]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/volunteer_application_analytics.py
[date-helpers]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/volunteer_application_analytics.py
[trend-query]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/volunteer_application_analytics.py
[merge-code]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/volunteer_application_analytics.py
[location-query]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/volunteer_application_analytics.py
[configuration]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/volunteer_application_analytics.py
[schema]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/database/Saayam_Table.column.names_data.xlsx
[status-lookup]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/database/lookup_tables/user_status.csv
[old-schema]: https://github.com/user-attachments/files/24040548/Table.column.names_data-1764970855601.xlsx
[historical-tests]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/data-analytics/lambda_functions/Test%20Cases%20and%20Acceptance%20Criteria.docx
[deployment]: https://github.com/saayam-for-all/data/blob/2602a8897d25b086624e202beb7515d1d31b634a/.github/workflows/deploy-lambda.yml
[volunteer-ui]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/components/Analytics/VolunteerAnalytics.jsx
[ui-requests]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/components/Analytics/VolunteerAnalytics.jsx
[ui-custom-cache]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/components/Analytics/VolunteerAnalytics.jsx
[ui-period-format]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/components/Analytics/VolunteerAnalytics.jsx
[application-ui]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/components/Analytics/ApplicationAnalytics.jsx
[superadmin-ui]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/views/SuperAdminDashboard.jsx
[dashboard-state]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/Dashboard.jsx
[chart-container]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/components/Analytics/charts/ChartContainer.jsx
[service]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/services/analyticsServices.js
[endpoints]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/services/endpoints.json
[http-client]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/services/api.js
[country-names]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/utils/isoCountryNames.js
[ui-tests]: https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/components/Analytics/VolunteerAnalytics.test.jsx
