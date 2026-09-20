# Mock Data Generation

Synthetic mock data for the Virginia analytics tables, for local development,
API testing, dashboard testing and demos.

**No real or sensitive user information is used.** Names are drawn at random
from generic pools, email addresses use the reserved `example.com` /
`example.org` domains (RFC 2606), phone numbers use the reserved fictional
`555-01xx` exchange, and city and organization names are invented rather than
copied from real places or entities.

## Tables included

| CSV | Rows at the default `--rows 400` | Notes |
| --- | --- | --- |
| `countries.csv` | 31 | Reference data; `country_id` values match the ids already in the Virginia `countries` table |
| `states.csv` | 51 | The 50 US states plus DC; `state_id` is the two-letter code |
| `cities.csv` | 400 | Spread across the states, near each state's centroid |
| `help_categories.csv` | 80 | Mirrors the taxonomy in `data-analytics/sql/help_category.csv` |
| `users.csv` | 400 | |
| `volunteer_details.csv` | 240 | 60% of users are volunteers |
| `user_skills.csv` | ~990 | 1-4 skills per user |
| `user_locations.csv` | 400 | One row per user |
| `volunteer_locations.csv` | 240 | One row per volunteer |
| `organizations.csv` | 400 | |

Column names and column order come from the current Virginia schema
([database wiki](https://github.com/saayam-for-all/database/wiki/*-Changes-to-the-Database,-Waiting-for-Microservice),
"Table after changes" blocks), including the post-8/17/2026 pluralized table
names and the `created_date` -> `created_at` / `last_update_date` ->
`last_updated_at` renames.

## Requirements

Python 3.8 or newer. **No third-party packages** - the generator uses only the
standard library, so there is nothing to install.

## How to run

From this directory:

```bash
python generate_mock_data.py
```

That regenerates all ten CSVs in place and then validates them.

## Configuring row counts

```bash
python generate_mock_data.py --rows 100     # smaller dataset
python generate_mock_data.py --rows 5000    # larger dataset
python generate_mock_data.py --seed 7       # different data, same shape
python generate_mock_data.py --out /tmp/mock  # write somewhere else
```

`--rows` sets the size of the user-scale tables (`cities`, `users`,
`organizations`); `volunteer_details`, `user_skills` and the two location
tables scale from it. The reference tables (`countries`, `states`,
`help_categories`) keep their natural size, because inflating them to an
arbitrary row count would mean inventing countries, states and help categories
that the application does not have.

Output is deterministic for a given `--rows` / `--seed` pair, so regenerating
produces the same dataset and reviews stay diff-friendly.

## Table relationships

```
users.country_id            -> countries.country_id
users.state_id              -> states.state_id
cities.state_id             -> states.state_id
states.country_id           -> countries.country_id   (NOT NULL)
volunteer_details.user_id   -> users.user_id
user_skills.user_id         -> users.user_id
user_skills.cat_id          -> help_categories.cat_id
organizations.state_id      -> states.state_id
volunteer_locations.user_id -> volunteer_details.user_id
user_locations.user_id      -> users.user_id
```

Note that `volunteer_locations.user_id` references `volunteer_details.user_id`,
not `users.user_id` directly, so every volunteer location row belongs to a user
that also has a `volunteer_details` row.

Consistency rules the generator enforces:

- Every user and organization sits in a city that really belongs to its state,
  with a ZIP code carrying that state's prefix and a time zone matching the
  state.
- `users.last_location` (a PostgreSQL `point`) and the `curr_loc` / `prev_loc`
  geography points are generated near the row's own city centroid, not as
  unrelated random coordinates.
- `created_at <= last_updated_at` wherever both columns exist, and no timestamp
  falls in the future.

### Out-of-scope foreign keys

Three FK columns point at tables outside this issue's scope, so they are left
`NULL` rather than filled with ids that may not exist in the target database:
`users.language_1` / `language_2` / `language_3` (-> `supporting_languages`).
`users.user_status_id` is set to `1`, the only value present in the existing
Virginia user data.

## Output file locations

All CSVs are written next to the scripts, in
`data-analytics/mock-data-generation/`.

Conventions used in the files:

- An **empty unquoted field means SQL NULL**, which is what
  `COPY ... WITH (FORMAT csv)` expects. The files do not contain the literal
  string `NULL`.
- Timestamps are `YYYY-MM-DD HH:MM:SS`; dates are `YYYY-MM-DD`.
- `geography(Point, 4326)` columns use EWKT, e.g.
  `SRID=4326;POINT(-77.036 38.897)` (longitude first).
- The `point` column `users.last_location` uses `(longitude,latitude)`.
- `JSONB` columns (`availability_days`, `availability_times`) hold compact JSON
  arrays.

Loading a file, for example:

```sql
\copy virginia_dev_saayam_rdbms.users FROM 'users.csv' WITH (FORMAT csv, HEADER true);
```

Load the tables in the order they are listed in the table above so that parent
rows exist before their children.

## Validation

Validation runs automatically at the end of every generation run. To re-check
CSVs already on disk without regenerating them:

```bash
python generate_mock_data.py --validate-only
```

It exits non-zero and prints each problem it finds. The checks are:

- CSV headers match the schema, in the schema's column order.
- Primary keys are present and unique, including the composite
  `(user_id, cat_id)` key on `user_skills`.
- Every foreign key resolves - no orphan `user_id`, `state_id`, `country_id` or
  `cat_id` values. (No table in this scope has a `city_id` or `org_id` foreign
  key under the current schema, so those checks are satisfied trivially.)
- `states.country_id` is never NULL.
- Each user's and organization's city belongs to its state, and its ZIP carries
  that state's prefix.
- Cities sit near their own state's centroid, and location points sit near
  their user's own city.
- Timestamps parse, and `created_at <= last_updated_at`.
- Enum-typed columns (`skill_level`, `org_type`, `org_size`) only carry values
  the database types allow, and `org_rating` stays within 1-5.
- The `organizations` CHECK constraints hold (`web_url LIKE 'http%'`,
  `email LIKE '%@%'`).
- No value looks like a real contact detail: user emails stay on
  `example.com`, phone numbers stay in the fictional `555-01xx` range.

## Files

```
data-analytics/mock-data-generation/
├── generate_mock_data.py   # generation + validation, CLI entry point
├── utils.py                # reference data and small helpers
├── readme.md
├── countries.csv
├── states.csv
├── cities.csv
├── help_categories.csv
├── users.csv
├── volunteer_details.csv
├── user_skills.csv
├── user_locations.csv
├── volunteer_locations.csv
└── organizations.csv
```
