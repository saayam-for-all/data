# Beneficiary Dashboard — Analytics Flow and Implementation

**Issue:** [saayam-for-all/data #603](https://github.com/saayam-for-all/data/issues/603)  
**Module:** Super Admin Dashboard → Analytics → Application Analytics → Beneficiaries  
**Suggested repository path:** `data-analytics/docs/issue_603_beneficiary_dashboard_analytics.md`

## 1. Purpose

The Beneficiaries tab helps Super Admins understand beneficiary-related activity. It shows how activity changes over time and how beneficiary-related records are distributed across countries. This document explains its features, user flow, data sources, calculations, implementation, development history, and limitations.

## 2. Dashboard Features and User Flow

The tab contains two charts:

- **Beneficiary Trend:** A line chart showing beneficiary-related activity over time.
- **Beneficiaries by Country:** A country-based visualization showing the geographic distribution of related records, with a Top 10 option.

An authorized administrator signs in, opens **Super Admin Dashboard → Analytics → Application Analytics → Beneficiaries**, selects a filter, and reviews the charts.

| Filter | Intended view |
|---|---|
| 7D | Last seven days |
| 30D | Last thirty days |
| 1Y | Last year |
| All | Available historical data |
| Custom | Selected start and end dates |

The frontend also provides Day/Month grouping for custom selections. Custom requests are made after both dates have been selected. These are frontend features; backend support for every option must be verified.

## 3. Previous Development Tasks

The following summaries explain the role of each task in developing the dashboard. They are based on the supplied reference review and linked issue descriptions; a complete independent check of every comment and attachment is still needed before claiming Issue #603 is fully reviewed.

### [Data #70 — Initial Trend Analysis](https://github.com/saayam-for-all/data/issues/70)
**What it was:** Early exploration of beneficiary trends and possible analytics calculations.  
**Why it matters:** Established an initial approach to grouping beneficiary-related data for charts.

### [Data #81 — Super Admin Analytics Dashboard](https://github.com/saayam-for-all/data/issues/81)
**What it was:** Planning the wider Super Admin analytics area.  
**Why it matters:** Established the dashboard structure in which the Beneficiaries tab appears.

### [Data #82 — Application Analytics Design](https://github.com/saayam-for-all/data/issues/82)
**What it was:** Defining chart and filter requirements for application analytics.  
**Why it matters:** Guided the beneficiary visualization design.

### [Data #84 — Test Data and Visualizations](https://github.com/saayam-for-all/data/issues/84)
**What it was:** Preparing sample analytics data and chart-ready outputs.  
**Why it matters:** Supported frontend development before full database integration.

### [Data #89 — Early Visualization Work](https://github.com/saayam-for-all/data/issues/89)
**What it was:** Preparing analytics visualizations and related data handoff.  
**Why it matters:** Connected early data exploration to chart development.

### [Data #138 — Beneficiary Analytics API](https://github.com/saayam-for-all/data/issues/138)
**What it was:** Replacing temporary or mock data processing with PostgreSQL-backed analytics.  
**Work requested:** Use AWS RDS data, account for Ireland data, handle empty results and errors, manage database connections, and test the Lambda.  
**Why it matters:** Intended to make the dashboard rely on application records instead of sample data.  
**Related backend PRs:** [#170](https://github.com/saayam-for-all/data/pull/170), [#172](https://github.com/saayam-for-all/data/pull/172), [#182](https://github.com/saayam-for-all/data/pull/182).

### [Data #302 — Database Schema Changes](https://github.com/saayam-for-all/data/issues/302)
**What it was:** Changes involving request tables and beneficiary identifiers.  
**Why it matters:** Older analytics SQL may need updates to match the current database schema.

### [Webapp #1518 — Beneficiary Frontend Integration](https://github.com/saayam-for-all/webapp/issues/1518)
**What it was:** Integrating the analytics API and refining the Beneficiaries tab.  
**Work discussed:** Two charts side by side; 7D/30D/1Y, All, and Custom filters; consistent chart controls; Top 10 country display; waiting for both custom dates before fetching.  
**Why it matters:** Connected analytics results to the interface used by administrators.  
**Related frontend PRs:** [#1530](https://github.com/saayam-for-all/webapp/pull/1530), [#1531](https://github.com/saayam-for-all/webapp/pull/1531), [#1597](https://github.com/saayam-for-all/webapp/pull/1597), [#1642](https://github.com/saayam-for-all/webapp/pull/1642), [#1811](https://github.com/saayam-for-all/webapp/pull/1811).

## 4. Data Sources

The reviewed backend uses PostgreSQL and reads database settings from AWS Systems Manager Parameter Store. Its queries refer to request, user, and country information:

| Data | Use |
|---|---|
| Request records | Identify beneficiary-related request activity |
| Request update timestamps | Group trends by day or month |
| User records | Associate requests with users |
| Country records | Group records by country |

The code references Virginia and Ireland environments, but the reviewed returned beneficiary results do not clearly include Ireland records. Current schema and deployment behavior need verification.

## 5. Metrics and Calculations

**Beneficiary Trend:** The reviewed query uses distinct combinations of requesting-user ID and request update timestamp, then groups them by day or month. Seven-day and 30-day periods use daily grouping; one-year uses monthly grouping; the reviewed custom calculation uses daily grouping. **This is request-related activity, not necessarily the count of unique registered beneficiaries.**

**Beneficiaries by Country:** The reviewed query joins requests, users, and countries and counts distinct requesting-user/country combinations. The country calculation does not apply the same date range as the trend chart, so their totals should not be treated as directly comparable.

## 6. Implementation Flow

1. The Super Admin opens the Beneficiaries tab.
2. The React component displays chart controls and requests analytics.
3. The analytics service calls `v1/ml/beneficiariesTrendAnalysis`.
4. The AWS Lambda connects to PostgreSQL and executes SQL queries.
5. Python/pandas groups results by time period and country.
6. The API returns analytics data for frontend charts.

**Frontend code:** [BeneficiariesAnalytics.jsx](https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/pages/Dashboard/components/Analytics/BeneficiariesAnalytics.jsx)  
**Service code:** [analyticsServices.js](https://github.com/saayam-for-all/webapp/blob/388534d902110bac4d4a38f7a4fc1cdbba8ac6ad/src/services/analyticsServices.js)  
**Backend code:** [beneficiariesTrendAnalysis.py](https://github.com/saayam-for-all/data/blob/a3b3d27abd95e366e6aab4b61b8c01e32be16c75/data-analytics/lambda_functions/beneficiariesTrendAnalysis.py)

## 7. Known Limitations and Questions

| Area | Finding or question |
|---|---|
| Metric definition | Does the product mean unique beneficiaries or request activity? |
| Regional coverage | Are Ireland records included in the deployed response? |
| API contract | Reviewed frontend and backend use different request/response field names. |
| Date filtering | Country counts do not follow the same date filters as trends. |
| Database schema | Are older table/column names still valid? |
| Error handling | Could some query failures appear as empty results? |

These are observations from reviewed versions, **not confirmed live-production failures**.

## 8. Testing and Verification

The supplied reference reports local backend checks with sample data/mocked connections and 32 passing frontend tests. These tests were **not independently rerun** for this document. Before final submission, verify the current API response, database schema, Virginia/Ireland coverage, custom dates, empty/error behavior, and frontend tests.

## 9. Conclusion

The Beneficiaries tab brings together chart controls, an analytics API, SQL queries, and PostgreSQL data to help Super Admins understand beneficiary-related activity. Development progressed from design and sample data to backend API work and frontend integration. The main open questions concern metric definitions, regional coverage, API compatibility, and current schema alignment.


