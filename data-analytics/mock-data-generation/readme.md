# Mock Data Generation — Virginia Analytics Tables

Generates realistic but **fully synthetic** CSV data for ten tables of the
Virginia database (`virginia_dev_saayam_rdbms`), so dashboards, APIs and demos
can be built and tested without touching real user data. Tracks issue
[#301](https://github.com/saayam-for-all/data/issues/301).

Nothing here is deployed to AWS. The CSVs are plain files you can load into a
local database.

## Contents

- [Tables included](#tables-included)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuring row counts](#configuring-row-counts)
- [Table relationships](#table-relationships)
- [How the data is kept consistent](#how-the-data-is-kept-consistent)
- [Output files](#output-files)
- [Validation](#validation)
- [Loading into PostgreSQL](#loading-into-postgresql)
- [Schema source and assumptions](#schema-source-and-assumptions)
- [Repository layout](#repository-layout)

## Tables included

| CSV | Rows (default) | What it holds |
|---|---|---|
| `countries.csv` | 5 | Real lookup rows (US, India, Canada, Australia, Germany) with the same `country_id`s as `database/lookup_tables/country.csv` |
| `states.csv` | 124 | Real lookup rows: 50 US states + DC, 36 Indian states/UTs, 13 Canadian provinces, 8 Australian states/territories, 16 German Länder. Same `state_id`s as `database/lookup_tables/state.csv` |
| `cities.csv` | 191 | Real cities with approximate centroids (curated in `reference_data/cities.csv`) |
| `help_categories.csv` | 80 | Real lookup rows copied from `database/lookup_tables/help_categories.csv` |
| `users.csv` | 400 | Synthetic people |
| `volunteer_details.csv` | 200 | Half of the users are volunteers |
| `user_skills.csv` | 400 | Skills (a help category + level) held by volunteers |
| `volunteer_locations.csv` | 200 | Previous/current position of each volunteer |
| `user_locations.csv` | 400 | Previous/current position of each user |
| `organizations.csv` | 400 | Synthetic non-profit and for-profit organizations |

The five geography/lookup tables are reference data, so their size is set by
`reference_data/`, not by the row-count options below.

## Requirements

- Python 3.8+ (developed on 3.12)
- **No third-party packages.** The generator and validator use only the standard library.
- Optional, for the database load test: Docker (uses the `postgis/postgis` image).

## Quick start

From this folder:

```bash
python generate_mock_data.py
```

That writes the ten CSVs next to the script (the default output location is this
folder) and then runs the validator on them. The same command with the same
options always produces byte-identical files (fixed random seed and a fixed
"as of" date), so regenerating does not create noisy diffs.

## Configuring row counts

`--users` is the main knob; the other tables scale from it unless overridden.

```bash
python generate_mock_data.py                       # 400 users, 200 volunteers, 400 skills, 400 orgs
python generate_mock_data.py --users 5000          # everything scales up (2500 volunteers, ...)
python generate_mock_data.py --users 100 --volunteers 30 --user-skills 60 --organizations 40
python generate_mock_data.py --output-dir /tmp/mock --seed 7
```

| Option | Default | Meaning |
|---|---|---|
| `--users N` | 400 | `users` rows (max 999,999) |
| `--volunteers N` | `users // 2` | `volunteer_details` rows; must be ≤ `--users` |
| `--user-skills N` | `users` | `user_skills` rows; every volunteer gets at least one skill when N ≥ volunteers |
| `--organizations N` | `users` | `organizations` rows |
| `--user-locations N` | every user with a city | `user_locations` rows (capped at users with a city) |
| `--volunteer-locations N` | every volunteer with a city | `volunteer_locations` rows (capped likewise) |
| `--cities N` | all 191 | Use a random subset of the reference cities |
| `--incomplete-profile-rate R` | 0 | Fraction (0–1) of users generated **without** state/city/zip/address, to exercise NULL handling. Those users get no location rows |
| `--seed N` | 42 | Random seed |
| `--as-of YYYY-MM-DD` | 2026-09-20 | No generated timestamp is later than this date |
| `--output-dir PATH` | this folder | Where the CSVs are written |
| `--no-validate` | off | Skip the automatic validation run |

If a requested count is larger than can be satisfied (for example more
`--user-skills` than volunteer × category pairs), the script generates the
maximum and prints a warning.

The logic is data-driven, so larger datasets and other countries need no code
changes: to add a city, add a row to `reference_data/cities.csv`; to add a
country, add it to `reference_data/countries.csv` and `states.csv`, then give it
a name group, languages and a share in `pools.py` / `COUNTRY_WEIGHTS`.

## Table relationships

```
countries ──< states ──< cities
    │            │
    │            ├──< users ──< volunteer_details ──< volunteer_locations
    │            │      │
    │            │      ├──< user_skills >── help_categories
    │            │      └──< user_locations
    │            └──< organizations
    └──< users
```

| Child column | → | Parent column | Notes |
|---|---|---|---|
| `states.country_id` | → | `countries.country_id` | NOT NULL |
| `cities.state_id` | → | `states.state_id` | NOT NULL |
| `users.country_id` | → | `countries.country_id` | |
| `users.state_id` | → | `states.state_id` | |
| `volunteer_details.user_id` | → | `users.user_id` | |
| `user_skills.user_id` | → | `users.user_id` | composite PK `(user_id, cat_id)`; generated for volunteers only |
| `user_skills.cat_id` | → | `help_categories.cat_id` | never the placeholder `0.0.0.0.0` |
| `volunteer_locations.user_id` | → | `volunteer_details.user_id` | **not** `users` — every row belongs to a volunteer |
| `user_locations.user_id` | → | `users.user_id` | |
| `organizations.state_id` | → | `states.state_id` | `organizations` is the child |

As of the current schema no table in scope has a `city_id` or `org_id` foreign
key (users and organizations store `city_name` as text; the location tables
store coordinates), so those "orphan" checks are trivially satisfied.

## How the data is kept consistent

**Geography** — each user or organization is assigned one city from
`reference_data/cities.csv`; everything else is derived from that city:

- `country_id` / `state_id` are the city's country and state; `city_name` is the city.
- `zip_code` starts with the city's real ZIP/postal prefix (US `981xx` for Seattle,
  Canadian `M5V xxx` for Toronto, Indian `560xxx` for Bengaluru, …) followed by random
  digits, in the country's format.
- `time_zone` is the city's IANA zone.
- `is_eu` equals `countries.is_eu_member`.
- Coordinates in `user_locations` / `volunteer_locations` (and `users.last_location`)
  are within ~15 km of the city's centroid. `prev_loc` (present for ~75% of rows) is
  either near the same city or near another city **of the same state**.
- A user has one location profile, so a volunteer's `curr_loc` is identical in
  `user_locations` and `volunteer_locations`, and `users.last_location` equals
  `user_locations.curr_loc`.

**Timestamps** (all `YYYY-MM-DD HH:MM:SS`, none later than `--as-of`):
`created_at <= last_updated_at` everywhere both exist; in `volunteer_details`,
`terms_accepted_at` and the `path*_updated_at` values fall between them;
`user_skills.created_at` is not before the volunteer's own `created_at`;
`promotion_wizard_last_updated_at <= users.last_updated_at`.

**Not real** — no real personal data is generated:

- User IDs use the group `99` (`SID-99-000-123-456`); production IDs use `00`.
- Emails are on `example.com` (users) / `example.org` (organizations) — reserved
  domains that cannot receive mail.
- Phone numbers are `+<country code><area>55501NN`, the fictional 555-01xx range.
- Names, streets and organization names are random combinations of generic words.
- Government-ID "paths" are just strings under `mock/`; no files exist.
- Countries, states, cities and help categories are public reference data.

**NULLs** — the generator writes NULL as an empty, unquoted CSV cell (what
PostgreSQL `COPY ... CSV` treats as NULL). Optional columns are realistically
sparse: `middle_name`, `addr_ln2`, `profile_picture_path`, `prev_loc`, ID uploads,
`org_rating`, org contact fields. `addr_ln3` is always NULL.

**Value formats**: booleans `true`/`false`; `users.last_location` is a PostgreSQL
`point` with x = longitude, y = latitude, e.g. `(-122.332100,47.606200)`;
location tables use EWKT for `geography(Point, 4326)`, e.g.
`SRID=4326;POINT(-122.332100 47.606200)`; `availability_*` are JSON arrays.

## Output files

By default the CSVs are written to this folder:

```
data-analytics/mock-data-generation/
├── countries.csv   states.csv   cities.csv   help_categories.csv
├── users.csv   volunteer_details.csv   user_skills.csv
├── volunteer_locations.csv   user_locations.csv   organizations.csv
```

Column names and order match the schema exactly (see `schema.py` / `schema.sql`).
Use `--output-dir` to write elsewhere.

## Validation

`validate_mock_data.py` is run automatically after generation and can be run on
its own (it exits non-zero on any failure):

```bash
python validate_mock_data.py                 # checks the CSVs in this folder
python validate_mock_data.py --dir /tmp/mock
```

It verifies that:

1. CSV headers match the schema (names **and** order).
2. Every cell parses as its column type (`VARCHAR(n)` length, `INT`/`BIGINT`,
   `BOOLEAN`, `TIMESTAMP`, `DATE`, `DECIMAL(9,6)`, `point`, `geography`, `JSONB`,
   enums), and NOT NULL columns are filled.
3. Primary keys (including the composite key on `user_skills`) are unique.
4. Every foreign key resolves — no orphan `user_id`, `state_id`, `country_id`,
   `cat_id` (the `city_id` / `org_id` checks are vacuous, see above).
5. The `organizations` CHECK constraints hold (`org_rating` 1–5, `web_url` starts
   with `http`, `email` contains `@`).
6. Timestamps are ordered as described above.
7. Country → state → city → ZIP → time zone → coordinates agree.
8. No value looks real (mock IDs, reserved email domains, fictional phones).

To confirm the checker itself is not vacuous, corrupt a copy of a file (delete a
parent row, swap two columns, move a coordinate to another continent, …) and
re-run it: it reports the problem and exits 1.

## Loading into PostgreSQL

`schema.sql` is the Virginia DDL for these tables (pluralized names), plus tiny
stubs of `user_status` and `supporting_languages` so the `users` foreign keys
resolve. It needs PostGIS for the `geography` columns.

```bash
docker run -d --name mockdb -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=saayam -p 5433:5432 postgis/postgis:16-3.4
docker cp . mockdb:/mock                    # run from this folder
docker exec mockdb psql -U postgres -d saayam -v ON_ERROR_STOP=1 -f /mock/schema.sql
for t in countries states cities help_categories users volunteer_details user_skills \
         volunteer_locations user_locations organizations; do
  docker exec mockdb psql -U postgres -d saayam -v ON_ERROR_STOP=1 \
    -c "SET search_path TO virginia_dev_saayam_rdbms, public" \
    -c "\copy $t FROM '/mock/$t.csv' WITH (FORMAT csv, HEADER true)"
done
docker rm -f mockdb
```

Load in that order (parents before children). Every `\copy` should report the
row counts listed above with no errors.

## Schema source and assumptions

Source of truth: the "Changes to the Database, Waiting for Microservice" page of
the [database wiki](https://github.com/saayam-for-all/database/wiki/*-Changes-to-the-Database,-Waiting-for-Microservice),
using the pluralized table names (`states`, `cities`, `countries`) from the
8/17/2026 rename. Items to be aware of:

- **`cities` spells the coordinate column `lattitude`** (sic), exactly as in the
  wiki DDL. If the column is ever corrected, change it in `schema.py` and `schema.sql`.
- **`volunteer_details` has 11 columns per the wiki.** The exports under
  `data-analytics/sql/` also carry `govt_id_expiry1/2` and `govt_id_name1/2`; they
  are not in the wiki DDL, so they are not generated. If the live table has them,
  add them to `schema.py` and `generate_mock_data.py`.
- **Enum values** come from the wiki: `skill_levels` = BEGINNER / INTERMEDIATE /
  ADVANCED / EXPERT; `org_type_enum` = `non_profit` / `for_profit`;
  `org_size_enum` = `small` / `medium` / `large`. (The older sample export uses
  `Non-Profit` / `Large`; the wiki enums are followed here.)
- **Free-form columns with no documented values** — `users.gender`,
  `external_auth_provider` (`google`/`apple`/`facebook`/NULL),
  `promotion_wizard_stage` (1–4), and the JSON shape of `availability_days`
  (`["monday", …]`) / `availability_times` (`["morning", …]`) — use plausible
  values; adjust `pools.py` if the application defines something specific.
- `users.user_status_id` is always `1` (`ACTIVE`, the only `user_status` lookup
  row) and `language_1..3` use `supporting_languages` ids 1–12
  (`database/lookup_tables/supporting_languages.csv`).
- Lookup snapshots keep the repo's values verbatim, including its placeholder
  `cat_desc` text (`FOOD_ASSISTANCE_DESC`), and use the current column name
  `last_updated_at` (the lookup CSVs still say `last_update_date`).
- Only the 50 US states + DC are included for the US (territories and minor
  outlying islands in the lookup are omitted).

## Repository layout

| File | Purpose |
|---|---|
| `generate_mock_data.py` | Entry point: builds all tables in dependency order and writes the CSVs |
| `utils.py` | CSV writing, PostgreSQL value formatting, random sampling, postal codes, geo math |
| `pools.py` | Word pools (names, streets, organization vocabulary, languages) |
| `schema.py` | Column names/order/types/nullability, PKs, FKs and enums — shared by generator and validator |
| `schema.sql` | The same schema as DDL, for the PostgreSQL load test |
| `validate_mock_data.py` | Standalone validator |
| `reference_data/` | Input data: `countries.csv`, `states.csv`, `help_categories.csv` (lookup snapshots) and `cities.csv` (curated cities with coordinates, ZIP prefix, time zone) |
