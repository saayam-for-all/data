# Mock Data Generation — Virginia Analytics Tables

Synthetic, schema-compliant CSV mock data for the Virginia analytics tables,
for local development, API testing, dashboard testing, and demos
([issue #301](https://github.com/saayam-for-all/data/issues/301)). No real
or sensitive user information is used anywhere in this dataset.

## Tables included

| # | Table | Rows (default) |
|---|-------|-----------------|
| 1 | `countries.csv` | 20 |
| 2 | `states.csv` | 77 |
| 3 | `cities.csv` | 89 |
| 4 | `help_categories.csv` | 80 |
| 5 | `users.csv` | 100 (configurable) |
| 6 | `volunteer_details.csv` | ~60% of users |
| 7 | `user_skills.csv` | ~1-4 rows per volunteer |
| 8 | `volunteer_locations.csv` | one row per volunteer with a resolved city |
| 9 | `user_locations.csv` | ~85% of users |
| 10 | `organizations.csv` | 100 (configurable) |

`countries` / `states` / `cities` / `help_categories` are reference/lookup
data, so their size is fixed by the curated reference set in
`reference_data.py` rather than by `--num-users`; the other six tables scale
with the `--num-users` / `--num-orgs` you pass in.

## Schema source

Column names, types, nullability and foreign keys were taken from the
**"Table after changes"** blocks (i.e. the current/latest schema, not the
pre-rename one) on the database wiki page: [*Changes to the Database,
Waiting for
Microservice*](https://github.com/saayam-for-all/database/wiki/*-Changes-to-the-Database,-Waiting-for-Microservice),
including the 8/17/2026 pluralization rename (`state`→`states`,
`city`→`cities`, `country`→`countries`). `data-analytics/sql/*.csv` in this
repo has older sample headers using the pre-rename column names
(`last_update_date`, etc.) and `volunteer_details.csv` there also has 4
extra columns (`govt_id_expiry1/2`, `govt_id_name1/2`) that are not present
in the wiki's current `volunteer_details` DDL — this generator follows the
wiki as the source of truth per the issue, so those legacy/extra columns
were intentionally excluded. If the live schema has since diverged from the
wiki, re-check `db_info.json` under `database/mock-data-generation/`
against the wiki before relying on this output (that file was already
stale relative to the wiki at generation time).

## Required Python dependencies

None beyond the standard library (`csv`, `json`, `random`, `datetime`,
`argparse`). Requires Python 3.8+. `validate_mock_data.py` is also stdlib
-only, so no `pip install` is needed to run either script.

## How to run the generation script

```bash
cd data-analytics/mock-data-generation
python generate_mock_data.py
```

This writes all 10 CSV files into the same directory.

## How to configure row counts

```bash
python generate_mock_data.py \
  --num-users 400 \
  --num-orgs 150 \
  --volunteer-ratio 0.6 \
  --user-location-ratio 0.85 \
  --seed 42 \
  --output-dir .
```

| Flag | Default | Effect |
|------|---------|--------|
| `--num-users` | 100 | Rows in `users.csv`; drives `volunteer_details`/`user_skills`/`*_locations` sizes |
| `--num-orgs` | 100 | Rows in `organizations.csv` |
| `--volunteer-ratio` | 0.6 | Fraction of users who also get a `volunteer_details` row |
| `--user-location-ratio` | 0.85 | Fraction of users who also get a `user_locations` row |
| `--seed` | 42 | Random seed — same seed always reproduces the same data |
| `--output-dir` | this directory | Where the CSVs are written |

The reference tables (`countries`/`states`/`cities`/`help_categories`) are
not affected by `--num-users`/`--num-orgs`; add entries to `reference_data.py`
to grow those.

## Table relationships

Foreign keys enforced by the generator (no orphan values are produced):

```
users.country_id        -> countries.country_id
users.state_id           -> states.state_id
states.country_id        -> countries.country_id      (NOT NULL)
cities.state_id           -> states.state_id           (NOT NULL)
volunteer_details.user_id -> users.user_id
user_skills.user_id       -> users.user_id
user_skills.cat_id        -> help_categories.cat_id
organizations.state_id    -> states.state_id
volunteer_locations.user_id -> volunteer_details.user_id   (NOT users.user_id directly)
user_locations.user_id      -> users.user_id
```

`state_id` values are constructed as `f"{country_code}-{state_code}"` (e.g.
`US-VA`, `IN-MH`) so they stay globally unique across countries while
remaining human-readable. `user_id` / `org_id` are generated with the same
format the database triggers use (`SID-00-XXX-XXX-XXX-XXX-XXX` /
`ORG-XXX-XXX-XXX-XXXX`).

### Geographic consistency

Every user/organization is assigned a state first, and its `country_id` and
`city_name` are always derived from *that same state* (never an unrelated
random country/city), matching the issue's `country -> state -> city -> ZIP`
requirement.

`volunteer_locations.curr_loc` / `prev_loc` and `user_locations.curr_loc` /
`prev_loc` are `geography(Point, 4326)` columns, written as EWKT text
(`SRID=4326;POINT(lon lat)`, per [the wiki's documented CSV-import
convention](<https://github.com/saayam-for-all/database/wiki/Importing-CSV-rows-with-geography-parsing-in-cities-table-(EWKT---WKT---GeoJSON)>)),
jittered a small amount around the user's/org's own city centroid rather
than placed at random global coordinates. `users.last_location` (a plain
Postgres `point`, not `geography`) is written as `(lat,lon)` text, matching
the ordering used in the DDL's own inline comment
(`-- Example: last_location (37.3382, -121.8863) for San Jose`).

### Timestamps

All timestamps are `YYYY-MM-DD HH:MM:SS` and `dob` is `YYYY-MM-DD`.
`created_at <= last_updated_at` (and similar orderings, e.g.
`path1_updated_at`/`terms_accepted_at` falling between a row's own
`created_at` and `last_updated_at`) is enforced wherever both columns
exist, and downstream tables (e.g. `user_skills`, `volunteer_locations`)
are always timestamped after the `users`/`volunteer_details` row they
depend on.

### Columns intentionally left blank

`users.user_status_id`, `users.language_1/2/3` reference `user_status` and
`supporting_languages`, which are outside this issue's 10-table scope — they
are left blank (`NULL`) rather than pointing at fabricated rows that don't
exist in any generated table.

## Output file locations

CSVs are written to `data-analytics/mock-data-generation/` by default (next
to these scripts), matching the issue's suggested structure:

```
data-analytics/mock-data-generation/
├── generate_mock_data.py   # orchestrator - run this
├── validate_mock_data.py   # run this after generating, to verify the output
├── reference_data.py       # curated countries/states/cities/help-category data
├── utils.py                 # shared helpers (IDs, timestamps, geo, CSV writer)
├── countries.py
├── states.py
├── cities.py
├── help_categories.py
├── users.py
├── volunteer_details.py
├── user_skills.py
├── volunteer_locations.py
├── user_locations.py
├── organizations.py
├── countries.csv
├── states.csv
├── cities.csv
├── help_categories.csv
├── users.csv
├── volunteer_details.csv
├── user_skills.csv
├── volunteer_locations.csv
├── user_locations.csv
└── organizations.csv
```

## Validation steps

```bash
python validate_mock_data.py
```

Checks performed:

- CSV headers match the schema derived from the wiki DDL exactly (name and order)
- Primary keys are unique (composite PK for `user_skills`)
- No orphan foreign keys (`country_id`, `state_id`, `user_id`, `cat_id`, incl. the
  `volunteer_locations.user_id -> volunteer_details.user_id` indirection)
- Required (`NOT NULL`) fields are populated
- Enum fields (`org_type`, `org_size`, `skill_level`) only use valid values
- `org_rating` is within 1-5
- `web_url` starts with `http`, `email` contains `@`
- Timestamps are valid `YYYY-MM-DD HH:MM:SS`, dates are valid `YYYY-MM-DD`
- `created_at <= last_updated_at` (and similar) where both columns exist
- `prev_loc`/`curr_loc` are valid `SRID=4326;POINT(lon lat)` EWKT;
  `users.last_location` is a valid `(lat,lon)` point
- Exits non-zero and prints every failure if any check fails

`validate_mock_data.py` was also cross-checked by loading every generated
CSV with `pandas.read_csv()` to confirm the files parse cleanly with no
datatype errors.

## Notes

- This generates fresh data on every run (unless you keep `--seed` fixed —
  the default seed of 42 always reproduces the same dataset).
- This does **not** deploy or write anything to AWS/RDS; it only produces
  local CSV files, per the issue's acceptance criteria.
