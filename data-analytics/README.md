# Data Analytics

This space is reserved for the Data Analytics team.

Use this folder for notebooks, SQL queries, dashboards, and visualizations
that are not embedded directly in the application codebase.

## Size and Contribution Analytics local check

Set `MOCK_DATA_DIR` to a directory containing `organizations.csv`, `states.csv`,
and `countries.csv`, then run:

```sh
USE_MOCK_DATA=true MOCK_DATA_DIR=/path/to/mock-csvs \
  venv/bin/python data-analytics/lambda_functions/size_contribution_analytics.py
```

The runner prints one JSON line for each of the six acceptance scenarios.
The [captured local output](size_contribution_local_run.jsonl) was produced on
2026-09-23 using temporary CSVs with five organizations: four in the USA and
one in Canada; four non-profits and one for-profit; two contributors and two
collaborators. The temporary CSVs are not part of the repository. The handler
tests create their own CSVs in temporary directories.
