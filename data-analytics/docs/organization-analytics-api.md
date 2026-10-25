# Organization Analytics API

`organization_analytics.lambda_handler` provides both organization dashboards
through one POST handler. Set `dashboard_type` to `overview` or `performance`.

## Local configuration

The API uses PostgreSQL environment variables and does not read AWS Parameter
Store:

| Variable | Default |
| --- | --- |
| `DB_HOST` | `localhost` |
| `DB_PORT` | `5432` |
| `DB_NAME` | `saayam_db` |
| `DB_USER` | `postgres` |
| `DB_PASSWORD` | `postgres` |
| `DB_SCHEMA` | `virginia_dev_saayam_rdbms` |
| `DB_CONNECT_TIMEOUT` | `10` |

The PostgreSQL schema is expected to contain `organizations` and `state`, using
the columns in `sql/organizations.csv` and `sql/state.csv`. The API detects
whether `organizations.is_contributor` exists. Until that migration is applied,
all organizations are reported as non-contributors, top contributors is empty,
and filtering for contributors returns an empty result.

## Request

```json
{
  "dashboard_type": "overview",
  "time_filter": "30D",
  "start_date": null,
  "end_date": null,
  "org_type": null,
  "org_size": null,
  "state_id": null,
  "city_name": null,
  "org_rating": null,
  "is_collaborator": null,
  "is_contributor": null,
  "group_by": "daily"
}
```

Supported time filters are `7D`, `30D`, `1Y`, `ALL`, and `CUSTOM`. `CUSTOM`
requires inclusive `start_date` and `end_date` values in `YYYY-MM-DD` format.
Supported trend groupings are `daily`, `weekly`, `monthly`, and `yearly`.

## Sample responses

The following summaries were produced locally from the 40 rows in
`sql/organizations.csv` with `time_filter: "ALL"`.

Overview:

```json
{
  "organization_overview": {
    "summary": {
      "total_organizations": 40,
      "non_profit_organizations": 21,
      "for_profit_organizations": 19,
      "collaborator_organizations": 21,
      "non_collaborator_organizations": 19,
      "contributor_organizations": 19,
      "non_contributor_organizations": 21
    },
    "organization_activity_trend": [],
    "organizations_by_type": [],
    "organizations_by_size": [],
    "organizations_by_location": [],
    "collaborator_distribution": [],
    "contributor_distribution": []
  }
}
```

Performance:

```json
{
  "organization_performance": {
    "summary": {
      "average_rating": 3.23,
      "rated_organizations": 40,
      "unrated_organizations": 0,
      "five_star_organizations": 12
    },
    "rating_distribution": [
      {"rating": 1, "count": 5},
      {"rating": 2, "count": 9},
      {"rating": 3, "count": 10},
      {"rating": 4, "count": 4},
      {"rating": 5, "count": 12}
    ],
    "top_rated_organizations": [],
    "top_collaborator_organizations": [],
    "top_contributor_organizations": [],
    "ratings_by_organization_type": [],
    "ratings_by_organization_size": []
  }
}
```

Arrays are abbreviated above; live responses include their complete contents.

## Tests

From the repository root, with `psycopg2-binary` installed:

```bash
python3 -m unittest discover \
  -s data-analytics/lambda_functions \
  -p 'test_organization_analytics.py' \
  -v
```

Local PostgreSQL integration verification was performed twice: first with both
CSV files loaded exactly as supplied, then after dropping `is_contributor` to
verify compatibility with the current database schema.
