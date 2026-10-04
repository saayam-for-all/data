# Issue 376 — local verification

Verified on October 4, 2026. No AWS deployment or live database access.

## Behavior

- No custom dates: exactly 7D, 30D, 1Y, All and empty Custom.
- Either/both date pairs: Custom only; each chart uses its own range.
- 7D and 30D include today and the previous 6/29 UTC calendar dates.
- 1Y includes the current month and preceding 11 months through today,
  following recent reviewer feedback. All is unbounded.
- Country matches a stored name or code, case-insensitively. Organization
  types compare without case, hyphens, underscores or spaces. Raw size
  labels are preserved, and absent categories are not zero-filled.
- Both contribution flags are independent. Empty windows produce empty
  arrays; absent contributor columns produce a zero Contributor row.
- Invalid requests return 400 before loading data; source failures return 500.

## Reproduce

From the repository root, with pandas and pytest installed:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider data-analytics/tests/test_size_contribution_analytics.py -q
USE_MOCK_DATA=true MOCK_DATA_DIR=/path/to/consistent/csvs python data-analytics/lambda_functions/size_contribution_analytics.py
```

To measure coverage, additionally install the development tool `coverage`:

```sh
python -m coverage run --branch --include='*/size_contribution_analytics.py' -m pytest -p no:cacheprovider data-analytics/tests/test_size_contribution_analytics.py -q
python -m coverage report -m
```

Runtime dependencies are unchanged: pandas and optional psycopg2. Verification
used Python 3.12, pandas 2.2.2 and pytest 8.3.3 in an isolated environment.
Both new files also pass Python 3.10 syntax parsing. Tests create temporary CSVs;
no CSV files are included in these changes.

## Automated test output

The database tests use fake cursors/connections to verify loading, missing-column
handling, cleanup and response parity. They do not establish live PostgreSQL
connectivity or validate the deployed schema. The unrelated repository test
suite was not run.

```text
........................................................................ [ 86%]
...........                                                              [100%]
83 passed in 1.19s
Name                                                                                                        Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------------------------------------------------------------------------------------------------
data-analytics/lambda_functions/size_contribution_analytics.py     209      0     88      0   100%
-------------------------------------------------------------------------------------------------------------------------------------------------------
TOTAL                                                                                                         209      0     88      0   100%
```

## Repository CSV verification

The six sample outputs below were produced using the consistent 400-organization
CSV set from `data-analytics/mock-data-generation` on main at commit
`443fc079091fce43058030ef1ac8bc1ef6cf9951`. Copies were kept outside this checkout.
The date-based samples intentionally use historical ranges because the dataset
has no organizations created in the current 7D/30D windows.

Additional checks against the older 40-row `data-analytics/sql` dataset returned:

- All organizations: 40 (Large 21, Medium 9, Small 10).
- `organization_type=non_profit`: 21 (Large 11, Medium 5, Small 5).
- `organization_type=for_profit`: 19 (Large 10, Medium 4, Small 5).

The older state/country lookups have inconsistent country IDs. The function
preserves their values; it does not silently reassign organizations to USA.
Use the consistent dataset above to verify geography.

### No body

```json
{
  "scenario": "No body",
  "request": {},
  "statusCode": 200,
  "body": {
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
          "size": "large",
          "count": 76
        },
        {
          "size": "medium",
          "count": 107
        },
        {
          "size": "small",
          "count": 83
        }
      ],
      "collaborator_vs_contributor": [
        {
          "type": "Collaborator",
          "count": 83,
          "percentage": 31.2
        },
        {
          "type": "Contributor",
          "count": 151,
          "percentage": 56.8
        }
      ]
    },
    "All": {
      "organizations_by_size": [
        {
          "size": "large",
          "count": 110
        },
        {
          "size": "medium",
          "count": 168
        },
        {
          "size": "small",
          "count": 122
        }
      ],
      "collaborator_vs_contributor": [
        {
          "type": "Collaborator",
          "count": 125,
          "percentage": 31.2
        },
        {
          "type": "Contributor",
          "count": 224,
          "percentage": 56.0
        }
      ]
    },
    "Custom": {
      "organizations_by_size": [],
      "collaborator_vs_contributor": []
    }
  }
}
```

### Country

```json
{
  "scenario": "Country",
  "request": {
    "country": "USA"
  },
  "statusCode": 200,
  "body": {
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
          "size": "large",
          "count": 5
        },
        {
          "size": "medium",
          "count": 17
        },
        {
          "size": "small",
          "count": 11
        }
      ],
      "collaborator_vs_contributor": [
        {
          "type": "Collaborator",
          "count": 8,
          "percentage": 24.2
        },
        {
          "type": "Contributor",
          "count": 24,
          "percentage": 72.7
        }
      ]
    },
    "All": {
      "organizations_by_size": [
        {
          "size": "large",
          "count": 7
        },
        {
          "size": "medium",
          "count": 30
        },
        {
          "size": "small",
          "count": 14
        }
      ],
      "collaborator_vs_contributor": [
        {
          "type": "Collaborator",
          "count": 16,
          "percentage": 31.4
        },
        {
          "type": "Contributor",
          "count": 32,
          "percentage": 62.7
        }
      ]
    },
    "Custom": {
      "organizations_by_size": [],
      "collaborator_vs_contributor": []
    }
  }
}
```

### Organization type

```json
{
  "scenario": "Organization type",
  "request": {
    "organization_type": "non_profit"
  },
  "statusCode": 200,
  "body": {
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
          "size": "large",
          "count": 56
        },
        {
          "size": "medium",
          "count": 74
        },
        {
          "size": "small",
          "count": 54
        }
      ],
      "collaborator_vs_contributor": [
        {
          "type": "Collaborator",
          "count": 56,
          "percentage": 30.4
        },
        {
          "type": "Contributor",
          "count": 104,
          "percentage": 56.5
        }
      ]
    },
    "All": {
      "organizations_by_size": [
        {
          "size": "large",
          "count": 78
        },
        {
          "size": "medium",
          "count": 113
        },
        {
          "size": "small",
          "count": 79
        }
      ],
      "collaborator_vs_contributor": [
        {
          "type": "Collaborator",
          "count": 81,
          "percentage": 30.0
        },
        {
          "type": "Contributor",
          "count": 150,
          "percentage": 55.6
        }
      ]
    },
    "Custom": {
      "organizations_by_size": [],
      "collaborator_vs_contributor": []
    }
  }
}
```

### Size Custom

```json
{
  "scenario": "Size Custom",
  "request": {
    "size_start_date": "2026-01-01",
    "size_end_date": "2026-06-30"
  },
  "statusCode": 200,
  "body": {
    "Custom": {
      "organizations_by_size": [
        {
          "size": "large",
          "count": 42
        },
        {
          "size": "medium",
          "count": 63
        },
        {
          "size": "small",
          "count": 45
        }
      ],
      "collaborator_vs_contributor": []
    }
  }
}
```

### Contribution Custom

```json
{
  "scenario": "Contribution Custom",
  "request": {
    "contribution_start_date": "2025-01-01",
    "contribution_end_date": "2025-12-31"
  },
  "statusCode": 200,
  "body": {
    "Custom": {
      "organizations_by_size": [],
      "collaborator_vs_contributor": [
        {
          "type": "Collaborator",
          "count": 60,
          "percentage": 31.1
        },
        {
          "type": "Contributor",
          "count": 104,
          "percentage": 53.9
        }
      ]
    }
  }
}
```

### Both Custom ranges

```json
{
  "scenario": "Both Custom ranges",
  "request": {
    "size_start_date": "2026-01-01",
    "size_end_date": "2026-06-30",
    "contribution_start_date": "2025-01-01",
    "contribution_end_date": "2025-12-31"
  },
  "statusCode": 200,
  "body": {
    "Custom": {
      "organizations_by_size": [
        {
          "size": "large",
          "count": 42
        },
        {
          "size": "medium",
          "count": 63
        },
        {
          "size": "small",
          "count": 45
        }
      ],
      "collaborator_vs_contributor": [
        {
          "type": "Collaborator",
          "count": 60,
          "percentage": 31.1
        },
        {
          "type": "Contributor",
          "count": 104,
          "percentage": 53.9
        }
      ]
    }
  }
}
```
