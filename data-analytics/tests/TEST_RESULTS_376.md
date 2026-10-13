# Size & Contribution Analytics API - Test Results (Issue #376)

**59/59 checks passed** in 0.31s.

| | |
|---|---|
| Module under test | `data-analytics/lambda_functions/size_contribution_analytics.py` |
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
| `size_*` only | `Custom` only - size populated |
| `contribution_*` only | `Custom` only - contribution populated |
| both pairs | `Custom` only - **both** populated, each from its own range |

---

## Checks

### Mock fixtures

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_booleans_parsed_from_uppercase_text` | The fixture's TRUE/FALSE strings become a real boolean dtype. |
| PASS | `test_fixture_cannot_show_flag_overlap` | Records why the independence tests use a synthetic frame instead. |
| PASS | `test_missing_csv_is_reported_clearly` | A directory with no fixtures raises a named error, not a KeyError. |
| PASS | `test_organizations_load` | The three CSVs resolve and join into a usable frame. |
| PASS | `test_singular_filenames_resolve` | state.csv/country.csv are found even though the issue says plural. |

### Full response (no Custom pair)

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_all_bucket_counts_every_organization` | The unbounded All bucket sees the whole fixture. |
| PASS | `test_categories_are_not_zero_filled` | Only categories present in the window appear. |
| PASS | `test_custom_is_empty_when_no_range_supplied` | Custom is present but both its arrays are empty. |
| PASS | `test_empty_body_has_exactly_five_keys` | An empty request returns exactly 7D, 30D, 1Y, All and Custom. |
| PASS | `test_every_bucket_has_exactly_two_chart_keys` | No bucket carries any key beyond the two charts. |
| PASS | `test_raw_enum_values_are_emitted` | Size categories use the stored casing, not a normalized form. |
| PASS | `test_size_counts_sum_to_the_window_total` | Every bucket's size counts sum to that window's organization count. |

### Bucket windows

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_all_bucket_is_unbounded` | All has no bounds at all, rather than a very wide range. |
| PASS | `test_empty_window_returns_empty_arrays` | A bucket with no organizations returns [], and does not crash. |
| PASS | `test_end_date_is_inclusive_of_the_whole_day` | A row timestamped late on the end date is still inside the window. |
| PASS | `test_windows_are_inclusive_of_today` | 7D covers today plus the previous six dates. |

### country / organization_type filters

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_all_sentinel_means_no_filter` | ALL and an absent filter produce the same response. |
| PASS | `test_country_code_filter` | Filtering by the code the fixture resolves to keeps every row. |
| PASS | `test_country_filter_is_case_insensitive` | Lowercase input matches the stored uppercase value. |
| PASS | `test_country_name_filter` | The country filter accepts a name as well as a code. |
| PASS | `test_filters_apply_to_custom_responses_too` | A Custom-only response honours country and organization_type. |
| PASS | `test_filters_partition_the_fixture` | The two org types together account for every organization. |
| PASS | `test_for_profit_filter_normalizes` | for_profit matches the stored For-profit, despite the casing. |
| PASS | `test_organization_type_filter_normalizes` | non_profit matches the stored Non-Profit. |
| PASS | `test_usa_matches_nothing_in_this_fixture` | The issue's "USA" example is empty: US states map to country_id 1, |

### Custom-only response shapes

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_both_ranges_populate_both_charts` | Both pairs are evaluated - neither is dropped, neither wins. |
| PASS | `test_contribution_range_only` | The mirror image: only the contribution chart is populated. |
| PASS | `test_custom_bucket_still_has_exactly_two_keys` | The Custom-only body keeps the same bucket shape. |
| PASS | `test_custom_range_with_no_matches_is_empty_not_an_error` | A valid range containing no organizations returns empty arrays. |
| PASS | `test_each_chart_uses_its_own_range` | The ranges are deliberately different, so a shared window fails. |
| PASS | `test_size_range_only` | Only the size chart is populated, and no fixed buckets appear. |

### Collaborator vs contributor

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_all_both_flags_gives_two_full_counts` | When every org is both, both rows report the full total at 100%. |
| PASS | `test_counts_match_the_columns` | Each count is its own column's true count. |
| PASS | `test_counts_need_not_sum_to_the_total` | An org can be both or neither, so the rows are not a partition. |
| PASS | `test_each_count_is_within_the_window_total` | Neither count can exceed the bucket's organization count. |
| PASS | `test_empty_frame_returns_empty_chart` | No organizations means an empty array, not two zero rows. |
| PASS | `test_exactly_two_rows_in_order` | The chart is always Collaborator then Contributor. |
| PASS | `test_missing_is_contributor_degrades_to_zero` | A frame without the column reports Contributor 0, without raising. |
| PASS | `test_percentages_are_shares_of_the_total` | Each percentage is its own count over the window total. |
| PASS | `test_single_row_frame_does_not_crash` | A one-row dataset produces valid charts. |

### Validation and error handling

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_bad_date_format_is_rejected` | Anything that is not YYYY-MM-DD is an error. |
| PASS | `test_data_failure_returns_500` | A load failure returns a generic 500 without leaking detail. |
| PASS | `test_half_a_contribution_pair_is_rejected` | The contribution pair is validated the same way. |
| PASS | `test_half_a_size_pair_is_rejected` | Only one half of the size pair is an error, not a silent skip. |
| PASS | `test_impossible_calendar_date_is_rejected` | A well-formed but non-existent date is still an error. |
| PASS | `test_malformed_json_body_is_rejected` | A body that is not valid JSON returns 400. |
| PASS | `test_non_object_json_body_is_rejected` | A JSON array body returns 400 rather than being treated as empty. |
| PASS | `test_one_bad_pair_fails_the_whole_request` | A valid pair alongside a broken one still returns 400, not partial data. |
| PASS | `test_start_after_end_is_rejected` | An inverted range is an error for both pairs. |
| PASS | `test_validation_precedes_data_access` | A malformed request never reads the CSVs. |

### Handler contract

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_accepts_a_dict_body` | A dict body is accepted as-is. |
| PASS | `test_accepts_a_json_string_body` | An API Gateway proxy event with a JSON string body is parsed. |
| PASS | `test_body_is_a_json_string` | The proxy body is serialized text, not a dict. |
| PASS | `test_cors_headers_are_present` | Every response carries the shared CORS headers. |
| PASS | `test_counts_are_plain_ints` | No numpy integer leaks into the JSON payload. |
| PASS | `test_db_path_requires_configuration` | Switching off mock data without DB_HOST is an error, not a fallback. |
| PASS | `test_module_runs_without_psycopg2` | The mock path does not need the database driver installed. |
| PASS | `test_none_event_is_treated_as_empty` | A null event returns the full response rather than raising. |
| PASS | `test_source_has_no_parameter_store_references` | No boto3/SSM call path exists in the module. |

---

## Sample API responses

Printed by `python data-analytics/lambda_functions/size_contribution_analytics.py`.

### No body

Request:

```json
{}
```

Response (HTTP 200):

```json
{
  "7D": {
    "organizations_by_size": [],
    "collaborator_vs_contributor": []
  },
  "30D": {
    "organizations_by_size": [],
    "collaborator_vs_contributor": []
  },
  "1Y": {
    "organizations_by_size": [
      {
        "size": "Large",
        "count": 5
      },
      {
        "size": "Medium",
        "count": 2
      },
      {
        "size": "Small",
        "count": 2
      }
    ],
    "collaborator_vs_contributor": [
      {
        "type": "Collaborator",
        "count": 4,
        "percentage": 44.4
      },
      {
        "type": "Contributor",
        "count": 5,
        "percentage": 55.6
      }
    ]
  },
  "All": {
    "organizations_by_size": [
      {
        "size": "Large",
        "count": 21
      },
      {
        "size": "Small",
        "count": 10
      },
      {
        "size": "Medium",
        "count": 9
      }
    ],
    "collaborator_vs_contributor": [
      {
        "type": "Collaborator",
        "count": 21,
        "percentage": 52.5
      },
      {
        "type": "Contributor",
        "count": 19,
        "percentage": 47.5
      }
    ]
  },
  "Custom": {
    "organizations_by_size": [],
    "collaborator_vs_contributor": []
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
    "organizations_by_size": [],
    "collaborator_vs_contributor": []
  },
  "30D": {
    "organizations_by_size": [],
    "collaborator_vs_contributor": []
  },
  "1Y": {
    "organizations_by_size": [
      {
        "size": "Large",
        "count": 5
      },
      {
        "size": "Medium",
        "count": 2
      },
      {
        "size": "Small",
        "count": 2
      }
    ],
    "collaborator_vs_contributor": [
      {
        "type": "Collaborator",
        "count": 4,
        "percentage": 44.4
      },
      {
        "type": "Contributor",
        "count": 5,
        "percentage": 55.6
      }
    ]
  },
  "All": {
    "organizations_by_size": [
      {
        "size": "Large",
        "count": 21
      },
      {
        "size": "Small",
        "count": 10
      },
      {
        "size": "Medium",
        "count": 9
      }
    ],
    "collaborator_vs_contributor": [
      {
        "type": "Collaborator",
        "count": 21,
        "percentage": 52.5
      },
      {
        "type": "Contributor",
        "count": 19,
        "percentage": 47.5
      }
    ]
  },
  "Custom": {
    "organizations_by_size": [],
    "collaborator_vs_contributor": []
  }
}
```

### Organization type filter

Request:

```json
{
  "organization_type": "non_profit"
}
```

Response (HTTP 200):

```json
{
  "7D": {
    "organizations_by_size": [],
    "collaborator_vs_contributor": []
  },
  "30D": {
    "organizations_by_size": [],
    "collaborator_vs_contributor": []
  },
  "1Y": {
    "organizations_by_size": [
      {
        "size": "Large",
        "count": 5
      },
      {
        "size": "Medium",
        "count": 1
      },
      {
        "size": "Small",
        "count": 1
      }
    ],
    "collaborator_vs_contributor": [
      {
        "type": "Collaborator",
        "count": 4,
        "percentage": 57.1
      },
      {
        "type": "Contributor",
        "count": 3,
        "percentage": 42.9
      }
    ]
  },
  "All": {
    "organizations_by_size": [
      {
        "size": "Large",
        "count": 11
      },
      {
        "size": "Medium",
        "count": 5
      },
      {
        "size": "Small",
        "count": 5
      }
    ],
    "collaborator_vs_contributor": [
      {
        "type": "Collaborator",
        "count": 11,
        "percentage": 52.4
      },
      {
        "type": "Contributor",
        "count": 10,
        "percentage": 47.6
      }
    ]
  },
  "Custom": {
    "organizations_by_size": [],
    "collaborator_vs_contributor": []
  }
}
```

### Size Custom range only

Request:

```json
{
  "size_start_date": "2023-09-08",
  "size_end_date": "2025-01-05"
}
```

Response (HTTP 200):

```json
{
  "Custom": {
    "organizations_by_size": [
      {
        "size": "Large",
        "count": 9
      },
      {
        "size": "Medium",
        "count": 6
      },
      {
        "size": "Small",
        "count": 6
      }
    ],
    "collaborator_vs_contributor": []
  }
}
```

### Contribution Custom range only

Request:

```json
{
  "contribution_start_date": "2025-01-05",
  "contribution_end_date": "2026-01-10"
}
```

Response (HTTP 200):

```json
{
  "Custom": {
    "organizations_by_size": [],
    "collaborator_vs_contributor": [
      {
        "type": "Collaborator",
        "count": 8,
        "percentage": 40.0
      },
      {
        "type": "Contributor",
        "count": 12,
        "percentage": 60.0
      }
    ]
  }
}
```

### Both Custom ranges together

Request:

```json
{
  "size_start_date": "2023-09-08",
  "size_end_date": "2025-01-05",
  "contribution_start_date": "2025-01-05",
  "contribution_end_date": "2026-01-10"
}
```

Response (HTTP 200):

```json
{
  "Custom": {
    "organizations_by_size": [
      {
        "size": "Large",
        "count": 9
      },
      {
        "size": "Medium",
        "count": 6
      },
      {
        "size": "Small",
        "count": 6
      }
    ],
    "collaborator_vs_contributor": [
      {
        "type": "Collaborator",
        "count": 8,
        "percentage": 40.0
      },
      {
        "type": "Contributor",
        "count": 12,
        "percentage": 60.0
      }
    ]
  }
}
```

### Validation error - half a pair

Request:

```json
{
  "size_start_date": "2023-09-08"
}
```

Response (HTTP 400):

```json
{
  "error": "size_start_date and size_end_date must be provided together"
}
```

---

## Notes

- `organizations_by_size` emits the **raw** stored enum values (`Small`/`Medium`/`Large`), per the issue's "use the raw enum value as-is". The issue's sample JSON shows `small`/`medium`/`large`, which does not match the data.
- `collaborator_vs_contributor` counts each flag independently against the window total. They are not a partition and need not sum to that total or to 100%. The committed fixture happens to have zero overlap (21 collaborators, 19 contributors, none both or neither), so the independence is proven with synthetic frames instead.
- `7D` and `30D` are empty against this fixture: its newest `created_at` is 2026-01-10, well outside both windows from the pinned reference date.
- A `country` filter of `"USA"` matches nothing. Every US state in `state.csv` carries `country_id=1`, which `country.csv` maps to `AFGHANISTAN`/`AFG`. That is a mock-data defect; the join itself is correct.
- No `states.csv`/`countries.csv` exists in this repository, so the loader prefers those plural names and falls back to the tracked `state.csv`/`country.csv`.
