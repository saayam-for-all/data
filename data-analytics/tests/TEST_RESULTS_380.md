# Rating & Type Analytics API - Test Results (Issue #380)

**62/62 checks passed** in 0.39s.

| | |
|---|---|
| Module under test | `data-analytics/lambda_functions/rating_type_analytics.py` |
| Data source | mock CSVs only - `organizations.csv`, `state.csv`, `country.csv` |
| Organizations in fixture | 40 |
| Reference date for fixed buckets | 2026-09-25 (pinned) |
| Python | 3.12.7 |
| pandas | 2.2.2 |
| AWS / Parameter Store access | none |

### Response-shape rules verified

| Request | Top-level keys |
|---|---|
| no Custom pair | `7D`, `30D`, `1Y`, `All`, `Custom` (Custom empty) |
| `rating_*` only | `Custom` only - rating populated |
| `type_*` only | `Custom` only - mix trend populated |
| both pairs | `Custom` only - **both** populated, each from its own range |

---

## Checks

### Mock fixtures

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_missing_csv_is_reported_clearly` | A directory with no fixtures raises a named error, not a KeyError. |
| PASS | `test_org_rating_is_a_nullable_integer` | org_rating is read as the literal integer, not a float or string. |
| PASS | `test_organizations_load` | The three CSVs resolve and join into a usable frame. |
| PASS | `test_ratings_are_within_the_expected_scale` | Every rating in the fixture falls on the 1-5 scale. |
| PASS | `test_short_buckets_are_empty_against_this_fixture` | Records why daily granularity is verified synthetically. |
| PASS | `test_singular_filenames_resolve` | state.csv/country.csv are found even though the issue says plural. |

### Full response (no Custom pair)

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_all_bucket_covers_every_organization` | The unbounded All bucket rates every organization in the fixture. |
| PASS | `test_custom_is_empty_when_no_range_supplied` | Custom is present, with an empty chart and two empty series. |
| PASS | `test_empty_body_has_exactly_five_keys` | An empty request returns exactly 7D, 30D, 1Y, All and Custom. |
| PASS | `test_empty_bucket_returns_empty_arrays` | A window with no organizations does not crash. |
| PASS | `test_every_bucket_has_exactly_two_chart_keys` | No bucket carries any key beyond the two charts. |
| PASS | `test_mix_trend_always_has_both_series` | Both series keys are present in every bucket, even when empty. |

### Chart 1 - rating distribution

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_absent_ratings_are_not_zero_filled` | Only ratings present in the window appear. |
| PASS | `test_all_null_ratings_gives_an_empty_chart` | A window where nothing is rated returns [], not a null bucket. |
| PASS | `test_counts_match_the_fixture` | The All bucket reproduces the fixture's rating counts. |
| PASS | `test_empty_frame_returns_empty_chart` | No organizations means an empty array. |
| PASS | `test_null_ratings_are_excluded` | An unrated organization is left out rather than bucketed. |
| PASS | `test_rating_is_a_plain_integer` | The literal integer rating is emitted, not a float or string. |
| PASS | `test_rows_are_ascending_by_rating` | Ratings have a natural order, so the chart reads left to right. |
| PASS | `test_single_row_frame` | A one-row dataset produces a single rating row. |

### Chart 2 - organization mix trend

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_accumulation_restarts_per_bucket` | A bucket counts only its own window, not all history before it. |
| PASS | `test_both_series_present_when_only_one_has_data` | A window with one type still reports the other as an empty list. |
| PASS | `test_bucket_granularity_matches_the_contract` | 1Y and All emit YYYY-MM; Custom emits YYYY-MM-DD. |
| PASS | `test_counts_are_non_decreasing` | Each series only ever climbs within a bucket. |
| PASS | `test_counts_are_plain_ints` | No numpy integer leaks into the series. |
| PASS | `test_daily_granularity` | 7D/30D/Custom group by day. |
| PASS | `test_empty_frame_returns_two_empty_series` | No organizations still yields both keys. |
| PASS | `test_final_value_equals_the_window_total` | The last running total is that type's count inside the window. |
| PASS | `test_periods_are_sparse` | Periods with no new organizations of that type are omitted. |
| PASS | `test_periods_are_strictly_increasing` | Periods are ordered oldest first with no repeats. |
| PASS | `test_stored_labels_map_to_snake_case_series` | Non-Profit/For-profit become non_profit/for_profit. |
| PASS | `test_unknown_type_does_not_create_a_third_series` | An unrecognized org_type is skipped, keeping the contract intact. |

### country filter

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_all_sentinel_means_no_filter` | ALL and an absent filter produce the same response. |
| PASS | `test_country_code_filter` | Filtering by the code the fixture resolves to keeps every row. |
| PASS | `test_country_filter_is_case_insensitive` | Lowercase input matches the stored uppercase value. |
| PASS | `test_country_name_filter` | The country filter accepts a name as well as a code. |
| PASS | `test_filter_applies_to_custom_responses` | A Custom-only response honours the country filter. |
| PASS | `test_no_organization_type_filter_exists` | This tab deliberately has no type filter; it is ignored if sent. |
| PASS | `test_usa_matches_nothing_in_this_fixture` | The issue's "USA" example is empty: US states map to country_id 1, |

### Custom-only response shapes

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_both_ranges_populate_both_charts` | Both pairs are evaluated - neither is dropped, neither wins. |
| PASS | `test_custom_bucket_keeps_the_same_shape` | The Custom-only body has the two chart keys and both series. |
| PASS | `test_custom_range_with_no_matches_is_empty_not_an_error` | A valid range containing no organizations returns empty arrays. |
| PASS | `test_each_chart_uses_its_own_range` | The ranges are deliberately disjoint, so a shared window fails. |
| PASS | `test_rating_range_only` | Only the rating chart is populated, and no fixed buckets appear. |
| PASS | `test_type_range_only` | The mirror image: only the mix trend is populated. |

### Validation and error handling

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_bad_date_format_is_rejected` | Anything that is not YYYY-MM-DD is an error. |
| PASS | `test_data_failure_returns_500` | A load failure returns a generic 500 without leaking detail. |
| PASS | `test_half_a_rating_pair_is_rejected` | Only one half of the rating pair is an error, not a silent skip. |
| PASS | `test_half_a_type_pair_is_rejected` | The type pair is validated the same way. |
| PASS | `test_impossible_calendar_date_is_rejected` | A well-formed but non-existent date is still an error. |
| PASS | `test_malformed_json_body_is_rejected` | A body that is not valid JSON returns 400. |
| PASS | `test_non_object_json_body_is_rejected` | A JSON array body returns 400 rather than being treated as empty. |
| PASS | `test_one_bad_pair_fails_the_whole_request` | A valid pair beside a broken one returns 400, not partial data. |
| PASS | `test_start_after_end_is_rejected` | An inverted range is an error for both pairs. |
| PASS | `test_validation_precedes_data_access` | A malformed request never reads the CSVs. |

### Handler contract

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_accepts_a_dict_body` | A dict body is accepted as-is. |
| PASS | `test_accepts_a_json_string_body` | An API Gateway proxy event with a JSON string body is parsed. |
| PASS | `test_body_is_a_json_string` | The proxy body is serialized text, not a dict. |
| PASS | `test_cors_headers_are_present` | Every response carries the shared CORS headers. |
| PASS | `test_db_path_requires_configuration` | Switching off mock data without DB_HOST is an error, not a fallback. |
| PASS | `test_none_event_is_treated_as_empty` | A null event returns the full response rather than raising. |
| PASS | `test_source_has_no_parameter_store_references` | No boto3/SSM call path exists in the module. |

---

## Sample API responses

Printed by `python data-analytics/lambda_functions/rating_type_analytics.py`.

### No body

Request:

```json
{}
```

Response (HTTP 200):

```json
{
  "7D": {
    "rating_distribution": [],
    "organization_mix_trend": {
      "non_profit": [],
      "for_profit": []
    }
  },
  "30D": {
    "rating_distribution": [],
    "organization_mix_trend": {
      "non_profit": [],
      "for_profit": []
    }
  },
  "1Y": {
    "rating_distribution": [
      {
        "rating": 1,
        "count": 3
      },
      {
        "rating": 2,
        "count": 1
      },
      {
        "rating": 3,
        "count": 2
      },
      {
        "rating": 4,
        "count": 1
      },
      {
        "rating": 5,
        "count": 2
      }
    ],
    "organization_mix_trend": {
      "non_profit": [
        {
          "period": "2025-09",
          "count": 1
        },
        {
          "period": "2025-10",
          "count": 2
        },
        {
          "period": "2025-11",
          "count": 4
        },
        {
          "period": "2025-12",
          "count": 6
        },
        {
          "period": "2026-01",
          "count": 7
        }
      ],
      "for_profit": [
        {
          "period": "2025-11",
          "count": 1
        },
        {
          "period": "2025-12",
          "count": 2
        }
      ]
    }
  },
  "All": {
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
    "organization_mix_trend": {
      "non_profit": [
        {
          "period": "2023-09",
          "count": 1
        },
        {
          "period": "2023-11",
          "count": 2
        },
        {
          "period": "2023-12",
          "count": 3
        },
        {
          "period": "2024-04",
          "count": 4
        },
        {
          "period": "2024-06",
          "count": 5
        },
        {
          "period": "2024-09",
          "count": 7
        },
        {
          "period": "2024-11",
          "count": 8
        },
        {
          "period": "2024-12",
          "count": 9
        },
        {
          "period": "2025-01",
          "count": 10
        },
        {
          "period": "2025-06",
          "count": 11
        },
        {
          "period": "2025-08",
          "count": 13
        },
        {
          "period": "2025-09",
          "count": 15
        },
        {
          "period": "2025-10",
          "count": 16
        },
        {
          "period": "2025-11",
          "count": 18
        },
        {
          "period": "2025-12",
          "count": 20
        },
        {
          "period": "2026-01",
          "count": 21
        }
      ],
      "for_profit": [
        {
          "period": "2023-09",
          "count": 1
        },
        {
          "period": "2023-12",
          "count": 2
        },
        {
          "period": "2024-02",
          "count": 4
        },
        {
          "period": "2024-04",
          "count": 5
        },
        {
          "period": "2024-07",
          "count": 7
        },
        {
          "period": "2024-08",
          "count": 9
        },
        {
          "period": "2024-09",
          "count": 10
        },
        {
          "period": "2024-11",
          "count": 11
        },
        {
          "period": "2025-01",
          "count": 13
        },
        {
          "period": "2025-04",
          "count": 14
        },
        {
          "period": "2025-08",
          "count": 16
        },
        {
          "period": "2025-09",
          "count": 17
        },
        {
          "period": "2025-11",
          "count": 18
        },
        {
          "period": "2025-12",
          "count": 19
        }
      ]
    }
  },
  "Custom": {
    "rating_distribution": [],
    "organization_mix_trend": {
      "non_profit": [],
      "for_profit": []
    }
  }
}
```

### Country filter

Request:

```json
{
  "country": "AFG"
}
```

Response (HTTP 200):

```json
{
  "7D": {
    "rating_distribution": [],
    "organization_mix_trend": {
      "non_profit": [],
      "for_profit": []
    }
  },
  "30D": {
    "rating_distribution": [],
    "organization_mix_trend": {
      "non_profit": [],
      "for_profit": []
    }
  },
  "1Y": {
    "rating_distribution": [
      {
        "rating": 1,
        "count": 3
      },
      {
        "rating": 2,
        "count": 1
      },
      {
        "rating": 3,
        "count": 2
      },
      {
        "rating": 4,
        "count": 1
      },
      {
        "rating": 5,
        "count": 2
      }
    ],
    "organization_mix_trend": {
      "non_profit": [
        {
          "period": "2025-09",
          "count": 1
        },
        {
          "period": "2025-10",
          "count": 2
        },
        {
          "period": "2025-11",
          "count": 4
        },
        {
          "period": "2025-12",
          "count": 6
        },
        {
          "period": "2026-01",
          "count": 7
        }
      ],
      "for_profit": [
        {
          "period": "2025-11",
          "count": 1
        },
        {
          "period": "2025-12",
          "count": 2
        }
      ]
    }
  },
  "All": {
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
    "organization_mix_trend": {
      "non_profit": [
        {
          "period": "2023-09",
          "count": 1
        },
        {
          "period": "2023-11",
          "count": 2
        },
        {
          "period": "2023-12",
          "count": 3
        },
        {
          "period": "2024-04",
          "count": 4
        },
        {
          "period": "2024-06",
          "count": 5
        },
        {
          "period": "2024-09",
          "count": 7
        },
        {
          "period": "2024-11",
          "count": 8
        },
        {
          "period": "2024-12",
          "count": 9
        },
        {
          "period": "2025-01",
          "count": 10
        },
        {
          "period": "2025-06",
          "count": 11
        },
        {
          "period": "2025-08",
          "count": 13
        },
        {
          "period": "2025-09",
          "count": 15
        },
        {
          "period": "2025-10",
          "count": 16
        },
        {
          "period": "2025-11",
          "count": 18
        },
        {
          "period": "2025-12",
          "count": 20
        },
        {
          "period": "2026-01",
          "count": 21
        }
      ],
      "for_profit": [
        {
          "period": "2023-09",
          "count": 1
        },
        {
          "period": "2023-12",
          "count": 2
        },
        {
          "period": "2024-02",
          "count": 4
        },
        {
          "period": "2024-04",
          "count": 5
        },
        {
          "period": "2024-07",
          "count": 7
        },
        {
          "period": "2024-08",
          "count": 9
        },
        {
          "period": "2024-09",
          "count": 10
        },
        {
          "period": "2024-11",
          "count": 11
        },
        {
          "period": "2025-01",
          "count": 13
        },
        {
          "period": "2025-04",
          "count": 14
        },
        {
          "period": "2025-08",
          "count": 16
        },
        {
          "period": "2025-09",
          "count": 17
        },
        {
          "period": "2025-11",
          "count": 18
        },
        {
          "period": "2025-12",
          "count": 19
        }
      ]
    }
  },
  "Custom": {
    "rating_distribution": [],
    "organization_mix_trend": {
      "non_profit": [],
      "for_profit": []
    }
  }
}
```

### Rating Custom range only

Request:

```json
{
  "rating_start_date": "2023-09-08",
  "rating_end_date": "2025-01-05"
}
```

Response (HTTP 200):

```json
{
  "Custom": {
    "rating_distribution": [
      {
        "rating": 1,
        "count": 1
      },
      {
        "rating": 2,
        "count": 7
      },
      {
        "rating": 3,
        "count": 4
      },
      {
        "rating": 4,
        "count": 2
      },
      {
        "rating": 5,
        "count": 7
      }
    ],
    "organization_mix_trend": {
      "non_profit": [],
      "for_profit": []
    }
  }
}
```

### Type Custom range only

Request:

```json
{
  "type_start_date": "2025-01-05",
  "type_end_date": "2026-01-10"
}
```

Response (HTTP 200):

```json
{
  "Custom": {
    "rating_distribution": [],
    "organization_mix_trend": {
      "non_profit": [
        {
          "period": "2025-01-13",
          "count": 1
        },
        {
          "period": "2025-06-01",
          "count": 2
        },
        {
          "period": "2025-08-04",
          "count": 3
        },
        {
          "period": "2025-08-06",
          "count": 4
        },
        {
          "period": "2025-09-01",
          "count": 5
        },
        {
          "period": "2025-09-26",
          "count": 6
        },
        {
          "period": "2025-10-01",
          "count": 7
        },
        {
          "period": "2025-11-03",
          "count": 8
        },
        {
          "period": "2025-11-20",
          "count": 9
        },
        {
          "period": "2025-12-16",
          "count": 10
        },
        {
          "period": "2025-12-17",
          "count": 11
        },
        {
          "period": "2026-01-10",
          "count": 12
        }
      ],
      "for_profit": [
        {
          "period": "2025-01-05",
          "count": 1
        },
        {
          "period": "2025-01-08",
          "count": 2
        },
        {
          "period": "2025-04-05",
          "count": 3
        },
        {
          "period": "2025-08-01",
          "count": 5
        },
        {
          "period": "2025-09-03",
          "count": 6
        },
        {
          "period": "2025-11-28",
          "count": 7
        },
        {
          "period": "2025-12-19",
          "count": 8
        }
      ]
    }
  }
}
```

### Both Custom ranges together

Request:

```json
{
  "rating_start_date": "2023-09-08",
  "rating_end_date": "2025-01-05",
  "type_start_date": "2025-01-05",
  "type_end_date": "2026-01-10"
}
```

Response (HTTP 200):

```json
{
  "Custom": {
    "rating_distribution": [
      {
        "rating": 1,
        "count": 1
      },
      {
        "rating": 2,
        "count": 7
      },
      {
        "rating": 3,
        "count": 4
      },
      {
        "rating": 4,
        "count": 2
      },
      {
        "rating": 5,
        "count": 7
      }
    ],
    "organization_mix_trend": {
      "non_profit": [
        {
          "period": "2025-01-13",
          "count": 1
        },
        {
          "period": "2025-06-01",
          "count": 2
        },
        {
          "period": "2025-08-04",
          "count": 3
        },
        {
          "period": "2025-08-06",
          "count": 4
        },
        {
          "period": "2025-09-01",
          "count": 5
        },
        {
          "period": "2025-09-26",
          "count": 6
        },
        {
          "period": "2025-10-01",
          "count": 7
        },
        {
          "period": "2025-11-03",
          "count": 8
        },
        {
          "period": "2025-11-20",
          "count": 9
        },
        {
          "period": "2025-12-16",
          "count": 10
        },
        {
          "period": "2025-12-17",
          "count": 11
        },
        {
          "period": "2026-01-10",
          "count": 12
        }
      ],
      "for_profit": [
        {
          "period": "2025-01-05",
          "count": 1
        },
        {
          "period": "2025-01-08",
          "count": 2
        },
        {
          "period": "2025-04-05",
          "count": 3
        },
        {
          "period": "2025-08-01",
          "count": 5
        },
        {
          "period": "2025-09-03",
          "count": 6
        },
        {
          "period": "2025-11-28",
          "count": 7
        },
        {
          "period": "2025-12-19",
          "count": 8
        }
      ]
    }
  }
}
```

### Validation error - half a pair

Request:

```json
{
  "rating_start_date": "2023-09-08"
}
```

Response (HTTP 400):

```json
{
  "error": "rating_start_date and rating_end_date must be provided together"
}
```

---

## Notes

- `organization_mix_trend` is **window-scoped**: every bucket restarts its running total at zero and counts only organizations created inside its own window. The issue calls these "all-time running totals", but its own worked example shows `1Y` opening at 8 while `All` has already reached 45 at an earlier period, which is only possible if each bucket restarts.
- Series are **sparse**: a period with no new organizations of that type is omitted rather than repeated. Both series keys are always present, even when empty.
- `rating_distribution` emits the literal integer rating, ascending, with no zero-filling of absent ratings. Unrated organizations are excluded rather than bucketed.
- The stored `Non-Profit`/`For-profit` labels are mapped onto the `non_profit`/`for_profit` series names the issue specifies. This differs from #376, where the issue asked for the raw enum value.
- `7D` and `30D` are empty against this fixture: its newest `created_at` is 2026-01-10, well outside both windows from the pinned reference date. Daily granularity is therefore verified with synthetic frames.
- A `country` filter of `"USA"` matches nothing. Every US state in `state.csv` carries `country_id=1`, which `country.csv` maps to `AFGHANISTAN`/`AFG`. That is a mock-data defect; the join itself is correct.
- There is deliberately no `organization_type` filter on this tab - chart 2 is the type breakdown, so filtering by type would show one side of its own stacked bar. An `organization_type` key in the request is ignored.
