# Request Tab — Application Analytics (Super Admin Dashboard)

Issue: #602


## What this tab does

The Requests tab sits under Application Analytics and shows Super Admins two things: how many help requests are coming in over time, and what kind of requests they are, broken down by category and country. It's the tab that loads by default when you open Application Analytics — the other tabs are KPI, Beneficiaries, and Volunteers.

Original spec is in #82 and the team wiki (Super-Admin-Dashboard-Analytics-tab-Design).

## What's on screen

Two charts side by side:

- A line chart (Request Volume Trend) — number of requests per day/month, switchable between 7D, 30D, 1Y, All, or a custom date range.
- A stacked bar chart (Requests by Category & Region) — request counts per category, color-coded by country. Has its own filters: pick a category, pick a country, sort by total or name. Also shows a small "Top 5 countries" badge row above the chart.

## How a user gets there

1. Log in as Super Admin, go to Analytics → Application Analytics. Requests is already selected.
2. Both charts load together on "All" — one API call covers every preset range, so switching between 7D/30D/1Y/All doesn't trigger new requests, it just reads from the same cached response.
3. Picking Custom shows date pickers; once a valid start/end is set, that one chart fires its own API call.
4. The category/country/sort filters on the second chart don't touch the API at all — they just re-filter whatever data is already loaded, in the browser.

## Filters, where they actually run

Time range runs server-side (API decides what data comes back). Category, country, and sort are all client-side — filtering happens in React after the data's already in. Worth noting: the backend Lambda *does* accept category/country/sort_by as parameters, but the frontend never sends them. So there are technically two filtering paths and only one gets used.

## Where the data comes from

Postgres, schema `virginia_dev_saayam_rdbms`. The Lambda pulls DB credentials from SSM Parameter Store at runtime (`/dev/saayam/db/Virginia/Analytics/user`).

Tables involved: `request` (the main table — submission date, category id, requester id), `users` (to get the requester's country), `country` (country code), `help_categories` (category name). They're joined with INNER JOIN, which matters — any request missing a linked user, country, or category just disappears from the results instead of showing up as "unknown."

One thing worth flagging: "region" in this tab means the requester's own country, not where the help request is actually needed. Those aren't always the same thing.

## How the numbers are calculated

Both charts are just SQL aggregation — `COUNT(*)` grouped by `DATE_TRUNC` for the trend line, and grouped by category + country for the bar chart. No application-level math happening, it's all done in the query.

## How it's built

Frontend (React/Recharts) calls `POST v1/ml/requestApplicationAnalytics`, which hits an API Gateway route into a Lambda (`application_analytics_request.py`), which reads SSM for creds and queries Postgres directly.

Backend code merged via PR #167 (closes #146). Frontend wiring merged via PR #1608 (closes part of #1589).

## Task history, briefly

- #82 — original design ask, six analytics categories total, Requests being one of them
- #84 — early fake CSV data so frontend could build independently of real data
- #146 / PR #167 — spec and build for the real backend API, merged
- #189 — open PR, not merged, adds custom date-range support to the backend
- #1057 — RBAC work for which dashboard shows to which user group; closed, but I couldn't find a PR backing it up
- #1589 / PR #1608 — swapped the frontend off mock data onto the real API, merged

## Where it's actually broken right now

This is the part worth taking seriously, not just a formality:

**The category/region chart doesn't actually load any data in production.** The frontend expects response keys like `requests_by_category_region 7 days` (time-windowed, with a space in the key name). The merged backend only returns one flat key, `requests_by_category_region`, with no time window. They don't match, so the chart, its Top 5 badges, and its filters all quietly render empty.

**Custom date range is also dead.** Frontend sends `start_date` / `end_date` / `group_by`. Merged backend code never reads any of them.

**There's an open PR (#189) that fixes both of those** — but it has its own problems. It comments out the CORS headers on the success response, and it stops JSON-serializing the response body. If deployed as-is, it'll likely break the actual HTTP response shape coming back through API Gateway.

Smaller stuff:
- Backend still accepts category/country/sort filters nobody sends.
- DB credentials get parsed out of the SSM parameter by counting line positions in the string — fragile, breaks if that parameter's formatting ever changes.
- RBAC status on this tab is unclear — closed issue says it was built but disabled by a feature flag, no PR to confirm either way.

## Links

- Issues: #82, #84, #146, #1057, #1589
- PRs: #167, #189, #1608
- Design doc: Super-Admin-Dashboard-Analytics-tab-Design (wiki)