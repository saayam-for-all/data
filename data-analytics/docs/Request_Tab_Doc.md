# Request Tab Documentation

> **Issue:** [#602 — Document Application Analytics Flow and Implementation — Request Dashboard](https://github.com/saayam-for-all/data/issues/602)
>
> **Pinned historical backend:** [`data-analytics/lambda_functions/requestApplicationAnalytics.py`](https://github.com/saayam-for-all/data/blob/7cda7bc6c8e4ec932fbcb2335ad9a142c6eef240/data-analytics/lambda_functions/requestApplicationAnalytics.py) at commit `7cda7bc` (author Vighnesh Sridhar, 2026-06-25). That commit currently lives on branch `vighneshsridhar-beneficiaries_trend_analysis`. **The file is not present on `test` or `main` at the time this document was written.**
>
> **Code documented (frontend, outside this repository):** webapp [`RequestsAnalytics.jsx`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Dashboard/components/Analytics/RequestsAnalytics.jsx) (commit `83f689d`), wired from [`ApplicationAnalytics.jsx`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Dashboard/components/Analytics/ApplicationAnalytics.jsx), calling `POST v1/ml/requestApplicationAnalytics` via [`analyticsServices.js`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/services/analyticsServices.js) / [`endpoints.json`](https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/services/endpoints.json).
>
> **Selected source:** Adapted from [PR #671](https://github.com/saayam-for-all/data/pull/671), by [affan00733](https://github.com/affan00733), documentation commit `778f3ef2db3d6d45e0c380092eeaec929f805efe`. Compared with [PR #664](https://github.com/saayam-for-all/data/pull/664) for consolidation under #602; subsequently reviewed [#643](https://github.com/saayam-for-all/data/pull/643), [#649](https://github.com/saayam-for-all/data/pull/649), and [#650](https://github.com/saayam-for-all/data/pull/650). #649 informed the additional integration history and display-limit notes below, rechecked against primary sources. Source links and a few accuracy details were corrected during review on November 11, 2026. Code claims refer to the pinned snapshots below; live deployment was not tested.
>
> **Scope of this document:** it records existing behavior and history. It does not change any implementation.

### How to read this document

| Label | Meaning |
|---|---|
| **Confirmed** | Verified directly from code, git history, or GitHub issue/PR metadata. |
| **Intended / historical** | Described in an issue, PR, or comment, but not necessarily present in the current code. |
| **Known limitation** | A confirmed gap in the pinned source; not evidence of a live production failure. |
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
5. The frontend posts to `v1/ml/requestApplicationAnalytics`; the intended backend is the Requests analytics Lambda. The exact gateway-to-function mapping needs deployment confirmation.
6. The Lambda connects to the Virginia PostgreSQL analytics database (credentials from SSM), runs several aggregations, and returns a JSON body with multiple named series.
7. The frontend maps response keys to chart series, applies client-side country/category filters and Top-5 logic for the stacked bar, and renders Recharts line / bar charts.

**Open question:** API Gateway mapping, Lambda function name in AWS, stage variables, and whether the live deployed package matches commit `7cda7bc` cannot be confirmed from this repository. The Lambda source is not on `test`/`main`.

---

### 2.1 Reported API evolution versus the pinned backend

The frontend and the historical backend snapshot are not the same versioned contract. The following records explain why the source mismatches below must not be described as confirmed current API failures:

| Evidence | What it establishes |
|---|---|
| [PR #167 discussion](https://github.com/saayam-for-all/data/pull/167) | The author reported deployment as `requestApplicationAnalytics` on May 12, 2026, with later Parameter Store/SQL updates. The PR remains unmerged; this is a historical deployment report, not verification of the current package. |
| [August 6 maintainer comment](https://github.com/saayam-for-all/webapp/issues/1589#issuecomment-5208253988) | Reports adding custom category ranges and removing the need for `group_by`; grouping was described as daily for ranges under a year and monthly otherwise. This is reported behavior, not logic present in `7cda7bc`. |
| [September 30 frontend testing report](https://github.com/saayam-for-all/webapp/issues/1589#issuecomment-5901572095) | Identifies `requests_by_category_region_custom_range`, `has_errors` and `error_message` in API responses; custom volume worked without `group_by`, while custom category data still failed. |
| [October 1 fix](https://github.com/saayam-for-all/webapp/issues/1589#issuecomment-5923700675) and [retest](https://github.com/saayam-for-all/webapp/issues/1589#issuecomment-5924907885) | Maintainer reports a custom-category fix; the contributor reports successful default/custom ranges, independent chart dates and `has_errors: false`. These are historical live-test reports, not tests performed during this documentation review. |

The exact deployed source and grouping threshold remain unverified. The missing custom category key and required `group_by` documented for `7cda7bc` describe that old file, while these reports indicate that the serving API had evolved beyond it.

## 3. Features

### 3.1 Request Volume Trend (Confirmed)

- Time-range buttons: `7D`, `30D`, `1Y`, `All`, `Custom`.
- Custom range shows start/end date inputs; validation requires both dates and `start ≤ end`.
- Series shape expected by the UI: `[{ "date": "<ISO>", "count": <int> }, ...]`.
- Dates are truncated to the calendar day for the X-axis (`(item.date || "").split("T")[0]`).

### 3.2 Requests by Category & Region (Confirmed)

- Independent time-range controls (separate state from the volume chart). Both charts initially select All. The category limit offers Top 5, Top 7 or Top 8, defaulting to 5.
- Client-side filters:
  - Category multi-select (optional); when none selected, show top *N* categories by total (`categoryLimit`, default **5**).
  - Country dropdown (`all` or one country).
  - Sort by total or category name.
- Stacked bars use the **Top 5 countries by total request count**, computed on the client from the category×country series (not from the Lambda `top_countries *` keys).
- Country codes from the API are mapped to display names via `country-codes-en.json` and `isoAlpha3ToName` (handles alpha-2 or alpha-3).

**Display limitation:** under All Countries, only the globally selected top-five countries are drawn as stacked segments, but category totals, Top-N selection and sorting still include other countries. A category's ranking can therefore exceed what its visible segments suggest. Selecting one country draws that country instead. The Top 5 badge row is computed before category/country filters and does not change with those controls. These are frontend behaviors, independently checked in `processStackedData` and `top5Countries`.

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

**Pinned-source mismatch — custom category series key:** the UI looks for `requests_by_category_region_custom_range`, but the Lambda at `7cda7bc` never builds that key (see [Section 8](#8-known-limitations-and-gaps)).

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
| `group_by` | Required by the custom handler path; `month` selects monthly grouping, any other supplied value selects daily grouping |
| `category` | Optional server-side category filter |
| `country` | Optional server-side country-code filter (`UPPER` match) |
| `sort_by` | `count` (default), `category`, or `country` |

**Pinned-source mismatch:** when `start_date` is present, the handler does `group_by = event['group_by']` with no default. The current frontend custom call sends only `{ start_date, end_date }`. Static review of that file shows a `KeyError: 'group_by'` before any custom volume series is built. Section 2.1 records later API reports in which the same frontend payload works; this is contract drift, not a verified live failure. See [Section 8](#8-known-limitations-and-gaps).

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

The beneficiary Lambda also references `req_user_id`; the KPI Lambda does not use that column. Repository code and fixtures do not establish the live schema. Confirm the deployed database columns before relying on this join. The creator/beneficiary divergence is also discussed in the Beneficiary documentation (#603).

The local fixture audit also found only **9 of 25** request `creator_id` values in `users.csv`, and **0 of 25** request category IDs in `help_category.csv`. These files cannot reproduce the reviewed category join as-is. Request submission dates span August 9, 2025 through August 14, 2026, so recent windows may be empty even after fixture/schema corrections.

A historical [team workflow document](https://github.com/saayam-for-all/data/blob/d03da126f8fc341cc0c318537cd5c118269632f2/data-analytics/docs/Request_Analytics_Workflow.docx), inspected during consolidation, describes the same dashboard → credentials → PostgreSQL → SQL analytics pipeline. It names plural `requests`/`countries`, unlike the pinned backend's singular names. This is additional schema/version evidence, not confirmation of the live DDL.

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

   For a custom range, `WHERE submission_date BETWEEN %s AND %s` replaces the rolling interval. Presets have no upper bound, so future-dated rows can qualify. A date-only custom end value normally means midnight on a timestamp column, excluding later times on that final day. Database timezone and timestamp types require live-schema confirmation.
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

**Requirement gap versus Issue #82:** Issue #82 asked for category and **region**. The implementation groups by **country_code** only. There is no state/region dimension in this Lambda or in the current Requests UI stacked bar.

**Naming note:** response keys intentionally contain spaces, e.g. `"requests_by_category_region 7 days"`. The frontend key maps match those exact strings.

### 6.3 Top 5 countries

**Function:** `get_top_countries(interval)`

Returns `[{"rank", "country", "count"}, ...]` limited to 5, for intervals `7 days`, `30 days`, and `1 year`.

**Known limitation:** `RequestsAnalytics.jsx` does **not** read these keys. The UI recomputes Top 5 from the category×region series instead. The Lambda keys are currently unused by the documented webapp component.

---

## 7. Implementation Approach

### 7.1 Backend response shape (Confirmed at `7cda7bc`)

On success the handler returns (schematic; `...` represents array contents):

```javascript
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

On failures caught by the outer handler (including a missing custom `group_by`, not only connection failures):

```json
{
  "statusCode": 500,
  "headers": { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" },
  "body": "{\"error\": \"Failed to connect to database\"}"
}
```

(500 `body` is a JSON **string**, unlike the success dict — inconsistent shapes.) SSM credential lookup and parsing happen before the handler’s `try`, so failures there escape this formatted 500 response. A SQL error can also leave the shared transaction aborted; no rollback occurs between helpers.

### 7.2 Frontend integration (Confirmed)

| Piece | Location / value |
|---|---|
| Endpoint key | `REQUEST_APPLICATION_ANALYTICS` → `v1/ml/requestApplicationAnalytics` |
| Client helper | `getRequestsApplicationAnalytics(payload)` → `api.post(...)` |
| Default payload | `{}` (shared via `useRef` promise cache) |
| Custom payload | `{ start_date, end_date }` only |
| Body unwrap | `response?.body \|\| response` so either Gateway proxy shape or already-unwrapped JSON works |
| Empty / error copy | Uses `has_errors` / `error_message` if present; otherwise "No data available..." |

**Open question:** whether the live API returns the Lambda proxy shape `{ statusCode, body }` or only the inner analytics object. The UI handles an object-valued `body` or an already-unwrapped object; it does not explicitly JSON-parse a string-valued `body` in this component.

### 7.3 Deployment status relative to this repo (Confirmed)

| Artifact | On `test` / `main`? |
|---|---|
| `requestApplicationAnalytics.py` | **No** — only found via commit `7cda7bc` / branch `vighneshsridhar-beneficiaries_trend_analysis` |
| Older names in history | `request_application_analytics.py`, `application_analytics_request.py` (see task review) |
| Webapp Requests tab integration | **Yes** — merged via webapp PR [#1608](https://github.com/saayam-for-all/webapp/pull/1608) for issue [#1589](https://github.com/saayam-for-all/webapp/issues/1589) (merged 2026-06-26) |

**Open question:** which exact Lambda package is deployed behind `v1/ml/requestApplicationAnalytics` today (the `7cda7bc` file, a fork from PR [#167](https://github.com/saayam-for-all/data/pull/167), or another unpublished package).

---

## 8. Known Limitations and Gaps

Findings below apply to the cited source snapshots. Later reported API behavior is recorded in Section 2.1; the source mismatches do not establish present production defects.

| # | Finding | Label | Evidence |
|---|---|---|---|
| 1 | Lambda source not on `test`/`main` | Known limitation | `git ls-tree` on `origin/test` has no matching path; file introduced in `7cda7bc` on another branch |
| 2 | Custom category key missing at `7cda7bc` | Source mismatch | UI expects `requests_by_category_region_custom_range`; Lambda response_body never sets it |
| 3 | Frontend omits `group_by` required by `7cda7bc` | Source mismatch | Frontend posts `{start_date,end_date}`; Lambda does `event['group_by']` → `KeyError` on that path |
| 4 | "All" uses 1-year data | Known limitation | `volumeKeyMap.all` / `categoryKeyMap.all` both point at 1-year keys |
| 5 | No true **region** dimension | Known limitation | Issue #82 wording vs country_code-only grouping |
| 6 | `top_countries *` unused by UI | Known limitation | Keys built in Lambda; not referenced in `RequestsAnalytics.jsx` |
| 7 | Server-side `category`/`country`/`sort_by` unused by UI | Known limitation | Filters applied client-side only |
| 8 | Pinned backend success response omits CORS headers | Source limitation | `# "headers": CORS_HEADERS` commented on 200 path |
| 9 | Success vs 500 body type inconsistency | Known limitation | dict vs `json.dumps` string |
| 10 | Local `__main__` harness broken on success | Known limitation | `json.loads` on dict body |
| 11 | Pinned query failures return empty arrays silently | Source limitation | bare `except` → `[]`; UI may show "No data" instead of an error unless `has_errors` is set (Lambda does not set `has_errors`) |
| 12 | `req_user_id` vs CSV `creator_id`/`beneficiary_id` | Open question | Reviewed Requests source uses `req_user_id`; `sql/requests.csv` does not |
| 13 | Deployed Lambda revision unknown | Open question | Endpoint exists in webapp; source not merged to `test` |
| 14 | Visible stacks omit non-top-five countries | Frontend limitation | Bar totals/ranking include countries that are not drawn as segments under All Countries |
| 15 | Interval naming: key `1_month` uses `30 days` | Confirmed quirk | Matches sibling analytics patterns; not a calendar month |
| 16 | Historical API evolved beyond the pinned backend | Contract drift | Section 2.1 records a reported custom-category fix and successful calls without `group_by` |

---

## 9. Task-by-Task Review

The selected PR author recorded the following individual task review (title, body, state, and linked PRs where applicable). Historical states reflect that review; they are not deployment evidence.

### 9.1 [data#82](https://github.com/saayam-for-all/data/issues/82) — Design of Application Analytics tab (CLOSED)

- Defined the original Request visuals: volume over 7D/month/year/custom, and volume by category and region.
- Also defined KPI / Beneficiaries / Volunteers tabs (siblings).
- **Relevance:** source of product intent for this tab.

### 9.2 [data#84](https://github.com/saayam-for-all/data/issues/84) — Creation of test data (CLOSED)

- MVP approach: realistic CSVs → JSON → API for UI while real DB data was unavailable.
- **Relevance:** explains why early analytics work used mocks; later #146 moved Requests analytics to real Virginia queries.

### 9.3 [data#89](https://github.com/saayam-for-all/data/issues/89) — Plotly dashboard implementation (CLOSED)

- Explored Python/Plotly analytics dashboards.
- **Relevance:** historical spike; the reviewed Super Admin UI source uses React/Recharts in the webapp, not a Plotly app in this repo.
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

### 9.7 [data PR #189](https://github.com/saayam-for-all/data/pull/189) — Beneficiaries title, mixed analytics changes

- Its title and description focus on Beneficiaries, but its diff also adds `requestApplicationAnalytics.py`. Both changed paths were checked directly.
- **Relevance:** contains the historical Requests implementation used as the backend baseline here; it must not be dismissed as Beneficiaries-only based on its title. Its code still does not establish the serving API revision.

### 9.8 [webapp#1057](https://github.com/saayam-for-all/webapp/issues/1057) — Different dashboard views using RBAC (CLOSED)

- Super Admin / Admin / Steward dashboard shells.
- **Relevance:** explains where Application Analytics lives in the product navigation.

### 9.9 [webapp#1589](https://github.com/saayam-for-all/webapp/issues/1589) + PR [#1608](https://github.com/saayam-for-all/webapp/pull/1608) — Requests tab API integration (CLOSED / MERGED 2026-06-26)

- Replace mock JSON with `POST` to the data/ml Requests analytics endpoint.
- Default call with empty payload for 7D/30D/1Y-style values; separate payloads for custom ranges (as described in the issue).
- **Relevance:** current frontend behavior documented in Sections 3–4 and 7.2. Later work includes [#1629](https://github.com/saayam-for-all/webapp/pull/1629) for independent category controls, [#1876](https://github.com/saayam-for-all/webapp/pull/1876) for custom ranges/response errors, and [#1942](https://github.com/saayam-for-all/webapp/pull/1942) for dropdown dismissal and country colors. The cited issue discussion and pinned UI confirm the resulting behavior; contributor test counts are not treated as our tests.


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
| UI component | https://github.com/saayam-for-all/webapp/blob/83f689de72b65a683ab2aa2837a6c684768104c9/src/pages/Dashboard/components/Analytics/RequestsAnalytics.jsx |
| Sibling beneficiary docs | [Beneficiary_Tab_Doc.md](Beneficiary_Tab_Doc.md) |

---

## 11. Verification

The original #671 author reports source/history inspection, issue/PR review and fixture-column comparison. These are historical author reports; no live integration result or frontend suite run is claimed for this document. Consolidation corrections are attributed at the top.

Consolidation on November 11, 2026 compared all five candidate PRs (#671, #664, #643, #649, #650). It rechecked #602, PR #167 public deployment discussion/merge status, the actual #189 diff, webapp #1589 integration/fix reports, #1608 merge metadata, the pinned backend/frontend, fixture join counts and the historical workflow DOCX. The #84 schema/visualization attachments were inspected during the dashboard documentation work. Frontend source paths, JSON examples and reference targets were checked. No new live API/database test or frontend suite run was performed.
