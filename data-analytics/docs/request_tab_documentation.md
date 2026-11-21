# Request Tab – Application Analytics (Super Admin Dashboard)

Issue: [#602](https://github.com/saayam-for-all/data/issues/602)

## Purpose

The Request tab gives Super Admins an overview of the help requests coming into Saayam. It answers two main questions: how request volume is changing over time, and which kinds of help are being requested in which countries.

This helps the team see whether demand is growing, notice spikes in a particular period, and understand which categories and regions need more volunteers or partner organizations. It also gives the organization numbers it can use when reporting on platform activity.

The tab lives under Dashboard → Analytics → Application Analytics. Application Analytics has four inner tabs (Requests, KPI, Beneficiaries and Volunteers), and Requests is the one that opens by default.

## Features

The tab has two charts, each with its own set of controls.

### Request Volume Trend

A line chart showing the number of requests over time. Above the chart there are five time range buttons:

- **7D** – daily counts for the last 7 days
- **30D** – daily counts for the last 30 days
- **1Y** – monthly counts for the last year
- **All** – currently shows the same data as 1Y
- **Custom** – opens a start date and end date picker so the admin can choose any period

Hovering over a point shows the date and the number of requests for that day or month.

### Requests by Category & Region

A stacked bar chart with one bar per help category (for example Food and Essentials). Each bar is split into coloured segments, one per country, so the admin can see both the total for a category and how it is spread across countries. India, United States, Canada, Australia and United Kingdom always use the same colours; other countries get a colour generated from their name.

This chart has its own time range buttons (7D, 30D, 1Y, All, Custom), separate from the trend chart, so the two charts can show different periods at the same time. It also has these controls:

- **Category selection** – a dropdown with checkboxes. By default all categories are included. The admin can pick specific categories, up to the current limit.
- **Category limit** – Top 5, Top 7 or Top 8. When no categories are picked, only this many categories (with the highest totals) are shown.
- **Country** – "All Countries" or a single country. With All Countries, the chart shows the top 5 countries by total requests.
- **Sort** – by total requests (highest first) or by category name.

## User flow

1. The Super Admin opens the Dashboard, switches to the Super Admin view and opens Analytics. The Analytics section opens on the Infrastructure sub-tab, so they select Application Analytics. The Requests tab loads by default.

2. When the tab loads, the webapp sends a single POST request with an empty body to `v1/ml/requestApplicationAnalytics`. While it waits, both charts show "Loading data...". The same response is shared by both charts, so the API is only called once at this stage.

3. Both charts start on the **All** range. When the admin clicks 7D, 30D or 1Y, the chart simply switches to the matching list from the response it already has. No new API call is made.

4. When the admin clicks **Custom**, two date pickers appear. The webapp checks the input before calling the API: if either date is empty it shows "Select a start and end date", and if the start date is after the end date it shows "Start date must be on or before end date". Once both dates are valid, it sends a new POST request with `start_date` and `end_date`. According to a comment in the code, the API decides whether to group the results by day or by month based on the length of the range. Each chart makes its own custom request, so choosing a custom range on one chart does not affect the other.

5. On the category chart, changing the category selection, limit, country or sort order does not call the API again. These controls filter and reorder the data already loaded in the browser.

6. Country codes returned by the API (either 2-letter or 3-letter codes) are converted to full country names before they are shown in the chart and the country dropdown.

7. If a chart has no data for the chosen period, it shows "No data available for the selected period". If the API reports an error, the chart shows the error message instead. If the request itself fails, it shows "Error:" followed by the reason.

## Filters

There are two kinds of filters on this tab: those that are sent to the API and those that are applied in the browser.

**Sent to the API.** Only the Custom date range is sent. When Custom is used, the request body contains `start_date` and `end_date` in YYYY-MM-DD format. For all other ranges the request body is empty.

**Applied in the browser.**
- The 7D, 30D, 1Y and All buttons choose which list from the response is shown.
- The category selection, category limit, country and sort controls on the category chart work on the loaded data only.

## Data sources

The backend is an AWS Lambda called `requestApplicationAnalytics`. It connects to the Virginia RDS PostgreSQL database, schema `virginia_dev_saayam_rdbms`. The Ireland database is not used.

The Lambda uses four tables:

- **request** – one row per help request. Columns used: `submission_date` (when the request was made), `req_user_id` (who made it) and `req_cat_id` (its help category).
- **users** – used to find the requester's country through `user_id` and `country_id`.
- **country** – used to turn `country_id` into a 3-letter `country_code` such as IND or USA.
- **help_categories** – used to turn `req_cat_id` into a category name through `cat_id` and `cat_name`.

The tables are joined like this: each request is linked to the user who created it, that user is linked to their country, and the request is linked to its category. Because of this, "region" in the charts means the country on the requester's profile, not the place where help is needed. Requests from users without a country are left out.

## Metrics and calculations

All counting is done in SQL, inside PostgreSQL.

### Request volume

For each time window, the Lambda counts requests whose `submission_date` falls within that window and groups them by day or month using `DATE_TRUNC`:

- **request_volume_7_days** – requests from the last 7 days, one count per day
- **request_volume_1_month** – requests from the last 30 days, one count per day
- **request_volume_1_year** – requests from the last year, one count per month

A few details to keep in mind:
- The windows are counted back from the current moment, not from calendar boundaries. For example, the first month in the 1-year view is usually a partial month.
- Days or months with no requests are not returned at all, rather than being returned as zero.
- Requests of every status are counted, including ones that were later cancelled.

Each entry looks like `{"date": "2026-06-01T00:00:00", "count": 3}`. The frontend drops the time part and shows only the date.

### Requests by category and country

The Lambda counts requests grouped by category name and country code, across all time. If the optional `category` or `country` inputs are given, only matching rows are counted. The results are ordered by count unless `sort_by` says otherwise.

Each entry looks like `{"category": "FOOD_AND_ESSENTIALS", "country": "IND", "count": 20}`.

### Top 5 countries

The Lambda counts requests per country across all time and returns the five highest, each with a rank from 1 to 5. This is returned as `top_countries`. The frontend does not use this list. Instead, it works out its own top 5 by adding up the category counts per country, and uses that to decide which countries appear in the category chart.

### Response

The Lambda returns status 200 with CORS headers, and the data as a JSON string in the response body. All five lists described above are always included, even if empty. If the database connection fails, it returns status 500 with the message "Failed to connect to database".

## Implementation approach

The Request tab was developed in three stages.

**Design.** [#82](https://github.com/saayam-for-all/data/issues/82) designed the Application Analytics section and defined the two Request charts: request volume over time and requests by category and region. 

**Mock data.** Since there was no real data in the database yet, [#84](https://github.com/saayam-for-all/data/issues/84) and its sub-task [#89](https://github.com/saayam-for-all/data/issues/89) created sample CSV data, converted it to JSON and shared it with the UI team. This let the frontend be built in parallel, with the plan to swap in real database queries later without changing the UI.

**Real database API.** [#146](https://github.com/saayam-for-all/data/issues/146) replaced the mock data with live queries. This was implemented in [PR#167](https://github.com/saayam-for-all/data/pull/167) as an AWS Lambda (`application_analytics_request.py`) that queries the Virginia PostgreSQL database and returns the volume trend, the category and region breakdown, and the top 5 countries. Credentials are read from AWS Parameter Store, and the counting is done in SQL.

On the frontend, the tab is the `RequestsAnalytics` component in the [webapp](https://github.com/saayam-for-all/webapp) repo. It calls the Lambda through API Gateway and draws both charts using the Recharts library.

### Code links

- Backend Lambda and tests: [PR#167 – files changed](https://github.com/saayam-for-all/data/pull/167/files)
- Frontend component: webapp `test` branch, `src/pages/Dashboard/components/Analytics/RequestsAnalytics.jsx`
- Frontend API call: webapp `src/services/analyticsServices.js` and `src/services/endpoints.json`

