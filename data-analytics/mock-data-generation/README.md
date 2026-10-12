# Mock Data Generation (data-analytics)

Synthetic CSV data for issue [#301](https://github.com/saayam-for-all/data/issues/301) —
supports local dashboard/API development, testing, and demos without AWS or
real-database access.

## Tables Generated

| Table | Rows (default) | Source |
|---|---|---|
| `countries.csv` | 242 | copied from `data-analytics/sql/country.csv` (public reference data) |
| `states.csv` | 51 | copied from `data-analytics/sql/state.csv`, with a bug fix (see Design Decisions) |
| `help_categories.csv` | 80 | copied from `data-analytics/sql/help_category.csv` (public reference data) |
| `cities.csv` | 100 (configurable) | synthesized, seeded with real city coordinates |
| `users.csv` | 100 (configurable) | synthesized |
| `organizations.csv` | 100 (configurable) | synthesized |
| `volunteer_details.csv` | ~60% of users | derived from `users` |
| `user_skills.csv` | ~2-4 rows per selected user | derived from `users` + `help_categories` |
| `volunteer_locations.csv` | 1 per `volunteer_details` row | derived, scoped to volunteers only |
| `user_locations.csv` | 1 per `users` row | derived |

`countries`, `states`, and `help_categories` are real public reference data
(country/state names, a help-category taxonomy) rather than synthetic mock
rows — regenerating them randomly would make dashboard geography/category
filters look wrong for no benefit. Everything else is fully synthetic.

## Dependencies

Python 3.9+, standard library only — no `pip install` required.

## Design Decisions

- **`states.csv` country_id bug fix**: the source `data-analytics/sql/state.csv`
  has `country_id=1` for every US state, but `country_id=1` in
  `country.csv` is Afghanistan — the real USA row is `country_id=233`. This
  generator remaps it during load so the FK is not just present but
  semantically correct.
- **`cities.lattitude` spelling**: kept as-is (misspelled) to match the real
  Virginia schema's actual column name, per the "correct column names"
  acceptance criterion — this isn't a typo in this code.
- **`cities.state_id` type**: modeled as the 2-letter state code (string) to
  match `states.csv`'s real primary key, rather than the `integer` type in
  the older schema doc (`db_info.json`), which is itself inconsistent with
  that same doc's own `varchar` `state.state_id` column.
- **Column naming for `user_skills` / `volunteer_locations` / `user_locations`**:
  follows the `created_at`/`last_updated_at` naming already used by the
  sibling files in `data-analytics/sql/`, not the older `created_date`/
  `last_update_date` naming in `db_info.json` — the sibling files are more
  current since they're consumed by `data-analytics/lambda_functions/*.py`.
- **`volunteer_locations.user_id` FK**: points at `volunteer_details.user_id`
  (not `users.user_id` directly), per the issue's explicit FK note — a
  location row only exists for someone who is actually a volunteer.
- **IDs**: `users` use `SID-00-000-XXX-XXX` and `organizations` use
  `ORG00001`-style padded IDs, matching the conventions already present in
  `data-analytics/sql/users.csv` and `organizations.csv`.
- **Missing/optional values**: written as empty strings (not the literal
  text `NULL`), the standard convention for `NULL` under `COPY`/`\copy` in
  PostgreSQL.
- Only column *shape* is borrowed from the existing `data-analytics/sql/*.csv`
  files for `users`, `volunteer_details`, `user_skills`, `volunteer_locations`,
  and `organizations` — their row *content* is not reused, since a check
  found their FKs don't fully resolve against each other (they were
  generated independently at different times).

## generate_mock_data.py

One `generate_<table>()` function per table, called in dependency order:

```
countries → states (country_id fix) → cities → users → organizations
users → volunteer_details → user_skills
volunteer_details → volunteer_locations
users → user_locations
```

Each function returns a list of row-dicts with exactly the target table's
real columns (no extra bookkeeping fields leak into the CSVs). Geographic
data is threaded through via a `geo_by_user` map built while generating
`users`, so downstream location tables jitter around each user's actual
assigned city rather than a random point.

## utils.py

Shared helpers: random seed control, timestamp/date formatting
(PostgreSQL-compatible `YYYY-MM-DD HH:MM:SS`), `SID-...`/`ORG...` ID
generators, WKT point encode/decode (`SRID=4326;POINT(lon lat)`, matching
the `geography` column type), coordinate jitter with lat/lon clamping,
CSV read/write, and `validate_all()` (see Validation below). Also holds the
static reference data: per-state seed cities (real name + coordinates),
name lists, timezones, and the PK/FK specification used by validation.

## Output Files

Running with defaults writes all 10 CSVs listed in the table above directly
into this directory (flat, not nested in a build subfolder), matching how
`database/mock-data-generation/*.csv` are already committed in this repo.

## How to Run

```bash
cd data-analytics/mock-data-generation
python generate_mock_data.py                          # defaults: --count 100 --seed 42
python generate_mock_data.py --count 400 --seed 7       # larger, reproducible dataset
python generate_mock_data.py --output-dir /tmp/mockout  # write elsewhere
```

`--count` controls `cities`, `users`, and `organizations`; every derived
table scales automatically off those.

## Validation

`validate_all()` checks, over all 10 tables together:

1. **Primary key uniqueness** (including the composite `user_skills` PK)
2. **Foreign key integrity** — every one of the 9 relationships in the
   issue resolves with no orphaned rows
3. **Geo sanity** — city/location coordinates fall inside a plausible
   continental-US + AK/HI bounding box
4. **Timestamp sanity** — parseable, and `created_at <= last_updated_at`
   wherever both exist on a row

Run it standalone against already-generated (or committed) CSVs without
regenerating anything:

```bash
python generate_mock_data.py --validate-only
```

It also runs automatically at the end of a normal generation run and exits
non-zero if anything fails.

## What Happens When It Runs

1. Loads `countries`, `help_categories`, and `states` from the existing
   `data-analytics/sql/` reference CSVs (fixing the `states` country_id bug)
2. Generates `cities`, seeded with real per-state coordinates
3. Generates `users`, each assigned a real state + city from step 2
4. Generates `organizations`, similarly assigned a real state + city
5. Derives `volunteer_details` as a subset of `users`
6. Derives `user_skills` linking a subset of `users` to `help_categories`
7. Derives `volunteer_locations` and `user_locations`, with coordinates
   jittered near each user's assigned city
8. Writes all 10 CSVs
9. Runs `validate_all()` and reports pass/fail

## Data Privacy Note

All names, emails (`@mock.saayam.test`), phone numbers (`+1555...`),
addresses, and government-ID paths are synthetic placeholders — no real or
sensitive data is included anywhere in this output. `countries.csv`,
`states.csv`, and `help_categories.csv` contain only public reference data
(country/state names and a category taxonomy), not personal information.
