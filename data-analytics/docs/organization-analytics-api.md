# Organization Analytics API

`POST /analytics/organizations` returns all three Organization Dashboard tabs in one response.

## Local configuration

The Lambda reads PostgreSQL connection settings from `DATABASE_URL` or from `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`. It does not read AWS Parameter Store.

The ticket's state lookup table is `virginia_dev_saayam_rdbms.states`. For an older local Saayam schema that still uses the singular table name, set:

```bash
export SAAYAM_STATE_TABLE=state
```

The handler checks `information_schema.columns` for `organizations.is_contributor`. Until that migration is present, contributor counts safely return `0` while all other metrics continue to work.

## Sample request

```json
{
  "time_filter": "1Y",
  "start_date": null,
  "end_date": null,
  "group_by": "monthly",
  "region": "California",
  "organization_type": "ALL"
}
```

Other local/PR test payloads:

```json
{"time_filter":"30D","start_date":null,"end_date":null,"group_by":"daily","region":"ALL","organization_type":"ALL"}
```

```json
{"time_filter":"1Y","start_date":null,"end_date":null,"group_by":"monthly","region":"ALL","organization_type":"ALL"}
```

```json
{"time_filter":"1Y","start_date":null,"end_date":null,"group_by":"monthly","region":"ALL","organization_type":"non_profit"}
```

```json
{"time_filter":"CUSTOM","start_date":"2026-01-01","end_date":"2026-06-30","group_by":"monthly","region":"ALL","organization_type":"ALL"}
```

Supported values:

- `time_filter`: `7D`, `30D`, `1Y`, `ALL`, `CUSTOM`
- `group_by`: `daily`, `weekly`, `monthly`, `yearly`
- `organization_type`: `ALL`, `for_profit`, `non_profit`
- `region`: `ALL`, a state name, or a state ID

`CUSTOM` requires both dates in `YYYY-MM-DD` format. The full `end_date` is included.

## Sample successful response body

```json
{
  "summary": {
    "total_organizations": 126,
    "total_collaborators": 42,
    "total_contributors": 84,
    "average_org_rating": 4.2
  },
  "growth_trend": [
    {
      "period": "2026-01",
      "total_organizations": 100,
      "total_collaborators": 34
    }
  ],
  "organizations_by_location": [
    {
      "state_id": "CA",
      "state_name": "California",
      "organization_count": 32,
      "percentage": 25.4,
      "cities": [
        {"city_name": "Los Angeles", "organization_count": 12}
      ]
    }
  ],
  "organizations_by_size": [
    {"org_size": "small", "organization_count": 50},
    {"org_size": "medium", "organization_count": 45},
    {"org_size": "large", "organization_count": 31}
  ],
  "collaborator_vs_contributor": [
    {"type": "collaborator", "organization_count": 42, "percentage": 33.3},
    {"type": "contributor", "organization_count": 84, "percentage": 66.7}
  ],
  "rating_distribution": [
    {"rating": 1, "organization_count": 1},
    {"rating": 2, "organization_count": 3},
    {"rating": 3, "organization_count": 12},
    {"rating": 4, "organization_count": 46},
    {"rating": 5, "organization_count": 64}
  ],
  "organization_type_distribution": [
    {"period": "2026-01", "for_profit": 41, "non_profit": 68, "total": 109}
  ]
}
```

API Gateway serializes this object in the response's `body` field. Invalid filters return HTTP `400`; a connection failure returns HTTP `500` with the stable empty dashboard structure.

## Local unit tests

```bash
python -m unittest discover -s data-analytics/tests -p "test_*.py" -v
```

The tests mock the PostgreSQL connection and cursor. They cover the documented filters, invalid input, custom date ranges, empty results, a missing `is_contributor` migration, query rollback/fallback behavior, connection failures, response shape, and resource cleanup.
