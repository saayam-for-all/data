# Organization Analytics API — Sample Responses (Issue #228)

All responses below were **captured from a real run** of `organization_analytics.py`
against a local PostgreSQL instance loaded with the real `organizations.csv` and
`state.csv` data from `data-analytics/sql/`.

The full automated suite (`test_organization_analytics.py`) validated:

- **52 / 52 checks passed**
- Both dashboards across all **5 time filters** — `7D`, `30D`, `1Y`, `All`, `Custom`
- All **4 `group_by`** options — `daily`, `weekly`, `monthly`, `yearly`
- Both **endpoint styles** — single-endpoint (`dashboard_type` param) and route-based
  (`/analytics/organizations/overview`, `/analytics/organizations/performance`)
- Additional filters — `org_type`, `org_size`, `state_id`, `is_collaborator`
- Exact response structure match against the spec + CORS headers on every response

> Numbers depend on the data in the local DB; the **structure is always identical**
> to what is shown here regardless of the underlying data.

---

## How to reproduce

```bash
# 1. Create a local DB and load the real organizations.csv and state.csv
#    from data-analytics/sql/ into your local PostgreSQL instance
createdb saayam_local

# 2. Run the full test suite (env vars have localhost defaults)
export PGHOST=localhost PGPORT=5432 PGDATABASE=saayam_local PGUSER=postgres PGPASSWORD=postgres
python test_organization_analytics.py          # summary
python test_organization_analytics.py --json   # + full JSON dumps
```

---

## Dashboard 1 — Organization Overview

**Request (route style):**
```
POST /analytics/organizations/overview
Content-Type: application/json

{ "time_filter": "All", "group_by": "monthly" }
```

**Request (single-endpoint style):**
```json
{ "dashboard_type": "overview", "time_filter": "All", "group_by": "monthly" }
```

**Response `body`:**
```json
{
  "organization_overview": {
    "summary": {
      "total_organizations": 40,
      "non_profit_organizations": 25,
      "for_profit_organizations": 15,
      "collaborator_organizations": 24,
      "non_collaborator_organizations": 16,
      "contributor_organizations": 16,
      "non_contributor_organizations": 24
    },
    "organization_activity_trend": [
      {"period": "2025-03", "count": 2},
      {"period": "2025-04", "count": 3},
      {"period": "2025-05", "count": 2},
      {"period": "2025-06", "count": 2},
      {"period": "2025-07", "count": 3},
      {"period": "2025-08", "count": 2},
      {"period": "2025-09", "count": 2},
      {"period": "2025-10", "count": 3},
      {"period": "2025-11", "count": 2},
      {"period": "2025-12", "count": 3},
      {"period": "2026-01", "count": 2},
      {"period": "2026-02", "count": 2},
      {"period": "2026-03", "count": 3},
      {"period": "2026-04", "count": 2},
      {"period": "2026-05", "count": 2},
      {"period": "2026-07", "count": 3},
      {"period": "2026-08", "count": 2}
    ],
    "organizations_by_type": [
      {"org_type": "non_profit", "label": "Non-Profit", "count": 25},
      {"org_type": "for_profit", "label": "For-Profit", "count": 15}
    ],
    "organizations_by_size": [
      {"org_size": "medium", "label": "Medium", "count": 15},
      {"org_size": "small",  "label": "Small",  "count": 15},
      {"org_size": "large",  "label": "Large",  "count": 10}
    ],
    "organizations_by_location": [
      {"state_id": "CA", "state_name": "California", "city_name": "San Francisco", "count": 4},
      {"state_id": "MD", "state_name": "Maryland",   "city_name": "Baltimore",     "count": 4},
      {"state_id": "NY", "state_name": "New York",   "city_name": "New York",      "count": 4},
      {"state_id": "TX", "state_name": "Texas",      "city_name": "Austin",        "count": 4},
      {"state_id": "VA", "state_name": "Virginia",   "city_name": "Alexandria",    "count": 4},
      {"state_id": "VA", "state_name": "Virginia",   "city_name": "Arlington",     "count": 4},
      {"state_id": "VA", "state_name": "Virginia",   "city_name": "Fairfax",       "count": 4},
      {"state_id": "VA", "state_name": "Virginia",   "city_name": "Norfolk",       "count": 4},
      {"state_id": "VA", "state_name": "Virginia",   "city_name": "Richmond",      "count": 4},
      {"state_id": "WA", "state_name": "Washington", "city_name": "Seattle",       "count": 4}
    ],
    "collaborator_distribution": [
      {"category": "Collaborator",     "is_collaborator": true,  "count": 24},
      {"category": "Non-Collaborator", "is_collaborator": false, "count": 16}
    ],
    "contributor_distribution": [
      {"category": "Contributor",     "is_contributor": true,  "count": 16},
      {"category": "Non-Contributor", "is_contributor": false, "count": 24}
    ]
  }
}
```

### Overview — `7D` filter (`group_by="daily"`)
```json
{
  "organization_overview": {
    "summary": {
      "total_organizations": 2,
      "non_profit_organizations": 1,
      "for_profit_organizations": 1,
      "collaborator_organizations": 2,
      "non_collaborator_organizations": 0,
      "contributor_organizations": 1,
      "non_contributor_organizations": 1
    },
    "organization_activity_trend": [ {"period": "2026-08-07", "count": 2} ],
    "organizations_by_type": [
      {"org_type": "non_profit", "label": "Non-Profit", "count": 1},
      {"org_type": "for_profit", "label": "For-Profit", "count": 1}
    ],
    "organizations_by_size": [
      {"org_size": "medium", "label": "Medium", "count": 1},
      {"org_size": "large",  "label": "Large",  "count": 1}
    ],
    "organizations_by_location": [
      {"state_id": "VA", "state_name": "Virginia", "city_name": "Alexandria", "count": 1},
      {"state_id": "VA", "state_name": "Virginia", "city_name": "Richmond",   "count": 1}
    ],
    "collaborator_distribution": [
      {"category": "Collaborator", "is_collaborator": true, "count": 2}
    ],
    "contributor_distribution": [
      {"category": "Contributor",     "is_contributor": true,  "count": 1},
      {"category": "Non-Contributor", "is_contributor": false, "count": 1}
    ]
  }
}
```

### Registration trend — all `group_by` options (`All` time)

**yearly:**
```json
[ {"period": "2025", "count": 24}, {"period": "2026", "count": 16} ]
```

**monthly:** 17 buckets (`2025-03` to `2026-08`) — see full response above.

**weekly (ISO week):**
```json
[ {"period": "2025-W10", "count": 1}, {"period": "2025-W12", "count": 1},
  {"period": "2026-W30", "count": 3}, {"period": "2026-W32", "count": 2} ]
```

**daily:** one bucket per registration date, e.g. `{"period": "2025-03-06", "count": 1}`.

---

## Dashboard 2 — Organization Performance

**Request (route style):**
```
POST /analytics/organizations/performance
Content-Type: application/json

{ "time_filter": "All" }
```

**Request (single-endpoint style):**
```json
{ "dashboard_type": "performance", "time_filter": "All" }
```

**Response `body`:**
```json
{
  "organization_performance": {
    "summary": {
      "average_rating": 3.0,
      "rated_organizations": 35,
      "unrated_organizations": 5,
      "five_star_organizations": 7
    },
    "rating_distribution": [
      {"rating": 1, "count": 7},
      {"rating": 2, "count": 7},
      {"rating": 3, "count": 7},
      {"rating": 4, "count": 7},
      {"rating": 5, "count": 7}
    ],
    "top_rated_organizations": [
      {"org_id": "ORG-00-000-000-034", "org_name": "Care Collective Trust",    "org_type": "for_profit", "org_size": "large",  "city_name": "San Francisco", "state_id": "CA", "org_rating": 5},
      {"org_id": "ORG-00-000-000-009", "org_name": "Community First Alliance", "org_type": "non_profit", "org_size": "medium", "city_name": "Fairfax",       "state_id": "VA", "org_rating": 5},
      {"org_id": "ORG-00-000-000-029", "org_name": "Gentle Wave Society",      "org_type": "non_profit", "org_size": "small",  "city_name": "Fairfax",       "state_id": "VA", "org_rating": 5}
    ],
    "top_collaborator_organizations": [
      {"org_id": "ORG-00-000-000-009", "org_name": "Community First Alliance", "org_type": "non_profit", "org_size": "medium", "city_name": "Fairfax", "state_id": "VA", "org_rating": 5}
    ],
    "top_contributor_organizations": [
      {"org_id": "ORG-00-000-000-001", "org_name": "Bright Future Alliance", "org_type": "non_profit", "org_size": "medium", "city_name": "Richmond", "state_id": "VA", "org_rating": 2}
    ],
    "ratings_by_organization_type": [
      {"org_type": "non_profit", "label": "Non-Profit", "average_rating": 3.05, "rated_count": 22},
      {"org_type": "for_profit", "label": "For-Profit", "average_rating": 2.92, "rated_count": 13}
    ],
    "ratings_by_organization_size": [
      {"org_size": "small",  "label": "Small",  "average_rating": 3.23, "rated_count": 13},
      {"org_size": "medium", "label": "Medium", "average_rating": 2.92, "rated_count": 13},
      {"org_size": "large",  "label": "Large",  "average_rating": 2.78, "rated_count": 9}
    ]
  }
}
```

### Performance summary across time filters

| time_filter | average_rating | rated | unrated | five_star |
|-------------|---------------:|------:|--------:|----------:|
| 7D          | 2.5            | 2     | 0       | 0         |
| 30D         | 3.0            | 5     | 0       | 1         |
| 1Y          | 2.92           | 24    | 4       | 4         |
| All         | 3.0            | 35    | 5       | 7         |
| Custom      | 3.0            | 35    | 5       | 7         |

---

## Full HTTP envelope

Every `lambda_handler` response is wrapped API-Gateway style:

```json
{
  "statusCode": 200,
  "headers": {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
  },
  "body": "<JSON string shown above>"
}
```

On a total DB failure the handler returns `statusCode: 500` with a well-shaped
empty body (correct top-level keys, zeroed summary, empty arrays) so the
front-end never has to special-case a missing structure.

---

## Filter reference

| Parameter             | Values / Example                                              |
|-----------------------|---------------------------------------------------------------|
| `dashboard_type`      | `overview` \| `performance` (ignored if route path present)  |
| `time_filter`         | `7D` \| `30D` \| `1Y` \| `All` \| `Custom` (default `ALL`)  |
| `start_date`, `end_date` | ISO dates, used when `time_filter="Custom"`               |
| `group_by`            | `daily` \| `weekly` \| `monthly` \| `yearly` (default `monthly`) |
| `org_type`            | `non_profit` \| `for_profit`                                  |
| `org_size`            | `small` \| `medium` \| `large`                                |
| `state_id`            | e.g. `VA`                                                     |
| `city_name`           | e.g. `Arlington`                                              |
| `org_rating`          | `1`–`5`                                                       |
| `is_collaborator`     | `true` \| `false`                                             |
| `is_contributor`      | `true` \| `false`                                             |

All values are bound as SQL parameters (`%s`) — no string interpolation of
user input, no hardcoded credentials anywhere.

---

## ⚠️ Schema note — `is_contributor`

The current upstream DDL (`ddl_organizations.sql`) defines `is_collaborator`
but **not** `is_contributor`, while Issue #228 requires contributor analytics.
`organization_analytics.py` references `o.is_contributor`. Until that column
is added to the real database, the contributor functions degrade gracefully to
their empty/default values — each query is wrapped in its own `try/except` so
the rest of each dashboard keeps working normally.