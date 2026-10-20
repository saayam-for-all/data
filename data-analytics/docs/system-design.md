# System Design Documentation — Data Engineering & Analytics Pipelines

> Issue #543 | `saayam-for-all/data`

---

## Table of Contents

1. [Repository Structure](#1-repository-structure)
2. [Lambda Function Architectures](#2-lambda-function-architectures)
   - [kpi_api_analytics.py](#21-kpi_api_analyticspy)
   - [beneficiariesTrendAnalysis.py](#22-beneficiariestrendanalysispy)
   - [volunteer_application_analytics.py](#23-volunteer_application_analyticspy)
   - [organization_rating_type_analytics.py](#24-organization_rating_type_analyticspy)
3. [Database Schema & Table Relationships](#3-database-schema--table-relationships)
4. [Data Access Layer](#4-data-access-layer)
5. [AWS Infrastructure](#5-aws-infrastructure)
6. [Developer Workflow & Local Testing](#6-developer-workflow--local-testing)

---

## 1. Repository Structure

```
data-analytics/
├── lambda_functions/
│   ├── kpi_api_analytics.py
│   ├── beneficiariesTrendAnalysis.py
│   ├── volunteer_application_analytics.py
│   ├── organization_rating_type_analytics.py
│   ├── mock_data/
│   │   ├── organizations.csv
│   │   ├── states.csv
│   │   └── countries.csv
│   └── tests/
│       └── test_organization_rating_type_analytics.py
├── sql/                    # Full-size mock CSVs for local development
└── docs/
    └── system-design.md    # This file
```

---

## 2. Lambda Function Architectures

### 2.1 `kpi_api_analytics.py`

**Purpose:** Request KPI dashboard — status distribution, total requests, and average resolution time across time buckets.

**Schema:** `virginia_dev_saayam_rdbms`

**Request payload:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `time_range` | string | No | `"Custom"` triggers a separate Custom-only response. Omit for consolidated response. |
| `start_date` | string | Only if `Custom` | `YYYY-MM-DD` |
| `end_date` | string | Only if `Custom` | `YYYY-MM-DD` |

**Response shapes:**

*Consolidated (no `time_range` in payload):*
```json
{
  "7D":       { "request_status_distribution": [...], "total_requests": [...], "average_resolution_time_by_category": [...] },
  "30D":      { ... },
  "1Y":       { ... },
  "All":      { ... },
  "Snapshot": { ... },
  "Custom":   { ... },
  "sla":      { "target_days": 10, "target_hours": 240, "warning_days": 8.33, "warning_hours": 200 }
}
```

*Custom (`time_range = "Custom"`):*
```json
{
  "request_status_distribution": [...],
  "total_requests": [...],
  "average_resolution_time_by_category": [...],
  "sla": { ... }
}
```

**Time-bucket aggregation logic:**

| Bucket | Grouping | Date format | Window |
|--------|----------|-------------|--------|
| `7D` | day | `YYYY-MM-DD` | Last 7 days |
| `30D` | day | `YYYY-MM-DD` | Last 30 days |
| `1Y` | month | `YYYY-MM` | Last 1 year |
| `All` | month | `YYYY-MM` | Last 2 years |
| `Snapshot` | none | — | All time, no period grouping |
| `Custom` | day | `YYYY-MM-DD` | `start_date` to `end_date` |

**Key queries:**

- `fetch_request_status_distribution` — joins `request` → `request_status`, groups by period and status
- `fetch_total_requests` — counts `request.req_id` per period
- `fetch_average_resolution_time_by_category` — joins `request` → `help_categories` → `request_status`, computes `AVG(EXTRACT(EPOCH FROM (serviced_date - submission_date)) / 3600)` for COMPLETED/RESOLVED requests only

**Error handling:** Each metric fetch is wrapped independently — one failure does not prevent the others from returning.

---

### 2.2 `beneficiariesTrendAnalysis.py`

**Purpose:** Beneficiary and help request trends by time and country, across Virginia and Ireland databases.

**Databases:** Virginia (`virginia_dev_saayam_rdbms`) + Ireland (`ireland_dev_saayam_rdbms`)

**Request payload:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `beneficiaries_start_date` | string | Yes | `YYYY-MM-DD` |
| `beneficiaries_end_date` | string | Yes | `YYYY-MM-DD` |
| `help_requests_start_date` | string | Yes | `YYYY-MM-DD` |
| `help_requests_end_date` | string | Yes | `YYYY-MM-DD` |

**Response shape:**
```json
{
  "7 days beneficiaries": [...],
  "1 month beneficiaries": [...],
  "1 year beneficiaries": [...],
  "Custom date range beneficiaries": [...],
  "Country beneficiaries": [{ "country": "India", "count": 42 }],
  "7 days help requests": [...],
  "1 month help requests": [...],
  "1 year help requests": [...],
  "Custom date range help requests": [...],
  "Country help requests": [...]
}
```

**Time buckets returned:** Always returns all buckets in one call (7 days, 1 month, 1 year, custom, country). Unlike other Lambdas, there is no separate Custom path — all ranges are resolved in a single invocation.

**Dual-database pattern:** Virginia and Ireland are queried independently. Currently only Virginia data is used (Ireland queries are commented out). Results are designed to be merged by country or period when both are active.

**Key tables:**

| Table | Usage |
|-------|-------|
| `request` | Beneficiary IDs, submission/update dates |
| `users` | Joined via `req_user_id = user_id` for country lookup |
| `country` | Country names via `u.country_id = c.country_id` |

---

### 2.3 `volunteer_application_analytics.py`

**Purpose:** Volunteer activity trends (new, active, cumulative total) and volunteer location breakdown, across Virginia and Ireland.

**Databases:** Virginia + Ireland

**Request payload:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `start_date` | string | No | Triggers Custom activity response only |
| `end_date` | string | No | Triggers Custom activity response only |
| `location_start_date` | string | No | Triggers Custom location response only |
| `location_end_date` | string | No | Triggers Custom location response only |
| `country` | string | No | Filter by country code, default `"All Countries"` |
| `chart_type` | string | No | Hint to frontend, default `"Bar Chart"` |
| `skill` | string | No | Filter by skill/category, default `"All Skills"` |

**Dual independent date ranges — important design detail:**

- `start_date` / `end_date` → controls **volunteer activity trend** Custom path only
- `location_start_date` / `location_end_date` → controls **volunteers by location** Custom path only
- These are evaluated independently. Sending `start_date` + `end_date` returns only the Custom activity block. Sending `location_start_date` + `location_end_date` returns only the Custom location block. Sending neither returns the full consolidated response.

**Response shape:**
```json
{
  "7D":  { "volunteer_activity_trend": { "new_volunteers": [...], "active_volunteers": [...], "total_volunteers": [...] }, "volunteers_by_location": [...] },
  "30D": { ... },
  "1Y":  { ... },
  "All": { ... },
  "Custom": { ... }
}
```

**Volunteer activity trend queries:**

| Metric | Logic |
|--------|-------|
| `new_volunteers` | COUNT DISTINCT users joined in period via `volunteer_details.created_at` |
| `active_volunteers` | Same as new but filtered to `user_status_id = 1` |
| `total_volunteers` | Cumulative running sum via `SUM(count) OVER (ORDER BY period)`. For Custom range, adds a base count of volunteers registered before `start_date`. |

**Key tables:**

| Table | Usage |
|-------|-------|
| `users` | Volunteer identity, status, country |
| `volunteer_details` | Join key and `created_at` for activity dating |
| `country` | Country code for location breakdown |
| `user_skills` | Skill filter via `cat_id` |
| `help_categories` | Skill name resolution |

---

### 2.4 `organization_rating_type_analytics.py`

**Purpose:** Organization rating distribution and type (for_profit / non_profit) mix trend over time.

**Data access:** Dual-mode — mock CSV files locally, PostgreSQL/RDS in production. Controlled by `USE_MOCK_DATA` environment variable.

**Request payload:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `rating_start_date` | string | No | Must be paired with `rating_end_date` |
| `rating_end_date` | string | No | Must be paired with `rating_start_date` |
| `type_start_date` | string | No | Must be paired with `type_end_date` |
| `type_end_date` | string | No | Must be paired with `type_start_date` |
| `country` | string | No | Filter by `country_code` |

**Dual independent date ranges:** `rating_start_date`/`rating_end_date` and `type_start_date`/`type_end_date` are validated and applied independently. Either, both, or neither can be provided. Providing only one date of a pair returns HTTP 400.

**Response shape:**
```json
{
  "7D":  { "rating_distribution": [...], "organization_mix_trend": { "for_profit": [...], "non_profit": [...] } },
  "30D": { ... },
  "1Y":  { ... },
  "All": { ... },
  "Custom": {
    "rating_distribution": [...],
    "organization_mix_trend": { "for_profit": [...], "non_profit": [...] }
  }
}
```

- Full 5-key response (`7D`, `30D`, `1Y`, `All`, `Custom`) is always returned in a single call.
- `Custom` keys are populated only when the corresponding date range is provided; otherwise they return empty arrays.

**Validation rules (HTTP 400):**
- Start/end dates must be provided together
- Dates must be in `YYYY-MM-DD` format
- `start_date` must not be after `end_date`
- Invalid JSON body returns HTTP 400

**Organization mix trend logic:** Computes a cumulative count per period using `created_at`, split by `org_type`. Only periods within the requested window are included in the output.

---

## 3. Database Schema & Table Relationships

### Core Tables

```
organizations
  org_id          PK
  org_size        enum: small | medium | large
  is_collaborator boolean
  is_contributor  boolean
  org_type        enum: for_profit | non_profit
  org_rating      integer (1–5)
  state_id        FK → states.state_id
  created_at      timestamp

states
  state_id        PK
  state_name      string
  country_id      FK → countries.country_id

countries
  country_id      PK
  country_code    string (e.g. "US", "IN")
  country_name    string

users
  user_id         PK
  country_id      FK → countries.country_id
  user_status_id  integer (1 = active)

requests  (table name: request)
  req_id          PK
  req_user_id     FK → users.user_id  (beneficiary)
  req_cat_id      FK → help_categories.cat_id
  req_status_id   FK → request_status.req_status_id
  submission_date timestamp
  serviced_date   timestamp
  last_update_date timestamp

request_status
  req_status_id   PK
  req_status      string (e.g. "Completed", "Resolved", "Pending")

help_categories
  cat_id          PK
  cat_name        string

volunteer_details
  user_id         FK → users.user_id
  created_at      timestamp

user_skills
  user_id         FK → users.user_id
  cat_id          FK → help_categories.cat_id

volunteer_applications
  (volunteer application records)

volunteer_locations / user_locations
  user_id         FK → users.user_id
  (location data)
```

### Key Join Patterns

**Request KPI:**
```sql
request r
  JOIN request_status rs ON r.req_status_id = rs.req_status_id
  JOIN help_categories hc ON r.req_cat_id = hc.cat_id
```

**Beneficiary by country:**
```sql
request
  JOIN users u ON request.req_user_id = u.user_id
  JOIN country c ON u.country_id = c.country_id
```

**Volunteer activity:**
```sql
users u
  JOIN volunteer_details vd ON u.user_id = vd.user_id
```

**Volunteer by location with skill filter:**
```sql
users u
  JOIN volunteer_details vd ON u.user_id = vd.user_id
  LEFT JOIN country c ON u.country_id = c.country_id
  -- skill filter:
  EXISTS (
    SELECT 1 FROM user_skills us
    JOIN help_categories h ON us.cat_id = h.cat_id
    WHERE us.user_id = u.user_id AND h.cat_name = %s
  )
```

**Organization rating/type:**
```sql
organizations o
  LEFT JOIN states s    ON o.state_id = s.state_id
  LEFT JOIN countries c ON s.country_id = c.country_id
```

---

## 4. Data Access Layer

### Dual Execution Pathways

| Mode | Trigger | Data source | Library |
|------|---------|-------------|---------|
| Mock (local) | `USE_MOCK_DATA=true` (default) | CSV files in `mock_data/` or `sql/` | `pandas.read_csv` |
| Production | `USE_MOCK_DATA=false` | PostgreSQL/RDS via AWS SSM credentials | `psycopg2` |

### Mock Data Resolution (`organization_rating_type_analytics.py`)

The data directory is resolved in this order:
1. `MOCK_DATA_DIR` environment variable
2. `mock_data/` subfolder next to the Lambda file (if it exists)
3. `../sql/` relative to the Lambda file

CSV files required: `organizations.csv`, `states.csv` (or `state.csv`), `countries.csv` (or `country.csv`).

### Production DB Connection (SSM)

All Lambdas retrieve credentials from AWS SSM Parameter Store:

| Lambda | SSM Parameter |
|--------|--------------|
| kpi_api_analytics | `/dev/saayam/db/Virginia/Analytics/user` |
| beneficiariesTrendAnalysis | `/dev/saayam/db/Virginia/Analytics/user` + `/dev/saayam/db/Ireland/Analytics/user` |
| volunteer_application_analytics | `/dev/saayam/db/Virginia/Analytics/user` + `/dev/saayam/db/Ireland/Analytics/user` |
| organization_rating_type_analytics | `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` env vars |

The SSM parameter value is a JSON string with keys: `HOST`, `USERNAME`, `PASSWORD`, `DATABASE NAME`, `PORT`.

---

## 5. AWS Infrastructure

### Lambda & API Gateway

| Setting | Value |
|---------|-------|
| Runtime | Python 3.x |
| Schema | `virginia_dev_saayam_rdbms` (Virginia), `ireland_dev_saayam_rdbms` (Ireland) |
| Region | `us-east-1` |
| CORS | `Access-Control-Allow-Origin: *` on all responses |

**Environment variables:**

| Variable | Used by | Description |
|----------|---------|-------------|
| `USE_MOCK_DATA` | organization_rating_type_analytics | `true` = use CSV files, `false` = use RDS |
| `MOCK_DATA_DIR` | organization_rating_type_analytics | Override path for mock CSV files |
| `DB_HOST` | organization_rating_type_analytics | RDS hostname (production mode) |
| `DB_NAME` | organization_rating_type_analytics | Database name (production mode) |
| `DB_USER` | organization_rating_type_analytics | DB username (production mode) |
| `DB_PASSWORD` | organization_rating_type_analytics | DB password (production mode) |
| `DB_PORT` | organization_rating_type_analytics | DB port, default `5432` |

**HTTP error codes:**

| Code | Condition |
|------|-----------|
| 200 | Success |
| 400 | Validation error (bad dates, missing paired field, invalid JSON) |
| 500 | DB connection failure or unhandled runtime error |

### S3 & RDS/PostgreSQL

- Mock CSV datasets are stored under `data-analytics/sql/` for local development
- Production data lives in Aurora PostgreSQL, accessed via psycopg2 / pg8000
- Connections are opened per invocation and closed in `finally` blocks

### CloudWatch & IAM

- All Lambdas use `print()` for logging — statements are routed to CloudWatch Logs automatically
- Each Lambda needs an IAM execution role with:
  - `ssm:GetParameter` on the relevant `/dev/saayam/db/...` parameter paths
  - `rds-db:connect` or VPC connectivity to the Aurora cluster
  - Standard `AWSLambdaBasicExecutionRole` for CloudWatch log writes

---

## 6. Developer Workflow & Local Testing

### Environment Setup

```bash
cd data-analytics/lambda_functions
pip install pandas psycopg2-binary boto3
export USE_MOCK_DATA=true
```

### Running Lambdas Locally

Each Lambda has a `if __name__ == "__main__":` block for standalone testing:

```bash
# KPI analytics — consolidated call
python kpi_api_analytics.py

# Organization rating/type — multiple scenarios
python organization_rating_type_analytics.py

# Volunteer analytics — empty event (consolidated)
python volunteer_application_analytics.py

# Beneficiaries trend — requires date params
python beneficiariesTrendAnalysis.py
```

### Local Test Scenarios (`organization_rating_type_analytics.py`)

The `__main__` block runs these scenarios automatically:

| Scenario | Event |
|----------|-------|
| No body | `{}` |
| Rating custom only | `{ "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30" }` |
| Type custom only | `{ "type_start_date": "2026-01-01", "type_end_date": "2026-06-30" }` |
| Both ranges | Both rating and type date ranges |
| Country filter | `{ "country": "USA" }` |
| Bad date format | `{ "rating_start_date": "01-01-2026", ... }` → HTTP 400 |
| Start after end | `{ "type_start_date": "2026-06-30", "type_end_date": "2026-01-01" }` → HTTP 400 |

### Automated Tests

```bash
cd data-analytics/lambda_functions
python -m pytest tests/test_organization_rating_type_analytics.py -v
```

### Mock Data Files

| File | Used by |
|------|---------|
| `mock_data/organizations.csv` | organization_rating_type_analytics |
| `mock_data/states.csv` | organization_rating_type_analytics |
| `mock_data/countries.csv` | organization_rating_type_analytics |
| `sql/organizations.csv` | Fallback for all analytics |
| `sql/requests.csv` | Local testing of KPI / beneficiary Lambdas |
| `sql/volunteer_applications.csv` | Local testing of volunteer analytics |
