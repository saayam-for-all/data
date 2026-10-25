# Organization Analytics API — Local Test Results (mock data)

Generated: 2026-08-18 13:31:55

Mock organizations loaded: **40** rows from `mock_data/organizations.csv`

No AWS/SSM/Postgres connection is used anywhere in this test run — all data comes from the mock CSV.

## Scenario: Overview - ALL time (unfiltered)

Request filters:
```json
{
  "dashboard_type": "overview",
  "time_filter": "ALL",
  "group_by": "monthly"
}
```

Response:
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
        "period": "2023-09",
        "count": 2
      },
      {
        "period": "2023-11",
        "count": 1
      },
      {
        "period": "2023-12",
        "count": 2
      },
      {
        "period": "2024-02",
        "count": 2
      },
      {
        "period": "2024-04",
        "count": 2
      },
      {
        "period": "2024-06",
        "count": 1
      },
      {
        "period": "2024-07",
        "count": 2
      },
      {
        "period": "2024-08",
        "count": 2
      },
      {
        "period": "2024-09",
        "count": 3
      },
      {
        "period": "2024-11",
        "count": 2
      },
      {
        "period": "2024-12",
        "count": 1
      },
      {
        "period": "2025-01",
        "count": 3
      },
      {
        "period": "2025-04",
        "count": 1
      },
      {
        "period": "2025-06",
        "count": 1
      },
      {
        "period": "2025-08",
        "count": 4
      },
      {
        "period": "2025-09",
        "count": 3
      },
      {
        "period": "2025-10",
        "count": 1
      },
      {
        "period": "2025-11",
        "count": 3
      },
      {
        "period": "2025-12",
        "count": 3
      },
      {
        "period": "2026-01",
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
    "organizations_by_location": [
      {
        "state": "AK",
        "city": "North Judithbury",
        "count": 1
      },
      {
        "state": "AL",
        "city": "Smithberg",
        "count": 1
      },
      {
        "state": "NC",
        "city": "Ronaldview",
        "count": 1
      },
      {
        "state": "NE",
        "city": "Barkerfurt",
        "count": 1
      },
      {
        "state": "NJ",
        "city": "South Williamton",
        "count": 1
      },
      {
        "state": "NV",
        "city": "Leehaven",
        "count": 1
      },
      {
        "state": "OH",
        "city": "South Jeffrey",
        "count": 1
      },
      {
        "state": "OK",
        "city": "Jeremyburgh",
        "count": 1
      },
      {
        "state": "OR",
        "city": "Johnberg",
        "count": 1
      },
      {
        "state": "RI",
        "city": "Mitchellside",
        "count": 1
      },
      {
        "state": "RI",
        "city": "South Rachelborough",
        "count": 1
      },
      {
        "state": "TX",
        "city": "East Jenniferfort",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Hortonberg",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Victoriaport",
        "count": 1
      },
      {
        "state": "UT",
        "city": "New Thomas",
        "count": 1
      },
      {
        "state": "VA",
        "city": "Sandrastad",
        "count": 1
      },
      {
        "state": "VT",
        "city": "Ortizmouth",
        "count": 1
      },
      {
        "state": "WA",
        "city": "Stephaniemouth",
        "count": 1
      },
      {
        "state": "WI",
        "city": "Thomasberg",
        "count": 1
      },
      {
        "state": "NC",
        "city": "Robinfort",
        "count": 1
      },
      {
        "state": "MT",
        "city": "Williamview",
        "count": 1
      },
      {
        "state": "MT",
        "city": "Wendyville",
        "count": 1
      },
      {
        "state": "IA",
        "city": "West Erik",
        "count": 1
      },
      {
        "state": "AR",
        "city": "East Amanda",
        "count": 1
      },
      {
        "state": "AR",
        "city": "Robertfort",
        "count": 1
      },
      {
        "state": "AZ",
        "city": "Kyleborough",
        "count": 1
      },
      {
        "state": "CA",
        "city": "New Susanville",
        "count": 1
      },
      {
        "state": "FL",
        "city": "North Jamesborough",
        "count": 1
      },
      {
        "state": "FL",
        "city": "West Amandastad",
        "count": 1
      },
      {
        "state": "IA",
        "city": "Lake Debbie",
        "count": 1
      },
      {
        "state": "IN",
        "city": "North Donnaport",
        "count": 1
      },
      {
        "state": "MO",
        "city": "Lake Deniseville",
        "count": 1
      },
      {
        "state": "IN",
        "city": "South Monicamouth",
        "count": 1
      },
      {
        "state": "KS",
        "city": "Burchborough",
        "count": 1
      },
      {
        "state": "KS",
        "city": "Port Andrew",
        "count": 1
      },
      {
        "state": "ME",
        "city": "Martinezbury",
        "count": 1
      },
      {
        "state": "MI",
        "city": "West Williamport",
        "count": 1
      },
      {
        "state": "MN",
        "city": "Lake Nancyview",
        "count": 1
      },
      {
        "state": "MN",
        "city": "New Amyhaven",
        "count": 1
      },
      {
        "state": "WY",
        "city": "Kingborough",
        "count": 1
      }
    ],
    "collaborator_distribution": [
      {
        "category": "collaborator",
        "count": 21
      },
      {
        "category": "non_collaborator",
        "count": 19
      }
    ],
    "contributor_distribution": [
      {
        "category": "contributor",
        "count": 19
      },
      {
        "category": "non_contributor",
        "count": 21
      }
    ]
  }
}
```

## Scenario: Overview - 7D

Request filters:
```json
{
  "dashboard_type": "overview",
  "time_filter": "7D",
  "group_by": "daily"
}
```

Response:
```json
{
  "organization_overview": {
    "summary": {
      "total_organizations": 0,
      "non_profit_organizations": 0,
      "for_profit_organizations": 0,
      "collaborator_organizations": 0,
      "non_collaborator_organizations": 0,
      "contributor_organizations": 0,
      "non_contributor_organizations": 0
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

## Scenario: Overview - 30D

Request filters:
```json
{
  "dashboard_type": "overview",
  "time_filter": "30D",
  "group_by": "daily"
}
```

Response:
```json
{
  "organization_overview": {
    "summary": {
      "total_organizations": 0,
      "non_profit_organizations": 0,
      "for_profit_organizations": 0,
      "collaborator_organizations": 0,
      "non_collaborator_organizations": 0,
      "contributor_organizations": 0,
      "non_contributor_organizations": 0
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

## Scenario: Overview - 1Y, grouped monthly

Request filters:
```json
{
  "dashboard_type": "overview",
  "time_filter": "1Y",
  "group_by": "monthly"
}
```

Response:
```json
{
  "organization_overview": {
    "summary": {
      "total_organizations": 11,
      "non_profit_organizations": 8,
      "for_profit_organizations": 3,
      "collaborator_organizations": 5,
      "non_collaborator_organizations": 6,
      "contributor_organizations": 6,
      "non_contributor_organizations": 5
    },
    "organization_activity_trend": [
      {
        "period": "2025-09",
        "count": 3
      },
      {
        "period": "2025-10",
        "count": 1
      },
      {
        "period": "2025-11",
        "count": 3
      },
      {
        "period": "2025-12",
        "count": 3
      },
      {
        "period": "2026-01",
        "count": 1
      }
    ],
    "organizations_by_type": [
      {
        "org_type": "Non-Profit",
        "count": 8
      },
      {
        "org_type": "For-profit",
        "count": 3
      }
    ],
    "organizations_by_size": [
      {
        "org_size": "Large",
        "count": 7
      },
      {
        "org_size": "Small",
        "count": 2
      },
      {
        "org_size": "Medium",
        "count": 2
      }
    ],
    "organizations_by_location": [
      {
        "state": "FL",
        "city": "West Amandastad",
        "count": 1
      },
      {
        "state": "ME",
        "city": "Martinezbury",
        "count": 1
      },
      {
        "state": "MI",
        "city": "West Williamport",
        "count": 1
      },
      {
        "state": "MN",
        "city": "Lake Nancyview",
        "count": 1
      },
      {
        "state": "MO",
        "city": "Lake Deniseville",
        "count": 1
      },
      {
        "state": "NC",
        "city": "Robinfort",
        "count": 1
      },
      {
        "state": "NE",
        "city": "Barkerfurt",
        "count": 1
      },
      {
        "state": "OH",
        "city": "South Jeffrey",
        "count": 1
      },
      {
        "state": "TX",
        "city": "East Jenniferfort",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Hortonberg",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Victoriaport",
        "count": 1
      }
    ],
    "collaborator_distribution": [
      {
        "category": "collaborator",
        "count": 5
      },
      {
        "category": "non_collaborator",
        "count": 6
      }
    ],
    "contributor_distribution": [
      {
        "category": "contributor",
        "count": 6
      },
      {
        "category": "non_contributor",
        "count": 5
      }
    ]
  }
}
```

## Scenario: Overview - filtered (Non-Profit)

Request filters:
```json
{
  "dashboard_type": "overview",
  "org_type": "Non-Profit",
  "time_filter": "ALL"
}
```

Response:
```json
{
  "organization_overview": {
    "summary": {
      "total_organizations": 21,
      "non_profit_organizations": 21,
      "for_profit_organizations": 0,
      "collaborator_organizations": 11,
      "non_collaborator_organizations": 10,
      "contributor_organizations": 10,
      "non_contributor_organizations": 11
    },
    "organization_activity_trend": [
      {
        "period": "2023-09-08",
        "count": 1
      },
      {
        "period": "2023-11-03",
        "count": 1
      },
      {
        "period": "2023-12-27",
        "count": 1
      },
      {
        "period": "2024-04-03",
        "count": 1
      },
      {
        "period": "2024-06-30",
        "count": 1
      },
      {
        "period": "2024-09-08",
        "count": 1
      },
      {
        "period": "2024-09-11",
        "count": 1
      },
      {
        "period": "2024-11-06",
        "count": 1
      },
      {
        "period": "2024-12-20",
        "count": 1
      },
      {
        "period": "2025-01-13",
        "count": 1
      },
      {
        "period": "2025-06-01",
        "count": 1
      },
      {
        "period": "2025-08-04",
        "count": 1
      },
      {
        "period": "2025-08-06",
        "count": 1
      },
      {
        "period": "2025-09-01",
        "count": 1
      },
      {
        "period": "2025-09-26",
        "count": 1
      },
      {
        "period": "2025-10-01",
        "count": 1
      },
      {
        "period": "2025-11-03",
        "count": 1
      },
      {
        "period": "2025-11-20",
        "count": 1
      },
      {
        "period": "2025-12-16",
        "count": 1
      },
      {
        "period": "2025-12-17",
        "count": 1
      },
      {
        "period": "2026-01-10",
        "count": 1
      }
    ],
    "organizations_by_type": [
      {
        "org_type": "Non-Profit",
        "count": 21
      }
    ],
    "organizations_by_size": [
      {
        "org_size": "Large",
        "count": 11
      },
      {
        "org_size": "Small",
        "count": 5
      },
      {
        "org_size": "Medium",
        "count": 5
      }
    ],
    "organizations_by_location": [
      {
        "state": "AK",
        "city": "North Judithbury",
        "count": 1
      },
      {
        "state": "NE",
        "city": "Barkerfurt",
        "count": 1
      },
      {
        "state": "WA",
        "city": "Stephaniemouth",
        "count": 1
      },
      {
        "state": "VT",
        "city": "Ortizmouth",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Victoriaport",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Hortonberg",
        "count": 1
      },
      {
        "state": "RI",
        "city": "South Rachelborough",
        "count": 1
      },
      {
        "state": "RI",
        "city": "Mitchellside",
        "count": 1
      },
      {
        "state": "NV",
        "city": "Leehaven",
        "count": 1
      },
      {
        "state": "NJ",
        "city": "South Williamton",
        "count": 1
      },
      {
        "state": "NC",
        "city": "Robinfort",
        "count": 1
      },
      {
        "state": "AR",
        "city": "Robertfort",
        "count": 1
      },
      {
        "state": "MT",
        "city": "Williamview",
        "count": 1
      },
      {
        "state": "MN",
        "city": "Lake Nancyview",
        "count": 1
      },
      {
        "state": "MI",
        "city": "West Williamport",
        "count": 1
      },
      {
        "state": "ME",
        "city": "Martinezbury",
        "count": 1
      },
      {
        "state": "KS",
        "city": "Burchborough",
        "count": 1
      },
      {
        "state": "FL",
        "city": "West Amandastad",
        "count": 1
      },
      {
        "state": "CA",
        "city": "New Susanville",
        "count": 1
      },
      {
        "state": "AZ",
        "city": "Kyleborough",
        "count": 1
      },
      {
        "state": "WI",
        "city": "Thomasberg",
        "count": 1
      }
    ],
    "collaborator_distribution": [
      {
        "category": "collaborator",
        "count": 11
      },
      {
        "category": "non_collaborator",
        "count": 10
      }
    ],
    "contributor_distribution": [
      {
        "category": "contributor",
        "count": 10
      },
      {
        "category": "non_contributor",
        "count": 11
      }
    ]
  }
}
```

## Scenario: Overview - filtered (is_collaborator=true)

Request filters:
```json
{
  "dashboard_type": "overview",
  "is_collaborator": true,
  "time_filter": "ALL"
}
```

Response:
```json
{
  "organization_overview": {
    "summary": {
      "total_organizations": 21,
      "non_profit_organizations": 11,
      "for_profit_organizations": 10,
      "collaborator_organizations": 21,
      "non_collaborator_organizations": 0,
      "contributor_organizations": 0,
      "non_contributor_organizations": 21
    },
    "organization_activity_trend": [
      {
        "period": "2023-09-20",
        "count": 1
      },
      {
        "period": "2023-11-03",
        "count": 1
      },
      {
        "period": "2024-02-06",
        "count": 1
      },
      {
        "period": "2024-02-22",
        "count": 1
      },
      {
        "period": "2024-04-03",
        "count": 1
      },
      {
        "period": "2024-07-12",
        "count": 1
      },
      {
        "period": "2024-08-02",
        "count": 1
      },
      {
        "period": "2024-08-04",
        "count": 1
      },
      {
        "period": "2024-09-08",
        "count": 1
      },
      {
        "period": "2024-09-11",
        "count": 1
      },
      {
        "period": "2024-11-06",
        "count": 1
      },
      {
        "period": "2024-11-15",
        "count": 1
      },
      {
        "period": "2024-12-20",
        "count": 1
      },
      {
        "period": "2025-01-05",
        "count": 1
      },
      {
        "period": "2025-04-05",
        "count": 1
      },
      {
        "period": "2025-08-04",
        "count": 1
      },
      {
        "period": "2025-09-03",
        "count": 1
      },
      {
        "period": "2025-09-26",
        "count": 1
      },
      {
        "period": "2025-10-01",
        "count": 1
      },
      {
        "period": "2025-11-03",
        "count": 1
      },
      {
        "period": "2025-12-17",
        "count": 1
      }
    ],
    "organizations_by_type": [
      {
        "org_type": "Non-Profit",
        "count": 11
      },
      {
        "org_type": "For-profit",
        "count": 10
      }
    ],
    "organizations_by_size": [
      {
        "org_size": "Large",
        "count": 11
      },
      {
        "org_size": "Small",
        "count": 5
      },
      {
        "org_size": "Medium",
        "count": 5
      }
    ],
    "organizations_by_location": [
      {
        "state": "AL",
        "city": "Smithberg",
        "count": 1
      },
      {
        "state": "NE",
        "city": "Barkerfurt",
        "count": 1
      },
      {
        "state": "VA",
        "city": "Sandrastad",
        "count": 1
      },
      {
        "state": "UT",
        "city": "New Thomas",
        "count": 1
      },
      {
        "state": "TX",
        "city": "East Jenniferfort",
        "count": 1
      },
      {
        "state": "RI",
        "city": "South Rachelborough",
        "count": 1
      },
      {
        "state": "RI",
        "city": "Mitchellside",
        "count": 1
      },
      {
        "state": "OR",
        "city": "Johnberg",
        "count": 1
      },
      {
        "state": "OK",
        "city": "Jeremyburgh",
        "count": 1
      },
      {
        "state": "NV",
        "city": "Leehaven",
        "count": 1
      },
      {
        "state": "MT",
        "city": "Wendyville",
        "count": 1
      },
      {
        "state": "AR",
        "city": "Robertfort",
        "count": 1
      },
      {
        "state": "MN",
        "city": "New Amyhaven",
        "count": 1
      },
      {
        "state": "MN",
        "city": "Lake Nancyview",
        "count": 1
      },
      {
        "state": "ME",
        "city": "Martinezbury",
        "count": 1
      },
      {
        "state": "IA",
        "city": "Lake Debbie",
        "count": 1
      },
      {
        "state": "FL",
        "city": "West Amandastad",
        "count": 1
      },
      {
        "state": "FL",
        "city": "North Jamesborough",
        "count": 1
      },
      {
        "state": "CA",
        "city": "New Susanville",
        "count": 1
      },
      {
        "state": "AZ",
        "city": "Kyleborough",
        "count": 1
      },
      {
        "state": "WA",
        "city": "Stephaniemouth",
        "count": 1
      }
    ],
    "collaborator_distribution": [
      {
        "category": "collaborator",
        "count": 21
      }
    ],
    "contributor_distribution": [
      {
        "category": "non_contributor",
        "count": 21
      }
    ]
  }
}
```

## Scenario: Overview - filtered (is_contributor=true)

Request filters:
```json
{
  "dashboard_type": "overview",
  "is_contributor": true,
  "time_filter": "ALL"
}
```

Response:
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
        "period": "2023-09-08",
        "count": 1
      },
      {
        "period": "2023-09-20",
        "count": 1
      },
      {
        "period": "2023-11-03",
        "count": 1
      },
      {
        "period": "2023-12-13",
        "count": 1
      },
      {
        "period": "2023-12-27",
        "count": 1
      },
      {
        "period": "2024-02-06",
        "count": 1
      },
      {
        "period": "2024-02-22",
        "count": 1
      },
      {
        "period": "2024-04-03",
        "count": 1
      },
      {
        "period": "2024-04-10",
        "count": 1
      },
      {
        "period": "2024-06-30",
        "count": 1
      },
      {
        "period": "2024-07-12",
        "count": 1
      },
      {
        "period": "2024-07-31",
        "count": 1
      },
      {
        "period": "2024-08-02",
        "count": 1
      },
      {
        "period": "2024-08-04",
        "count": 1
      },
      {
        "period": "2024-09-06",
        "count": 1
      },
      {
        "period": "2024-09-08",
        "count": 1
      },
      {
        "period": "2024-09-11",
        "count": 1
      },
      {
        "period": "2024-11-06",
        "count": 1
      },
      {
        "period": "2024-11-15",
        "count": 1
      },
      {
        "period": "2024-12-20",
        "count": 1
      },
      {
        "period": "2025-01-05",
        "count": 1
      },
      {
        "period": "2025-01-08",
        "count": 1
      },
      {
        "period": "2025-01-13",
        "count": 1
      },
      {
        "period": "2025-04-05",
        "count": 1
      },
      {
        "period": "2025-06-01",
        "count": 1
      },
      {
        "period": "2025-08-01",
        "count": 2
      },
      {
        "period": "2025-08-04",
        "count": 1
      },
      {
        "period": "2025-08-06",
        "count": 1
      },
      {
        "period": "2025-09-01",
        "count": 1
      },
      {
        "period": "2025-09-03",
        "count": 1
      },
      {
        "period": "2025-09-26",
        "count": 1
      },
      {
        "period": "2025-10-01",
        "count": 1
      },
      {
        "period": "2025-11-03",
        "count": 1
      },
      {
        "period": "2025-11-20",
        "count": 1
      },
      {
        "period": "2025-11-28",
        "count": 1
      },
      {
        "period": "2025-12-16",
        "count": 1
      },
      {
        "period": "2025-12-17",
        "count": 1
      },
      {
        "period": "2025-12-19",
        "count": 1
      },
      {
        "period": "2026-01-10",
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
    "organizations_by_location": [
      {
        "state": "AK",
        "city": "North Judithbury",
        "count": 1
      },
      {
        "state": "AL",
        "city": "Smithberg",
        "count": 1
      },
      {
        "state": "NC",
        "city": "Ronaldview",
        "count": 1
      },
      {
        "state": "NE",
        "city": "Barkerfurt",
        "count": 1
      },
      {
        "state": "NJ",
        "city": "South Williamton",
        "count": 1
      },
      {
        "state": "NV",
        "city": "Leehaven",
        "count": 1
      },
      {
        "state": "OH",
        "city": "South Jeffrey",
        "count": 1
      },
      {
        "state": "OK",
        "city": "Jeremyburgh",
        "count": 1
      },
      {
        "state": "OR",
        "city": "Johnberg",
        "count": 1
      },
      {
        "state": "RI",
        "city": "Mitchellside",
        "count": 1
      },
      {
        "state": "RI",
        "city": "South Rachelborough",
        "count": 1
      },
      {
        "state": "TX",
        "city": "East Jenniferfort",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Hortonberg",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Victoriaport",
        "count": 1
      },
      {
        "state": "UT",
        "city": "New Thomas",
        "count": 1
      },
      {
        "state": "VA",
        "city": "Sandrastad",
        "count": 1
      },
      {
        "state": "VT",
        "city": "Ortizmouth",
        "count": 1
      },
      {
        "state": "WA",
        "city": "Stephaniemouth",
        "count": 1
      },
      {
        "state": "WI",
        "city": "Thomasberg",
        "count": 1
      },
      {
        "state": "NC",
        "city": "Robinfort",
        "count": 1
      },
      {
        "state": "MT",
        "city": "Williamview",
        "count": 1
      },
      {
        "state": "MT",
        "city": "Wendyville",
        "count": 1
      },
      {
        "state": "IA",
        "city": "West Erik",
        "count": 1
      },
      {
        "state": "AR",
        "city": "East Amanda",
        "count": 1
      },
      {
        "state": "AR",
        "city": "Robertfort",
        "count": 1
      },
      {
        "state": "AZ",
        "city": "Kyleborough",
        "count": 1
      },
      {
        "state": "CA",
        "city": "New Susanville",
        "count": 1
      },
      {
        "state": "FL",
        "city": "North Jamesborough",
        "count": 1
      },
      {
        "state": "FL",
        "city": "West Amandastad",
        "count": 1
      },
      {
        "state": "IA",
        "city": "Lake Debbie",
        "count": 1
      },
      {
        "state": "IN",
        "city": "North Donnaport",
        "count": 1
      },
      {
        "state": "MO",
        "city": "Lake Deniseville",
        "count": 1
      },
      {
        "state": "IN",
        "city": "South Monicamouth",
        "count": 1
      },
      {
        "state": "KS",
        "city": "Burchborough",
        "count": 1
      },
      {
        "state": "KS",
        "city": "Port Andrew",
        "count": 1
      },
      {
        "state": "ME",
        "city": "Martinezbury",
        "count": 1
      },
      {
        "state": "MI",
        "city": "West Williamport",
        "count": 1
      },
      {
        "state": "MN",
        "city": "Lake Nancyview",
        "count": 1
      },
      {
        "state": "MN",
        "city": "New Amyhaven",
        "count": 1
      },
      {
        "state": "WY",
        "city": "Kingborough",
        "count": 1
      }
    ],
    "collaborator_distribution": [
      {
        "category": "collaborator",
        "count": 21
      },
      {
        "category": "non_collaborator",
        "count": 19
      }
    ],
    "contributor_distribution": [
      {
        "category": "contributor",
        "count": 19
      },
      {
        "category": "non_contributor",
        "count": 21
      }
    ]
  }
}
```

## Scenario: Overview - CUSTOM date range

Request filters:
```json
{
  "dashboard_type": "overview",
  "time_filter": "CUSTOM",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31"
}
```

Response:
```json
{
  "organization_overview": {
    "summary": {
      "total_organizations": 19,
      "non_profit_organizations": 11,
      "for_profit_organizations": 8,
      "collaborator_organizations": 8,
      "non_collaborator_organizations": 11,
      "contributor_organizations": 11,
      "non_contributor_organizations": 8
    },
    "organization_activity_trend": [
      {
        "period": "2025-01-05",
        "count": 1
      },
      {
        "period": "2025-01-08",
        "count": 1
      },
      {
        "period": "2025-01-13",
        "count": 1
      },
      {
        "period": "2025-04-05",
        "count": 1
      },
      {
        "period": "2025-06-01",
        "count": 1
      },
      {
        "period": "2025-08-01",
        "count": 2
      },
      {
        "period": "2025-08-04",
        "count": 1
      },
      {
        "period": "2025-08-06",
        "count": 1
      },
      {
        "period": "2025-09-01",
        "count": 1
      },
      {
        "period": "2025-09-03",
        "count": 1
      },
      {
        "period": "2025-09-26",
        "count": 1
      },
      {
        "period": "2025-10-01",
        "count": 1
      },
      {
        "period": "2025-11-03",
        "count": 1
      },
      {
        "period": "2025-11-20",
        "count": 1
      },
      {
        "period": "2025-11-28",
        "count": 1
      },
      {
        "period": "2025-12-16",
        "count": 1
      },
      {
        "period": "2025-12-17",
        "count": 1
      },
      {
        "period": "2025-12-19",
        "count": 1
      }
    ],
    "organizations_by_type": [
      {
        "org_type": "Non-Profit",
        "count": 11
      },
      {
        "org_type": "For-profit",
        "count": 8
      }
    ],
    "organizations_by_size": [
      {
        "org_size": "Large",
        "count": 13
      },
      {
        "org_size": "Small",
        "count": 4
      },
      {
        "org_size": "Medium",
        "count": 2
      }
    ],
    "organizations_by_location": [
      {
        "state": "AK",
        "city": "North Judithbury",
        "count": 1
      },
      {
        "state": "NC",
        "city": "Robinfort",
        "count": 1
      },
      {
        "state": "UT",
        "city": "New Thomas",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Victoriaport",
        "count": 1
      },
      {
        "state": "TX",
        "city": "East Jenniferfort",
        "count": 1
      },
      {
        "state": "OK",
        "city": "Jeremyburgh",
        "count": 1
      },
      {
        "state": "OH",
        "city": "South Jeffrey",
        "count": 1
      },
      {
        "state": "NJ",
        "city": "South Williamton",
        "count": 1
      },
      {
        "state": "NE",
        "city": "Barkerfurt",
        "count": 1
      },
      {
        "state": "MT",
        "city": "Williamview",
        "count": 1
      },
      {
        "state": "AR",
        "city": "East Amanda",
        "count": 1
      },
      {
        "state": "MO",
        "city": "Lake Deniseville",
        "count": 1
      },
      {
        "state": "MN",
        "city": "Lake Nancyview",
        "count": 1
      },
      {
        "state": "MI",
        "city": "West Williamport",
        "count": 1
      },
      {
        "state": "ME",
        "city": "Martinezbury",
        "count": 1
      },
      {
        "state": "KS",
        "city": "Port Andrew",
        "count": 1
      },
      {
        "state": "IN",
        "city": "South Monicamouth",
        "count": 1
      },
      {
        "state": "FL",
        "city": "West Amandastad",
        "count": 1
      },
      {
        "state": "WA",
        "city": "Stephaniemouth",
        "count": 1
      }
    ],
    "collaborator_distribution": [
      {
        "category": "collaborator",
        "count": 8
      },
      {
        "category": "non_collaborator",
        "count": 11
      }
    ],
    "contributor_distribution": [
      {
        "category": "contributor",
        "count": 11
      },
      {
        "category": "non_contributor",
        "count": 8
      }
    ]
  }
}
```

## Scenario: Performance - ALL

Request filters:
```json
{
  "dashboard_type": "performance",
  "time_filter": "ALL"
}
```

Response:
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
        "org_rating": 5.0,
        "city_name": "New Susanville",
        "state_id": "CA"
      },
      {
        "org_id": "ORG00036",
        "org_name": "Golden Gate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Kyleborough",
        "state_id": "AZ"
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Nancyview",
        "state_id": "MN"
      },
      {
        "org_id": "ORG00001",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "North Judithbury",
        "state_id": "AK"
      },
      {
        "org_id": "ORG00011",
        "org_name": "Hopewell Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 5.0,
        "city_name": "South Rachelborough",
        "state_id": "RI"
      },
      {
        "org_id": "ORG00009",
        "org_name": "Lakeside Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Williamview",
        "state_id": "MT"
      },
      {
        "org_id": "ORG00031",
        "org_name": "Maplewood Housing Trust",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Sandrastad",
        "state_id": "VA"
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Leehaven",
        "state_id": "NV"
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "West Williamport",
        "state_id": "MI"
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Debbie",
        "state_id": "IA"
      }
    ],
    "top_collaborator_organizations": [
      {
        "org_id": "ORG00019",
        "org_name": "Cedar Valley Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "New Susanville",
        "state_id": "CA"
      },
      {
        "org_id": "ORG00036",
        "org_name": "Golden Gate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Kyleborough",
        "state_id": "AZ"
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Nancyview",
        "state_id": "MN"
      },
      {
        "org_id": "ORG00011",
        "org_name": "Hopewell Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 5.0,
        "city_name": "South Rachelborough",
        "state_id": "RI"
      },
      {
        "org_id": "ORG00031",
        "org_name": "Maplewood Housing Trust",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Sandrastad",
        "state_id": "VA"
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Leehaven",
        "state_id": "NV"
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Debbie",
        "state_id": "IA"
      },
      {
        "org_id": "ORG00027",
        "org_name": "Silverline Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Wendyville",
        "state_id": "MT"
      },
      {
        "org_id": "ORG00020",
        "org_name": "Lakeside Legal Aid Society",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Barkerfurt",
        "state_id": "NE"
      },
      {
        "org_id": "ORG00023",
        "org_name": "Maplewood Veterans Support",
        "org_type": "For-profit",
        "org_size": "Medium",
        "org_rating": 4.0,
        "city_name": "Smithberg",
        "state_id": "AL"
      }
    ],
    "top_contributor_organizations": [
      {
        "org_id": "ORG00001",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "North Judithbury",
        "state_id": "AK"
      },
      {
        "org_id": "ORG00009",
        "org_name": "Lakeside Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Williamview",
        "state_id": "MT"
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "West Williamport",
        "state_id": "MI"
      },
      {
        "org_id": "ORG00029",
        "org_name": "Unity Youth Alliance",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "South Williamton",
        "state_id": "NJ"
      },
      {
        "org_id": "ORG00035",
        "org_name": "Summit Relief Network",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Ortizmouth",
        "state_id": "VT"
      },
      {
        "org_id": "ORG00015",
        "org_name": "Unity Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Port Andrew",
        "state_id": "KS"
      },
      {
        "org_id": "ORG00006",
        "org_name": "Harbor Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Medium",
        "org_rating": 3.0,
        "city_name": "Lake Deniseville",
        "state_id": "MO"
      },
      {
        "org_id": "ORG00024",
        "org_name": "Liberty Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3.0,
        "city_name": "East Amanda",
        "state_id": "AR"
      },
      {
        "org_id": "ORG00025",
        "org_name": "Maplewood Animal Rescue",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 3.0,
        "city_name": "Victoriaport",
        "state_id": "TX"
      },
      {
        "org_id": "ORG00003",
        "org_name": "Northgate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 3.0,
        "city_name": "Thomasberg",
        "state_id": "WI"
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

## Scenario: Performance - filtered (org_rating=5)

Request filters:
```json
{
  "dashboard_type": "performance",
  "org_rating": 5,
  "time_filter": "ALL"
}
```

Response:
```json
{
  "organization_performance": {
    "summary": {
      "average_rating": 5.0,
      "rated_organizations": 12,
      "unrated_organizations": 0,
      "five_star_organizations": 12
    },
    "rating_distribution": [
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
        "org_rating": 5.0,
        "city_name": "New Susanville",
        "state_id": "CA"
      },
      {
        "org_id": "ORG00036",
        "org_name": "Golden Gate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Kyleborough",
        "state_id": "AZ"
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Nancyview",
        "state_id": "MN"
      },
      {
        "org_id": "ORG00001",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "North Judithbury",
        "state_id": "AK"
      },
      {
        "org_id": "ORG00011",
        "org_name": "Hopewell Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 5.0,
        "city_name": "South Rachelborough",
        "state_id": "RI"
      },
      {
        "org_id": "ORG00009",
        "org_name": "Lakeside Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Williamview",
        "state_id": "MT"
      },
      {
        "org_id": "ORG00031",
        "org_name": "Maplewood Housing Trust",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Sandrastad",
        "state_id": "VA"
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Leehaven",
        "state_id": "NV"
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "West Williamport",
        "state_id": "MI"
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Debbie",
        "state_id": "IA"
      }
    ],
    "top_collaborator_organizations": [
      {
        "org_id": "ORG00019",
        "org_name": "Cedar Valley Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "New Susanville",
        "state_id": "CA"
      },
      {
        "org_id": "ORG00036",
        "org_name": "Golden Gate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Kyleborough",
        "state_id": "AZ"
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Nancyview",
        "state_id": "MN"
      },
      {
        "org_id": "ORG00011",
        "org_name": "Hopewell Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 5.0,
        "city_name": "South Rachelborough",
        "state_id": "RI"
      },
      {
        "org_id": "ORG00031",
        "org_name": "Maplewood Housing Trust",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Sandrastad",
        "state_id": "VA"
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Leehaven",
        "state_id": "NV"
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Debbie",
        "state_id": "IA"
      },
      {
        "org_id": "ORG00027",
        "org_name": "Silverline Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Wendyville",
        "state_id": "MT"
      }
    ],
    "top_contributor_organizations": [
      {
        "org_id": "ORG00001",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "North Judithbury",
        "state_id": "AK"
      },
      {
        "org_id": "ORG00009",
        "org_name": "Lakeside Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Williamview",
        "state_id": "MT"
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "West Williamport",
        "state_id": "MI"
      },
      {
        "org_id": "ORG00029",
        "org_name": "Unity Youth Alliance",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "South Williamton",
        "state_id": "NJ"
      }
    ],
    "ratings_by_organization_type": [
      {
        "org_type": "For-profit",
        "average_rating": 5.0,
        "rated_count": 3
      },
      {
        "org_type": "Non-Profit",
        "average_rating": 5.0,
        "rated_count": 9
      }
    ],
    "ratings_by_organization_size": [
      {
        "org_size": "Large",
        "average_rating": 5.0,
        "rated_count": 6
      },
      {
        "org_size": "Medium",
        "average_rating": 5.0,
        "rated_count": 1
      },
      {
        "org_size": "Small",
        "average_rating": 5.0,
        "rated_count": 5
      }
    ]
  }
}
```

## Scenario: Performance - filtered (org_size=Large)

Request filters:
```json
{
  "dashboard_type": "performance",
  "org_size": "Large",
  "time_filter": "ALL"
}
```

Response:
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
        "org_rating": 5.0,
        "city_name": "New Susanville",
        "state_id": "CA"
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Nancyview",
        "state_id": "MN"
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Leehaven",
        "state_id": "NV"
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "West Williamport",
        "state_id": "MI"
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Debbie",
        "state_id": "IA"
      },
      {
        "org_id": "ORG00029",
        "org_name": "Unity Youth Alliance",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "South Williamton",
        "state_id": "NJ"
      },
      {
        "org_id": "ORG00020",
        "org_name": "Lakeside Legal Aid Society",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Barkerfurt",
        "state_id": "NE"
      },
      {
        "org_id": "ORG00035",
        "org_name": "Summit Relief Network",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Ortizmouth",
        "state_id": "VT"
      },
      {
        "org_id": "ORG00015",
        "org_name": "Unity Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Port Andrew",
        "state_id": "KS"
      },
      {
        "org_id": "ORG00012",
        "org_name": "Harbor Animal Rescue",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3.0,
        "city_name": "New Thomas",
        "state_id": "UT"
      }
    ],
    "top_collaborator_organizations": [
      {
        "org_id": "ORG00019",
        "org_name": "Cedar Valley Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "New Susanville",
        "state_id": "CA"
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Nancyview",
        "state_id": "MN"
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Leehaven",
        "state_id": "NV"
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Debbie",
        "state_id": "IA"
      },
      {
        "org_id": "ORG00020",
        "org_name": "Lakeside Legal Aid Society",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Barkerfurt",
        "state_id": "NE"
      },
      {
        "org_id": "ORG00012",
        "org_name": "Harbor Animal Rescue",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3.0,
        "city_name": "New Thomas",
        "state_id": "UT"
      },
      {
        "org_id": "ORG00021",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 2.0,
        "city_name": "Robertfort",
        "state_id": "AR"
      },
      {
        "org_id": "ORG00017",
        "org_name": "Liberty Education Fund",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 2.0,
        "city_name": "East Jenniferfort",
        "state_id": "TX"
      },
      {
        "org_id": "ORG00016",
        "org_name": "Meadowbrook Legal Aid Society",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 2.0,
        "city_name": "West Amandastad",
        "state_id": "FL"
      },
      {
        "org_id": "ORG00018",
        "org_name": "Sunrise Community Foundation",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 2.0,
        "city_name": "Jeremyburgh",
        "state_id": "OK"
      }
    ],
    "top_contributor_organizations": [
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "West Williamport",
        "state_id": "MI"
      },
      {
        "org_id": "ORG00029",
        "org_name": "Unity Youth Alliance",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "South Williamton",
        "state_id": "NJ"
      },
      {
        "org_id": "ORG00035",
        "org_name": "Summit Relief Network",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Ortizmouth",
        "state_id": "VT"
      },
      {
        "org_id": "ORG00015",
        "org_name": "Unity Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Port Andrew",
        "state_id": "KS"
      },
      {
        "org_id": "ORG00024",
        "org_name": "Liberty Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3.0,
        "city_name": "East Amanda",
        "state_id": "AR"
      },
      {
        "org_id": "ORG00025",
        "org_name": "Maplewood Animal Rescue",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 3.0,
        "city_name": "Victoriaport",
        "state_id": "TX"
      },
      {
        "org_id": "ORG00030",
        "org_name": "Pinecrest Arts Collective",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3.0,
        "city_name": "Ronaldview",
        "state_id": "NC"
      },
      {
        "org_id": "ORG00002",
        "org_name": "Summit Community Foundation",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 2.0,
        "city_name": "North Donnaport",
        "state_id": "IN"
      },
      {
        "org_id": "ORG00033",
        "org_name": "Cedar Valley Health Initiative",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 1.0,
        "city_name": "South Monicamouth",
        "state_id": "IN"
      },
      {
        "org_id": "ORG00026",
        "org_name": "Lakeside Food Bank",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 1.0,
        "city_name": "Robinfort",
        "state_id": "NC"
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

## Scenario: Both dashboards - ALL

Request filters:
```json
{
  "dashboard_type": "both",
  "time_filter": "ALL",
  "group_by": "monthly"
}
```

Response:
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
        "period": "2023-09",
        "count": 2
      },
      {
        "period": "2023-11",
        "count": 1
      },
      {
        "period": "2023-12",
        "count": 2
      },
      {
        "period": "2024-02",
        "count": 2
      },
      {
        "period": "2024-04",
        "count": 2
      },
      {
        "period": "2024-06",
        "count": 1
      },
      {
        "period": "2024-07",
        "count": 2
      },
      {
        "period": "2024-08",
        "count": 2
      },
      {
        "period": "2024-09",
        "count": 3
      },
      {
        "period": "2024-11",
        "count": 2
      },
      {
        "period": "2024-12",
        "count": 1
      },
      {
        "period": "2025-01",
        "count": 3
      },
      {
        "period": "2025-04",
        "count": 1
      },
      {
        "period": "2025-06",
        "count": 1
      },
      {
        "period": "2025-08",
        "count": 4
      },
      {
        "period": "2025-09",
        "count": 3
      },
      {
        "period": "2025-10",
        "count": 1
      },
      {
        "period": "2025-11",
        "count": 3
      },
      {
        "period": "2025-12",
        "count": 3
      },
      {
        "period": "2026-01",
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
    "organizations_by_location": [
      {
        "state": "AK",
        "city": "North Judithbury",
        "count": 1
      },
      {
        "state": "AL",
        "city": "Smithberg",
        "count": 1
      },
      {
        "state": "NC",
        "city": "Ronaldview",
        "count": 1
      },
      {
        "state": "NE",
        "city": "Barkerfurt",
        "count": 1
      },
      {
        "state": "NJ",
        "city": "South Williamton",
        "count": 1
      },
      {
        "state": "NV",
        "city": "Leehaven",
        "count": 1
      },
      {
        "state": "OH",
        "city": "South Jeffrey",
        "count": 1
      },
      {
        "state": "OK",
        "city": "Jeremyburgh",
        "count": 1
      },
      {
        "state": "OR",
        "city": "Johnberg",
        "count": 1
      },
      {
        "state": "RI",
        "city": "Mitchellside",
        "count": 1
      },
      {
        "state": "RI",
        "city": "South Rachelborough",
        "count": 1
      },
      {
        "state": "TX",
        "city": "East Jenniferfort",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Hortonberg",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Victoriaport",
        "count": 1
      },
      {
        "state": "UT",
        "city": "New Thomas",
        "count": 1
      },
      {
        "state": "VA",
        "city": "Sandrastad",
        "count": 1
      },
      {
        "state": "VT",
        "city": "Ortizmouth",
        "count": 1
      },
      {
        "state": "WA",
        "city": "Stephaniemouth",
        "count": 1
      },
      {
        "state": "WI",
        "city": "Thomasberg",
        "count": 1
      },
      {
        "state": "NC",
        "city": "Robinfort",
        "count": 1
      },
      {
        "state": "MT",
        "city": "Williamview",
        "count": 1
      },
      {
        "state": "MT",
        "city": "Wendyville",
        "count": 1
      },
      {
        "state": "IA",
        "city": "West Erik",
        "count": 1
      },
      {
        "state": "AR",
        "city": "East Amanda",
        "count": 1
      },
      {
        "state": "AR",
        "city": "Robertfort",
        "count": 1
      },
      {
        "state": "AZ",
        "city": "Kyleborough",
        "count": 1
      },
      {
        "state": "CA",
        "city": "New Susanville",
        "count": 1
      },
      {
        "state": "FL",
        "city": "North Jamesborough",
        "count": 1
      },
      {
        "state": "FL",
        "city": "West Amandastad",
        "count": 1
      },
      {
        "state": "IA",
        "city": "Lake Debbie",
        "count": 1
      },
      {
        "state": "IN",
        "city": "North Donnaport",
        "count": 1
      },
      {
        "state": "MO",
        "city": "Lake Deniseville",
        "count": 1
      },
      {
        "state": "IN",
        "city": "South Monicamouth",
        "count": 1
      },
      {
        "state": "KS",
        "city": "Burchborough",
        "count": 1
      },
      {
        "state": "KS",
        "city": "Port Andrew",
        "count": 1
      },
      {
        "state": "ME",
        "city": "Martinezbury",
        "count": 1
      },
      {
        "state": "MI",
        "city": "West Williamport",
        "count": 1
      },
      {
        "state": "MN",
        "city": "Lake Nancyview",
        "count": 1
      },
      {
        "state": "MN",
        "city": "New Amyhaven",
        "count": 1
      },
      {
        "state": "WY",
        "city": "Kingborough",
        "count": 1
      }
    ],
    "collaborator_distribution": [
      {
        "category": "collaborator",
        "count": 21
      },
      {
        "category": "non_collaborator",
        "count": 19
      }
    ],
    "contributor_distribution": [
      {
        "category": "contributor",
        "count": 19
      },
      {
        "category": "non_contributor",
        "count": 21
      }
    ]
  },
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
        "org_rating": 5.0,
        "city_name": "New Susanville",
        "state_id": "CA"
      },
      {
        "org_id": "ORG00036",
        "org_name": "Golden Gate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Kyleborough",
        "state_id": "AZ"
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Nancyview",
        "state_id": "MN"
      },
      {
        "org_id": "ORG00001",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "North Judithbury",
        "state_id": "AK"
      },
      {
        "org_id": "ORG00011",
        "org_name": "Hopewell Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 5.0,
        "city_name": "South Rachelborough",
        "state_id": "RI"
      },
      {
        "org_id": "ORG00009",
        "org_name": "Lakeside Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Williamview",
        "state_id": "MT"
      },
      {
        "org_id": "ORG00031",
        "org_name": "Maplewood Housing Trust",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Sandrastad",
        "state_id": "VA"
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Leehaven",
        "state_id": "NV"
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "West Williamport",
        "state_id": "MI"
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Debbie",
        "state_id": "IA"
      }
    ],
    "top_collaborator_organizations": [
      {
        "org_id": "ORG00019",
        "org_name": "Cedar Valley Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "New Susanville",
        "state_id": "CA"
      },
      {
        "org_id": "ORG00036",
        "org_name": "Golden Gate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Kyleborough",
        "state_id": "AZ"
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Nancyview",
        "state_id": "MN"
      },
      {
        "org_id": "ORG00011",
        "org_name": "Hopewell Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 5.0,
        "city_name": "South Rachelborough",
        "state_id": "RI"
      },
      {
        "org_id": "ORG00031",
        "org_name": "Maplewood Housing Trust",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Sandrastad",
        "state_id": "VA"
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Leehaven",
        "state_id": "NV"
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Debbie",
        "state_id": "IA"
      },
      {
        "org_id": "ORG00027",
        "org_name": "Silverline Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Wendyville",
        "state_id": "MT"
      },
      {
        "org_id": "ORG00020",
        "org_name": "Lakeside Legal Aid Society",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Barkerfurt",
        "state_id": "NE"
      },
      {
        "org_id": "ORG00023",
        "org_name": "Maplewood Veterans Support",
        "org_type": "For-profit",
        "org_size": "Medium",
        "org_rating": 4.0,
        "city_name": "Smithberg",
        "state_id": "AL"
      }
    ],
    "top_contributor_organizations": [
      {
        "org_id": "ORG00001",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "North Judithbury",
        "state_id": "AK"
      },
      {
        "org_id": "ORG00009",
        "org_name": "Lakeside Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Williamview",
        "state_id": "MT"
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "West Williamport",
        "state_id": "MI"
      },
      {
        "org_id": "ORG00029",
        "org_name": "Unity Youth Alliance",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "South Williamton",
        "state_id": "NJ"
      },
      {
        "org_id": "ORG00035",
        "org_name": "Summit Relief Network",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Ortizmouth",
        "state_id": "VT"
      },
      {
        "org_id": "ORG00015",
        "org_name": "Unity Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Port Andrew",
        "state_id": "KS"
      },
      {
        "org_id": "ORG00006",
        "org_name": "Harbor Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Medium",
        "org_rating": 3.0,
        "city_name": "Lake Deniseville",
        "state_id": "MO"
      },
      {
        "org_id": "ORG00024",
        "org_name": "Liberty Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3.0,
        "city_name": "East Amanda",
        "state_id": "AR"
      },
      {
        "org_id": "ORG00025",
        "org_name": "Maplewood Animal Rescue",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 3.0,
        "city_name": "Victoriaport",
        "state_id": "TX"
      },
      {
        "org_id": "ORG00003",
        "org_name": "Northgate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 3.0,
        "city_name": "Thomasberg",
        "state_id": "WI"
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

## Scenario: lambda_handler(event) end-to-end

Event:
```json
{
  "body": "{\"dashboard_type\": \"both\", \"time_filter\": \"ALL\"}"
}
```

statusCode: 200

Response body:
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
        "period": "2023-09-08",
        "count": 1
      },
      {
        "period": "2023-09-20",
        "count": 1
      },
      {
        "period": "2023-11-03",
        "count": 1
      },
      {
        "period": "2023-12-13",
        "count": 1
      },
      {
        "period": "2023-12-27",
        "count": 1
      },
      {
        "period": "2024-02-06",
        "count": 1
      },
      {
        "period": "2024-02-22",
        "count": 1
      },
      {
        "period": "2024-04-03",
        "count": 1
      },
      {
        "period": "2024-04-10",
        "count": 1
      },
      {
        "period": "2024-06-30",
        "count": 1
      },
      {
        "period": "2024-07-12",
        "count": 1
      },
      {
        "period": "2024-07-31",
        "count": 1
      },
      {
        "period": "2024-08-02",
        "count": 1
      },
      {
        "period": "2024-08-04",
        "count": 1
      },
      {
        "period": "2024-09-06",
        "count": 1
      },
      {
        "period": "2024-09-08",
        "count": 1
      },
      {
        "period": "2024-09-11",
        "count": 1
      },
      {
        "period": "2024-11-06",
        "count": 1
      },
      {
        "period": "2024-11-15",
        "count": 1
      },
      {
        "period": "2024-12-20",
        "count": 1
      },
      {
        "period": "2025-01-05",
        "count": 1
      },
      {
        "period": "2025-01-08",
        "count": 1
      },
      {
        "period": "2025-01-13",
        "count": 1
      },
      {
        "period": "2025-04-05",
        "count": 1
      },
      {
        "period": "2025-06-01",
        "count": 1
      },
      {
        "period": "2025-08-01",
        "count": 2
      },
      {
        "period": "2025-08-04",
        "count": 1
      },
      {
        "period": "2025-08-06",
        "count": 1
      },
      {
        "period": "2025-09-01",
        "count": 1
      },
      {
        "period": "2025-09-03",
        "count": 1
      },
      {
        "period": "2025-09-26",
        "count": 1
      },
      {
        "period": "2025-10-01",
        "count": 1
      },
      {
        "period": "2025-11-03",
        "count": 1
      },
      {
        "period": "2025-11-20",
        "count": 1
      },
      {
        "period": "2025-11-28",
        "count": 1
      },
      {
        "period": "2025-12-16",
        "count": 1
      },
      {
        "period": "2025-12-17",
        "count": 1
      },
      {
        "period": "2025-12-19",
        "count": 1
      },
      {
        "period": "2026-01-10",
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
    "organizations_by_location": [
      {
        "state": "AK",
        "city": "North Judithbury",
        "count": 1
      },
      {
        "state": "AL",
        "city": "Smithberg",
        "count": 1
      },
      {
        "state": "NC",
        "city": "Ronaldview",
        "count": 1
      },
      {
        "state": "NE",
        "city": "Barkerfurt",
        "count": 1
      },
      {
        "state": "NJ",
        "city": "South Williamton",
        "count": 1
      },
      {
        "state": "NV",
        "city": "Leehaven",
        "count": 1
      },
      {
        "state": "OH",
        "city": "South Jeffrey",
        "count": 1
      },
      {
        "state": "OK",
        "city": "Jeremyburgh",
        "count": 1
      },
      {
        "state": "OR",
        "city": "Johnberg",
        "count": 1
      },
      {
        "state": "RI",
        "city": "Mitchellside",
        "count": 1
      },
      {
        "state": "RI",
        "city": "South Rachelborough",
        "count": 1
      },
      {
        "state": "TX",
        "city": "East Jenniferfort",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Hortonberg",
        "count": 1
      },
      {
        "state": "TX",
        "city": "Victoriaport",
        "count": 1
      },
      {
        "state": "UT",
        "city": "New Thomas",
        "count": 1
      },
      {
        "state": "VA",
        "city": "Sandrastad",
        "count": 1
      },
      {
        "state": "VT",
        "city": "Ortizmouth",
        "count": 1
      },
      {
        "state": "WA",
        "city": "Stephaniemouth",
        "count": 1
      },
      {
        "state": "WI",
        "city": "Thomasberg",
        "count": 1
      },
      {
        "state": "NC",
        "city": "Robinfort",
        "count": 1
      },
      {
        "state": "MT",
        "city": "Williamview",
        "count": 1
      },
      {
        "state": "MT",
        "city": "Wendyville",
        "count": 1
      },
      {
        "state": "IA",
        "city": "West Erik",
        "count": 1
      },
      {
        "state": "AR",
        "city": "East Amanda",
        "count": 1
      },
      {
        "state": "AR",
        "city": "Robertfort",
        "count": 1
      },
      {
        "state": "AZ",
        "city": "Kyleborough",
        "count": 1
      },
      {
        "state": "CA",
        "city": "New Susanville",
        "count": 1
      },
      {
        "state": "FL",
        "city": "North Jamesborough",
        "count": 1
      },
      {
        "state": "FL",
        "city": "West Amandastad",
        "count": 1
      },
      {
        "state": "IA",
        "city": "Lake Debbie",
        "count": 1
      },
      {
        "state": "IN",
        "city": "North Donnaport",
        "count": 1
      },
      {
        "state": "MO",
        "city": "Lake Deniseville",
        "count": 1
      },
      {
        "state": "IN",
        "city": "South Monicamouth",
        "count": 1
      },
      {
        "state": "KS",
        "city": "Burchborough",
        "count": 1
      },
      {
        "state": "KS",
        "city": "Port Andrew",
        "count": 1
      },
      {
        "state": "ME",
        "city": "Martinezbury",
        "count": 1
      },
      {
        "state": "MI",
        "city": "West Williamport",
        "count": 1
      },
      {
        "state": "MN",
        "city": "Lake Nancyview",
        "count": 1
      },
      {
        "state": "MN",
        "city": "New Amyhaven",
        "count": 1
      },
      {
        "state": "WY",
        "city": "Kingborough",
        "count": 1
      }
    ],
    "collaborator_distribution": [
      {
        "category": "collaborator",
        "count": 21
      },
      {
        "category": "non_collaborator",
        "count": 19
      }
    ],
    "contributor_distribution": [
      {
        "category": "contributor",
        "count": 19
      },
      {
        "category": "non_contributor",
        "count": 21
      }
    ]
  },
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
        "org_rating": 5.0,
        "city_name": "New Susanville",
        "state_id": "CA"
      },
      {
        "org_id": "ORG00036",
        "org_name": "Golden Gate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Kyleborough",
        "state_id": "AZ"
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Nancyview",
        "state_id": "MN"
      },
      {
        "org_id": "ORG00001",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "North Judithbury",
        "state_id": "AK"
      },
      {
        "org_id": "ORG00011",
        "org_name": "Hopewell Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 5.0,
        "city_name": "South Rachelborough",
        "state_id": "RI"
      },
      {
        "org_id": "ORG00009",
        "org_name": "Lakeside Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Williamview",
        "state_id": "MT"
      },
      {
        "org_id": "ORG00031",
        "org_name": "Maplewood Housing Trust",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Sandrastad",
        "state_id": "VA"
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Leehaven",
        "state_id": "NV"
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "West Williamport",
        "state_id": "MI"
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Debbie",
        "state_id": "IA"
      }
    ],
    "top_collaborator_organizations": [
      {
        "org_id": "ORG00019",
        "org_name": "Cedar Valley Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "New Susanville",
        "state_id": "CA"
      },
      {
        "org_id": "ORG00036",
        "org_name": "Golden Gate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Kyleborough",
        "state_id": "AZ"
      },
      {
        "org_id": "ORG00004",
        "org_name": "Harbor Family Services",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Nancyview",
        "state_id": "MN"
      },
      {
        "org_id": "ORG00011",
        "org_name": "Hopewell Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 5.0,
        "city_name": "South Rachelborough",
        "state_id": "RI"
      },
      {
        "org_id": "ORG00031",
        "org_name": "Maplewood Housing Trust",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Sandrastad",
        "state_id": "VA"
      },
      {
        "org_id": "ORG00022",
        "org_name": "Meadowbrook Housing Trust",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Leehaven",
        "state_id": "NV"
      },
      {
        "org_id": "ORG00008",
        "org_name": "Riverside Environmental Coalition",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "Lake Debbie",
        "state_id": "IA"
      },
      {
        "org_id": "ORG00027",
        "org_name": "Silverline Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Wendyville",
        "state_id": "MT"
      },
      {
        "org_id": "ORG00020",
        "org_name": "Lakeside Legal Aid Society",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Barkerfurt",
        "state_id": "NE"
      },
      {
        "org_id": "ORG00023",
        "org_name": "Maplewood Veterans Support",
        "org_type": "For-profit",
        "org_size": "Medium",
        "org_rating": 4.0,
        "city_name": "Smithberg",
        "state_id": "AL"
      }
    ],
    "top_contributor_organizations": [
      {
        "org_id": "ORG00001",
        "org_name": "Harbor Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "North Judithbury",
        "state_id": "AK"
      },
      {
        "org_id": "ORG00009",
        "org_name": "Lakeside Veterans Support",
        "org_type": "Non-Profit",
        "org_size": "Small",
        "org_rating": 5.0,
        "city_name": "Williamview",
        "state_id": "MT"
      },
      {
        "org_id": "ORG00034",
        "org_name": "Northgate Community Foundation",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "West Williamport",
        "state_id": "MI"
      },
      {
        "org_id": "ORG00029",
        "org_name": "Unity Youth Alliance",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 5.0,
        "city_name": "South Williamton",
        "state_id": "NJ"
      },
      {
        "org_id": "ORG00035",
        "org_name": "Summit Relief Network",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Ortizmouth",
        "state_id": "VT"
      },
      {
        "org_id": "ORG00015",
        "org_name": "Unity Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 4.0,
        "city_name": "Port Andrew",
        "state_id": "KS"
      },
      {
        "org_id": "ORG00006",
        "org_name": "Harbor Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Medium",
        "org_rating": 3.0,
        "city_name": "Lake Deniseville",
        "state_id": "MO"
      },
      {
        "org_id": "ORG00024",
        "org_name": "Liberty Senior Care Network",
        "org_type": "For-profit",
        "org_size": "Large",
        "org_rating": 3.0,
        "city_name": "East Amanda",
        "state_id": "AR"
      },
      {
        "org_id": "ORG00025",
        "org_name": "Maplewood Animal Rescue",
        "org_type": "Non-Profit",
        "org_size": "Large",
        "org_rating": 3.0,
        "city_name": "Victoriaport",
        "state_id": "TX"
      },
      {
        "org_id": "ORG00003",
        "org_name": "Northgate Education Fund",
        "org_type": "Non-Profit",
        "org_size": "Medium",
        "org_rating": 3.0,
        "city_name": "Thomasberg",
        "state_id": "WI"
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

## Scenario: lambda_handler(event) with invalid dashboard_type

statusCode: 400

Response body:
```json
{
  "error": "Invalid dashboard_type. Expected 'overview', 'performance', or 'both'."
}
```

## Summary

✅ All 14 scenarios ran and all invariant checks passed.
