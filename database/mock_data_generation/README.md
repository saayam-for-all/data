# Schema-driven mock data generation for `users` and `request`

This package replaces hardcoded table generation with a schema-driven flow that reads:

- `db_info.json`
- lookup/reference CSV files under `database/lookup_tables`

It is designed for local development first, matching the repo guidance in `CONTRIBUTING.md` about testing locally with mock data before handing work to team leads for deployment. The code is structured as reusable Python modules with tests and a thin HTTP wrapper for curl-based validation, which fits the contribution rules and local-first workflow described in the repo guidance. See the contributing reference here: fileciteturn1file0

## What this solves

- adapts to column additions/removals in schema metadata
- preserves exact schema column order in generated CSVs
- enforces FK relationships using parent tables and lookup tables
- keeps `users` and `request` generation realistic without baking the full schema into the code
- supports curl-based smoke tests through a small FastAPI wrapper

## Suggested placement in the repo

Place these files under:

```text
/database/mock-data-generation/
```

Suggested structure:

```text
mock-data-generation/
├── README.md
├── scripts/
│   ├── test_cli.sh
│   └── test_http.sh
├── src/
│   └── mock_data_generation/
│       ├── __init__.py
│       ├── api_app.py
│       ├── config.py
│       ├── dependency_resolver.py
│       ├── generate_tables.py
│       ├── lookup_loader.py
│       ├── schema_parser.py
│       ├── validators.py
│       └── generators/
│           ├── __init__.py
│           ├── base_generators.py
│           └── table_rules.py
└── tests/
    ├── test_http_api.py
    └── test_schema_driven_generation.py
```

## Install

```bash
pip install faker fastapi uvicorn pytest
```

## CLI usage

```bash
python -m mock_data_generation.generate_tables \
  --schema ./database/mock-data-generation/db_info.json \
  --lookup-dir ./database/lookup_tables \
  --output-dir ./database/mock_db \
  --tables users,request \
  --seed 42 \
  --row-counts '{"users":5000,"request":20000}'
```

## HTTP usage for curl-based tests

Start the local app:

```bash
uvicorn mock_data_generation.api_app:app --reload
```

Health check:

```bash
curl -s http://127.0.0.1:8000/health
```

Generate output:

```bash
curl -s -X POST http://127.0.0.1:8000/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_path": "./database/mock-data-generation/db_info.json",
    "lookup_dir": "./database/lookup_tables",
    "output_dir": "./database/mock_db",
    "tables": ["users", "request"],
    "row_counts": {"users": 5000, "request": 20000},
    "seed": 42
  }'
```

## What is schema-driven vs what is table-aware

Schema-driven:
- which columns exist
- column order
- base data types
- PK/FK relationships
- nullability

Light table-aware overrides:
- `users.full_name` assembled from name columns
- `users.state_id` and `users.country_id` kept consistent from real lookup rows
- `request.serviced_date` only populated for resolved statuses
- `request.last_update_date` forced after `submission_date`

This keeps the engine flexible while still producing useful mock data.

## Validation

The validator checks:
- output file exists
- CSV header matches schema order
- required columns are not blank
- FK values point to valid parent/lookup IDs

## Practical notes

- `DEFAULT_FK_MAP` is included because many schema exports do not carry FK metadata cleanly. If your `db_info.json` already includes FK metadata, the parser will use it.
- The current implementation focuses on `users` and `request`, but the structure is reusable enough to extend to more tables later.
- The `/validate` endpoint currently reruns the service to reuse the same validation path. In the repo, I would likely split pure validation into a dedicated function so validation can run without regeneration.
