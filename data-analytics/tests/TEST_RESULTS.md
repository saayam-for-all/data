# Organization Analytics API - Test Results (Issue #228)

**74/76 checks passed**, 2 skipped in 5.69s on the `postgres` backend.

| | |
|---|---|
| Endpoint | `POST /analytics/organizations` |
| Module under test | `data-analytics/lambda_functions/organization_analytics.py` |
| Data source | mock fixtures only - `data-analytics/sql/organizations.csv`, `data-analytics/sql/state.csv` |
| Organizations in fixture | 40 |
| States in fixture | 51 |
| Python | 3.14.3 |
| AWS / Parameter Store access | none - no boto3 import, no SSM call path |

### Backend coverage

The identical suite runs against both a real local PostgreSQL and a zero-dependency SQLite shim, so the SQL is verified on the engine it will actually run on and the suite stays runnable with no setup.

| Backend | Engine | Result |
|---|---|---|
| `sqlite` | SQLite 3.50.4 (in-memory, PostgreSQL shim) | 76/76 passed in 0.32s |
| `postgres` | PostgreSQL 16.14 | 74/76 passed, 2 skipped in 5.69s |

Reproduce with:

```bash
# zero-setup run (SQLite shim)
python data-analytics/tests/test_organization_analytics.py --emit-results

# against a local PostgreSQL
docker run -d --name saayam-pg -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_DB=saayam_local -p 55432:5432 postgres:16-alpine
MOCK_DB_BACKEND=postgres DB_HOST=localhost DB_PORT=55432 \
DB_NAME=saayam_local DB_USER=postgres DB_PASSWORD=postgres \
    python data-analytics/tests/test_organization_analytics.py
```

---

## Checks

### No shared-database access (review feedback)

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_boto3_is_not_imported` | Importing the module must not pull in boto3. |
| PASS | `test_connection_refuses_to_guess_credentials` | With DB_HOST unset the connection raises instead of falling back. |
| PASS | `test_no_ssm_even_with_aws_environment_present` | AWS credentials in the environment do not unlock a fallback path. |
| PASS | `test_source_has_no_parameter_store_references` | No boto3/SSM/Parameter Store call sites remain in the module. |

### Mock fixtures

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_booleans_are_real_booleans` | is_collaborator/is_contributor parse to bools, not strings. |
| PASS | `test_every_org_state_resolves` | Every state_id used by an organization exists in state.csv. |
| PASS | `test_organizations_fixture_loads` | organizations.csv loads with the columns the queries reference. |
| PASS | `test_state_fixture_loads` | state.csv loads and provides state_id -> state_name. |

### KPI cards

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_average_org_rating_ignores_nulls` | average_org_rating averages only the rated organizations. |
| PASS | `test_summary_has_exactly_the_four_cards` | summary carries the four documented keys and nothing else. |
| PASS | `test_total_collaborators` | total_collaborators counts organizations with is_collaborator true. |
| PASS | `test_total_contributors` | total_contributors counts organizations with is_contributor true. |
| PASS | `test_total_organizations` | total_organizations equals the fixture row count. |

### Tab 1 - Growth trend

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_final_point_matches_summary` | The last period equals the KPI totals. |
| PASS | `test_period_formats` | Trend period strings use the format tied to each grouping. |
| PASS | `test_periods_ascending_and_unique` | Every grouping returns ordered, non-repeating periods. |
| PASS | `test_row_shape` | Each point carries period, total_organizations, total_collaborators. |
| PASS | `test_series_are_cumulative` | Both series are non-decreasing across periods. |
| PASS | `test_yearly_trend_matches_oracle` | Yearly cumulative totals match a running count over created_at. |

### Tab 1 - Organizations by location

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_city_row_shape` | City rows carry their owning state for disambiguation. |
| PASS | `test_city_rows_match_oracle` | Per-city counts match the fixture and total every organization. |
| PASS | `test_state_percentages_total_100` | Percentages are shares of the filtered population. |
| PASS | `test_state_row_shape_and_names` | Each row has the documented keys and a resolved state_name. |
| PASS | `test_state_rows_match_oracle` | Per-state counts match the fixture. |
| PASS | `test_state_rows_sorted_by_count` | Rows are ordered by organization_count descending. |

### Tab 2 - Organizations by size

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_canonical_buckets_always_present_in_order` | All three buckets are returned, in small-medium-large order. |
| PASS | `test_counts_match_oracle` | Counts match the fixture, compared case-insensitively. |
| PASS | `test_counts_total_the_population` | Every organization lands in exactly one bucket. |
| PASS | `test_row_shape` | Each row carries org_size and organization_count. |

### Tab 2 - Collaborator vs contributor

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_counts_match_oracle` | Counts match the is_collaborator / is_contributor flags. |
| PASS | `test_percentages_are_share_of_population` | Each percentage is that flag's share of all filtered organizations. |
| PASS | `test_row_shape` | Each row carries type, organization_count and percentage. |
| PASS | `test_two_rows_in_documented_order` | Exactly the collaborator and contributor rows are returned. |

### Tab 3 - Rating distribution

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_counts_match_oracle` | Counts match the rated organizations in the fixture. |
| PASS | `test_full_scale_always_present` | Ratings 1 through 5 are returned in ascending order. |
| PASS | `test_null_ratings_are_excluded_not_fatal` | Unrated organizations are omitted from the buckets without error. |
| PASS | `test_row_shape` | Each row carries rating and organization_count. |

### Tab 3 - For-profit vs non-profit

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_final_point_matches_oracle` | The last period totals every organization, split by type. |
| PASS | `test_row_shape` | Each point carries period, for_profit, non_profit and total. |
| PASS | `test_series_are_cumulative` | Both series are non-decreasing across periods. |
| PASS | `test_total_is_the_sum_of_both_types` | total always equals for_profit + non_profit. |
| PASS | `test_yearly_split_matches_oracle` | Cumulative per-year splits match a running count over created_at. |

### Common filters

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_all_sentinel_means_unfiltered` | 'ALL' and null are both treated as no filter. |
| PASS | `test_combined_filters_intersect` | region and organization_type combine with AND. |
| PASS | `test_custom_range_matches_oracle` | A CUSTOM window returns exactly the rows created inside it. |
| PASS | `test_filters_apply_to_every_section` | A filter narrows every section consistently, not just the summary. |
| PASS | `test_organization_type_filter` | organization_type filters on the snake_case values. |
| PASS | `test_region_by_state_code` | region also accepts a state code. |
| PASS | `test_region_by_state_name` | region accepts a readable state name. |
| PASS | `test_region_is_case_insensitive` | region matching ignores case. |
| PASS | `test_time_filters_are_monotonic` | 7D <= 30D <= 1Y <= ALL over the same fixture. |

### Invalid filters

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_custom_without_dates_rejected` | CUSTOM without both bounds is a validation error. |
| PASS | `test_supported_values_accepted` | Every documented filter value parses without error. |
| PASS | `test_unknown_group_by_rejected` | An unsupported group_by is a validation error. |
| PASS | `test_unknown_organization_type_rejected` | An unsupported organization_type is a validation error. |
| PASS | `test_unknown_time_filter_rejected` | An unsupported time_filter is a validation error. |

### Empty result sets

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_collections_are_empty_or_zero_filled` | Trends empty out while fixed-scale sections stay zero-filled. |
| PASS | `test_matches_nothing` | The chosen filter genuinely selects no organizations. |
| PASS | `test_percentages_do_not_divide_by_zero` | Shares degrade to 0.0 rather than raising on an empty population. |
| PASS | `test_structure_is_still_complete` | Every documented key is present even with no matching rows. |
| PASS | `test_summary_is_zeroed` | All four KPI cards report zero, including the average. |

### Contributor guard (ORG_IS_CONTRIBUTOR)

| Result | Check | What it verifies |
|---|---|---|
| SKIP | `test_guard_off_never_references_the_column` | No executed statement mentions is_contributor when disabled. |
| PASS | `test_guard_off_zeroes_contributor_figures` | Disabled guard reports 0 contributors without dropping keys. |
| SKIP | `test_recorder_sees_the_column_when_enabled` | Sanity check: the guard really is what suppresses the column. |
| PASS | `test_response_shape_is_identical_either_way` | Toggling the guard adds or drops no JSON keys. |

### Lambda handler contract

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_accepts_api_gateway_string_body` | Filters are read from a JSON string body, as API Gateway sends. |
| PASS | `test_accepts_dict_body_and_bare_event` | A dict body and a bare invocation payload behave identically. |
| PASS | `test_body_is_json_encoded_string` | The body is a JSON string, as API Gateway proxy integration expects. |
| PASS | `test_connection_failure_returns_500` | A dead database surfaces as a 500 without leaking details. |
| PASS | `test_documented_sample_payloads_all_succeed` | Every sample payload in the issue returns 200. |
| PASS | `test_invalid_filters_return_400` | Every unsupported filter value surfaces as a 400 with a message. |
| PASS | `test_malformed_body_is_treated_as_no_filters` | An unparseable body does not crash the request. |
| PASS | `test_missing_and_empty_events` | None and {} are valid unfiltered requests. |
| PASS | `test_response_envelope` | Responses carry JSON content-type and CORS headers. |
| PASS | `test_returns_200_with_the_full_structure` | A standard request returns every documented top-level key. |
| PASS | `test_single_query_failure_degrades_to_default` | One failing query yields a safe default while the request stays 200. |

---

## Sample API responses

Generated by invoking `lambda_handler` against the mock fixtures. The first five payloads are the sample payloads from the issue, verbatim.

### Standard test

Request:

```json
{
  "time_filter": "30D",
  "start_date": null,
  "end_date": null,
  "group_by": "daily",
  "region": "ALL",
  "organization_type": "ALL"
}
```

Response (HTTP 200):

```json
{
  "summary": {
    "total_organizations": 0,
    "total_collaborators": 0,
    "total_contributors": 0,
    "average_org_rating": 0.0
  },
  "growth_trend": [],
  "organizations_by_location": [],
  "organizations_by_city": [],
  "organizations_by_size": [
    {
      "org_size": "small",
      "organization_count": 0
    },
    {
      "org_size": "medium",
      "organization_count": 0
    },
    {
      "org_size": "large",
      "organization_count": 0
    }
  ],
  "collaborator_vs_contributor": [
    {
      "type": "collaborator",
      "organization_count": 0,
      "percentage": 0.0
    },
    {
      "type": "contributor",
      "organization_count": 0,
      "percentage": 0.0
    }
  ],
  "rating_distribution": [
    {
      "rating": 1,
      "organization_count": 0
    },
    {
      "rating": 2,
      "organization_count": 0
    },
    {
      "rating": 3,
      "organization_count": 0
    },
    {
      "rating": 4,
      "organization_count": 0
    },
    {
      "rating": 5,
      "organization_count": 0
    }
  ],
  "organization_type_distribution": []
}
```

### Last 12 months

Request:

```json
{
  "time_filter": "1Y",
  "start_date": null,
  "end_date": null,
  "group_by": "monthly",
  "region": "ALL",
  "organization_type": "ALL"
}
```

Response (HTTP 200):

```json
{
  "summary": {
    "total_organizations": 11,
    "total_collaborators": 5,
    "total_contributors": 6,
    "average_org_rating": 2.73
  },
  "growth_trend": [
    {
      "period": "2025-09",
      "total_organizations": 3,
      "total_collaborators": 2
    },
    {
      "period": "2025-10",
      "total_organizations": 4,
      "total_collaborators": 3
    },
    {
      "period": "2025-11",
      "total_organizations": 7,
      "total_collaborators": 4
    },
    {
      "period": "2025-12",
      "total_organizations": 10,
      "total_collaborators": 5
    },
    {
      "period": "2026-01",
      "total_organizations": 11,
      "total_collaborators": 5
    }
  ],
  "organizations_by_location": [
    {
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 3,
      "percentage": 27.3
    },
    {
      "state_id": "FL",
      "state_name": "Florida",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "state_id": "ME",
      "state_name": "Maine",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "state_id": "MI",
      "state_name": "Michigan",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "state_id": "MN",
      "state_name": "Minnesota",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "state_id": "MO",
      "state_name": "Missouri",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "state_id": "NC",
      "state_name": "North Carolina",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "state_id": "NE",
      "state_name": "Nebraska",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "state_id": "OH",
      "state_name": "Ohio",
      "organization_count": 1,
      "percentage": 9.1
    }
  ],
  "organizations_by_city": [
    {
      "city_name": "Barkerfurt",
      "state_id": "NE",
      "state_name": "Nebraska",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "city_name": "East Jenniferfort",
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "city_name": "Hortonberg",
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "city_name": "Lake Deniseville",
      "state_id": "MO",
      "state_name": "Missouri",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "city_name": "Lake Nancyview",
      "state_id": "MN",
      "state_name": "Minnesota",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "city_name": "Martinezbury",
      "state_id": "ME",
      "state_name": "Maine",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "city_name": "Robinfort",
      "state_id": "NC",
      "state_name": "North Carolina",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "city_name": "South Jeffrey",
      "state_id": "OH",
      "state_name": "Ohio",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "city_name": "Victoriaport",
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "city_name": "West Amandastad",
      "state_id": "FL",
      "state_name": "Florida",
      "organization_count": 1,
      "percentage": 9.1
    },
    {
      "city_name": "West Williamport",
      "state_id": "MI",
      "state_name": "Michigan",
      "organization_count": 1,
      "percentage": 9.1
    }
  ],
  "organizations_by_size": [
    {
      "org_size": "small",
      "organization_count": 2
    },
    {
      "org_size": "medium",
      "organization_count": 2
    },
    {
      "org_size": "large",
      "organization_count": 7
    }
  ],
  "collaborator_vs_contributor": [
    {
      "type": "collaborator",
      "organization_count": 5,
      "percentage": 45.5
    },
    {
      "type": "contributor",
      "organization_count": 6,
      "percentage": 54.5
    }
  ],
  "rating_distribution": [
    {
      "rating": 1,
      "organization_count": 3
    },
    {
      "rating": 2,
      "organization_count": 2
    },
    {
      "rating": 3,
      "organization_count": 3
    },
    {
      "rating": 4,
      "organization_count": 1
    },
    {
      "rating": 5,
      "organization_count": 2
    }
  ],
  "organization_type_distribution": [
    {
      "period": "2025-09",
      "for_profit": 1,
      "non_profit": 2,
      "total": 3
    },
    {
      "period": "2025-10",
      "for_profit": 1,
      "non_profit": 3,
      "total": 4
    },
    {
      "period": "2025-11",
      "for_profit": 2,
      "non_profit": 5,
      "total": 7
    },
    {
      "period": "2025-12",
      "for_profit": 3,
      "non_profit": 7,
      "total": 10
    },
    {
      "period": "2026-01",
      "for_profit": 3,
      "non_profit": 8,
      "total": 11
    }
  ]
}
```

### Filter by region

Request:

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

Response (HTTP 200):

```json
{
  "summary": {
    "total_organizations": 0,
    "total_collaborators": 0,
    "total_contributors": 0,
    "average_org_rating": 0.0
  },
  "growth_trend": [],
  "organizations_by_location": [],
  "organizations_by_city": [],
  "organizations_by_size": [
    {
      "org_size": "small",
      "organization_count": 0
    },
    {
      "org_size": "medium",
      "organization_count": 0
    },
    {
      "org_size": "large",
      "organization_count": 0
    }
  ],
  "collaborator_vs_contributor": [
    {
      "type": "collaborator",
      "organization_count": 0,
      "percentage": 0.0
    },
    {
      "type": "contributor",
      "organization_count": 0,
      "percentage": 0.0
    }
  ],
  "rating_distribution": [
    {
      "rating": 1,
      "organization_count": 0
    },
    {
      "rating": 2,
      "organization_count": 0
    },
    {
      "rating": 3,
      "organization_count": 0
    },
    {
      "rating": 4,
      "organization_count": 0
    },
    {
      "rating": 5,
      "organization_count": 0
    }
  ],
  "organization_type_distribution": []
}
```

### Filter by organization type

Request:

```json
{
  "time_filter": "1Y",
  "start_date": null,
  "end_date": null,
  "group_by": "monthly",
  "region": "ALL",
  "organization_type": "non_profit"
}
```

Response (HTTP 200):

```json
{
  "summary": {
    "total_organizations": 8,
    "total_collaborators": 4,
    "total_contributors": 4,
    "average_org_rating": 3.0
  },
  "growth_trend": [
    {
      "period": "2025-09",
      "total_organizations": 2,
      "total_collaborators": 1
    },
    {
      "period": "2025-10",
      "total_organizations": 3,
      "total_collaborators": 2
    },
    {
      "period": "2025-11",
      "total_organizations": 5,
      "total_collaborators": 3
    },
    {
      "period": "2025-12",
      "total_organizations": 7,
      "total_collaborators": 4
    },
    {
      "period": "2026-01",
      "total_organizations": 8,
      "total_collaborators": 4
    }
  ],
  "organizations_by_location": [
    {
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 2,
      "percentage": 25.0
    },
    {
      "state_id": "FL",
      "state_name": "Florida",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "state_id": "ME",
      "state_name": "Maine",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "state_id": "MI",
      "state_name": "Michigan",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "state_id": "MN",
      "state_name": "Minnesota",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "state_id": "NC",
      "state_name": "North Carolina",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "state_id": "NE",
      "state_name": "Nebraska",
      "organization_count": 1,
      "percentage": 12.5
    }
  ],
  "organizations_by_city": [
    {
      "city_name": "Barkerfurt",
      "state_id": "NE",
      "state_name": "Nebraska",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "city_name": "Hortonberg",
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "city_name": "Lake Nancyview",
      "state_id": "MN",
      "state_name": "Minnesota",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "city_name": "Martinezbury",
      "state_id": "ME",
      "state_name": "Maine",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "city_name": "Robinfort",
      "state_id": "NC",
      "state_name": "North Carolina",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "city_name": "Victoriaport",
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "city_name": "West Amandastad",
      "state_id": "FL",
      "state_name": "Florida",
      "organization_count": 1,
      "percentage": 12.5
    },
    {
      "city_name": "West Williamport",
      "state_id": "MI",
      "state_name": "Michigan",
      "organization_count": 1,
      "percentage": 12.5
    }
  ],
  "organizations_by_size": [
    {
      "org_size": "small",
      "organization_count": 1
    },
    {
      "org_size": "medium",
      "organization_count": 1
    },
    {
      "org_size": "large",
      "organization_count": 6
    }
  ],
  "collaborator_vs_contributor": [
    {
      "type": "collaborator",
      "organization_count": 4,
      "percentage": 50.0
    },
    {
      "type": "contributor",
      "organization_count": 4,
      "percentage": 50.0
    }
  ],
  "rating_distribution": [
    {
      "rating": 1,
      "organization_count": 2
    },
    {
      "rating": 2,
      "organization_count": 1
    },
    {
      "rating": 3,
      "organization_count": 2
    },
    {
      "rating": 4,
      "organization_count": 1
    },
    {
      "rating": 5,
      "organization_count": 2
    }
  ],
  "organization_type_distribution": [
    {
      "period": "2025-09",
      "for_profit": 0,
      "non_profit": 2,
      "total": 2
    },
    {
      "period": "2025-10",
      "for_profit": 0,
      "non_profit": 3,
      "total": 3
    },
    {
      "period": "2025-11",
      "for_profit": 0,
      "non_profit": 5,
      "total": 5
    },
    {
      "period": "2025-12",
      "for_profit": 0,
      "non_profit": 7,
      "total": 7
    },
    {
      "period": "2026-01",
      "for_profit": 0,
      "non_profit": 8,
      "total": 8
    }
  ]
}
```

### Custom date range

Request:

```json
{
  "time_filter": "CUSTOM",
  "start_date": "2026-01-01",
  "end_date": "2026-06-30",
  "group_by": "monthly",
  "region": "ALL",
  "organization_type": "ALL"
}
```

Response (HTTP 200):

```json
{
  "summary": {
    "total_organizations": 1,
    "total_collaborators": 0,
    "total_contributors": 1,
    "average_org_rating": 1.0
  },
  "growth_trend": [
    {
      "period": "2026-01",
      "total_organizations": 1,
      "total_collaborators": 0
    }
  ],
  "organizations_by_location": [
    {
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 1,
      "percentage": 100.0
    }
  ],
  "organizations_by_city": [
    {
      "city_name": "Hortonberg",
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 1,
      "percentage": 100.0
    }
  ],
  "organizations_by_size": [
    {
      "org_size": "small",
      "organization_count": 0
    },
    {
      "org_size": "medium",
      "organization_count": 1
    },
    {
      "org_size": "large",
      "organization_count": 0
    }
  ],
  "collaborator_vs_contributor": [
    {
      "type": "collaborator",
      "organization_count": 0,
      "percentage": 0.0
    },
    {
      "type": "contributor",
      "organization_count": 1,
      "percentage": 100.0
    }
  ],
  "rating_distribution": [
    {
      "rating": 1,
      "organization_count": 1
    },
    {
      "rating": 2,
      "organization_count": 0
    },
    {
      "rating": 3,
      "organization_count": 0
    },
    {
      "rating": 4,
      "organization_count": 0
    },
    {
      "rating": 5,
      "organization_count": 0
    }
  ],
  "organization_type_distribution": [
    {
      "period": "2026-01",
      "for_profit": 0,
      "non_profit": 1,
      "total": 1
    }
  ]
}
```

### Filter by region - Texas (present in the fixture)

Request:

```json
{
  "time_filter": "ALL",
  "start_date": null,
  "end_date": null,
  "group_by": "yearly",
  "region": "Texas",
  "organization_type": "ALL"
}
```

Response (HTTP 200):

```json
{
  "summary": {
    "total_organizations": 3,
    "total_collaborators": 1,
    "total_contributors": 2,
    "average_org_rating": 2.0
  },
  "growth_trend": [
    {
      "period": "2025",
      "total_organizations": 2,
      "total_collaborators": 1
    },
    {
      "period": "2026",
      "total_organizations": 3,
      "total_collaborators": 1
    }
  ],
  "organizations_by_location": [
    {
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 3,
      "percentage": 100.0
    }
  ],
  "organizations_by_city": [
    {
      "city_name": "East Jenniferfort",
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 1,
      "percentage": 33.3
    },
    {
      "city_name": "Hortonberg",
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 1,
      "percentage": 33.3
    },
    {
      "city_name": "Victoriaport",
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 1,
      "percentage": 33.3
    }
  ],
  "organizations_by_size": [
    {
      "org_size": "small",
      "organization_count": 0
    },
    {
      "org_size": "medium",
      "organization_count": 1
    },
    {
      "org_size": "large",
      "organization_count": 2
    }
  ],
  "collaborator_vs_contributor": [
    {
      "type": "collaborator",
      "organization_count": 1,
      "percentage": 33.3
    },
    {
      "type": "contributor",
      "organization_count": 2,
      "percentage": 66.7
    }
  ],
  "rating_distribution": [
    {
      "rating": 1,
      "organization_count": 1
    },
    {
      "rating": 2,
      "organization_count": 1
    },
    {
      "rating": 3,
      "organization_count": 1
    },
    {
      "rating": 4,
      "organization_count": 0
    },
    {
      "rating": 5,
      "organization_count": 0
    }
  ],
  "organization_type_distribution": [
    {
      "period": "2025",
      "for_profit": 1,
      "non_profit": 1,
      "total": 2
    },
    {
      "period": "2026",
      "for_profit": 1,
      "non_profit": 2,
      "total": 3
    }
  ]
}
```

### Validation error - CUSTOM without dates

Request:

```json
{
  "time_filter": "CUSTOM"
}
```

Response (HTTP 400):

```json
{
  "error": "start_date and end_date are required when time_filter is CUSTOM"
}
```

### Validation error - unsupported organization_type

Request:

```json
{
  "organization_type": "charity"
}
```

Response (HTTP 400):

```json
{
  "error": "organization_type must be one of for_profit, non_profit or ALL; got 'charity'"
}
```

### Database failure - connection refused

Request:

```json
{}
```

Response (HTTP 500):

```json
{
  "error": "internal server error"
}
```

---

## Notes

- `growth_trend` and `organization_type_distribution` are **cumulative** running totals, matching the figures in the issue (its stacked-bar sample reaches 109 then 111 against a 126 total, which only holds if each period reports the total reached rather than the number added).
- The fixture contains 0 organizations with a NULL rating. NULL handling is still exercised: unrated rows are excluded from the buckets and from the average without error, and `rating_distribution` always returns the full 1-5 scale zero-filled.
- `region` resolves through the `state` lookup table and accepts either a readable state name (`California`) or a state code (`CA`), case-insensitively.
- The default SQLite backend applies a small compatibility shim (`%s` placeholders, `INTERVAL` arithmetic, `::numeric`, `DATE_TRUNC`, `TO_CHAR`). Set `MOCK_DB_BACKEND=postgres` with `DB_*` pointing at a local PostgreSQL to run the identical assertions against real PostgreSQL; see `data-analytics/tests/mock_db.py`.
- `is_contributor` is present in the fixture, so contributor figures return real values. `ORG_IS_CONTRIBUTOR=false` still suppresses them without referencing the column, for databases where the migration has not landed.
