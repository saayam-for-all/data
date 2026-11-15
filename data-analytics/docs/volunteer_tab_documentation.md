# Volunteer Tab — Application Analytics (Super Admin Dashboard)

**Issue:** [#605 — Document Application Analytics Flow and Implementation: Volunteer Dashboard](https://github.com/saayam-for-all/data/issues/605)
**Backend file:** [`data-analytics/lambda_functions/volunteer_application_analytics.py`](https://github.com/saayam-for-all/data/blob/main/data-analytics/lambda_functions/volunteer_application_analytics.py)
**Frontend task:** [webapp #1680 — Application Analytics: Volunteers tab](https://github.com/saayam-for-all/webapp/issues/1680)
**Last reviewed:** October 2026

> Code behaviour in this document was read from a `main` branch snapshot of `volunteer_application_analytics.py` taken on Sep 30, 2026.

---

## Contents

1. [Purpose](#1-purpose)
2. [Features](#2-features)
3. [User flow](#3-user-flow)
4. [Filters and request payload](#4-filters-and-request-payload)
5. [Data sources](#5-data-sources)
6. [Metrics and calculations](#6-metrics-and-calculations)
7. [Reference links](#7-reference-links)

---

## 1. Purpose

The Volunteer tab gives Super Admins a view of how Saayam's volunteer base is growing and where volunteers are located. It answers three questions:

- How many volunteers joined in a given period?
- How many of those volunteers are currently active?
- Which countries do volunteers come from, optionally narrowed to a skill?

It is one of the tabs under **Super Admin Dashboard → Application Analytics**, alongside the Requests and Beneficiaries tabs.

## 2. Features

The tab has two widgets, both served by a single Lambda.

| Widget | Chart | What it shows |
|---|---|---|
| **Volunteer Activity Trend** | Line chart over time. Subtitle: "New, active, and total volunteers over time" | Active volunteers and cumulative total volunteers per day or month |
| **Volunteers by Location** | Horizontal bar chart. Subtitle: "Top 10 countries by volunteer count" | Volunteer count per country, largest first, with full country names |

Each card has its own `7D / 30D / 1Y / All / Custom` buttons (labelled "Period" on the location card) and an expand icon. On the test site the Volunteers by Location card shows no country, skill or chart-type controls, although the API supports them.

The API also returns a `new_volunteers` series. [webapp PR #1838](https://github.com/saayam-for-all/webapp/pull/1838) removed it from the chart, but on the test site the trend card's subtitle and legend still list "New Volunteers". The tooltip shows `New: —` for every month, so the series is kept in the chart but receives no values.

Several display behaviours come from the frontend rather than the API: limiting the location chart to the top 10 countries, sorting countries by count, and turning country codes (for example `USA`) into names (for example "United States").

## 3. User flow

1. The Super Admin opens the dashboard (test environment: [https://test-saayam.netlify.app/dashboard?view=superAdmin](https://test-saayam.netlify.app/dashboard?view=superAdmin), which requires signing in with a Super Admin account), selects **Super Admin Dashboard** from the dashboard dropdown, then **Analytics → Application Analytics → Volunteers**. The other Application Analytics sub-tabs are Requests, KPI and Beneficiaries.
2. The frontend calls the volunteer analytics API with an empty payload (`{}`).
3. The API returns all four fixed time buckets (`7D`, `30D`, `1Y`, `All`) in one response, plus an empty `Custom` bucket.
4. When the admin switches between 7D / 30D / 1Y / All, the frontend shows the matching bucket from the response it already has. No new call is needed.
5. When the admin picks a custom date range, the frontend sends a new call with the date pair, and the API returns only the `Custom` bucket.
6. The API also accepts country and skill filters for the location widget, but the test site does not show controls for them.
7. When a bucket is empty, the frontend shows "No data available for the selected period" ([webapp #1518](https://github.com/saayam-for-all/webapp/issues/1518) refers to the Volunteers tab as the reference for this behaviour).

On the test site, each Volunteers chart card has its own row of `7D / 30D / 1Y / All / Custom` buttons, so the two charts can show different ranges. This matches the API's separate date pairs for each widget. With `All` selected, the trend chart shows monthly points from Jun 2025 to Aug 2026, a total line rising to about 400, and an active line of roughly 20–30 per month. The location chart shows three countries: United States (about 300), India (about 75) and United Kingdom (about 20).

Steps 4–6 describe how the response is designed to be used. The exact frontend calling pattern and the API Gateway route are not documented in the data repo.

## 4. Filters and request payload

### 4.1 Payload keys read by the Lambda

| Key | Applies to | Default | Notes |
|---|---|---|---|
| `start_date` | Activity Trend | none | Custom range start (`YYYY-MM-DD`). Only used when `end_date` is also present. |
| `end_date` | Activity Trend | none | Custom range end. |
| `location_start_date` | Volunteers by Location | none | Custom range start for the location widget. |
| `location_end_date` | Volunteers by Location | none | Custom range end for the location widget. |
| `country` | Volunteers by Location | `"All Countries"` | Matched against `country.country_code` (for example `USA`). |
| `skill` | Volunteers by Location | `"All Skills"` | Matched against `help_categories.cat_name` (for example `FOOD_AND_ESSENTIALS`). |
| `chart_type` | Volunteers by Location | `"Bar Chart"` | Accepted and passed through, but not used in any query. |

The payload can arrive as the event itself or as a JSON string in `event["body"]` (API Gateway proxy format). `parse_event_body()` handles both.

### 4.2 Time ranges

| Range | Window (on `volunteer_details.created_at`) | Trend grouping | Period format |
|---|---|---|---|
| `7D` | `>= CURRENT_DATE - 7 days` | Daily | `YYYY-MM-DD` |
| `30D` | `>= CURRENT_DATE - 30 days` | Daily | `YYYY-MM-DD` |
| `1Y` | `>= CURRENT_DATE - 1 year` | Monthly | `YYYY-MM` |
| `All` | No filter | Monthly | `YYYY-MM` |
| `Custom` | `BETWEEN start AND end` | Daily | `YYYY-MM-DD` |

The Volunteers by Location widget uses the same windows but never groups by date.

### 4.3 Which payload returns what

| Payload | Response contains |
|---|---|
| `{}` or only `country` / `skill` | `7D`, `30D`, `1Y`, `All` (both widgets filled) and an empty `Custom` |
| `start_date` + `end_date` | Only `Custom`, with Activity Trend filled and `volunteers_by_location: []` |
| `location_start_date` + `location_end_date` | Only `Custom`, with Volunteers by Location filled and an empty trend |
| Both date pairs | Same as the trend-only case. The location pair is ignored. |

### 4.4 Example

Request:

```json
{ "country": "USA", "skill": "FOOD_AND_ESSENTIALS" }
```

Response body (shape only):

```json
{
  "7D":  { "volunteer_activity_trend": { "new_volunteers": [], "active_volunteers": [], "total_volunteers": [] },
           "volunteers_by_location": [] },
  "30D": { "...": "same shape" },
  "1Y":  { "volunteer_activity_trend": {
             "new_volunteers":    [{ "period": "2026-01", "count": 4 }],
             "active_volunteers": [{ "period": "2026-01", "count": 3 }],
             "total_volunteers":  [{ "period": "2026-01", "count": 4 }] },
           "volunteers_by_location": [{ "country": "USA", "count": 7 }] },
  "All": { "...": "same shape" },
  "Custom": { "volunteer_activity_trend": { "new_volunteers": [], "active_volunteers": [], "total_volunteers": [] },
              "volunteers_by_location": [] }
}
```

The response always carries CORS headers (`Access-Control-Allow-Origin: *`, methods `GET,POST,OPTIONS`).

## 5. Data sources

### 5.1 Databases

The Lambda reads from two PostgreSQL databases and adds the results together:

| Region | Schema | SSM parameter |
|---|---|---|
| Virginia (us-east-1) | `virginia_dev_saayam_rdbms` | `/dev/saayam/db/Virginia/Analytics/user` |
| Ireland (eu-west-1) | `ireland_dev_saayam_rdbms` | `/dev/saayam/db/Ireland/Analytics/user` |

### 5.2 Tables and columns used

| Table | Columns used | Purpose |
|---|---|---|
| `users` | `user_id`, `user_status_id`, `country_id` | Volunteer identity, active status, country |
| `volunteer_details` | `user_id`, `created_at` | Marks a user as a volunteer; `created_at` is the date used for every time filter |
| `country` | `country_id`, `country_code` | Country label for the location widget |
| `user_skills` | `user_id`, `cat_id` | Links a volunteer to skills |
| `help_categories` | `cat_id`, `cat_name` | Skill name used by the skill filter |
| `user_status` (lookup only) | `user_status_id = 1` → `ACTIVE` | Meaning of the active check ([lookup](https://github.com/saayam-for-all/data/blob/main/database/lookup_tables/user_status.csv)) |

`state`, `city`, `volunteer_locations` and `user_locations` are declared as table constants in the file but are not queried.

### 5.3 Joins

```
users u
  JOIN volunteer_details vd ON u.user_id = vd.user_id         -- base join (all queries)
  LEFT JOIN country c       ON u.country_id = c.country_id    -- location widget
  EXISTS (user_skills us JOIN help_categories h ON us.cat_id = h.cat_id
          WHERE us.user_id = u.user_id AND h.cat_name = :skill) -- skill filter
```

Schema reference: [`database/Saayam_Table.column.names_data.xlsx`](https://github.com/saayam-for-all/data/blob/main/database/Saayam_Table.column.names_data.xlsx).

### 5.4 Local test data

- `data-analytics/sql/*.csv` — exports used for local testing in #179.
- `data-analytics/mock-data-generation/` — synthetic CSVs for 10 tables from [#301](https://github.com/saayam-for-all/data/issues/301) / [PR #314](https://github.com/saayam-for-all/data/pull/314).

## 6. Metrics and calculations

All counts use `COUNT(DISTINCT u.user_id)` and only include rows where `vd.created_at IS NOT NULL`. Each metric is computed separately in Virginia and Ireland, then summed per period (trend) or per country (location).

### 6.1 New volunteers (`new_volunteers`)

Volunteers whose `volunteer_details.created_at` falls in each period of the window.

```sql
SELECT TO_CHAR(DATE_TRUNC(:period, vd.created_at), :fmt) AS period,
       COUNT(DISTINCT u.user_id)
FROM users u JOIN volunteer_details vd ON u.user_id = vd.user_id
WHERE vd.created_at IS NOT NULL <date filter>
GROUP BY 1 ORDER BY 1
```

Still returned by the API, no longer shown on the chart.

### 6.2 Active volunteers (`active_volunteers`)

The same query as 6.1 with `AND u.user_status_id = 1` added. In practice this is "volunteers who joined in this period **and** whose account is active today". It does not measure activity (for example requests handled) during the period.

### 6.3 Total volunteers (`total_volunteers`)

A running total of new volunteers, using `SUM(count) OVER (ORDER BY period)`.

- **7D / 30D / 1Y / All:** the running total starts at zero at the beginning of the window. For 7D, 30D and 1Y it is therefore a cumulative count of volunteers who joined *within the window*, not the platform total.
- **Custom:** a `base_count` of volunteers created before `start_date` is added, so the line starts from the true total at the start of the range.

### 6.4 Volunteers by location

```sql
SELECT COALESCE(c.country_code, 'Unknown') AS country, COUNT(DISTINCT u.user_id)
FROM users u
JOIN volunteer_details vd ON u.user_id = vd.user_id
LEFT JOIN country c ON u.country_id = c.country_id
WHERE 1=1
  [AND UPPER(c.country_code) = :country]
  [AND EXISTS (... h.cat_name = :skill)]
  [<date filter>]
GROUP BY 1 ORDER BY count DESC
```

- Location comes from the user's profile country (`users.country_id`), not from GPS data in `volunteer_locations`.
- Users without a matching country are grouped as `Unknown`.
- After Virginia and Ireland are merged, the list is sorted **alphabetically by country code**, not by count.

## 7. Reference links

**Data repo tasks:** [#71](https://github.com/saayam-for-all/data/issues/71) · [#117](https://github.com/saayam-for-all/data/issues/117) · [#118](https://github.com/saayam-for-all/data/issues/118) · [#151](https://github.com/saayam-for-all/data/issues/151) · [#179](https://github.com/saayam-for-all/data/issues/179) · [#301](https://github.com/saayam-for-all/data/issues/301) · [#543](https://github.com/saayam-for-all/data/issues/543) · [#605](https://github.com/saayam-for-all/data/issues/605)

**Data repo PRs:** [#202](https://github.com/saayam-for-all/data/pull/202) · [#204](https://github.com/saayam-for-all/data/pull/204) · [#212](https://github.com/saayam-for-all/data/pull/212) · [#218](https://github.com/saayam-for-all/data/pull/218) · [#224](https://github.com/saayam-for-all/data/pull/224) · [#229](https://github.com/saayam-for-all/data/pull/229) · [#238](https://github.com/saayam-for-all/data/pull/238) · [#314](https://github.com/saayam-for-all/data/pull/314) · [#341](https://github.com/saayam-for-all/data/pull/341) · [#403](https://github.com/saayam-for-all/data/pull/403)

**Webapp:** [#1680](https://github.com/saayam-for-all/webapp/issues/1680) · [PR #1838](https://github.com/saayam-for-all/webapp/pull/1838) · [#1518](https://github.com/saayam-for-all/webapp/issues/1518)

**Code and data:**
- [`volunteer_application_analytics.py`](https://github.com/saayam-for-all/data/blob/main/data-analytics/lambda_functions/volunteer_application_analytics.py)
- [`Test Cases and Acceptance Criteria.docx`](https://github.com/saayam-for-all/data/blob/main/data-analytics/lambda_functions/Test%20Cases%20and%20Acceptance%20Criteria.docx)
- [`Saayam_Table.column.names_data.xlsx`](https://github.com/saayam-for-all/data/blob/main/database/Saayam_Table.column.names_data.xlsx)
- [`database/lookup_tables/`](https://github.com/saayam-for-all/data/tree/main/database/lookup_tables)
- [`data-analytics/mock-data-generation/`](https://github.com/saayam-for-all/data/tree/main/data-analytics/mock-data-generation)
