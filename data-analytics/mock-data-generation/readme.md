# Mock Data Generation

Generates mock CSV data for local dev, API testing, dashboards, and demos.
It never touches a database -- it just writes plain CSV files, one per table,
into this directory.

## Purpose

The Saayam app needs realistic-looking sample data to develop and test
against without relying on production or a live database. This script
produces internally consistent data (valid foreign keys, unique primary
keys, plausible values) for the core Saayam tables so it can be loaded into
a local database, used in dashboards, or handed to API tests.

## Tables included

- `countries.csv`
- `states.csv` (US only)
- `cities.csv`
- `help_categories.csv`
- `users.csv`
- `volunteer_details.csv`
- `user_skills.csv`
- `user_locations.csv`
- `volunteer_locations.csv`
- `organizations.csv`

## Requirements

- Python 3.10+ (uses `X | Y` type hints)
- `pandas`
- `numpy`

Install dependencies:

```bash
pip install pandas numpy
```

## Running the script

From this directory:

```bash
python generate_mock_data.py
```

This regenerates all CSV files in place using the defaults defined in
`utils.py` (400 rows, 50% volunteer fraction, seed 42, dates between
2024-01-01 and 2026-09-11).

## Configuring row counts and other options

All options are available via the CLI; run `python generate_mock_data.py -h`
for the full list. The main ones:

| Flag | Description | Default |
|---|---|---|
| `--rows` | Target row count for non-reference-bounded tables (cities, users, organizations) | 400 |
| `--volunteer-fraction` | Fraction of users who are volunteers | 0.5 |
| `--seed` | Random seed, for reproducible output | 42 |
| `--today` | Reference "today" date (`YYYY-MM-DD`) that generated timestamps won't exceed | 2026-09-11 |
| `--earliest-date` | Earliest date (`YYYY-MM-DD`) generated timestamps may fall on | 2024-01-01 |

Example:

```bash
python generate_mock_data.py --rows 1000 --volunteer-fraction 0.3 --seed 7
```

Note that `countries`, `states`, and `help_categories` are reference data
(defined in `utils.py`) and always generate a fixed number of rows,
regardless of `--rows`.

## Table relationships

Rows are built in dependency order so every foreign key points at a row
that already exists:

- `states.country_id` -> `countries.country_id`
- `cities.state_id` -> `states.state_id`
- `users.country_id` -> `countries.country_id`
- `users.state_id` -> `states.state_id` (nullable -- only set for US-based users)
- `volunteer_details.user_id` -> `users.user_id` (one row per volunteer, ~`--volunteer-fraction` of users)
- `user_skills.user_id` -> `users.user_id`
- `user_skills.cat_id` -> `help_categories.cat_id`
- `user_locations.user_id` -> `users.user_id` (one row per user)
- `volunteer_locations.user_id` -> `volunteer_details.user_id` (one row per volunteer)
- `organizations.state_id` -> `states.state_id` (nullable)

Users get their city/state/zip/lat-long from the same sampled city row, so a
user's location fields are always mutually consistent. About 85% of users
are US-based (with a real city/state); the rest are international with
those fields left null, matching the nullable FK columns in the schema.

## Output file locations

All CSVs are written to this directory (`data-analytics/mock-data-generation/`),
next to the script, overwriting any existing files with the same name.

## Validation steps

### Automated

After building each table, the script asserts (and fails loudly with a
clear error if violated):

- **Primary key uniqueness** -- `assert_unique_pk` checks each table's PK
  column(s) contain no duplicates.
- **Foreign key validity** -- `assert_fk_valid` checks every FK value exists
  in its parent table's PK column (nullable FKs skip null values).

These checks run automatically as part of `main()` -- if they pass, the
script proceeds to write the CSVs and prints a row count per file, followed
by `Done`.

### Manual

A few spot checks worth doing after generating a fresh batch, especially
after changing `--rows`, `--volunteer-fraction`, or editing `utils.py`:

1. **Row counts printed match the CSVs.** The console output
   (`Wrote N rows to <table>.csv`) should match the number of lines minus 1
   (for the header).
2. **Every state has at least one city.** `cities.csv` should contain all
   50 US state codes at least once, even when `--rows` is smaller than 50
   -- `generate_cities` seeds one city per state before topping up.
3. **Volunteer fraction is roughly as configured.** Row count of
   `volunteer_details.csv` divided by row count of `users.csv` should be
   close to `--volunteer-fraction` (exact only up to `DataFrame.sample`'s
   rounding).
4. **`volunteer_locations.csv` is a subset of `volunteer_details.csv`.**
   Every `user_id` in `volunteer_locations.csv` should also appear in
   `volunteer_details.csv`, and neither should contain a `user_id` that
   isn't in `users.csv`.
5. **International users have null location fields.** Filter `users.csv`
   for rows where `country_id` isn't the US country_id -- `state_id`,
   `city_name`, `zip_code`, and `last_location` should all be empty, and
   `time_zone` should also be empty.
6. **`user_id` / `org_id` formats look right.** Spot-check a few rows:
   `user_id` should match `SID-00-XXX-XXX-XXX-XXX-XXX`, `org_id` should
   match `ORG-XXX-XXX-XXX-XXXX`.
7. **Dates fall inside the configured range.** `last_updated_at`,
   `created_at`, etc. should all be between `--earliest-date` and
   `--today` (default 2024-01-01 to 2026-09-11), and within a given row,
   `created_at` should never be after `last_updated_at`.
8. **Re-running with the same `--seed` reproduces identical output.** Run
   the script twice with the same flags and diff the resulting CSVs --
   they should be byte-identical.
