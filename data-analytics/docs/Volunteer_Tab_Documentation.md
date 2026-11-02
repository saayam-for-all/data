# Volunteer Tab Documentation

**Super Admin Dashboard -> Analytics -> Application Analytics -> Volunteers**

| | |
|---|---|
| Tracking issue | [data#605](https://github.com/saayam-for-all/data/issues/605) |
| Backend | [`data-analytics/lambda_functions/volunteer_application_analytics.py`](https://github.com/saayam-for-all/data/blob/main/data-analytics/lambda_functions/volunteer_application_analytics.py) (`data` repo) |
| Frontend | [`src/pages/Dashboard/components/Analytics/VolunteerAnalytics.jsx`](https://github.com/saayam-for-all/webapp/blob/dev/src/pages/Dashboard/components/Analytics/VolunteerAnalytics.jsx) (`webapp` repo, `dev` branch) |
| API endpoint | `POST v1/ml/volunteerApplicationAnalytics` (AWS Lambda) |
| Reviewed as of | 1 November 2026: backend at commit [`8b640fc`](https://github.com/saayam-for-all/data/commit/8b640fc093abbb64cbadd7d06820958f4aefde57), identical on `main`, `test` and `dev` |

Anything unclear or inconsistent is listed in [Section 9](#9-open-questions-and-flags) with an ID (F1, F2, ...) so it can be followed up.

---

## 1. Purpose

The Volunteers tab gives Super Admins a view of how Saayam's volunteer base is growing and where volunteers are located. It answers three questions:

1. How many volunteers joined in a given period?
2. How many registered volunteers are currently active, and how has the total grown?
3. Which countries have the most volunteers?

It is one of four Application Analytics tabs (Requests, KPI, Beneficiaries, Volunteers). Each tab has its own Lambda in `data-analytics/lambda_functions/`.

---

## 2. Features

The tab has two charts side by side. Each chart has its own period filter.

### 2.1 Volunteer Activity Trend (line chart)

| Series | Colour | Meaning (see [Section 5](#5-metrics-and-calculations)) |
|---|---|---|
| Active Volunteers | Green | Volunteers with active user status, by sign-up period |
| New Volunteers | Orange | Volunteers who signed up in each period. Being removed: see [Section 9](#9-open-questions-and-flags), F1 |
| Total Volunteers | Blue | Running total of sign-ups |

- Tooltip shows New, Active and Total for the hovered period.
- Subtitle: "New, active, and total volunteers over time". Changing it to "Active and total volunteers over time" is in progress in [webapp#1944](https://github.com/saayam-for-all/webapp/pull/1944).
- The expand icon opens the chart larger (shared `ChartContainer` component).

### 2.2 Volunteers by Location (horizontal bar chart)

- Shows volunteer count per country, top 10 only (subtitle: "Top 10 countries by volunteer count").
- Country codes from the API are converted to names in the browser with `isoAlpha3ToName()`. A code that can't be converted is shown as-is.

---

## 3. User Flow

```
Super Admin logs in
  -> Super Admin Dashboard -> Analytics tab -> Application Analytics -> Volunteers
      -> On load, the UI calls the API with an empty body: {}
          -> Lambda queries the Virginia + Ireland DBs for 7D, 30D, 1Y, All
          -> Returns all four windows in one response (plus an empty "Custom")
      -> Both charts default to "All"
      -> Clicking 7D / 30D / 1Y / All only switches which part of that response is shown (no new API call)
      -> Clicking "Custom" shows two date pickers
          -> Once both dates are picked, a new API call is made:
              Trend chart:    { "start_date": "...", "end_date": "..." }
              Location chart: { "location_start_date": "...", "location_end_date": "..." }
```

UI states: "Loading volunteer data..." while loading; "No data available for the selected period." when a series is empty; a yellow "Could not load data. Please try again later." banner when the request fails.

---

## 4. Filters

### 4.1 Period filters (used by the UI)

Each chart has its own filter, as required by [data#179](https://github.com/saayam-for-all/data/issues/179).

| Button | Backend window (`build_date_filter`) | Trend grouping (`get_grouping`) | Period format |
|---|---|---|---|
| 7D | `vd.created_at >= CURRENT_DATE - INTERVAL '7 days'` | Daily | `YYYY-MM-DD` |
| 30D | `vd.created_at >= CURRENT_DATE - INTERVAL '30 days'` | Daily | `YYYY-MM-DD` |
| 1Y | `vd.created_at >= CURRENT_DATE - INTERVAL '1 year'` | Monthly | `YYYY-MM` |
| All | No filter | Monthly | `YYYY-MM` |
| Custom | `vd.created_at BETWEEN start AND end` | Daily | `YYYY-MM-DD` |

The location chart is filtered by date only; it is never grouped by period.

### 4.2 Location filters (backend only, not used by the UI)

The Lambda accepts these in the request body, as specified in [data#151](https://github.com/saayam-for-all/data/issues/151). The current UI never sends them, so the defaults always apply.

| Parameter | Default | Effect |
|---|---|---|
| `country` | `"All Countries"` | Keeps only rows where `UPPER(country.country_code) = <value>` |
| `skill` | `"All Skills"` | Keeps only volunteers who have a `user_skills` row whose `help_categories.cat_name = <value>` |
| `chart_type` | `"Bar Chart"` | Accepted but not used in any query |

---

## 5. Metrics and Calculations

All counts use `COUNT(DISTINCT u.user_id)` over `users u JOIN volunteer_details vd ON u.user_id = vd.user_id`, with `vd.created_at` as the volunteer sign-up date.

| Metric | Calculation | Notes |
|---|---|---|
| New Volunteers | Distinct volunteers per period, by `vd.created_at` | |
| Active Volunteers | Same as New, plus `u.user_status_id = 1` | A volunteer's current status, grouped by sign-up period. This does not measure activity during the period. See F4. |
| Total Volunteers (7D / 30D / 1Y / All) | `SUM(count) OVER (ORDER BY period)` over the filtered window | Running total within the window only. For 7D/30D/1Y it starts from 0, not from the true all-time total. See F3. |
| Total Volunteers (Custom) | `base_count + SUM(count) OVER (ORDER BY period)`, where `base_count` = volunteers who signed up before `start_date` | A true running total |
| Volunteers by Location | Distinct volunteers grouped by `COALESCE(country.country_code, 'Unknown')`, ordered by count | Uses `LEFT JOIN country`, so volunteers with no country show up as `Unknown` |

### Combining the two regions

The Lambda runs every query against both the Virginia and Ireland databases and merges the results in Python:

- Trend (`merge_periodic_data`): adds counts that share the same `period` and sorts by period.
- Location (`merge_volunteer_by_location`): adds counts that share the same country, then sorts alphabetically by country. The frontend re-sorts by count and keeps the top 10.

Note (F5): adding *running totals* period by period is only correct when both regions have a row for every period. If one region had no sign-ups in a period, its running total is missing for that period, so the combined Total dips.

---

## 6. Data Sources

| Table | Columns used | Role |
|---|---|---|
| `users` | `user_id`, `user_status_id`, `country_id` | Volunteer identity, active status, country |
| `volunteer_details` | `user_id`, `created_at` | Marks a user as a volunteer; `created_at` is the sign-up date |
| `country` | `country_id`, `country_code` | Location chart |
| `user_skills` | `user_id`, `cat_id` | Skill filter |
| `help_categories` | `cat_id`, `cat_name` | Skill filter |

Schemas: `virginia_dev_saayam_rdbms.*` and `ireland_dev_saayam_rdbms.*` (AWS RDS PostgreSQL). The table reference is in [`Saayam_Table.column.names_data.xlsx`](https://github.com/saayam-for-all/data/blob/main/database/Saayam_Table.column.names_data.xlsx).

`state`, `city`, `volunteer_locations` and `user_locations` are declared as constants but not used yet. They are there for the state/city drill-down planned in data#151.

Credentials: `get_db_config()` reads the connection string from AWS SSM Parameter Store (`/dev/saayam/db/{Virginia|Ireland}/Analytics/user`, region `us-east-1`, decrypted). None are hard-coded, which meets the security phase of data#151.

Current data: after a database reset, the API returned no data for a while ([webapp#1680](https://github.com/saayam-for-all/webapp/issues/1680), 24 Aug 2026). The Data Engineering team added mock data in late September 2026, so current dashboard numbers are mock data, not real volunteer activity.

---

## 7. Implementation

### 7.1 Request / response contract

Request types (the handler checks them in this order):

| Body | Response |
|---|---|
| Has both `start_date` and `end_date` | `{ "Custom": { trend for the range, "volunteers_by_location": [] } }` |
| Has both `location_start_date` and `location_end_date` | `{ "Custom": { empty trend, location for the range } }` |
| Anything else, e.g. `{}` | `{ "7D": ..., "30D": ..., "1Y": ..., "All": ..., "Custom": <empty> }` |

A body that has both custom date pairs only gets the trend result, because the trend check runs first.

Shape of each window:

```json
{
  "volunteer_activity_trend": {
    "new_volunteers":    [{ "period": "2026-05", "count": 3 }],
    "active_volunteers": [{ "period": "2026-05", "count": 2 }],
    "total_volunteers":  [{ "period": "2026-05", "count": 41 }]
  },
  "volunteers_by_location": [{ "country": "USA", "count": 300 }]
}
```

The Lambda returns `statusCode`, CORS headers and `body` (a JSON string). The frontend reads `apiData.body ?? apiData`.

### 7.2 Backend function map

| Function | Purpose |
|---|---|
| `lambda_handler` | Opens both DB connections, picks the request type, builds the response, handles errors, closes connections in `finally` |
| `parse_event_body` | Accepts an API Gateway event (`body` as a string or dict) or a raw dict |
| `get_volunteer_activity_by_time_range_VI_combined` | Runs the trend queries on both regions and merges them |
| `get_volunteer_locations_by_time_range_VI_combined` | Runs the location query on both regions and merges them |
| `get_grouping` | Time range -> (`day`/`month`, date format) |
| `build_date_filter` | Time range -> SQL `WHERE` fragment and parameters (one helper shared by both charts) |
| `get_volunteer_activity_trend` | The three trend queries (new, active, total) |
| `get_volunteers_by_location` | Location query with optional country and skill filters |
| `merge_periodic_data` / `merge_volunteer_activity_trend` / `merge_volunteer_by_location` | Combine Virginia and Ireland results |
| `get_db_config` | Reads and parses the SSM connection parameter |

Error handling: a connection or unexpected error returns `statusCode 500` with a body where every window has empty lists. An error inside a single query is logged and returns empty lists for that part, while the overall response stays `200`.

Cost of the default call: a `{}` request runs 4 windows x 2 regions x 4 queries (3 trend + 1 location) = 32 queries on every page load.

### 7.3 Frontend

- Service: `getVolunteerApplicationAnalytics(payload)` in `src/services/analyticsServices.js`, which POSTs to `endpoints.VOLUNTEER_APPLICATION_ANALYTICS`.
- `parseTrendData()` merges the three series into one Recharts dataset keyed by `period` and labels each point with `formatPeriod()`.
- `parseLocationData()` converts country codes to names, sorts by count and keeps the top 10 (`.slice(0, 10)`).
- Charts are built with Recharts (`LineChart`, `BarChart`).
- Tests: `VolunteerAnalytics.test.jsx` (15 tests, according to webapp#1680 comments).

### 7.4 Development history

| # | Repo | Type | What it did | Outcome |
|---|---|---|---|---|
| [#30](https://github.com/saayam-for-all/data/issues/30) | data | Issue | Original epic: analytics for requestors and volunteers (counts, locations) | Open (umbrella) |
| [#71](https://github.com/saayam-for-all/data/issues/71) | data | Issue | Trend analysis for volunteers: counts by period, country/region and rating, built on synthetic data in notebooks/PDF (attached in comments) | Closed 23 Sep 2026. The prototype analysis behind the charts |
| [#117](https://github.com/saayam-for-all/data/issues/117), [#118](https://github.com/saayam-for-all/data/issues/118) | data | Issues | Synthetic CSVs for `volunteer_details`, `volunteers_assigned`, `volunteer_applications` and `user_skills` (used in the `sql/` folder for local testing) | Closed |
| [#151](https://github.com/saayam-for-all/data/issues/151) | data | Issue | Build the real Lambda: Virginia + Ireland, trend + location, country/skill/chart_type filters, empty-data and error handling, SSM credentials, deploy | Closed 22 Sep 2026. Code written by the issue owner and maintainer (commits `9292b64`...`c7e6311`, Apr-Jun 2026). No contributor PR was merged |
| [#179](https://github.com/saayam-for-all/data/issues/179) | data | Issue | Separate date filters for both charts, daily/monthly grouping, `period` instead of `month` key | Closed 22 Sep 2026. See below |
| PRs [#202](https://github.com/saayam-for-all/data/pull/202), [#218](https://github.com/saayam-for-all/data/pull/218), [#229](https://github.com/saayam-for-all/data/pull/229) | data | PRs | Contributor date-filter versions | Merged, then reverted ([#204](https://github.com/saayam-for-all/data/pull/204), [#219](https://github.com/saayam-for-all/data/pull/219), [#238](https://github.com/saayam-for-all/data/pull/238)) |
| `8b640fc` | data | Commit | "Add files via upload": final date-filter version uploaded by a maintainer on 26 Jul 2026 | This is the current code |
| [#1680](https://github.com/saayam-for-all/webapp/issues/1680) | webapp | Issue | Connect the Volunteers tab to the Data Analytics API; later: remove "New Volunteers" | Open; listed as a blocker on [ba#17](https://github.com/saayam-for-all/ba/issues/17) |
| [#1681](https://github.com/saayam-for-all/webapp/pull/1681) | webapp | PR | Replaced mock JSON with the live API; separate period filters; ISO alpha-3 -> country names; 7 tests | Merged to `test` 20 Jul 2026 |
| [#1683](https://github.com/saayam-for-all/webapp/pull/1683) | webapp | PR | Removed the static mock-data fallback | Merged |
| [#1838](https://github.com/saayam-for-all/webapp/pull/1838) | webapp | PR | Removed the "New Volunteers" line and tooltip | Merged to `features/dashboard-analytics` (not `test`/`dev`) 27 Sep 2026 |
| [#1944](https://github.com/saayam-for-all/webapp/pull/1944) | webapp | PR | Subtitle -> "Active and total volunteers over time" | Open. Reviewer (1 Nov) says the orange "New Volunteers" legend label still needs removing |

Earlier UI work (mock-data version, Jan-Feb 2026) was done by Mustafa Ahmed in webapp PRs [#1189](https://github.com/saayam-for-all/webapp/pull/1189), [#1202](https://github.com/saayam-for-all/webapp/pull/1202) and [#1246](https://github.com/saayam-for-all/webapp/pull/1246). Mock JSON files remain in `src/data/analytics/volunteers_activity_monthly.json` and `volunteers_by_location.json`.

### 7.5 Local testing

From data#179: install `psycopg2-binary` and `pandas`, then run `python volunteer_application_analytics.py` (the `__main__` block calls the handler with `{}`). The issue says to use the CSVs in `data-analytics/sql/` and to change the connection code for local runs. Test cases are in [`Test Cases and Acceptance Criteria.docx`](https://github.com/saayam-for-all/data/blob/main/data-analytics/lambda_functions/Test%20Cases%20and%20Acceptance%20Criteria.docx).

---

## 8. Known Limitations

1. The trend chart has no country or skill breakdown. The location chart's country/skill filters exist in the backend but not in the UI.
2. Location is country-level only. State/city drill-down was planned (data#151) but not built.
3. Periods with no sign-ups are skipped rather than returned with a count of 0, so daily charts have gaps that the line chart bridges.
4. The top-10 cut is done in the browser. The backend returns every country.
5. Every page load runs 32 queries across two regions, with no caching.
6. `get_db_config()` reads the SSM value by fixed line positions and character offsets. Any change to that parameter's format will break the connection.
7. The `ValueError` message in `get_grouping()` lists the valid ranges but leaves out `'All'`, though `'All'` is handled.

---

## 9. Open Questions and Flags

| ID | Area | Issue | Where | Who to ask |
|---|---|---|---|---|
| F1 | Backend <-> Frontend | The "New Volunteers" removal is out of sync. The frontend team says `new_volunteers` "is removed" from the API response, but the backend on `main`/`test`/`dev` still returns it. The line-removal PR #1838 is on `features/dashboard-analytics`, so `dev`/`test` still draw the line and legend. | `lambda_handler()` default response; `get_volunteer_activity_trend()` | Data Analytics + webapp#1680 assignee |
| F2 | Spec vs. code | The shipped contract differs from the #179 spec. The spec asked for `time_range` / `time_range_location` parameters and two helpers (`build_date_filter_trend`, `build_date_filter_location`). The code has one `build_date_filter`, ignores `time_range`, and returns all windows for `{}`. The frontend follows the code, so it works, but the closed issue doesn't describe it. | data#179 body vs. `lambda_handler()` | Issue owner (confirm which is correct) |
| F3 | Metric | "Total Volunteers" for 7D/30D/1Y is a running total within the window, not the true total. It starts at 0 at the start of the window. Custom does add the earlier total (`base_count`), so the presets and Custom behave differently. | Total query in `get_volunteer_activity_trend()` | Data Analytics |
| F4 | Metric | "Active Volunteers" is not defined anywhere. It is counted as current `user_status_id = 1`, grouped by sign-up date. It is not "volunteers active in the period" (e.g. assigned to a request). Also needs confirmation that status `1` means Active in both regions. | Active query in `get_volunteer_activity_trend()` | Product / issue owner |
| F5 | Calculation | Merging the two regions can make Total dip. Running totals are added only for periods where both regions have a row. | `merge_periodic_data()` | Data Analytics |
| F6 | Calculation | The Custom end date is handled inconsistently. The New/Active queries use `vd.created_at BETWEEN start AND end` on a timestamp, which drops sign-ups after 00:00 on the end date. The Total query casts to `::date` and includes the whole day. | `build_date_filter()` vs. the Custom total query | Data Analytics |
| F7 | Frontend | Daily periods are mislabelled. `formatPeriod()` assumes `YYYY-MM`, so every daily point in 7D/30D/Custom gets a month label (e.g. "May 2026"). | `formatPeriod()` in VolunteerAnalytics.jsx | webapp |
| F8 | Frontend | Custom breaks the preset buttons. A Custom trend request replaces the stored response with one that has only a `Custom` key, so switching back to 7D/30D/1Y/All shows "No data" until the page is reloaded. | Custom trend `useEffect` in VolunteerAnalytics.jsx | webapp |
| F9 | Backend | `country` filter case: the SQL compares `UPPER(country_code)` to the value as sent, without upper-casing it, so lower-case input matches nothing. `chart_type` is accepted but does nothing. Neither is sent by the UI. | `get_volunteers_by_location()` | Data Analytics |
| F10 | Data | Country code format is undocumented. The UI expects ISO alpha-3 codes for `isoAlpha3ToName()`, while the #179 example response shows values like `UNITED_STATES_OF_AMERICA`. Needs confirmation of what `country.country_code` holds in both databases. | data#179 example; `parseLocationData()` in VolunteerAnalytics.jsx | Data Engineering |
| F11 | Response shape | The default response always includes an empty `Custom` key. Issue [data#506](https://github.com/saayam-for-all/data/issues/506) removed this pattern from the Rating & Type Lambda; it hasn't been decided whether the Volunteer Lambda should match. | `lambda_handler()` default response | Data Analytics |
| F12 | Traceability | The frontend PRs #1681 and #1683 reference webapp#1589 (Requests tab) instead of #1680 (Volunteers tab). The final #179 code was uploaded directly (`8b640fc`) rather than through a PR, so there is no review record for it. | PR titles; commit log | - |
| F13 | Deployment | Not confirmed whether the deployed Lambda matches commit `8b640fc`, or which API Gateway stage the webapp points to. | - | DevOps / issue owner |

---

## 10. References

data repo: [#30](https://github.com/saayam-for-all/data/issues/30) | [#71](https://github.com/saayam-for-all/data/issues/71) | [#117](https://github.com/saayam-for-all/data/issues/117) | [#118](https://github.com/saayam-for-all/data/issues/118) | [#151](https://github.com/saayam-for-all/data/issues/151) | [#179](https://github.com/saayam-for-all/data/issues/179) | [#506](https://github.com/saayam-for-all/data/issues/506) | [#605](https://github.com/saayam-for-all/data/issues/605) | [commit history of the Lambda](https://github.com/saayam-for-all/data/commits/main/data-analytics/lambda_functions/volunteer_application_analytics.py)

webapp repo: [#1680](https://github.com/saayam-for-all/webapp/issues/1680) | [#1681](https://github.com/saayam-for-all/webapp/pull/1681) | [#1683](https://github.com/saayam-for-all/webapp/pull/1683) | [#1838](https://github.com/saayam-for-all/webapp/pull/1838) | [#1944](https://github.com/saayam-for-all/webapp/pull/1944) | [VolunteerAnalytics.jsx](https://github.com/saayam-for-all/webapp/blob/dev/src/pages/Dashboard/components/Analytics/VolunteerAnalytics.jsx) | [SuperAdminDashboard.jsx](https://github.com/saayam-for-all/webapp/blob/dev/src/pages/Dashboard/views/SuperAdminDashboard.jsx)

Related: [ba#17](https://github.com/saayam-for-all/ba/issues/17) (Super Admin Dashboard tracking) | [Table schema reference](https://github.com/saayam-for-all/data/blob/main/database/Saayam_Table.column.names_data.xlsx)
