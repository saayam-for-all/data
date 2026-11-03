# Organization Tab Documentation

Super Admin Dashboard → Analytics → Application Analytics → **Organization**

| | |
|---|---|
| Task | [#604 Document Application Analytics Flow and Implementation - Organization Dashboard][i604] |
| Status of this document | Snapshot as of **2026-11-01** |
| Backend reviewed | `saayam-for-all/data`, branch `test` at [`f64938f`][data-test] (merge of PR #493, 2026-10-28) |
| Frontend reviewed | `saayam-for-all/webapp`, branch `features/dashboard-analytics` at [`f5b940a`][web-tip] (2026-10-13) |
| Tasks reviewed | #81, #82, #84, #89, #228, #301, #336, #376, #380, #506, #539, #569, #583 (section 8) |

Throughout this document, **⚠ Flag** marks information that is missing, contradictory or unverified. All flags are collected in [section 11](#11-missing-or-unclear-information).

---

## 1. Summary

- **What the tab is for.** It gives Super Admins one place to see how many partner organizations Saayam has and how that changes over time. It shows where they are, how big they are, how they participate (collaborator / contributor), how they are rated, and the mix of for-profit and non-profit organizations.
- **What a user sees.** A filter bar (date range, region, reset), four KPI cards, and three sub-tabs with two charts each:
  - Growth & Location
  - Size & Contribution
  - Rating & Type
- **The frontend is not merged and is not connected to an API.** The Organization tab exists only on the webapp branch `features/dashboard-analytics`. That branch is not merged into webapp `test`, `dev` or `main`. Its charts are drawn from hard-coded sample numbers in `organizationData.js`.
- **There is one backend Lambda per sub-tab.** All three live in `data-analytics/lambda_functions/` and exist only on the data repo's `test` branch:

  | Sub-tab | Lambda | Task |
  |---|---|---|
  | Growth & Location | [`growth_trend_analytics.py`][growth] | #336, #539 |
  | Size & Contribution | [`size_and_contribution.py`][size] | #376 |
  | Rating & Type | [`rating_type_analytics.py`][rating] | #380 |

- **Those Lambdas read sample data.** They run on the mock CSVs from #301 (400 synthetic organizations). Growth can only read CSVs. Rating and Size can also query Postgres, but neither path has been confirmed against the live table.
- **Three follow-up fixes are still open.** #506, #569 and #583 change the Rating and Size request/response contracts. Several PRs exist for each, but none is merged into `test` yet.
- **No API serves the KPI cards.**

### Status at a glance

| Piece | Where | Status |
|---|---|---|
| Organization tab UI | webapp `features/dashboard-analytics` | Built with sample data; **not merged**, **no API calls** |
| Growth & Location API | data `test` | Merged via PR [#538][pr538] (2026-10-14), updated by PR [#541][pr541] (#539, 2026-10-22) |
| Rating & Type API | data `test` | Merged via PR [#503][pr503] (2026-10-12); fix #506 **pending** |
| Size & Contribution API | data `test` | Merged via PR [#568][pr568] (2026-10-20); fixes #569 and #583 **pending** |
| KPI cards API | — | **None.** See [section 6.1](#61-kpi-cards) |
| Mock data | data `test` and `main`, `data-analytics/mock-data-generation/` | Merged (#301 dataset) |
| Deployment / API Gateway routes | — | **Not found** in either repo ⚠ |

---

## 2. Purpose

Product scoping for this tab goes back to the Application Analytics design in [#82][i82]. That design has six categories; category 5 is "Organizations". Its [design wiki][wiki] describes it only as *"Count the total number of organizations involved"* over 7 days / month / year / custom, split by for-profit vs non-profit.

[#228][i228] (July 2026) expanded this into a full Organization dashboard with:

- KPI cards (Total Organizations, Total Collaborators, Total Contributors, Average Organization Rating);
- growth trend and geographic distribution;
- size distribution and collaborator-vs-contributor split;
- rating distribution and for-profit vs non-profit over time;
- common filters: Date Range (7D/30D/1Y/ALL/CUSTOM), Region, Organization Type, Reset.

The goal is to let Super Admins judge the health of Saayam's organization network:

- Is it growing?
- Where is it concentrated?
- What kinds of organizations take part, and how actively?
- How are they rated?

---

## 3. Features

### 3.1 Layout

| Area | Contents |
|---|---|
| Header | "ORGANIZATION DASHBOARD" and the subtitle "Overview of organization performance and impact" |
| Filter bar | Date range buttons, a Custom date picker, a Region dropdown and a Reset button (see [section 5.1](#51-filters-in-the-ui)) |
| KPI cards | Total Organizations · Total Collaborators · Total Contributors · Avg. Org Rating (each with a % change) |
| Sub-tab: **Growth & Location** (default) | 1. Growth Trend (line) · 2. Organizations by Location (bar) |
| Sub-tab: **Size & Contribution** | 3. Organizations by Size (bar) · 4. Collaborator vs Contributor (donut) |
| Sub-tab: **Rating & Type** | 5. Rating Distribution (bar) · 6. Profit vs Non-Profit (stacked bar) |
| Every chart | ⋮ menu: view as table, **Export CSV**, **Download PNG** ([`ChartContainer.jsx`][web-chartcontainer]) |

Source: [`OrganizationAnalytics.jsx`][web-org] (sub-tabs at [L30–34][web-tabs], filters at [L303–383][web-filters], KPI cards at [L385–418][web-kpis]).

### 3.2 Charts and their backend fields

| # | Chart | Intended backend field | Lambda |
|---|---|---|---|
| 1 | Growth Trend | `growth_trend.total_organizations`, `growth_trend.collaborators` | Growth |
| 2 | Organizations by Location | `organizations_by_location` | Growth |
| 3 | Organizations by Size | `organizations_by_size` | Size |
| 4 | Collaborator vs Contributor | `collaborator_vs_contributor` | Size |
| 5 | Rating Distribution | `rating_distribution` | Rating |
| 6 | Profit vs Non-Profit | `organization_mix_trend.for_profit` / `.non_profit` | Rating |
| — | 4 KPI cards | none | — |

⚠ **Flag:** the UI and the APIs do not yet agree on several of these charts (different series, labels and semantics). See [section 5.4](#54-ui--api-mismatches).

---

## 4. User flow

### 4.1 As built in the UI branch

1. A Super Admin signs in and opens **Dashboard**. On the **Analytics** tab, they choose the **Application Analytics** sub-tab. The other sub-tabs are Infrastructure and Google Analytics ([`SuperAdminDashboard.jsx`][web-superadmin]).
2. Application Analytics shows five tabs: Requests · KPI · Beneficiaries · Volunteers · **Organization** ([`ApplicationAnalytics.jsx`][web-appanalytics] on the feature branch).
3. The Organization tab opens with **Date range = 1 Year**, **Region = All**, and the **Growth & Location** sub-tab selected.
4. Changing any filter recomputes the KPI cards and all six charts in the browser by calling `getOrganizationAnalytics()` from [`organizationData.js`][web-data]. No network request is made. That file's header says: *"There is no organization analytics API endpoint yet."*
5. Choosing **Custom** shows two date inputs. **Reset** restores the defaults; it is disabled while the defaults are active.
6. The user switches sub-tabs to see the other chart pairs. They can open any chart as a table or export it.

⚠ **Flag:** on webapp `main`, `dev` and `test`, Application Analytics has only four tabs (no Organization). The test app at [test-saayam.netlify.app](https://test-saayam.netlify.app/) could not be checked for this document because it requires a Super Admin login.

### 4.2 Intended data flow once wired

```
UI filter change
   │  (one call per sub-tab; body = filters)
   ▼
API Gateway route  (⚠ not defined in webapp endpoints.json or in the data repo)
   ▼
Lambda (growth_trend_analytics | size_and_contribution | rating_type_analytics)
   │  loads organizations + states + countries
   │    • CSVs in a mock_data/ folder next to the .py file, or
   │    • Postgres (Rating / Size only, when USE_MOCK_DATA is not "true")
   ▼
JSON with every fixed window: {"7D", "30D", "1Y", "All"}
   — or, when custom dates are sent, only {"Custom"}
```

**Design principle (#336, #376, #380):** one default call returns every fixed window, so switching between 7D, 30D, 1Y and All needs no new request. A Custom range triggers a separate call that returns only `Custom`.

---

## 5. Filters

### 5.1 Filters in the UI

| Control | Values | Default | Notes |
|---|---|---|---|
| Date range | `7d` "7 Days", `30d` "30 Days", `1Y` "1 Year", `all` "All", `custom` "Custom" | `1Y` | Custom shows start/end date inputs |
| Region | All, North, South, East, West | All | The UI scales its sample data by a fixed share per region |
| Reset | — | — | Restores the defaults |

⚠ **Flag:** #228 asks for an **Organization Type** filter. `organizationData.js` supports `orgType`, but the component never shows a control for it or passes it.

### 5.2 Filters in each API

| | Growth & Location | Size & Contribution | Rating & Type |
|---|---|---|---|
| Custom dates | `start_date` + `end_date`, applied to **both** charts (since #539) | `size_start_date`/`size_end_date` **and** `contribution_start_date`/`contribution_end_date`, one pair per chart | `rating_start_date`/`rating_end_date` **and** `type_start_date`/`type_end_date`, one pair per chart |
| Date format | `YYYY-MM-DD`, both ends inclusive | `YYYY-MM-DD`, both ends inclusive | `YYYY-MM-DD`, both ends inclusive |
| Blank `""` / `null` dates | Treated as not sent | Treated as not sent | **`""` → 400** (only `null` or a missing key counts as not sent) |
| `country` | Code or name, case-insensitive; spaces = underscores; blank/`null`/`ALL` = no filter | Same matching rules | Same matching rules |
| Unknown country | **400** `{"error": "Unknown country"}` | 200 with empty charts | 200 with empty charts |
| `organization_type` | not supported | `non_profit` / `for_profit` / `ALL` (case and `-`/space tolerant); anything else → 400 | not supported by design (#380) |
| Default response keys | `7D`, `30D`, `1Y`, `All` | `7D`, `30D`, `1Y`, `All` **+ empty `Custom`** | `7D`, `30D`, `1Y`, `All` **+ empty `Custom`** |
| Body formats | dict, or API Gateway `{"body": "<json>"}` | dict, or `{"body": "<json>"}` | dict, `{"body": ...}`, or `queryStringParameters` |

All three were confirmed by running them locally (see [section 12](#12-how-this-document-was-verified)).

**Pending contract changes (open PRs, not merged into `test`):**

| Task | Lambda | Change |
|---|---|---|
| [#506][i506] | Rating | Drop the empty `Custom` key from the default response |
| [#569][i569] | Size | Drop the empty `Custom` key; read `mock_data/` by default (Postgres only when `USE_MOCK_DATA=false`); accept time-zone-aware `created_at`; unknown country → 400 |
| [#583][i583] | Size | Replace both date pairs with a single `start_date`/`end_date` for both charts; drop the empty `Custom`; read only `mock_data/`; **remove** the Postgres code and the `USE_MOCK_DATA`/`MOCK_DATA_DIR` switches |

⚠ **Flag:** #569 and #583 overlap and partly conflict. #569 keeps Postgres behind a switch; #583 removes it. #569 keeps the two date pairs; #583 replaces them. #583 is newer, so it likely wins, but nobody has stated the merge order.

### 5.3 Time windows

| Window | Growth & Location | Size & Contribution | Rating & Type |
|---|---|---|---|
| 7D | today − 6 days → (no upper bound) | today − 6 days → end of today | today − 6 days → now |
| 30D | today − 29 days → (no upper bound) | today − 29 days → end of today | today − 29 days → now |
| **1Y** | **1st of the month, 11 months back** (12 calendar months) | **1st of the month, 11 months back** (12 calendar months) | **same date last year + 1 day** (rolling 365 days) |
| All | everything | everything | everything up to now |
| Custom | start 00:00 → end 23:59:59 | start 00:00 → end 23:59:59 | start 00:00 → end 23:59:59.999999 |
| Grouping | day: 7D, 30D, Custom · month: 1Y, All | n/a (no time series) | day: 7D, 30D, Custom · month: 1Y, All |
| "Today" | `pd.Timestamp.now()` (container clock) | UTC date | `datetime.now()` (container clock) |

⚠ **Flag: inconsistent "1Y".** With the clock pinned to 2026-09-01:

- Growth and Size count **301** organizations in 1Y (from 2025-10-01).
- Rating counts **329** organizations in 1Y (from 2025-09-02).

So the same filter covers different organizations on different sub-tabs. A Lambda container runs in UTC, so the clock difference only matters when running locally.

### 5.4 UI ↔ API mismatches

These need to be settled when the UI is wired to the Lambdas.

| Topic | UI (feature branch) | API (`test`) |
|---|---|---|
| Date range keys | `7d`, `30d`, `1Y`, `all`, `custom` | `7D`, `30D`, `1Y`, `All`, `Custom` |
| Location filter | **Region**: North/South/East/West | **Country** code or name; no region concept |
| Org type filter | Not shown | Size only |
| Growth Trend series | Three lines: Total Organizations, Total **Collaborators**, Total **Contributors** | `total_organizations` (cumulative) and `collaborators` (**new per period**, not cumulative); **no contributor series** |
| Location chart | US state names, plus an "Other" bucket and "% of Total" | Country codes (or that country's states when filtered); no cap, no "Other", no percentage |
| Collaborator vs Contributor | Donut of "Collaborator" vs "**Contributor (Non-Collaborator)**", i.e. mutually exclusive and summing to 100% | Two **independent** flags that can overlap (73 of the 400 mock orgs are both), so the percentages need not sum to 100. **A donut cannot show overlapping groups faithfully** |
| Rating Distribution | Always five bars (1–5 stars) | Only ratings that occur (no zero rows); the UI must zero-fill |
| Profit vs Non-Profit | Stacked bars per period | `organization_mix_trend` gives **cumulative** totals with separate, sparse periods per type; the UI must align periods |
| KPI cards | Four cards with % change | No API (see [section 6.1](#61-kpi-cards)) |

---

## 6. Metrics and calculations

All three Lambdas use the same join: **organizations → states (on `state_id`) → countries (on `country_id`)**.

The numbers below come from running the `test` code on the repo mock data with the clock pinned to **2026-09-01** (the mock data ends on 2026-08-31).

### 6.1 KPI cards

| Card | Definition in #228 | What the UI shows today |
|---|---|---|
| Total Organizations | count of organizations | last point of the sample growth series |
| Total Collaborators | `is_collaborator = true` | sample series value |
| Total Contributors | `is_contributor = true` | sample series value |
| Avg. Org Rating | average organization rating | **hard-coded `4.2`**, with a hard-coded change of `4` |

The % change on each card is `(last − first) / first × 100` over the selected window of sample data.

⚠ **Flag: no API returns these four values.** The #336/#376/#380 Lambdas don't include them. The only KPI-style backend is the #228 FastAPI service in `data-engineering/src/main.py` ([`/analytics/organizations/overview/summary`][main-summary] and [`/performance/summary`][main-perf]). It has three problems:

- It defines contributors as `is_collaborator IS NOT TRUE`, which contradicts the independent `is_contributor` flag in #228/#376.
- It uses column names marked as unconfirmed guesses in the code ([L49–56][main-cols]): `org_size`, `rating`, `registered_at`. The mock data uses `org_size`, `org_rating` and `created_at`.
- The UI doesn't reference it.

### 6.2 Growth Trend (Growth & Location)

Code: [`build_growth_trend`][growth-trend]

- **`total_organizations`**: a cumulative, all-time count.
  1. Group **all** organizations by period (day or month) and take a running sum.
  2. Return only the periods in which at least one organization was created inside the window.
  3. The value therefore never resets at the start of the window. Periods with no new organizations are left out.
- **`collaborators`**: the number of **new** collaborator organizations (`is_collaborator = true`) created in each of those periods. It is not cumulative and is 0 for periods without one.

| Window (as of 2026-09-01) | Periods | Last `total_organizations` | Sum of `collaborators` |
|---|---|---|---|
| 7D | 3 days | 400 | 2 |
| 30D | 20 days | 400 | 7 |
| 1Y | 11 months | 400 | 94 |
| All | 15 months (2025-06 → 2026-08) | 400 | 125 |

### 6.3 Organizations by Location (Growth & Location)

Code: [`build_orgs_by_location`][growth-location]

- **No country filter:** one row per country, `{"country": "<country_code>", "count": n}`.
- **Country filter:** one row per state of that country, `{"state": "<state_name>", "count": n}`.
- **Sort order:** count descending, then name. There is no cap and no "Other" row (#539 removed the top-4 cap from #336). Organizations that can't be mapped are labelled `"Unknown"`.
- **Invariant:** the counts sum to the number of organizations created in the window. Checked: All = 400 across 18 countries (JPN 61, USA 51, IND 32, …); 30D = 24.

### 6.4 Organizations by Size (Size & Contribution)

Code: [`size_chart`][size-chart]

- One row per `org_size` value present in the window, `{"size": ..., "count": n}`.
- Sorted small → medium → large, with any other values after those.
- NULL sizes are excluded. There are no zero rows.
- All window: small 122 · medium 168 · large 110 (= 400).

### 6.5 Collaborator vs Contributor (Size & Contribution)

Code: [`contribution_chart`][size-contrib]

- Two rows, always in this order: Collaborator, then Contributor.
- `count` is the number of organizations in the window with the flag set.
- `percentage = round(count / window_total × 100, 1)`.
- The flags are independent, so an organization can count in both rows and the percentages need not sum to 100.
- An empty window returns `[]`.
- If the `is_contributor` column is missing, Contributor = 0 ([mock path][size-mock], [DB path][size-db]).
- All window: Collaborator 125 (31.2%) · Contributor 224 (56.0%) · 73 organizations are both.

### 6.6 Rating Distribution (Rating & Type)

Code: [`compute_rating_distribution`][rating-dist]

- One row per whole-number rating 1–5 present in the window, `{"rating": r, "count": n}`.
- NULL, non-integer and out-of-range ratings are excluded. There is no zero-filling.
- All window: 1★ 9 · 2★ 13 · 3★ 46 · 4★ 119 · 5★ 136. That is 323 rated organizations; the 77 unrated ones are excluded.

### 6.7 Profit vs Non-Profit (Rating & Type)

Code: [`compute_organization_mix_trend`][rating-mix]

- One series each for `non_profit` and `for_profit`, after normalising `org_type` spellings such as "Non-Profit" or "for profit".
- Each point is the **cumulative, all-time** count of that type at the end of the period.
- Only periods in which an organization of that type was created inside the window are returned. The two series therefore have different, sparse periods.
- Checked: both series never decrease. They end at non_profit 270 and for_profit 130 (= 400).

---

## 7. Data sources

### 7.1 Tables and columns used

| Table | Columns used | Used by |
|---|---|---|
| `organizations` | `org_id`, `org_type`, `org_size`, `org_rating`, `is_collaborator`, `is_contributor`, `state_id`, `created_at` | all three (each uses the columns it needs) |
| `states` | `state_id`, `country_id`, `state_name` | all three |
| `countries` | `country_id`, `country_code`, `country_name` | all three |

### 7.2 Where each Lambda reads from

| Lambda | Data source |
|---|---|
| Growth | **Always** reads CSVs from a `mock_data/` folder next to the `.py` file ([`load_data`][growth-load]). There is no database code or environment variable. |
| Rating | `USE_MOCK_DATA=true` → CSVs from `MOCK_DATA_DIR` (default `mock_data/`). Otherwise Postgres, using `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` and `ORG_ANALYTICS_SCHEMA` (default `virginia_dev_saayam_rdbms`) ([`load_data`][rating-load]). |
| Size | Same switch as Rating. The default is Postgres ([L355][size-switch]). It checks whether `is_contributor` exists before using it. |

With no environment variables set, Rating and Size return **500**, because they try Postgres without credentials. Growth works.

### 7.3 Mock dataset (#301)

- **Location:** [`data-analytics/mock-data-generation/`][mock-dir] (`organizations.csv`, `states.csv`, `countries.csv`, plus seven other tables, `generate_mock_data.py` and `readme.md`).
- **Contents:** 400 organizations, 400 states and 18 countries.
  - `created_at` runs from 2025-06-02 to 2026-08-31.
  - 270 non_profit and 130 for_profit.
  - 77 organizations have no rating.
- **How it arrived:**
  - In `test`: commit [`35bdf0d`][mock-commit], merged in PR [#536][pr536] on 2026-10-14.
  - In `main`: via PR [#414][pr414].
  - The generator script is identical to hamsaram1406's PR [#314][pr314].
- **Packaging:** the Lambdas expect a `mock_data/` folder next to them. That folder isn't committed (#336/#376/#380 forbid committing CSVs into PRs), so it must be created when packaging.

⚠ **Flag:** the mock-data `readme.md` says three countries (US, India, UK), but the CSVs contain 18 countries and 400 states.

⚠ **Flag: two schema references disagree.**

- The repo's schema snapshot ([`database/mock-data-generation/db_info.json`][dbinfo] and the `Saayam_Table.column.names_data.xlsx` files) lists:
  - `organizations` columns `size`, `rating`, `state_code`;
  - **no** `is_collaborator`, `is_contributor` or `state_id`;
  - singular table names `state`/`country`.
- The mock data and the org-aggregator Lambda's column mapping use `org_size`, `org_rating`, `is_collaborator` and `state_id`. #301 notes that `states`/`cities`/`countries` were pluralised on 2026-08-17.
- The snapshot is therefore probably stale, but the live column list hasn't been confirmed for this document.
- The Postgres paths are affected:
  - Size joins `{schema}.state` and `{schema}.country` (singular).
  - Rating joins `state` and `country` **without a schema prefix** ([L127][rating-join]).

---

## 8. How the tab was developed

### 8.1 Timeline

| Date | Event |
|---|---|
| 2025-11-20 → 2026-03-24 | [#81][i81] / [#82][i82] / [#84][i84] / [#89][i89]: Super Admin analytics design. Organizations is category 5 of Application Analytics; test data was produced as JSON for the UI team |
| 2026-07-14 | [#228][i228] opened: a single Organization Analytics API covering all charts and KPI cards |
| 2026-08-18 | PR [#272][pr272] (#228) merged into **`main`** by its author: FastAPI endpoints in `src/main.py` |
| 2026-08-31 | [#301][i301] opened: mock data for 10 tables, including organizations/states/countries |
| 2026-09-05 → 10-13 | webapp: Organization tab built on `features/dashboard-analytics` ([`64e6879`][web-c1] Aniket Kumar; [`99fb66e`][web-c2], [`508e04e`][web-c3], [`343b1f7`][web-c4], [`f5b940a`][web-tip] nishchay1111) |
| 2026-09-12 | [#336][i336] opened: standalone Growth & Location Lambda |
| 2026-09-22 / 23 | [#376][i376] Size & Contribution and [#380][i380] Rating & Type opened |
| 2026-09-29 → 10-10 | Several contributor PRs land on `test` and are later reverted or deleted (section 8.2) |
| 2026-10-12 | PR [#503][pr503] merges `rating_type_analytics.py`; [#506][i506] opened |
| 2026-10-14 | PR [#538][pr538] merges `growth_trend_analytics.py`; PR [#536][pr536] merges the mock data |
| 2026-10-15 | [#539][i539] opened: single date range and country filter for Growth |
| 2026-10-20 | PR [#568][pr568] merges `size_and_contribution.py`; [#569][i569] opened |
| 2026-10-22 | PR [#541][pr541] (#539) merged after review ("Good job!") |
| 2026-10-23 | [#583][i583] opened: single date range for Size |
| 2026-10-26 | [#604][i604] (this documentation task) opened |

### 8.2 Individual task reviews

PR counts are the PRs found for each task by issue number, branch name or changed files (`refs/pull/*`). They are approximate.

**[#81][i81] Creation of Super Admin Dashboard Analytics** (closed 2026-03-24)
- **Asked:** three sub-categories under Super Admin Analytics.
- **Outcome:** closed as "Complemented the implementation". No PRs are linked. Background only.

**[#82][i82] Design of Application Analytics tab** (closed 2026-03-24)
- **Asked:** six categories; Organizations (category 5) = count over a period by for-profit vs non-profit.
- **Attachment:** [design wiki][wiki] (last edited 2026-01-08). It specifies no charts, KPIs or data sources for Organizations.

**[#84][i84] Creation of test data** (closed 2026-03-24) and **[#89][i89] Plotly implementation** (closed 2026-03-24)
- **Approach:** CSV → JSON → API so the UI team could work without real data.
- **Comments:** the JSON was "sent to the UI team".
- **Attachments:** a schema xlsx and "Types of Visualizations for Application Analytics Dashboard.docx".
- No PRs are linked.
- ⚠ The docx couldn't be downloaded without signing in, so it was **not reviewed**.

**[#228][i228] Create Organization Analytics API**

| | |
|---|---|
| Asked | One `POST /analytics/organizations` returning the KPI cards plus all six charts; reuse the common filters; parameterised SQL; no AWS Parameter Store path; no direct AWS deploy |
| PRs | About 22 (#261–#300, #316, …). Most add an `organization_analytics.py`; none of those were merged |
| Merged | PR [#272][pr272]: FastAPI endpoints in `data-engineering/src/main.py`, `utils/time_filters.py`, a seed SQL and tests. Merged into `main` by its author with no review. Its column names are marked as unconfirmed guesses |
| Comments | One comment points to PR #300 ("26 passed"); #300 is not merged |
| Outcome | The single-endpoint design was replaced by three standalone Lambdas (#336/#376/#380). The issue is still **open**, and nothing serves the KPI cards |

**[#301][i301] Create mock data**

| | |
|---|---|
| Asked | Synthetic CSVs for 10 tables that follow the post-2026-08-17 schema (plural `states`/`countries`/`cities`); foreign keys valid; row counts configurable |
| PRs | About 21; none of them was merged as a #301 PR |
| Merged | The dataset reached `main` inside PR [#414][pr414] (titled "Update README.md") and `test` through maintainer commit [`35bdf0d`][mock-commit] / PR [#536][pr536]. Its generator is identical to hamsaram1406's PR [#314][pr314] |
| Outcome | The issue is still open. ⚠ It asks for both "~100 rows" and "400 rows"; the merged data has 400 |

**[#336][i336] Growth & Location Analytics API**

| | |
|---|---|
| Asked | Standalone Lambda; two charts; two independent custom ranges (`start_date`/`end_date` and `location_*`); top-4 countries; 7D/30D/Custom by day, 1Y/All by month |
| PRs | About 36 |
| Review feedback | On PR #356, the reviewer found 1Y spanning 366 days and asked for exactly 365 |
| Churn on `test` | PR #347 (`org_growth_location_analytics.py`) and PR #425 (`growth_location_analytics.py`, merged by its author) were merged. Code from PR #356 landed via merge commit [`f2acf3c`][c-f2acf3c] and was reverted by PR [#489][pr489]. Both files were later deleted by PR [#502][pr502] and PR [#537][pr537] |
| Final code | PR [#538][pr538] by the maintainer (`growth_trend_analytics.py`; no description or review). By text similarity it is ~82% identical to PR [#451][pr451] (hamsaram1406) |
| Outcome | Superseded in part by #539. The issue is still open |

**[#376][i376] Size & Contribution Analytics API**

| | |
|---|---|
| Asked | Two charts; independent `size_*` and `contribution_*` ranges (both honoured when sent together); `country` and `organization_type` filters; independent flags; `is_contributor` may be missing |
| PRs | About 40 |
| Churn on `test` | PR [#419][pr419] (Om Sali, `data-engineering/src/organization_size_contribution_analytics/`) was self-merged. **Its revert was never merged, so this second implementation is still on `test`** ⚠. PR [#471][pr471] was self-merged without review and reverted by PR [#490][pr490]; no reason is recorded |
| Final code | PR [#568][pr568] by the maintainer (`size_and_contribution.py`; no description or review). It is **byte-for-byte identical** to sakshg37's PR [#415][pr415] (renamed) |
| Outcome | Follow-ups in #569 and #583. The issue is still open |

**[#380][i380] Rating & Type Analytics API**

| | |
|---|---|
| Asked | Rating distribution (1–5, no zero-fill) and cumulative for-profit/non-profit trend; independent `rating_*` and `type_*` ranges; `country` filter only |
| PRs | About 41 |
| Final code | PR [#503][pr503] by the maintainer (no description or review). It is ~99% identical to thotasaiakash's PRs [#444][pr444]/[#445][pr445]. Note that #445 ("Treat empty-string date pairs as not supplied") is **not** reflected in the merged code |
| Outcome | Follow-up in #506. The issue is still open |

**[#506][i506] Fix JSON response: Rating & Type** (Bug, MVP)

| | |
|---|---|
| Asked | `{}` should return exactly `7D`, `30D`, `1Y`, `All`, with no empty `Custom` |
| PRs | 11 (e.g. #514, #515, #520, #529, #535, #544, #550, #555, #614, #616); a comment from poojan644 reports a fix |
| Outcome | **None merged.** `test` still returns the empty `Custom` ([L384][rating-custom]) |

**[#539][i539] Growth & Trend: single Custom range and country filter** (Feature, MVP)

| | |
|---|---|
| Asked | One `start_date`/`end_date` for both charts; drop `location_*`; `country` filter (code or name); per-country or per-state location rows; no cap and no "Other"; error messages fixed |
| PRs | 8 |
| Merged | PR [#541][pr541] (Somesh-Kennedy), approved by the maintainer. When both the country and the dates are invalid, the country error wins (the issue didn't specify) |
| Outcome | **Done in `test`**, although the issue is still open |

**[#569][i569] Size & Contribution: default response, data source, timestamps, unknown country** (Bug, MVP)

| | |
|---|---|
| PRs | 8 (#572, #575, #588, #595, #597, #607, #608, #634) |
| Outcome | **None merged** |
| ⚠ | The issue names the file `size_and_contribution.py` in its header but `size_contribution_analytics.py` in its expected layout |

**[#583][i583] Size & Contribution: one date range, no empty Custom, read from mock_data** (Bug, MVP)

| | |
|---|---|
| PRs | 5 (#596, #598, #600, #606, #630) |
| Outcome | **None merged** |
| ⚠ | The issue targets `size_contribution_analytics.py`, which doesn't exist on `test` (the file is `size_and_contribution.py`); PR #630 follows the issue and works on `size_contribution_analytics.py`. Its background says Rating & Type "already" uses one date range, but Rating on `test` still takes two pairs |

**webapp Organization tab** (no issue found)

| | |
|---|---|
| Commits | Created by Aniket Kumar on 2026-09-05 ("DashBoard mock data", with tests and chart export). nishchay1111 then made it work on mobile and tablet (09-06), added it under Application Analytics, aligned the date-range format and removed the "net profit" KPI card (09-22), and refined it on 09-28 and 10-13 |
| Outcome | None of these commits belongs to a PR, and the branch isn't merged ⚠ |

### 8.3 Observations about the process

- **Many volunteers worked on each task.** Every build task was assigned to about 10 volunteers, who each opened a PR. The maintainer (`bakugou123-ai`, Sahil Mane, Data Analytics lead) then merged a single version through his own PR.
- **The merged PRs explain nothing.** None of the merging PRs (#503, #538, #568) has a description, review or test output, and none says which contributor's work was chosen. The provenance in section 8.2 comes from text-similarity comparison and is **not documented anywhere** ⚠.
- **Most self-merges were undone.** Several PRs were merged by their own authors without review: #272 into `main`; #419, #425 and #471, plus the #356 code (through a direct merge commit), into `test`. The maintainer removed most of these from `test` (#489, #490, #502). The revert of #419 was never merged, so that code remains. #272 also remains, on both `main` and `test`.
- **The base branch moved from `dev` to `test`.** #376 and #380 ask for PRs against `dev`; from #506 onward, tasks target `test`. None of the Organization Lambdas is on `dev` or `main`.

---

## 9. Implementation details

### 9.1 Code map

| Component | File | Branch |
|---|---|---|
| UI tab | [`OrganizationAnalytics.jsx`][web-org], [`organizationData.js`][web-data], [`OrganizationAnalytics.test.jsx`][web-test] | webapp `features/dashboard-analytics` |
| Tab registration | [`ApplicationAnalytics.jsx`][web-appanalytics] | webapp `features/dashboard-analytics` |
| Growth & Location | [`growth_trend_analytics.py`][growth] | data `test` |
| Size & Contribution | [`size_and_contribution.py`][size] | data `test` |
| Rating & Type | [`rating_type_analytics.py`][rating] | data `test` |
| Older Size & Contribution (duplicate) | [`data-engineering/src/organization_size_contribution_analytics/lambda_function.py`][size-old] + [tests][size-old-tests] | data `test` |
| #228 FastAPI endpoints | [`data-engineering/src/main.py`][main] + [`utils/time_filters.py`][timefilters] + [tests][main-tests] | data `main`/`test` |
| Mock data | [`data-analytics/mock-data-generation/`][mock-dir] | data `main`/`test` |

### 9.2 Request and response examples

These are real outputs from the `test` code, with the clock pinned to 2026-09-01.

**Growth & Location**: `{"country": "USA"}` returns the four fixed windows, with states in the location chart. A custom request looks like this:

```json
// request
{"start_date": "2026-08-25", "end_date": "2026-08-31"}
// response (only the Custom key)
{"Custom": {
  "growth_trend": {
    "total_organizations": [{"period": "2026-08-25", "count": 397}, {"period": "2026-08-27", "count": 398},
                            {"period": "2026-08-28", "count": 399}, {"period": "2026-08-31", "count": 400}],
    "collaborators":       [{"period": "2026-08-25", "count": 0}, {"period": "2026-08-27", "count": 1},
                            {"period": "2026-08-28", "count": 1}, {"period": "2026-08-31", "count": 0}]
  },
  "organizations_by_location": [{"country": "BRA", "count": 1}, {"country": "IND", "count": 1},
                                {"country": "MEX", "count": 1}, {"country": "NGA", "count": 1}]
}}
```

**Size & Contribution** (current contract on `test`):

```json
// request
{"size_start_date": "2026-01-01", "size_end_date": "2026-03-31",
 "contribution_start_date": "2026-01-01", "contribution_end_date": "2026-03-31"}
// response
{"Custom": {
  "organizations_by_size": [{"size": "small", "count": 24}, {"size": "medium", "count": 30}, {"size": "large", "count": 21}],
  "collaborator_vs_contributor": [
    {"type": "Collaborator", "count": 25, "percentage": 33.3},
    {"type": "Contributor",  "count": 42, "percentage": 56.0}]
}}
```

**Rating & Type** (current contract on `test`):

```json
// request
{"rating_start_date": "2026-01-01", "rating_end_date": "2026-03-31",
 "type_start_date": "2026-08-25", "type_end_date": "2026-08-31"}
// response
{"Custom": {
  "rating_distribution": [{"rating": 2, "count": 2}, {"rating": 3, "count": 13}, {"rating": 4, "count": 22}, {"rating": 5, "count": 26}],
  "organization_mix_trend": {
    "non_profit": [{"period": "2026-08-25", "count": 269}, {"period": "2026-08-28", "count": 270}],
    "for_profit": [{"period": "2026-08-27", "count": 129}, {"period": "2026-08-31", "count": 130}]}
}}
```

Every response uses `statusCode`, `headers` (`Content-Type: application/json`, `Access-Control-Allow-Origin: *`) and a JSON-string `body`.

### 9.3 Error responses

| Condition | Growth | Size | Rating |
|---|---|---|---|
| Half date pair | 400 `Invalid date format or start_date after end_date` | 400 `<start> and <end> must be sent together` | 400 `<end> is required when <start> is provided` |
| Bad format / impossible date | same message as above | 400 `... must be a date in YYYY-MM-DD format` / `... is not a real calendar date` | 400 `Invalid date format for <field>: <value> (expected YYYY-MM-DD)` |
| Start after end | same message as above | 400 `<start> must be on or before <end>` | 400 `<start> must be on or before <end>` |
| Non-string `country` | 400 `country must be a string` | 400 `country and organization_type must be text` | 400 `country must be a string` |
| Invalid JSON body | 400 | 400 | 400 |
| Missing data or config | 500 `Internal server error` | 500 with the missing file, column or variable named | 500 `Internal server error (<ExceptionType>)` |

### 9.4 Running the Lambdas locally

```bash
cd data-analytics/lambda_functions
mkdir -p mock_data
cp ../mock-data-generation/{organizations,states,countries}.csv mock_data/   # do not commit mock_data/
export USE_MOCK_DATA=true MOCK_DATA_DIR="$PWD/mock_data"                       # Growth ignores both
python -c 'import json, growth_trend_analytics as m; print(json.dumps(json.loads(m.lambda_handler({}, None)["body"]), indent=1))'
```

Today the mock data ends on 2026-08-31, so **7D and 30D come back empty**. To see populated windows, pin the clock (for example with `freezegun`), or regenerate the data with recent dates.

---

## 10. Known limitations

1. **The UI isn't wired to any API and isn't merged.** Every number on the tab is sample data (`asOf: "Jun 30, 2025"`). That includes the hard-coded average rating of 4.2.
2. **Nothing serves the KPI cards.** None of the three Lambdas returns them, and the #228 FastAPI service uses a different definition of "contributors".
3. **Growth can only read CSVs.** It has no database path. Under #583, Size will be CSV-only too. Until a live data path exists, the tab can only show the synthetic dataset.
4. **Rating and Size fail on default settings.** They default to Postgres and return 500 when the DB variables are missing. This is fixed in Size by the pending #569/#583, but not in Rating.
5. **Contracts are inconsistent across sub-tabs:**
   - date parameters: one pair (Growth) vs two pairs (Size, Rating);
   - unknown country: 400 vs 200 with empty charts;
   - blank dates: ignored vs 400 (Rating);
   - an empty `Custom` key in the Size and Rating defaults;
   - the "1Y" window: calendar months vs rolling 365 days.
6. **The Postgres paths are unverified.** Size joins singular `state`/`country`; Rating joins unqualified `state`/`country`. The schema snapshot in the repo disagrees with the mock column names.
7. **The collaborator/contributor donut misrepresents the data**, because the two flags overlap (section 5.4).
8. **Mock data is stale relative to today.** `created_at` ends on 2026-08-31, so 7D and 30D are empty.
9. **There are two Size & Contribution implementations on `test`.** The `data-engineering` copy from PR #419 has a different response contract and data path.
10. **No deployment path exists.** The repo's deploy workflow only deploys `data-engineering/src/saayam-org-*` folders on merge to `main`. Neither repo defines an API Gateway route or webapp endpoint for these Lambdas, and the `mock_data/` folder must be packaged by hand.
11. **Small edge cases:**
    - Growth's 7D/30D windows have no upper bound, so future-dated rows would be counted.
    - Growth reads `is_collaborator` with a fixed `TRUE`/`FALSE` mapping; other spellings become missing values.

---

## 11. Missing or unclear information

| # | Question | Why it matters | Who can likely answer |
|---|---|---|---|
| 1 | Which webapp branch does test-saayam.netlify.app deploy from, and is the Organization tab visible there? | The task description says the tab exists, but it isn't in webapp `main`/`dev`/`test` | Webapp team / nishchay1111, Aniket Kumar |
| 2 | Is there a webapp issue or PR for the Organization tab, and when will it be wired to the Lambdas? | No issue was found, and none of the tab's commits is in a PR | Webapp team |
| 3 | Where should the KPI cards come from: a new Lambda, one of the three, or the #228 FastAPI? | The cards have no backend | Data Analytics leads (Sahil Mane, Vighnesh Sridhar) |
| 4 | Should collaborators and contributors be mutually exclusive (UI donut) or independent flags (#228/#376 and the API)? | The UI and API disagree; it also affects the Growth Trend's contributor line | Product / Data Analytics leads |
| 5 | Region (North/South/East/West) or Country, and is Organization Type needed in the UI? | The UI filters don't match any API parameter | Product / Data Analytics leads |
| 6 | Which contributor PRs were the merged files (#503, #538, #568) taken from? | Credit and review history aren't recorded; section 8.2's provenance is inferred from text similarity | Maintainer (bakugou123-ai) |
| 7 | Why were #471 and #356 reverted, and should the #419 duplicate be removed from `test`? | No reason is recorded on the revert PRs; the #419 revert was never merged | Maintainer |
| 8 | What is the merge order for #569 and #583, and what is the final Size file name? | The issues conflict on the data source and date parameters; #583 names a file that doesn't exist | Maintainer |
| 9 | Will Rating & Type move to a single `start_date`/`end_date` like Growth and Size? | #583 claims it already has, but `test` disagrees | Maintainer |
| 10 | Which "1Y" definition is correct: 12 calendar months or rolling 365 days? | The sub-tabs currently disagree (301 vs 329 organizations in the example above) | Data Analytics leads |
| 11 | What are the live `organizations` columns and table names (`org_size`/`org_rating` vs `size`/`rating`; `states` vs `state`)? | They decide whether the Postgres paths work | Database team |
| 12 | Is the plan to serve real data, or to keep CSVs packaged in the Lambda zip? | It decides whether the tab ever shows real organizations | Data Engineering leads / DevSecOps |
| 13 | What does the #84 attachment "Types of Visualizations for Application Analytics Dashboard.docx" specify for Organizations? | It couldn't be downloaded for this review | #84 assignees |
| 14 | When should the open issues (#228, #301, #336, #376, #380, #539) be closed? | #539's work is merged; the others are superseded or done | Project managers |

---

## 12. How this document was verified

- **Tasks:** every issue in section 8.2 was read on GitHub (body, comments, attachments and linked PRs). PR pages were read for #272, #356, #471, #489, #490, #503, #538, #541 and #568.
- **Code and history:**
  - The data repo was cloned with all branches and PR refs (`refs/pull/*/head`).
  - Each PR was checked for membership in `test` with `git merge-base --is-ancestor`.
  - Merged files were compared with contributor PR versions using `difflib`.
- **Behaviour:** the three Lambdas from `test` were run against `data-analytics/mock-data-generation/*.csv`. Runs used the real clock (2026-11-01) and a pinned clock (2026-09-01), with 30+ request scenarios covering filters, custom ranges, blank, half and invalid input, unknown country and default environment. The following were checked against counts computed directly from the CSV:
  - location sums;
  - cumulative series never decreasing;
  - totals.
- **Frontend:** read from webapp `features/dashboard-analytics` at `f5b940a`. Tab presence was compared with webapp `main`, `dev` and `test`.
- **Not verified:** the deployed test app (requires a Super Admin login), AWS or API Gateway configuration, and the live database schema.

---

<!-- Issues -->
[i81]: https://github.com/saayam-for-all/data/issues/81
[i82]: https://github.com/saayam-for-all/data/issues/82
[i84]: https://github.com/saayam-for-all/data/issues/84
[i89]: https://github.com/saayam-for-all/data/issues/89
[i228]: https://github.com/saayam-for-all/data/issues/228
[i301]: https://github.com/saayam-for-all/data/issues/301
[i336]: https://github.com/saayam-for-all/data/issues/336
[i376]: https://github.com/saayam-for-all/data/issues/376
[i380]: https://github.com/saayam-for-all/data/issues/380
[i506]: https://github.com/saayam-for-all/data/issues/506
[i539]: https://github.com/saayam-for-all/data/issues/539
[i569]: https://github.com/saayam-for-all/data/issues/569
[i583]: https://github.com/saayam-for-all/data/issues/583
[i604]: https://github.com/saayam-for-all/data/issues/604
[wiki]: https://github.com/saayam-for-all/ml/wiki/Super-Admin-Dashboard-Analytics-tab-Design
<!-- Pull requests -->
[pr272]: https://github.com/saayam-for-all/data/pull/272
[pr314]: https://github.com/saayam-for-all/data/pull/314
[pr414]: https://github.com/saayam-for-all/data/pull/414
[pr415]: https://github.com/saayam-for-all/data/pull/415
[pr419]: https://github.com/saayam-for-all/data/pull/419
[pr444]: https://github.com/saayam-for-all/data/pull/444
[pr445]: https://github.com/saayam-for-all/data/pull/445
[pr451]: https://github.com/saayam-for-all/data/pull/451
[pr471]: https://github.com/saayam-for-all/data/pull/471
[pr489]: https://github.com/saayam-for-all/data/pull/489
[pr490]: https://github.com/saayam-for-all/data/pull/490
[pr502]: https://github.com/saayam-for-all/data/pull/502
[pr503]: https://github.com/saayam-for-all/data/pull/503
[pr536]: https://github.com/saayam-for-all/data/pull/536
[pr537]: https://github.com/saayam-for-all/data/pull/537
[pr538]: https://github.com/saayam-for-all/data/pull/538
[pr541]: https://github.com/saayam-for-all/data/pull/541
[pr568]: https://github.com/saayam-for-all/data/pull/568
<!-- Data repo code, pinned to test @ f64938f -->
[data-test]: https://github.com/saayam-for-all/data/tree/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97
[growth]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/growth_trend_analytics.py
[growth-load]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/growth_trend_analytics.py#L12-L35
[growth-trend]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/growth_trend_analytics.py#L141-L179
[growth-location]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/growth_trend_analytics.py#L182-L220
[size]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/size_and_contribution.py
[size-chart]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/size_and_contribution.py#L150-L155
[size-contrib]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/size_and_contribution.py#L158-L173
[size-mock]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/size_and_contribution.py#L220-L262
[size-db]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/size_and_contribution.py#L282-L333
[size-switch]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/size_and_contribution.py#L355
[rating]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/rating_type_analytics.py
[rating-load]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/rating_type_analytics.py#L93-L153
[rating-join]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/rating_type_analytics.py#L127
[rating-dist]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/rating_type_analytics.py#L209-L215
[rating-mix]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/rating_type_analytics.py#L218-L241
[rating-custom]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/lambda_functions/rating_type_analytics.py#L384-L387
[size-old]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-engineering/src/organization_size_contribution_analytics/lambda_function.py
[size-old-tests]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-engineering/tests/test_organization_size_contribution_analytics.py
[main]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-engineering/src/main.py
[main-cols]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-engineering/src/main.py#L49-L56
[main-summary]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-engineering/src/main.py#L326-L365
[main-perf]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-engineering/src/main.py#L518-L552
[main-tests]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-engineering/tests/test_organization_analytics.py
[timefilters]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-engineering/src/utils/time_filters.py
[mock-dir]: https://github.com/saayam-for-all/data/tree/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/data-analytics/mock-data-generation
[mock-commit]: https://github.com/saayam-for-all/data/commit/35bdf0d988a77de070f4cb86c33e21a9222ee3fe
[dbinfo]: https://github.com/saayam-for-all/data/blob/f64938fef70d2a629f00d8edf9d39b4cd2dcfc97/database/mock-data-generation/db_info.json
[c-f2acf3c]: https://github.com/saayam-for-all/data/commit/f2acf3c
<!-- Webapp code, pinned to features/dashboard-analytics @ f5b940a -->
[web-tip]: https://github.com/saayam-for-all/webapp/commit/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85
[web-c1]: https://github.com/saayam-for-all/webapp/commit/64e68792fead2480db0824d08f051e5ee6f8004b
[web-c2]: https://github.com/saayam-for-all/webapp/commit/99fb66ee
[web-c3]: https://github.com/saayam-for-all/webapp/commit/508e04e108c528c15a3c5c97ba191de45c8edd34
[web-c4]: https://github.com/saayam-for-all/webapp/commit/343b1f75f119c7abcaf206f1cdbe4cabb2a9e06d
[web-org]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/components/Analytics/OrganizationAnalytics.jsx
[web-tabs]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/components/Analytics/OrganizationAnalytics.jsx#L30-L34
[web-filters]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/components/Analytics/OrganizationAnalytics.jsx#L303-L383
[web-kpis]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/components/Analytics/OrganizationAnalytics.jsx#L385-L418
[web-data]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/components/Analytics/organizationData.js
[web-test]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/components/Analytics/OrganizationAnalytics.test.jsx
[web-chartcontainer]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/components/Analytics/charts/ChartContainer.jsx
[web-appanalytics]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/components/Analytics/ApplicationAnalytics.jsx
[web-superadmin]: https://github.com/saayam-for-all/webapp/blob/f5b940ad3e9075a1743a7e3fae7dd75cd244dd85/src/pages/Dashboard/views/SuperAdminDashboard.jsx
