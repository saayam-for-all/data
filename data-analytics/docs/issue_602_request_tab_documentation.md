# Request Tab — Application Analytics (Super Admin / Admin Dashboard)

> **Issue:** [#602 — Document Application Analytics Flow and Implementation — Request Dashboard](https://github.com/saayam-for-all/data/issues/602)
>
> **Code documented (backend):** [`data-analytics/lambda_functions/requestApplicationAnalytics.py`](https://github.com/saayam-for-all/data/blob/7cda7bc6c8e4ec932fbcb2335ad9a142c6eef240/data-analytics/lambda_functions/requestApplicationAnalytics.py) at commit `7cda7bc` (author Vighnesh Sridhar, 2026-06-25). That commit currently lives on branch `vighneshsridhar-beneficiaries_trend_analysis`. **The file is not present on `test` or `main` at the time this document was written.**
>
> **Code documented (frontend, outside this repository):** webapp [`RequestsAnalytics.jsx`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Auth/Dashboard/components/RequestsAnalytics.jsx) (commit `83f689d`), wired from [`ApplicationAnalytics.jsx`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Auth/Dashboard/components/ApplicationAnalytics.jsx), calling `POST v1/ml/requestApplicationAnalytics` via [`analyticsServices.js`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/services/analyticsServices.js) / [`endpoints.json`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/services/endpoints.json).
>
> **Scope of this document:** it records existing behavior and history. It does not change any implementation.

### How to read this document

| Label | Meaning |
|---|---|
| **Confirmed** | Verified directly from code, git history, or GitHub issue/PR metadata. |
| **Intended / historical** | Described in an issue, PR, or comment, but not necessarily present in the current code. |
| **Known limitation** | A confirmed gap between the current code and the intended behavior. |
| **Open question** | Cannot be resolved from the repository alone; needs live database, AWS, or team confirmation. |

---

## 1. Purpose and Scope

This document covers:

**Super Admin Dashboard / Admin Dashboard → Application Analytics → Requests tab**

**Intended purpose (from Issue [#82](https://github.com/saayam-for-all/data/issues/82)):**

1. Track the total number of help requests over the past 7 days, month, year, or a custom range.
2. Track the number of help requests by **category and region**.

The same design issue also defined sibling tabs (KPI, Beneficiaries, Volunteers). Those are out of scope here except where they share infrastructure or history with the Requests tab.

**What the current UI actually shows (Confirmed from webapp `RequestsAnalytics.jsx`):**

| Chart | UI title | Visualization |
|---|---|---|
| 1 | Request Volume Trend | Line chart of request counts over time |
| 2 | Requests by Category & Region | Stacked bar chart of category × country |

---

## 2. User Flow

High-level flow assembled from Issues [#82](https://github.com/saayam-for-all/data/issues/82), [#146](https://github.com/saayam-for-all/data/issues/146), webapp [#1589](https://github.com/saayam-for-all/webapp/issues/1589), and the current webapp / Lambda code:

1. A Super Admin or Admin opens **Application Analytics** on their dashboard (RBAC work tracked in webapp [#1057](https://github.com/saayam-for-all/webapp/issues/1057)).
2. The user selects the **Requests** tab (`ApplicationAnalytics.jsx` default tab id `"requests"`).
3. On first load, the frontend calls `getRequestsApplicationAnalytics({})` once and caches the promise so both charts share the default payload response.
4. For each chart the user can pick **7D / 30D / 1Y / All / Custom**. Fixed ranges read different keys from the same default response. Custom range triggers a second POST with `{ start_date, end_date }`.
5. The API Gateway route `POST v1/ml/requestApplicationAnalytics` invokes the `requestApplicationAnalytics` Lambda.
6. The Lambda connects to the Virginia PostgreSQL analytics database (credentials from SSM), runs several aggregations, and returns a JSON body with multiple named series.
7. The frontend maps response keys to chart series, applies client-side country/category filters and Top-5 logic for the stacked bar, and renders Recharts line / bar charts.

**Open question:** API Gateway mapping, Lambda function name in AWS, stage variables, and whether the live deployed package matches commit `7cda7bc` cannot be confirmed from this repository. The Lambda source is not on `test`/`main`.

---

## 3. Features

### 3.1 Request Volume Trend (Confirmed)

- Time-range buttons: `7D`, `30D`, `1Y`, `All`, `Custom`.
- Custom range shows start/end date inputs; validation requires both dates and `start ≤ end`.
- Series shape expected by the UI: `[{ "date": "<ISO>", "count": <int> }, ...]`.
- Dates are truncated to the calendar day for the X-axis (`(item.date || "").split("T")[0]`).

### 3.2 Requests by Category & Region (Confirmed)

- Independent time-range controls (separate state from the volume chart).
- Client-side filters:
  - Category multi-select (optional); when none selected, show top *N* categories by total (`categoryLimit`, default **5**).
  - Country dropdown (`all` or one country).
  - Sort by total or category name.
- Stacked bars use the **Top 5 countries by total request count**, computed on the client from the category×country series (not from the Lambda `top_countries *` keys).
- Country codes from the API are mapped to display names via `country-codes-en.json` and `isoAlpha3ToName` (handles alpha-2 or alpha-3).

### 3.3 Backend capabilities present but unused by the current UI (Confirmed)

The Lambda accepts optional event fields `category`, `country`, and `sort_by` for server-side filtering of the category×region queries. The current `RequestsAnalytics.jsx` does **not** send those fields; it filters locally after fetch.

---

## 4. Filters

### 4.1 Frontend time ranges (Confirmed)

| UI control | Internal id | Volume response key used | Category×region response key used |
|---|---|---|---|
| 7D | `7d` | `request_volume_7_days` | `requests_by_category_region 7 days` |
| 30D | `30d` | `request_volume_1_month` | `requests_by_category_region 1 month` |
| 1Y | `1yr` | `request_volume_1_year` | `requests_by_category_region 1 year` |
| All | `all` | `request_volume_1_year` | `requests_by_category_region 1 year` |
| Custom | `custom` | `request_volume_custom_range` | `requests_by_category_region_custom_range` |

**Known limitation — "All" is not all-time:** both charts map `all` to the **1 year** series. There is no all-time aggregation in the Lambda response.

**Known limitation — custom category series key:** the UI looks for `requests_by_category_region_custom_range`, but the Lambda at `7cda7bc` never builds that key (see [Section 8](#8-known-limitations-and-gaps)).

### 4.2 Backend intervals and grouping (Confirmed from Lambda)

| Response key | SQL interval / range | `DATE_TRUNC` unit |
|---|---|---|
| `request_volume_7_days` | `7 days` | day |
| `request_volume_1_month` | `30 days` (note: key says "1_month", interval is 30 days) | day |
| `request_volume_1_year` | `1 year` | month |
| `request_volume_custom_range` | `BETWEEN start_date AND end_date` | from event `group_by` (`day` or `month`) |
| `requests_by_category_region 7 days` | `7 days` | n/a (grouped by category + country) |
| `requests_by_category_region 1 month` | `30 days` | n/a |
| `requests_by_category_region 1 year` | `1 year` | n/a |
| `top_countries 7 days` / `30 days` / `1 year` | matching interval | n/a (LIMIT 5) |

### 4.3 Custom date event fields (Confirmed)

| Event field | Used for |
|---|---|
| `start_date` | Start of custom volume trend range |
| `end_date` | End of custom volume trend range |
| `group_by` | `day` or `month` for custom volume trend |
| `category` | Optional server-side category filter |
| `country` | Optional server-side country-code filter (`UPPER` match) |
| `sort_by` | `count` (default), `category`, or `country` |

**Known limitation:** when `start_date` is present, the handler does `group_by = event['group_by']` with no default. The current frontend custom call sends only `{ start_date, end_date }`. Static review of that path shows a `KeyError: 'group_by'` before any custom volume series is built. See [Section 8](#8-known-limitations-and-gaps).

The handler reads these fields from the **top-level `event` object** (not from `event["body"]`). Whether API Gateway is configured to unwrap the body is an **open question**.

---

## 5. Data Sources

### 5.1 Database and tables (Confirmed, as written in Lambda)

| Constant / alias | Value in code |
|---|---|
| Schema | `virginia_dev_saayam_rdbms` |
| Requests | `virginia_dev_saayam_rdbms.request` |
| Users | `virginia_dev_saayam_rdbms.users` |
| Country | `virginia_dev_saayam_rdbms.country` |
| Categories | `virginia_dev_saayam_rdbms.help_categories` |

Only the **Virginia** SSM profile is used (`get_db_config("Virginia")`). There is no Ireland path in this Lambda (unlike `beneficiariesTrendAnalysis.py`).

### 5.2 Credentials (Confirmed)

| Item | Value |
|---|---|
| Store | AWS Systems Manager Parameter Store |
| SSM client region | `us-east-1` |
| Parameter | `/dev/saayam/db/Virginia/Analytics/user` (`WithDecryption=True`) |

Host, port, dbname, user, and password are parsed from fixed line positions in the parameter value. **Open question:** the expected layout of that parameter string is not documented in-repo; the parser is shared in spirit with other analytics Lambdas.

### 5.3 Join pattern for geographic / category metrics (Confirmed)

```
request r
  INNER JOIN users u          ON r.req_user_id = u.user_id
  INNER JOIN country c        ON u.country_id = c.country_id
  INNER JOIN help_categories  ON r.req_cat_id = cat.cat_id   -- category series only
```

Geography is taken from the **user** linked by `req_user_id`, not from a location field on the request row.

**Open question / schema drift vs repo CSV mocks:**

| Live Lambda assumes | `data-analytics/sql/requests.csv` on `test` |
|---|---|
| Column `req_user_id` | Not present; CSV has `creator_id`, `req_for_id`, `beneficiary_id` |
| Table `help_categories` | Repo also has `help_category.csv` (singular) in `data-analytics/sql/`; mock generator writes `help_categories.csv` |

Other Lambdas on `test` (for example `beneficiariesTrendAnalysis.py`, `kpi_api_analytics.py`) also use `req_user_id` and `help_categories`, so the **production column name is likely still `req_user_id`**. The CSV mock split into creator/beneficiary is a known divergence already flagged in the Beneficiary docs (#603). Whether production has since migrated is an **open question**.

### 5.4 Date column (Confirmed)

Volume and category queries filter on `request.submission_date`. Rows with `submission_date IS NULL` are excluded from the volume trend.

---

## 6. Metrics and Calculations

### 6.1 Request volume trend

**Function:** `get_request_volume_trend(interval, group_by="day")`

**Logic (Confirmed):**

1. Optionally prints `COUNT(*)` from the full request table (debug).
2. Runs:

```sql
SELECT DATE_TRUNC(<day|month>, submission_date) AS date,
       COUNT(*) AS count
FROM virginia_dev_saayam_rdbms.request
WHERE submission_date > CURRENT_TIMESTAMP - INTERVAL <interval>
  AND submission_date IS NOT NULL
GROUP BY DATE_TRUNC(<day|month>, submission_date)
ORDER BY date
```

   For a custom range, `WHERE submission_date BETWEEN %s AND %s` replaces the rolling interval.
3. Returns `[{"date": <isoformat>, "count": <int>}, ...]`.
4. On any exception inside the helper, returns `[]` (errors are swallowed per series).

**What the metric represents:** total help-request rows with a non-null `submission_date` in the window, bucketed by day or month. It is a **row count of requests**, not unique beneficiaries or unique requesters.

### 6.2 Requests by category and region

**Function:** `get_requests_by_category_region(...)`

**Logic (Confirmed):**

1. Join request → users → country → help_categories as above.
2. Require non-null `country_code` and `cat_name`.
3. Apply rolling interval on `r.submission_date`.
4. Optional equality filters on `cat.cat_name` and `UPPER(c.country_code)`.
5. `GROUP BY cat.cat_name, c.country_code`.
6. Order by count DESC (default), category name, or country code.
7. Return `[{"category", "country", "count"}, ...]`.

**Known limitation vs Issue #82 wording:** Issue #82 asked for category and **region**. The implementation groups by **country_code** only. There is no state/region dimension in this Lambda or in the current Requests UI stacked bar.

**Naming note:** response keys intentionally contain spaces, e.g. `"requests_by_category_region 7 days"`. The frontend key maps match those exact strings.

### 6.3 Top 5 countries

**Function:** `get_top_countries(interval)`

Returns `[{"rank", "country", "count"}, ...]` limited to 5, for intervals `7 days`, `30 days`, and `1 year`.

**Known limitation:** `RequestsAnalytics.jsx` does **not** read these keys. The UI recomputes Top 5 from the category×region series instead. The Lambda keys are currently unused by the documented webapp component.

---

## 7. Implementation Approach

### 7.1 Backend response shape (Confirmed at `7cda7bc`)

On success the handler returns:

```json
{
  "statusCode": 200,
  "body": {
    "request_volume_7_days": [...],
    "request_volume_1_month": [...],
    "request_volume_1_year": [...],
    "request_volume_custom_range": [...],
    "top_countries 7 days": [...],
    "top_countries 30 days": [...],
    "top_countries 1 year": [...],
    "requests_by_category_region 7 days": [...],
    "requests_by_category_region 1 month": [...],
    "requests_by_category_region 1 year": [...]
  }
}
```

Notes:

- Success path has CORS headers **commented out**; the 500 path still attaches `CORS_HEADERS`.
- `body` is a **dict**, not a `json.dumps` string. The `__main__` local harness then does `json.loads(result["body"])`, which cannot work as written when the handler succeeds.
- Fixed-range series are always computed on every invocation; the caller does not ask for a single window.

On connection-level failure:

```json
{
  "statusCode": 500,
  "headers": { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
  "body": "{\"error\": \"Failed to connect to database\"}"
}
```

(500 `body` is a JSON **string**, unlike the success dict — inconsistent shapes.)

### 7.2 Frontend integration (Confirmed)

| Piece | Location / value |
|---|---|
| Endpoint key | `REQUEST_APPLICATION_ANALYTICS` → `v1/ml/requestApplicationAnalytics` |
| Client helper | `getRequestsApplicationAnalytics(payload)` → `api.post(...)` |
| Default payload | `{}` (shared via `useRef` promise cache) |
| Custom payload | `{ start_date, end_date }` only |
| Body unwrap | `response?.body \|\| response` so either Gateway proxy shape or already-unwrapped JSON works |
| Empty / error copy | Uses `has_errors` / `error_message` if present; otherwise "No data available..." |

**Open question:** whether the live API returns the Lambda proxy shape `{ statusCode, body }` or only the inner analytics object. The UI tolerates both.

### 7.3 Deployment status relative to this repo (Confirmed)

| Artifact | On `test` / `main`? |
|---|---|
| `requestApplicationAnalytics.py` | **No** — only found via commit `7cda7bc` / branch `vighneshsridhar-beneficiaries_trend_analysis` |
| Older names in history | `request_application_analytics.py`, `application_analytics_request.py` (see task review) |
| Webapp Requests tab integration | **Yes** — merged via webapp PR [#1608](https://github.com/saayam-for-all/webapp/pull/1608) for issue [#1589](https://github.com/saayam-for-all/webapp/issues/1589) (merged 2026-06-26) |

**Open question:** which exact Lambda package is deployed behind `v1/ml/requestApplicationAnalytics` today (the `7cda7bc` file, a fork from PR [#167](https://github.com/saayam-for-all/data/pull/167), or another unpublished package).

---

## 8. Known Limitations and Gaps

Findings below were verified against the cited sources. Severity is informal.

| # | Finding | Label | Evidence |
|---|---|---|---|
| 1 | Lambda source not on `test`/`main` | Known limitation | `git ls-tree` on `origin/test` has no matching path; file introduced in `7cda7bc` on another branch |
| 2 | Custom category key missing | Known limitation | UI expects `requests_by_category_region_custom_range`; Lambda response_body never sets it |
| 3 | Custom volume call omits `group_by` | Known limitation | Frontend posts `{start_date,end_date}`; Lambda does `event['group_by']` → `KeyError` on that path |
| 4 | "All" uses 1-year data | Known limitation | `volumeKeyMap.all` / `categoryKeyMap.all` both point at 1-year keys |
| 5 | No true **region** dimension | Known limitation | Issue #82 wording vs country_code-only grouping |
| 6 | `top_countries *` unused by UI | Known limitation | Keys built in Lambda; not referenced in `RequestsAnalytics.jsx` |
| 7 | Server-side `category`/`country`/`sort_by` unused by UI | Known limitation | Filters applied client-side only |
| 8 | Success response omits CORS headers | Known limitation | `# "headers": CORS_HEADERS` commented on 200 path |
| 9 | Success vs 500 body type inconsistency | Known limitation | dict vs `json.dumps` string |
| 10 | Local `__main__` harness broken on success | Known limitation | `json.loads` on dict body |
| 11 | Per-query failures return empty arrays silently | Known limitation / design choice | bare `except` → `[]`; UI may show "No data" instead of an error unless `has_errors` is set (Lambda does not set `has_errors`) |
| 12 | `req_user_id` vs CSV `creator_id`/`beneficiary_id` | Open question | Live Lambdas use `req_user_id`; `sql/requests.csv` does not |
| 13 | Deployed Lambda revision unknown | Open question | Endpoint exists in webapp; source not merged to `test` |
| 14 | Competing open doc PRs for #602 | Historical | [#643](https://github.com/saayam-for-all/data/pull/643), [#664](https://github.com/saayam-for-all/data/pull/664) — this document is an independent review against primary sources |
| 15 | Interval naming: key `1_month` uses `30 days` | Confirmed quirk | Matches sibling analytics patterns; not a calendar month |
| 16 | Category custom range cannot work end-to-end today | Known limitation | Combination of gaps #2 and #3 |

---

## 9. Task-by-Task Review

Each related task was opened individually (title, body, state, and linked PRs where applicable).

### 9.1 [data#82](https://github.com/saayam-for-all/data/issues/82) — Design of Application Analytics tab (CLOSED)

- Defined the original Request visuals: volume over 7D/month/year/custom, and volume by category and region.
- Also defined KPI / Beneficiaries / Volunteers tabs (siblings).
- **Relevance:** source of product intent for this tab.

### 9.2 [data#84](https://github.com/saayam-for-all/data/issues/84) — Creation of test data (CLOSED)

- MVP approach: realistic CSVs → JSON → API for UI while real DB data was unavailable.
- **Relevance:** explains why early analytics work used mocks; later #146 moved Requests analytics to real Virginia queries.

### 9.3 [data#89](https://github.com/saayam-for-all/data/issues/89) — Plotly dashboard implementation (CLOSED)

- Explored Python/Plotly analytics dashboards.
- **Relevance:** historical spike; the production Super Admin UI is React/Recharts in the webapp, not a Plotly app in this repo.
- `data-analytics/dashboards/` on `test` still contains only a `.gitkeep`.

### 9.4 [data#146](https://github.com/saayam-for-all/data/issues/146) — Implement real API for `application_analytics_request.py` (CLOSED)

- Goal: replace mock/partial logic with Virginia RDS queries for Request Volume Trend and Requests by Category & Region.
- Phases covered code completion, testing, and deployment.
- **Relevance:** primary backend implementation ticket for this tab’s API.

### 9.5 [data#167](https://github.com/saayam-for-all/data/issues/167) / PR [#167](https://github.com/saayam-for-all/data/pull/167) — Real DB queries PR (OPEN at doc time)

- Describes volume trends (7d daily, 30d daily, 1y monthly), category×country filters, top 5 countries, try/except per query, `finally` cleanup.
- Head branch noted in metadata: `dokababa_146_application_analytics_api`.
- **Relevance:** alternate / parallel implementation track for the same API. Not merged at the time of writing; relationship to the live endpoint is an **open question**.

### 9.6 Commit `7cda7bc` — `Create requestApplicationAnalytics.py`

- Adds the 262-line Lambda reviewed throughout this document.
- Branch containing the commit: `vighneshsridhar-beneficiaries_trend_analysis`.
- Earlier history also shows renames: `request_application_analytics.py` → `application_analytics_request.py` (commits `75715b2`, `e1c8a45`, `8b630f5`).
- **Relevance:** concrete code snapshot used for Confirmed claims in this doc when the file is absent from `test`.

### 9.7 [data#189](https://github.com/saayam-for-all/data/issues/189) — Date filters for `beneficiariesTrendAnalysis.py` (OPEN)

- About beneficiary Lambda date filtering, not the Requests Lambda.
- **Relevance:** weak / sibling only. Reviewed because Application Analytics date-filter work often cross-links; **no Requests-tab code changes** confirmed from this issue alone.

### 9.8 [webapp#1057](https://github.com/saayam-for-all/webapp/issues/1057) — Different dashboard views using RBAC (CLOSED)

- Super Admin / Admin / Steward dashboard shells.
- **Relevance:** explains where Application Analytics lives in the product navigation.

### 9.9 [webapp#1589](https://github.com/saayam-for-all/webapp/issues/1589) + PR [#1608](https://github.com/saayam-for-all/webapp/pull/1608) — Requests tab API integration (CLOSED / MERGED 2026-06-26)

- Replace mock JSON with `POST` to the data/ml Requests analytics endpoint.
- Default call with empty payload for 7D/30D/1Y-style values; separate payloads for custom ranges (as described in the issue).
- **Relevance:** current frontend behavior documented in Sections 3–4 and 7.2.

### 9.10 Sibling documentation pattern

- [#603](https://github.com/saayam-for-all/data/issues/603) / docs file `issue_603_beneficiary_dashboard_analytics.md` on `test` establishes the Confirmed / Known limitation / Open question labelling used here.

---

## 10. Supporting Links

| Kind | Link |
|---|---|
| Tracking issue | https://github.com/saayam-for-all/data/issues/602 |
| Design | https://github.com/saayam-for-all/data/issues/82 |
| Test data approach | https://github.com/saayam-for-all/data/issues/84 |
| Real API implementation | https://github.com/saayam-for-all/data/issues/146 |
| Open implementation PR | https://github.com/saayam-for-all/data/pull/167 |
| Lambda snapshot | https://github.com/saayam-for-all/data/blob/7cda7bc6c8e4ec932fbcb2335ad9a142c6eef240/data-analytics/lambda_functions/requestApplicationAnalytics.py |
| Webapp integration issue | https://github.com/saayam-for-all/webapp/issues/1589 |
| Webapp integration PR | https://github.com/saayam-for-all/webapp/pull/1608 |
| Endpoint registration | https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/services/endpoints.json |
| UI component | https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Auth/Dashboard/components/RequestsAnalytics.jsx |
| Sibling beneficiary docs | https://github.com/saayam-for-all/data/blob/test/data-analytics/docs/issue_603_beneficiary_dashboard_analytics.md |

---

## 11. Out of Scope / Not Changed by This Work

- No Lambda, SQL, mock data, or webapp code changes.
- No deployment or AWS configuration changes.
- No attempt to resolve the open implementation PR (#167) or to merge `requestApplicationAnalytics.py` onto `test`.
- KPI / Beneficiaries / Volunteers Application Analytics tabs are documented elsewhere (see #603 for Beneficiaries).

---

## 12. How This Document Was Verified

Verification performed while authoring (documentation-only; no production writes):

1. Read issue #602 acceptance criteria and label (`documentation`).
2. Opened and summarized issues #82, #84, #89, #146, #167, #189 and webapp #1057, #1589 (titles, bodies, states).
3. Inspected PR #167 metadata (open) and webapp PR #1608 (merged).
4. Loaded Lambda source from git commit `7cda7bc` (262 lines) and checked response keys, SQL, SSM path, join columns, and error handling.
5. Loaded webapp `RequestsAnalytics.jsx`, `ApplicationAnalytics.jsx`, `analyticsServices.js`, and `endpoints.json` at commit `83f689d`; confirmed key maps, custom payload shape, and client-side Top-5 / filters.
6. Confirmed the Lambda path is **absent** from `origin/test` via `git ls-tree`.
7. Compared `data-analytics/sql/requests.csv` / `users.csv` / `help_category.csv` column names against the Lambda join assumptions.
8. Cross-checked sibling doc style against `issue_603_beneficiary_dashboard_analytics.md`.
9. Noted existing open documentation PRs #643 and #664 for the same issue; this file is written from primary sources rather than copied from those PRs.

**Not verified (access / environment limits):** live AWS Lambda package contents, API Gateway integration mapping, live Virginia table DDL, or runtime responses from `v1/ml/requestApplicationAnalytics`.
