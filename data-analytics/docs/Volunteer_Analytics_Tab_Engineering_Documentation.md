# Volunteer Analytics Tab — Engineering Notes

**Location:** Super Admin Dashboard → Analytics → Application Analytics → Volunteers
**Documentation scope:** Backend Lambda, frontend integration, data model, historical implementation work, and items requiring engineering confirmation
**Backend entry point:** [`volunteer_application_analytics.py`](https://github.com/saayam-for-all/data/blob/main/data-analytics/lambda_functions/volunteer_application_analytics.py)
**Frontend component:** [`VolunteerAnalytics.jsx`](https://github.com/saayam-for-all/webapp/blob/dev/src/pages/Dashboard/components/Analytics/VolunteerAnalytics.jsx)
**API:** `POST v1/ml/volunteerApplicationAnalytics`

> **Source and version note:** The code-level behavior below is based on the Lambda source shared for this task and the reviewed repository snapshot described in the supplied engineering notes: data commit [`8b640fc`](https://github.com/saayam-for-all/data/commit/8b640fc093abbb64cbadd7d06820958f4aefde57) and webapp test commit `2490d9feac37dadb0f62bd2d5c7b5761a1008f55` (reviewed October 30, 2026). Later frontend pull-request activity is described separately. This document does not claim that the deployed Lambda, API Gateway stage, database contents, or live dashboard were independently verified.

---

## 1. What the tab reports

The Volunteers view presents two different cuts of volunteer registration data:

- **Volunteer Activity Trend:** registration counts grouped by sign-up period, with New, Active, and Total series in the reviewed backend/frontend snapshot.
- **Volunteers by Location:** distinct volunteer counts grouped by country.

The tab is a view of the registered volunteer population. The supplied implementation does not calculate volunteer hours, completed assignments, request fulfilment, or engagement during a reporting period.

The reviewed UI places the two charts in the Application Analytics → Volunteers view. The trend and location charts have independent period controls.

## 2. What an administrator does

1. Open the Super Admin Dashboard.
2. Navigate to Analytics, then Application Analytics, and select Volunteers.
3. The frontend requests analytics with an empty JSON payload (`{}`).
4. The backend prepares the standard period results for 7D, 30D, 1Y, and All, and includes an empty Custom result in the standard response.
5. Both charts initially display the All period in the reviewed frontend implementation.
6. Selecting 7D, 30D, or 1Y changes the displayed period using the data already returned by the initial request.
7. Selecting Custom exposes date inputs. Once both dates for that chart are supplied, the frontend makes a separate request for that chart's date range.
8. The chart expand control opens a larger chart view; it does not itself require another analytics query.

The activity chart and location chart maintain separate period selections and send different custom-date parameter names.

### Custom request payloads

| Chart | Request fields |
|---|---|
| Activity trend | `start_date`, `end_date` |
| Location | `location_start_date`, `location_end_date` |

The handler checks the activity custom-date pair before the location pair. If a request contains both pairs, the activity branch is selected first.

## 3. Charts and filters

### 3.1 Activity trend

The backend response contains three arrays:

- `new_volunteers`
- `active_volunteers`
- `total_volunteers`

Each item contains a `period` and a `count`. The frontend combines the arrays by period to construct the chart dataset.

The reviewed frontend snapshot displayed New, Active, and Total. The subsequent removal work is described in Section 8; do not assume that the October 30 source snapshot and the later branch state have identical chart series.

### 3.2 Country distribution

The location chart displays volunteer counts by country. The frontend converts country codes to readable country names where its ISO alpha-3 lookup recognizes them, sorts the results by count, and displays the first ten. An unrecognized code is retained as its original value.

The backend location query can return country-level results; the state/city tables and location-related constants are not used by the supplied query implementation.

### 3.3 Period windows

| Selection | Backend date condition | Trend bucket |
|---|---|---|
| 7D | `created_at >= CURRENT_DATE - INTERVAL '7 days'` | Daily |
| 30D | `created_at >= CURRENT_DATE - INTERVAL '30 days'` | Daily |
| 1Y | `created_at >= CURRENT_DATE - INTERVAL '1 year'` | Monthly |
| All | No lower date condition | Monthly |
| Custom | Date range supplied by the caller | Daily |

The date predicates use the database's `CURRENT_DATE`. The reviewed code does not apply a viewer-specific timezone conversion. The fixed windows have a lower bound but no explicit upper bound.

### 3.4 Backend parameters not exposed as chart controls

The handler reads the following request fields for the location query:

| Parameter | Default | Behavior in the supplied Lambda |
|---|---|---|
| `country` | `All Countries` | When not the sentinel value, filters on `UPPER(country_code) = supplied value`. |
| `skill` | `All Skills` | When not the sentinel value, keeps users with a matching `help_categories.cat_name` through `user_skills`. |
| `chart_type` | `Bar Chart` | Read by the handler but does not alter the SQL query. |

The reviewed frontend does not send country or skill filter values and does not expose corresponding selectors. The `time_range` and `time_range_location` fields discussed in earlier requirements are not used by the current handler logic described here.

## 4. Data model and query inputs

The Lambda connects to two PostgreSQL schemas:

- `virginia_dev_saayam_rdbms`
- `ireland_dev_saayam_rdbms`

The queries are run against both regions. The principal joins and fields are:

| Table | Fields used | How the query uses them |
|---|---|---|
| `users` | `user_id`, `user_status_id`, `country_id` | User identity, current status, and country reference |
| `volunteer_details` | `user_id`, `created_at` | Identifies volunteer records; `created_at` supplies the registration date |
| `country` | `country_id`, `country_code` | Resolves a user's country code for location aggregation |
| `user_skills` | `user_id`, `cat_id` | Links a user to a skill/category |
| `help_categories` | `cat_id`, `cat_name` | Supplies the category name used by the skill filter |

The trend and location queries join `users` to `volunteer_details` on `user_id`. The country lookup is a left join, allowing a missing country reference to be grouped under `Unknown`.

The skill filter uses an `EXISTS` subquery joining `user_skills` to `help_categories`. The supplied implementation declares constants for state, city, volunteer_locations, and user_locations, but those tables are not part of the current analytics SQL described above.

The database connection configuration is retrieved by `get_db_config()` from encrypted AWS Systems Manager Parameter Store values in `us-east-1`:

- `/dev/saayam/db/Virginia/Analytics/user`
- `/dev/saayam/db/Ireland/Analytics/user`

The source does not hard-code database credentials.

## 5. How the figures are calculated

### New Volunteers

For each period, the query counts distinct `users.user_id` values joined to `volunteer_details` where `volunteer_details.created_at` is not null and falls within the selected window.

### Active Volunteers

The Active query applies the same registration-date cohort condition as New Volunteers and additionally requires:

```sql
users.user_status_id = 1
```

This is a current user-status check applied to users grouped by their registration date. It is not evidence that a volunteer performed work or was active during the selected period. The business meaning of status ID `1` should be confirmed with the owning team.

### Total Volunteers

For 7D, 30D, 1Y, and All, the query calculates a running sum of the period counts within the selected query window:

```sql
SUM(count) OVER (ORDER BY period)
```

For the fixed windows, this running total starts with the first registration bucket in that window; it does not add registrations from before the window.

For Custom, the implementation calculates a baseline count of volunteers registered before the start date, then adds the running sum of registrations within the requested range. Consequently, Custom Total and fixed-window Total do not have the same baseline semantics.

### Volunteers by Location

The location query counts distinct user IDs by:

```sql
COALESCE(country.country_code, 'Unknown')
```

The query can apply the country, skill, and date conditions described in Section 3. It does not apply the Active status condition, so the location count is not restricted to users whose `user_status_id` is `1`.

### Combining Virginia and Ireland

The Lambda obtains results separately from each regional database and merges the returned aggregates in Python:

- Trend series are combined by matching `period` and adding the counts.
- Location results are combined by matching country code and adding the counts.
- The trend merge sorts periods; the location merge combines matching country values. The frontend then sorts location counts and applies the top-ten display limit.

This is aggregation of regional query results. The supplied code does not perform a cross-database identity-level deduplication step.

## 6. Request handling and implementation map

### Backend request behavior

The handler accepts a raw dictionary or an event with a `body` supplied as a dictionary or JSON string. If the body string cannot be parsed as JSON, the parser returns an empty dictionary.

The request handling order is:

| Input | Handler path | Returned data |
|---|---|---|
| Both `start_date` and `end_date` | Activity custom range | Custom trend data; location list is empty |
| Both `location_start_date` and `location_end_date` | Location custom range | Custom location data; trend arrays are empty |
| No complete custom pair | Standard request | 7D, 30D, 1Y, All, and empty Custom bucket |

The Lambda response is an API Gateway-style object containing a status code, CORS headers, and a JSON-encoded body. The frontend service/component reads `data.body ?? data`; whether the deployed API Gateway integration returns a shape that always matches this expectation has not been confirmed from the supplied materials.

### Main backend functions

| Function | Responsibility |
|---|---|
| `lambda_handler` | Establishes regional connections, selects the request path, assembles the response, handles outer errors, and closes resources |
| `parse_event_body` | Normalizes raw dictionaries and API Gateway body values |
| `get_db_config` | Retrieves and parses regional connection settings from SSM |
| `get_grouping` | Chooses daily or monthly grouping and the period format |
| `build_date_filter` | Builds the date predicate and its SQL parameters |
| `get_volunteer_activity_trend` | Runs the New, Active, and Total queries for one database |
| `get_volunteers_by_location` | Runs the country aggregation, with optional country/skill/date conditions |
| `get_volunteer_activity_by_time_range_VI_combined` | Retrieves and combines the two regional trend results |
| `get_volunteer_locations_by_time_range_VI_combined` | Retrieves and combines the two regional location results |
| `merge_periodic_data`, `merge_volunteer_activity_trend`, `merge_volunteer_by_location` | Merge regional aggregates |

### Frontend responsibilities

The reviewed frontend integration uses `getVolunteerApplicationAnalytics(payload)` from the analytics service to call the endpoint. The component:

- stores the response and selected period state for each chart;
- combines trend arrays into chart rows keyed by `period`;
- formats period labels for display;
- maps recognized country codes to country names;
- sorts location data and limits the chart to ten countries;
- renders the charts using Recharts; and
- displays loading, empty-data, and request-error states.

The supplied engineering notes identify `VolunteerAnalytics.test.jsx` as the component test file. The issue discussion reports test coverage, but the exact passing test count depends on which revision is being discussed; see the history below.

## 7. Development trail

The following items were reviewed as part of understanding the feature. They represent different stages of the work and should not be treated as interchangeable evidence of the currently selected implementation.

| Repository item | Contribution to the feature | Review interpretation |
|---|---|---|
| [data #71](https://github.com/saayam-for-all/data/issues/71) | Early exploration of volunteer trends, geographic counts, and ratings using synthetic data and analysis artifacts. | Prototype/research work; not the production Lambda contract. |
| [data #117](https://github.com/saayam-for-all/data/issues/117) | Synthetic data work for `volunteers_assigned` and `volunteer_details`. The issue records commit [`8947e42`](https://github.com/saayam-for-all/data/commit/8947e42). | Historical test-data preparation; does not establish the runtime source for the analytics endpoint. |
| [data #118](https://github.com/saayam-for-all/data/issues/118) | Synthetic data work for `volunteer_applications` and `user_skills`; associated [PR #145](https://github.com/saayam-for-all/data/pull/145) and commits [`53418fa`](https://github.com/saayam-for-all/data/commit/53418fa) and [`42c7e8c`](https://github.com/saayam-for-all/data/commit/42c7e8c). | Historical test-data preparation. |
| [data #151](https://github.com/saayam-for-all/data/issues/151) | Specification and implementation work for the two-region volunteer analytics Lambda, including trend/location queries, optional filters, error handling, and SSM-based credentials. | The issue documents the intended backend scope. The supplied history identifies the selected code as maintainer-authored commits rather than a merged contributor PR. |
| [data #179](https://github.com/saayam-for-all/data/issues/179) | Date filtering and period grouping for the activity and location charts. | The final handler behavior must be read from the selected source revision; some issue-level parameter/helper descriptions do not match the implementation. |
| [data PR #200](https://github.com/saayam-for-all/data/pull/200), [#202](https://github.com/saayam-for-all/data/pull/202), [#204](https://github.com/saayam-for-all/data/pull/204), [#208](https://github.com/saayam-for-all/data/pull/208), [#209](https://github.com/saayam-for-all/data/pull/209), [#217](https://github.com/saayam-for-all/data/pull/217), [#218](https://github.com/saayam-for-all/data/pull/218), [#219](https://github.com/saayam-for-all/data/pull/219), [#221](https://github.com/saayam-for-all/data/pull/221), [#224](https://github.com/saayam-for-all/data/pull/224), [#226](https://github.com/saayam-for-all/data/pull/226), [#229](https://github.com/saayam-for-all/data/pull/229), [#238](https://github.com/saayam-for-all/data/pull/238), [#243](https://github.com/saayam-for-all/data/pull/243) | Date-filter implementation attempts, revisions, reversions, and alternatives associated with the backend work. | The supplied history identifies #202, #218, and #229 as merged and subsequently reverted by #204, #219, and #238 respectively; other listed PRs were not part of the selected final implementation. |
| [data commit `8b640fc`](https://github.com/saayam-for-all/data/commit/8b640fc093abbb64cbadd7d06820958f4aefde57) | Maintainer-uploaded version identified in the supplied review notes as the selected date-filter implementation. | Use this commit when tracing the reviewed backend snapshot; verify the target branch before relying on it for a later deployment. |
| [webapp #1680](https://github.com/saayam-for-all/webapp/issues/1680) | Frontend integration and subsequent discussion of the Volunteers tab, API fields, tests, and removal of New Volunteers. | Primary frontend tracking issue reviewed for this document. |
| [webapp PR #1681](https://github.com/saayam-for-all/webapp/pull/1681) | Replaced the mock-data integration with the analytics API and added independent period controls and country-name conversion. | The supplied history records this PR as merged to `test`. Its PR references should be read alongside #1680 because the issue linkage/title history is not fully consistent. |
| [webapp PR #1683](https://github.com/saayam-for-all/webapp/pull/1683) | Removed the static mock-data fallback. | Confirms that the later integration path no longer relies on that frontend fallback. |
| [webapp PR #1838](https://github.com/saayam-for-all/webapp/pull/1838) | Removed the New Volunteers line and tooltip. | The supplied history places this merge on `features/dashboard-analytics`, not the reviewed `test` snapshot. |
| [webapp PR #1944](https://github.com/saayam-for-all/webapp/pull/1944) | Updated the trend subtitle and addressed the remaining New Volunteers legend presentation. | The supplied issue history records this PR as merged on November 3, 2026. The reviewed October 30 frontend snapshot predates that update. |

### Earlier frontend mock-up work

The supplied example notes identify webapp PRs [#1189](https://github.com/saayam-for-all/webapp/pull/1189), [#1202](https://github.com/saayam-for-all/webapp/pull/1202), and [#1246](https://github.com/saayam-for-all/webapp/pull/1246) as earlier mock-data UI work. The mock JSON filenames recorded there are `src/data/analytics/volunteers_activity_monthly.json` and `src/data/analytics/volunteers_by_location.json`. These are historical frontend artifacts, not proof that the current Lambda reads those JSON files.

## 8. Engineering issues to resolve or keep visible

These points follow from the supplied Lambda, frontend review notes, and issue/PR history. They are not silently corrected in this document.

| Ref | Area | Observation | Why it matters |
|---|---|---|---|
| E1 | Metric definition | Active Volunteers is implemented as current `user_status_id = 1` applied to the registration cohort. | Confirm the business definition and the meaning of status ID `1` in both regional databases. |
| E2 | Total calculation | Fixed windows calculate a running total only within the selected window; Custom adds a pre-range baseline. | Totals are not directly comparable across preset and custom selections. |
| E3 | Regional merge | The merge adds regional aggregates by period/country; it does not deduplicate identities across databases. | Correctness depends on the regional populations and period rows behaving as expected. |
| E4 | Missing periods | The merge does not create zero-count buckets for periods absent from a region. | Combined running totals may be incorrect or non-monotonic when one region has no row for a period. |
| E5 | Custom end boundary | New/Active and location date filters use timestamp `BETWEEN`; the Custom Total calculation uses date casts for its range. | Registrations later on the selected end date may be treated differently by the component calculations. |
| E6 | Date labels | The supplied frontend notes identify period formatting that assumes a year-month value. | Daily values may be labelled as month-level values unless the formatter handles daily strings in the deployed revision. |
| E7 | Custom state | The supplied frontend notes identify a Custom trend response that replaces the stored response with a Custom-only object. | Switching back to a preset may show no data until the page is reloaded. |
| E8 | Optional filters | Country comparison uppercases the database field but uses the supplied value as-is; `chart_type` does not change the query. | Lowercase country input may not match; chart type is currently informational/unused in SQL. |
| E9 | API response envelope | Lambda returns a JSON-string `body`; frontend reads `data.body ?? data`. | Confirm the deployed API Gateway/client response shape, including whether `body` is parsed before the component consumes it. |
| E10 | Query volume | The default request executes four period windows, each with three trend queries and one location query, against two databases: 32 query executions. | Page-load cost and latency may become material as the data grows. |
| E11 | Error visibility | Query-level exceptions are caught and converted to empty arrays; outer failures return a 500 response with the safe empty structure. | A query failure can resemble a legitimate no-data result unless logs/monitoring are checked. |
| E12 | Deployment | The supplied review notes state that the deployment workflow targets a different Lambda path under `data-engineering/src/saayam-org-*`. | Confirm which artifact is actually deployed and whether it matches the reviewed analytics Lambda. |
| E13 | Data environment | The supplied review notes report historical database reset/mock-data discussion, but no live database inspection was performed for this documentation. | Do not describe current dashboard counts as production or real volunteer activity without confirmation. |
| E14 | Location coverage | The current query aggregates by country; state/city/location constants are not queried. | State/city drill-down should not be represented as an implemented feature. |

## 9. Items requiring confirmation

The following questions remain open based on the materials supplied for this review:

1. Does the deployed Lambda match commit `8b640fc`, and which API Gateway stage does the webapp call?
2. Are the Virginia and Ireland volunteer populations guaranteed to be disjoint, and are their database date/time settings aligned?
3. Is `user_status_id = 1` formally defined as Active in both environments?
4. What country-code format is stored in both `country.country_code` columns, and is it consistently ISO alpha-3 as expected by the frontend conversion?
5. Should preset Total represent a window-only running count or the all-time cumulative volunteer count?
6. Should the two custom date endpoints include the full end date consistently across New, Active, Total, and Location?
7. Should the backend return `new_volunteers` after the frontend removal work, or should the API contract be changed in a coordinated backend/frontend update?
8. Is the `Custom` key required in the standard response when no custom range has been requested?
9. Should query-level failures be returned distinctly from a valid empty result?
10. Is the 32-query default request acceptable, or should the query strategy be consolidated or cached?

## 10. Source references

### Data repository

- [Issue #71 — volunteer trend analysis](https://github.com/saayam-for-all/data/issues/71)
- [Issue #117 — volunteer synthetic data](https://github.com/saayam-for-all/data/issues/117)
- [Issue #118 — application and skill synthetic data](https://github.com/saayam-for-all/data/issues/118)
- [Issue #151 — volunteer analytics backend](https://github.com/saayam-for-all/data/issues/151)
- [Issue #179 — date filtering](https://github.com/saayam-for-all/data/issues/179)
- [Issue #605 — documentation tracking](https://github.com/saayam-for-all/data/issues/605)
- [Backend Lambda source](https://github.com/saayam-for-all/data/blob/main/data-analytics/lambda_functions/volunteer_application_analytics.py)
- [Backend Lambda commit history](https://github.com/saayam-for-all/data/commits/main/data-analytics/lambda_functions/volunteer_application_analytics.py)
- [Database column reference workbook](https://github.com/saayam-for-all/data/blob/main/database/Saayam_Table.column.names_data.xlsx)

### Web application repository

- [Issue #1680 — Volunteers tab integration and updates](https://github.com/saayam-for-all/webapp/issues/1680)
- [PR #1681 — API integration](https://github.com/saayam-for-all/webapp/pull/1681)
- [PR #1683 — mock fallback removal](https://github.com/saayam-for-all/webapp/pull/1683)
- [PR #1838 — New Volunteers series removal](https://github.com/saayam-for-all/webapp/pull/1838)
- [PR #1944 — chart subtitle / legend follow-up](https://github.com/saayam-for-all/webapp/pull/1944)
- [VolunteerAnalytics.jsx](https://github.com/saayam-for-all/webapp/blob/dev/src/pages/Dashboard/components/Analytics/VolunteerAnalytics.jsx)
- [SuperAdminDashboard.jsx](https://github.com/saayam-for-all/webapp/blob/dev/src/pages/Dashboard/views/SuperAdminDashboard.jsx)

---

**Review boundary:** This document records behavior and history supported by the source material supplied for the task. It is not a live deployment verification, a database audit, or a sign-off on the business definitions listed in Section 9.
