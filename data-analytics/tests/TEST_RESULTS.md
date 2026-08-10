# Organization Analytics API - Test Results (Issue #228)

**56/58 checks passed**, 2 skipped in 5.36s on the `postgres` backend.

| | |
|---|---|
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
| `sqlite` | SQLite 3.50.4 (in-memory, PostgreSQL shim) | 58/58 passed in 0.17s |
| `postgres` | PostgreSQL 16.14 | 56/58 passed, 2 skipped in 5.36s |

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

### Common filters

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_boolean_filter_accepts_strings` | String 'true'/'false' are coerced like real booleans. |
| PASS | `test_boolean_filters` | is_collaborator / is_contributor filter on both true and false. |
| PASS | `test_combined_filters_intersect` | Multiple filters combine with AND. |
| PASS | `test_custom_range_matches_oracle` | A CUSTOM window returns exactly the rows created inside it. |
| PASS | `test_custom_without_dates_raises` | CUSTOM without both bounds is a validation error. |
| PASS | `test_filters_apply_to_performance_dashboard_too` | The same filters narrow the performance dashboard. |
| PASS | `test_org_rating_filter_accepts_int_and_string` | org_rating filters correctly whether passed as int or string. |
| PASS | `test_org_size_filter` | Filtering by org_size returns exactly that size's rows. |
| PASS | `test_org_type_filter` | Filtering by org_type returns exactly that type's rows. |
| PASS | `test_state_and_city_filters` | state_id and city_name filters match the oracle. |
| PASS | `test_time_filters_are_monotonic` | 7D <= 30D <= 1Y <= ALL over the same fixture. |
| PASS | `test_unknown_time_filter_returns_everything` | An unrecognized time_filter applies no date restriction. |

### Contributor guard (ORG_IS_CONTRIBUTOR)

| Result | Check | What it verifies |
|---|---|---|
| SKIP | `test_guard_off_never_references_the_column` | No executed statement mentions is_contributor when disabled. |
| SKIP | `test_guard_off_still_references_it_when_enabled` | Sanity check: the recorder does see the column when enabled. |
| PASS | `test_guard_off_zeroes_contributor_metrics` | Disabled guard returns 0 / [] for every contributor metric. |
| PASS | `test_response_shape_is_identical_either_way` | Toggling the guard adds or drops no JSON keys. |

### Mock fixtures

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_booleans_are_real_booleans` | is_collaborator/is_contributor parse to bools, not strings. |
| PASS | `test_every_org_state_resolves` | Every state_id used by an organization exists in state.csv. |
| PASS | `test_organizations_fixture_loads` | organizations.csv loads with the columns the queries reference. |
| PASS | `test_state_fixture_loads` | state.csv loads and provides state_id -> state_name. |

### Lambda handler contract

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_body_is_json_encoded_string` | The body is a JSON string, as API Gateway proxy integration expects. |
| PASS | `test_connection_failure_returns_500` | A dead database surfaces as a 500 without leaking details. |
| PASS | `test_custom_without_dates_returns_400` | CUSTOM without start_date/end_date is a 400, not a 500. |
| PASS | `test_invalid_org_rating_returns_400` | A non-integer org_rating is rejected up front. |
| PASS | `test_missing_and_unknown_dashboard_type_default_to_overview` | An absent or unrecognized dashboard_type falls back to overview. |
| PASS | `test_overview_returns_200` | dashboard_type=overview returns 200 with the overview payload. |
| PASS | `test_performance_returns_200` | dashboard_type=performance returns 200 with the performance payload. |
| PASS | `test_response_envelope` | Responses carry JSON content-type and CORS headers. |
| PASS | `test_single_query_failure_degrades_to_default` | One failing query yields a safe default while the request stays 200. |

### No shared-database access (review feedback)

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_boto3_is_not_imported` | Importing the module must not pull in boto3. |
| PASS | `test_connection_refuses_to_guess_credentials` | With DB_HOST unset the connection raises instead of falling back. |
| PASS | `test_no_ssm_even_with_aws_environment_present` | AWS credentials in the environment do not unlock a fallback path. |
| PASS | `test_source_has_no_parameter_store_references` | No boto3/SSM/Parameter Store call sites remain in the module. |

### Dashboard 1 - Organization Overview

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_collaborator_summary` | Collaborator / non-collaborator counts match the oracle. |
| PASS | `test_contributor_summary_returns_real_values` | Contributor counts are real numbers now the fixture has the column. |
| PASS | `test_distributions_present` | Collaborator and contributor distributions total the fixture. |
| PASS | `test_non_profit_and_for_profit_counts` | Type summary matches the 'Non-Profit'/'For-profit' fixture labels. |
| PASS | `test_organizations_by_city` | by_city matches the oracle and totals every organization. |
| PASS | `test_organizations_by_size` | organizations_by_size covers Small/Medium/Large per the oracle. |
| PASS | `test_organizations_by_state` | by_state matches the oracle and resolves state_name via the join. |
| PASS | `test_organizations_by_type` | organizations_by_type matches the oracle and is sorted descending. |
| PASS | `test_registration_trend_groupings` | Every group_by totals the fixture and is ordered ascending. |
| PASS | `test_response_contains_every_required_key` | The payload matches the response structure named in the issue. |
| PASS | `test_total_organizations` | total_organizations equals the fixture row count. |
| PASS | `test_trend_period_formats` | Trend period strings use the format tied to each grouping. |
| PASS | `test_type_counts_partition_the_total` | Non-profit + for-profit accounts for every organization. |
| PASS | `test_unknown_group_by_falls_back_to_daily` | An unrecognized group_by degrades to the daily grouping. |
| PASS | `test_yearly_trend_matches_oracle` | Yearly buckets match the years present in created_at. |

### Dashboard 2 - Organization Performance

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_average_rating` | average_rating matches the mean of the fixture ratings. |
| PASS | `test_five_star_count` | five_star_organizations matches the oracle. |
| PASS | `test_rated_and_unrated_partition_the_total` | rated + unrated equals every organization. |
| PASS | `test_rating_distribution` | rating_distribution matches the oracle, ascending, ratings 1-5. |
| PASS | `test_ratings_by_organization_size` | Average rating per org_size matches the oracle. |
| PASS | `test_ratings_by_organization_type` | Average rating per org_type matches the oracle. |
| PASS | `test_response_contains_every_required_key` | The payload matches the response structure named in the issue. |
| PASS | `test_top_collaborator_organizations` | Collaborator leaderboard contains only collaborators. |
| PASS | `test_top_contributor_organizations` | Contributor leaderboard is populated and contains only contributors. |
| PASS | `test_top_rated_organizations` | Leaderboard is capped at TOP_N and ordered by rating descending. |

---

## Sample API responses

Generated by invoking `lambda_handler` against the mock fixtures.

### Overview - all organizations

Request:

```json
{
  "dashboard_type": "overview",
  "time_filter": "ALL",
  "group_by": "yearly"
}
```

Response (HTTP 200):

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
    "organization_activity_trend": [
      {
        "period": "2023",
        "count": 5
      },
      {
        "period": "2024",
        "count": 15
      },
      {
        "period": "2025",
        "count": 19
      },
      {
        "period": "2026",
        "count": 1
      }
    ],
    "organizations_by_type": [
      {
        "org_type": "Non-Profit",
        "count": 21
      },
      {
        "org_type": "For-profit",
        "count": 19
      }
    ],
    "organizations_by_size": [
      {
        "org_size": "Large",
        "count": 21
      },
      {
        "org_size": "Small",
        "count": 10
      },
      {
        "org_size": "Medium",
        "count": 9
      }
    ],
    "organizations_by_location": {
      "by_state": [
        {
          "state_id": "TX",
          "state_name": "Texas",
          "count": 3
        },
        {
          "state_id": "IN",
          "state_name": "Indiana",
          "count": 2
        },
        {
          "state_id": "FL",
          "state_name": "Florida",
          "count": 2
        },
        {
          "state_id": "IA",
          "state_name": "Iowa",
          "count": 2
        },
        {
          "state_id": "MT",
          "state_name": "Montana",
          "count": 2
        },
        {
          "state_id": "KS",
          "state_name": "Kansas",
          "count": 2
        },
        {
          "state_id": "MN",
          "state_name": "Minnesota",
          "count": 2
        },
        {
          "state_id": "NC",
          "state_name": "North Carolina",
          "count": 2
        },
        {
          "state_id": "AR",
          "state_name": "Arkansas",
          "count": 2
        },
        {
          "state_id": "RI",
          "state_name": "Rhode Island",
          "count": 2
        },
        {
          "state_id": "VT",
          "state_name": "Vermont",
          "count": 1
        },
        {
          "state_id": "WY",
          "state_name": "Wyoming",
          "count": 1
        },
        {
          "state_id": "AL",
          "state_name": "Alabama",
          "count": 1
        },
        {
          "state_id": "NJ",
          "state_name": "New Jersey",
          "count": 1
        },
        {
          "state_id": "WA",
          "state_name": "Washington",
          "count": 1
        },
        {
          "state_id": "WI",
          "state_name": "Wisconsin",
          "count": 1
        },
        {
          "state_id": "MO",
          "state_name": "Missouri",
          "count": 1
        },
        {
          "state_id": "UT",
          "state_name": "Utah",
          "count": 1
        },
        {
          "state_id": "NE",
          "state_name": "Nebraska",
          "count": 1
        },
        {
          "state_id": "AZ",
          "state_name": "Arizona",
          "count": 1
        },
        {
          "state_id": "AK",
          "state_name": "Alaska",
          "count": 1
        },
        {
          "state_id": "OH",
          "state_name": "Ohio",
          "count": 1
        },
        {
          "state_id": "CA",
          "state_name": "California",
          "count": 1
        },
        {
          "state_id": "VA",
          "state_name": "Virginia",
          "count": 1
        },
        {
          "state_id": "MI",
          "state_name": "Michigan",
          "count": 1
        },
        {
          "state_id": "NV",
          "state_name": "Nevada",
          "count": 1
        },
        {
          "state_id": "OK",
          "state_name": "Oklahoma",
          "count": 1
        },
        {
          "state_id": "OR",
          "state_name": "Oregon",
          "count": 1
        },
        {
          "state_id": "ME",
          "state_name": "Maine",
          "count": 1
        }
      ],
      "by_city": [
        {
          "city_name": "Kingborough",
          "count": 1
        },
        {
          "city_name": "New Amyhaven",
          "count": 1
        },
        {
          "city_name": "South Monicamouth",
          "count": 1
        },
        {
          "city_name": "East Jenniferfort",
          "count": 1
        },
        {
          "city_name": "Burchborough",
          "count": 1
        },
        {
          "city_name": "Lake Deniseville",
          "count": 1
        },
        {
          "city_name": "Martinezbury",
          "count": 1
        },
        {
          "city_name": "North Judithbury",
          "count": 1
        },
        {
          "city_name": "Smithberg",
          "count": 1
        },
        {
          "city_name": "South Williamton",
          "count": 1
        },
        {
          "city_name": "Victoriaport",
          "count": 1
        },
        {
          "city_name": "West Amandastad",
          "count": 1
        },
        {
          "city_name": "Johnberg",
          "count": 1
        },
        {
          "city_name": "Leehaven",
          "count": 1
        },
        {
          "city_name": "Stephaniemouth",
          "count": 1
        },
        {
          "city_name": "Port Andrew",
          "count": 1
        },
        {
          "city_name": "East Amanda",
          "count": 1
        },
        {
          "city_name": "New Thomas",
          "count": 1
        },
        {
          "city_name": "Ronaldview",
          "count": 1
        },
        {
          "city_name": "Lake Debbie",
          "count": 1
        },
        {
          "city_name": "New Susanville",
          "count": 1
        },
        {
          "city_name": "Barkerfurt",
          "count": 1
        },
        {
          "city_name": "Ortizmouth",
          "count": 1
        },
        {
          "city_name": "South Rachelborough",
          "count": 1
        },
        {
          "city_name": "North Donnaport",
          "count": 1
        },
        {
          "city_name": "Jeremyburgh",
          "count": 1
        },
        {
          "city_name": "Williamview",
          "count": 1
        },
        {
          "city_name": "Kyleborough",
          "count": 1
        },
        {
          "city_name": "Wendyville",
          "count": 1
        },
        {
          "city_name": "North Jamesborough",
          "count": 1
        },
        {
          "city_name": "Robertfort",
          "count": 1
        },
        {
          "city_name": "South Jeffrey",
          "count": 1
        },
        {
          "city_name": "Hortonberg",
          "count": 1
        },
        {
          "city_name": "Robinfort",
          "count": 1
        },
        {
          "city_name": "West Erik",
          "count": 1
        },
        {
          "city_name": "Lake Nancyview",
          "count": 1
        },
        {
          "city_name": "Mitchellside",
          "count": 1
        },
        {
          "city_name": "Thomasberg",
          "count": 1
        },
        {
          "city_name": "West Williamport",
          "count": 1
        },
        {
          "city_name": "Sandrastad",
          "count": 1
        }
      ]
    },
    "collaborator_distribution": [
      {
        "is_collaborator": true,
        "count": 21
      },
      {
        "is_collaborator": false,
        "count": 19
      }
    ],
    "contributor_distribution": [
      {
        "is_contributor": true,
        "count": 19
      },
      {
        "is_contributor": false,
        "count": 21
      }
    ]
  }
}
```

### Overview - non-profit collaborators only

Request:

```json
{
  "dashboard_type": "overview",
  "org_type": "Non-Profit",
  "is_collaborator": true,
  "group_by": "yearly"
}
```

Response (HTTP 200):

```json
{
  "organization_overview": {
    "summary": {
      "total_organizations": 11,
      "non_profit_organizations": 11,
      "for_profit_organizations": 0,
      "collaborator_organizations": 11,
      "non_collaborator_organizations": 0,
      "contributor_organizations": 0,
      "non_contributor_organizations": 11
    },
    "organization_activity_trend": [
      {
        "period": "2023",
        "count": 1
      },
      {
        "period": "2024",
        "count": 5
      },
      {
        "period": "2025",
        "count": 5
      }
    ],
    "organizations_by_type": [
      {
        "org_type": "Non-Profit",
        "count": 11
      }
    ],
    "organizations_by_size": [
      {
        "org_size": "Large",
        "count": 6
      },
      {
        "org_size": "Small",
        "count": 3
      },
      {
        "org_size": "Medium",
        "count": 2
      }
    ],
    "organizations_by_location": {
      "by_state": [
        {
          "state_id": "RI",
          "state_name": "Rhode Island",
          "count": 2
        },
        {
          "state_id": "AZ",
          "state_name": "Arizona",
          "count": 1
        },
        {
          "state_id": "CA",
          "state_name": "California",
          "count": 1
        },
        {
          "state_id": "FL",
          "state_name": "Florida",
          "count": 1
        },
        {
          "state_id": "ME",
          "state_name": "Maine",
          "count": 1
        },
        {
          "state_id": "MN",
          "state_name": "Minnesota",
          "count": 1
        },
        {
          "state_id": "NE",
          "state_name": "Nebraska",
          "count": 1
        },
        {
          "state_id": "NV",
          "state_name": "Nevada",
          "count": 1
        },
        {
          "state_id": "AR",
          "state_name": "Arkansas",
          "count": 1
        },
        {
          "state_id": "WA",
          "state_name": "Washington",
          "count": 1
        }
      ],
      "by_city": [
        {
          "city_name": "Barkerfurt",
          "count": 1
        },
        {
          "city_name": "Kyleborough",
          "count": 1
        },
        {
          "city_name": "Lake Nancyview",
          "count": 1
        },
        {
          "city_name": "Leehaven",
          "count": 1
        },
        {
          "city_name": "Martinezbury",
          "count": 1
        },
        {
          "city_name": "Mitchellside",
          "count": 1
        },
        {
          "city_name": "New Susanville",
          "count": 1
        },
        {
          "city_name": "Robertfort",
          "count": 1
        },
        {
          "city_name": "South Rachelborough",
          "count": 1
        },
        {
          "city_name": "Stephaniemouth",
          "count": 1
        },
        {
          "city_name": "West Amandastad",
          "count": 1
        }
      ]
    },
    "collaborator_distribution": [
      {
        "is_collaborator": true,
        "count": 11
      }
    ],
    "contributor_distribution": [
      {
        "is_contributor": false,
        "count": 11
      }
    ]
  }
}
```

### Performance - all organizations

Request:

```json
{
  "dashboard_type": "performance",
  "time_filter": "ALL"
}
```

Response (HTTP 200):

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
      {
        "rating": 1,
        "count": 5
      },
      {
        "rating": 2,
        "count": 9
      },
      {
        "rating": 3,
        "count": 10
      },
      {
        "rating": 4,
        "count": 4
      },
      {
        "rating": 5,
        "count": 12
      }
    ],
    "top_rated_organizations": [
      {
        "org_id": "ORG00019",
        "org_name": "Cedar Valley Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00036",
        "org_name": "Golden Gate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00001",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5
      },
      {
        "org_id": "ORG00011",
        "org_name": "Hopewell Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 5
      },
      {
        "org_id": "ORG00009",
        "org_name": "Lakeside Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5
      },
      {
        "org_id": "ORG00031",
        "org_name": "Maplewood Housing Trust",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5
      }
    ],
    "top_collaborator_organizations": [
      {
        "org_id": "ORG00019",
        "org_name": "Cedar Valley Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00036",
        "org_name": "Golden Gate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00011",
        "org_name": "Hopewell Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 5
      },
      {
        "org_id": "ORG00031",
        "org_name": "Maplewood Housing Trust",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00027",
        "org_name": "Silverline Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5
      },
      {
        "org_id": "ORG00020",
        "org_name": "Lakeside Legal Aid Society",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4
      },
      {
        "org_id": "ORG00023",
        "org_name": "Maplewood Veterans Support",
        "org_type": "For-profit",
        "org_size": "Medium",
        "org_rating": 4
      }
    ],
    "top_contributor_organizations": [
      {
        "org_id": "ORG00001",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5
      },
      {
        "org_id": "ORG00009",
        "org_name": "Lakeside Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00029",
        "org_name": "Unity Youth Alliance",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00035",
        "org_name": "Summit Relief Network",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4
      },
      {
        "org_id": "ORG00015",
        "org_name": "Unity Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 4
      },
      {
        "org_id": "ORG00006",
        "org_name": "Harbor Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Medium",
        "org_rating": 3
      },
      {
        "org_id": "ORG00024",
        "org_name": "Liberty Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3
      },
      {
        "org_id": "ORG00025",
        "org_name": "Maplewood Animal Rescue",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 3
      },
      {
        "org_id": "ORG00003",
        "org_name": "Northgate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 3
      }
    ],
    "ratings_by_organization_type": [
      {
        "org_type": "Non-Profit",
        "average_rating": 3.62,
        "rated_count": 21
      },
      {
        "org_type": "For-profit",
        "average_rating": 2.79,
        "rated_count": 19
      }
    ],
    "ratings_by_organization_size": [
      {
        "org_size": "Small",
        "average_rating": 3.5,
        "rated_count": 10
      },
      {
        "org_size": "Large",
        "average_rating": 3.24,
        "rated_count": 21
      },
      {
        "org_size": "Medium",
        "average_rating": 2.89,
        "rated_count": 9
      }
    ]
  }
}
```

### Performance - large organizations only

Request:

```json
{
  "dashboard_type": "performance",
  "org_size": "Large"
}
```

Response (HTTP 200):

```json
{
  "organization_performance": {
    "summary": {
      "average_rating": 3.24,
      "rated_organizations": 21,
      "unrated_organizations": 0,
      "five_star_organizations": 6
    },
    "rating_distribution": [
      {
        "rating": 1,
        "count": 2
      },
      {
        "rating": 2,
        "count": 6
      },
      {
        "rating": 3,
        "count": 4
      },
      {
        "rating": 4,
        "count": 3
      },
      {
        "rating": 5,
        "count": 6
      }
    ],
    "top_rated_organizations": [
      {
        "org_id": "ORG00019",
        "org_name": "Cedar Valley Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00029",
        "org_name": "Unity Youth Alliance",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00020",
        "org_name": "Lakeside Legal Aid Society",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4
      },
      {
        "org_id": "ORG00035",
        "org_name": "Summit Relief Network",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4
      },
      {
        "org_id": "ORG00015",
        "org_name": "Unity Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 4
      },
      {
        "org_id": "ORG00012",
        "org_name": "Harbor Animal Rescue",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3
      }
    ],
    "top_collaborator_organizations": [
      {
        "org_id": "ORG00019",
        "org_name": "Cedar Valley Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00020",
        "org_name": "Lakeside Legal Aid Society",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4
      },
      {
        "org_id": "ORG00012",
        "org_name": "Harbor Animal Rescue",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3
      },
      {
        "org_id": "ORG00021",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 2
      },
      {
        "org_id": "ORG00017",
        "org_name": "Liberty Education Fund",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 2
      },
      {
        "org_id": "ORG00016",
        "org_name": "Meadowbrook Legal Aid Society",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 2
      },
      {
        "org_id": "ORG00018",
        "org_name": "Sunrise Community Foundation",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 2
      }
    ],
    "top_contributor_organizations": [
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00029",
        "org_name": "Unity Youth Alliance",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5
      },
      {
        "org_id": "ORG00035",
        "org_name": "Summit Relief Network",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4
      },
      {
        "org_id": "ORG00015",
        "org_name": "Unity Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 4
      },
      {
        "org_id": "ORG00024",
        "org_name": "Liberty Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3
      },
      {
        "org_id": "ORG00025",
        "org_name": "Maplewood Animal Rescue",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 3
      },
      {
        "org_id": "ORG00030",
        "org_name": "Pinecrest Arts Collective",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3
      },
      {
        "org_id": "ORG00002",
        "org_name": "Summit Community Foundation",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 2
      },
      {
        "org_id": "ORG00033",
        "org_name": "Cedar Valley Health Initiative",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 1
      },
      {
        "org_id": "ORG00026",
        "org_name": "Lakeside Food Bank",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 1
      }
    ],
    "ratings_by_organization_type": [
      {
        "org_type": "Non-Profit",
        "average_rating": 3.73,
        "rated_count": 11
      },
      {
        "org_type": "For-profit",
        "average_rating": 2.7,
        "rated_count": 10
      }
    ],
    "ratings_by_organization_size": [
      {
        "org_size": "Large",
        "average_rating": 3.24,
        "rated_count": 21
      }
    ]
  }
}
```

### Validation error - CUSTOM without dates

Request:

```json
{
  "dashboard_type": "overview",
  "time_filter": "CUSTOM"
}
```

Response (HTTP 400):

```json
{
  "error": "start_date and end_date are required when time_filter is CUSTOM"
}
```

### Validation error - non-integer org_rating

Request:

```json
{
  "dashboard_type": "overview",
  "org_rating": "five"
}
```

Response (HTTP 400):

```json
{
  "error": "org_rating must be an integer"
}
```

### Database failure - connection refused

Request:

```json
{
  "dashboard_type": "overview"
}
```

Response (HTTP 500):

```json
{
  "error": "internal server error"
}
```

---

## Notes

- Every organization in the current fixture carries a rating, so `unrated_organizations` is 0 here. The metric and its SQL are still exercised (`rated + unrated == total`), but a fixture containing NULL ratings would give it a non-zero value to assert against.
- The default SQLite backend applies a small compatibility shim (`%s` placeholders, `INTERVAL` arithmetic, `::numeric`, `DATE_TRUNC`, `TO_CHAR`). Set `MOCK_DB_BACKEND=postgres` with `DB_*` pointing at a local PostgreSQL to run the identical assertions against real PostgreSQL; see `data-analytics/tests/mock_db.py`.
- `is_contributor` is present in the fixture, so contributor metrics return real values. `ORG_IS_CONTRIBUTOR=false` still suppresses them without referencing the column, for databases where the migration has not landed.
