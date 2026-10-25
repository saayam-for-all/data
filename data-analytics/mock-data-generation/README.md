# Mock Data Generation — Virginia Analytics Tables

Synthetic mock data for ten tables of the Virginia (`virginia_dev_saayam_rdbms`)
database, for local development, API testing, dashboard testing and demos.

Issue: [saayam-for-all/data#301](https://github.com/saayam-for-all/data/issues/301)

No real or sensitive personal data is used. Names, e-mail addresses, phone
numbers, street addresses and user ids are all synthetic. Only geography
(country, state, city and their coordinates) is real, because the issue
requires `country → state → city → ZIP/location` to be logically consistent —
its own worked example is `United States → California → San Jose`.

## Tables included

| CSV | Rows | Source of values |
| --- | ---: | --- |
| `countries.csv` | 242 | Real reference data from `database/lookup_tables/country.csv` |
| `states.csv` | 168 | Real reference data, limited to the focus countries |
| `cities.csv` | 335 | Curated real cities with centroid coordinates (`reference/cities_seed.csv`) |
| `help_categories.csv` | 80 | Real reference data from `database/lookup_tables/help_categories.csv` |
| `users.csv` | 400 | Generated |
| `volunteer_details.csv` | 220 | Generated (55% of users) |
| `user_skills.csv` | 984 | Generated |
| `user_locations.csv` | 400 | Generated |
| `volunteer_locations.csv` | 198 | Generated (90% of volunteers) |
| `organizations.csv` | 400 | Generated |

`countries`, `states` and `help_categories` are reference tables: they are
emitted at their real-world size rather than padded to an artificial row count,
because inventing extra countries or categories would break both referential
integrity against the live lookups and the geographic-consistency requirement.
`cities.csv` is likewise capped by the curated real-city seed. See
[Row counts](#configuring-row-counts).

## Source schema

The schema is taken from the database wiki page
[Changes to the Database, Waiting for Microservice](https://github.com/saayam-for-all/database/wiki/*-Changes-to-the-Database,-Waiting-for-Microservice),
which issue #301 names as the source of truth. Each table on that page is
presented as the current DDL, a list of *Needed Changes*, and a
**Table after changes** block. These CSVs follow the **Table after changes**
blocks, i.e. the latest schema, which in several places differs from what is
live today:

| Table | Difference from the currently deployed DDL |
| --- | --- |
| `countries`, `states`, `cities`, `user_locations`, `volunteer_locations` | `last_update_date` / `updated_at` renamed to `last_updated_at` |
| `cities` | `state_id` corrected from `INT` to `VARCHAR(50)` so it can reference the `VARCHAR` primary key on `states` |
| `users` | `user_category_id` removed (moved to `user_category_map`); `language_1..3` changed from `VARCHAR` to `BIGINT` FK; `external_auth_provider`, `dob`, `is_eu` added |
| `user_skills` | `skill_level` enum added (05/21/2026) |
| `help_categories` | `last_updated_at` added |
| `organizations` | `is_contributor` added |

Two id formats also changed and are reproduced exactly from the database
triggers, so generated ids match what the database itself would mint:

- `users.user_id` — `generate_sid()`, updated 07/07/2026: the sequence value is
  padded to 15 digits and split into five groups of three, e.g.
  `SID-00-000-000-000-000-001`. This is **not** the older three-group form
  (`SID-00-000-000-058`) still seen in older CSVs elsewhere in this repo.
- `organizations.org_id` — `generate_org_id()`: padded to 13 digits and split
  3-3-3-4, e.g. `ORG-000-000-000-0001`.

Note: `lattitude` in `cities.csv` is misspelled in the schema itself. The
header has to match the column name, so it is left as-is.

## Requirements

- Python 3.9+
- [`Faker`](https://faker.readthedocs.io/) — see `requirements.txt`

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the generator

```bash
python generate_mock_data.py
```

This rewrites all ten CSVs in this directory. Generation is seeded
(`config.RANDOM_SEED`, default `42`), so re-running with unchanged
configuration reproduces byte-identical files.

## Validating

```bash
python validate_mock_data.py
```

The validator restates the schema independently of the generators and checks
every item in the issue's Data Quality Validation list: headers and column
order, data types and lengths, NOT NULL columns, primary-key uniqueness, every
foreign key, geographic coherence, timestamp validity and ordering, the schema
`CHECK` constraints, and that no real-looking contact data is present. It exits
non-zero on any failure.

To confirm the files load into PostgreSQL without schema or datatype errors,
against a database with the schema already created from the
[database repo DDL](https://github.com/saayam-for-all/database/tree/main/ddl/Tables):

```bash
psql -d saayam_local -v ON_ERROR_STOP=1 -f load_mock_data.sql
```

PostGIS is required, because both location tables use `geography(Point, 4326)`.

## Configuring row counts

Everything is declared in `config.py`; no generator logic needs to change to
produce a larger dataset.

| Setting | Meaning |
| --- | --- |
| `USER_ROWS` | Number of users; drives most dependent tables |
| `ORGANIZATION_ROWS` | Number of organizations |
| `CITY_ROWS` | Cap on cities emitted from the curated seed |
| `VOLUNTEER_RATIO` | Share of users with a `volunteer_details` row |
| `VOLUNTEER_LOCATION_RATIO`, `USER_LOCATION_RATIO` | Share of each population with a location row |
| `SKILLS_PER_VOLUNTEER`, `SKILLS_PER_NON_VOLUNTEER` | Skills per user, as `(min, max)` |
| `FOCUS_COUNTRY_IDS`, `COUNTRY_WEIGHTS` | Which countries users and organizations are placed in, and in what proportion |
| `STATE_SCOPE_ALL` | `True` emits every state of every country instead of just the focus countries |
| `WINDOW_START`, `WINDOW_END` | Time window that all generated timestamps fall inside |
| `RANDOM_SEED` | Change for a different dataset; keep for reproducibility |

Growing the dataset beyond the curated city seed means adding rows to
`reference/cities_seed.csv` (`country_id,state_code,city_name,latitude,longitude`);
they resolve to real `state_id` values at load time, and the generator fails
loudly if a seed row names a state that does not exist in the lookup data.

## Table relationships

```
countries ──< states ──< cities
                │
                ├──< users ──< volunteer_details ──< volunteer_locations
                │        ├──< user_locations
                │        └──< user_skills >── help_categories
                └──< organizations
```

| Child | Column | Parent |
| --- | --- | --- |
| `states` | `country_id` | `countries.country_id` (NOT NULL) |
| `cities` | `state_id` | `states.state_id` |
| `users` | `country_id` | `countries.country_id` |
| `users` | `state_id` | `states.state_id` |
| `volunteer_details` | `user_id` | `users.user_id` |
| `user_skills` | `user_id` | `users.user_id` |
| `user_skills` | `cat_id` | `help_categories.cat_id` |
| `user_locations` | `user_id` | `users.user_id` |
| `volunteer_locations` | `user_id` | **`volunteer_details.user_id`** |
| `organizations` | `state_id` | `states.state_id` |

The relationship most easily got wrong is the last-but-one:
`volunteer_locations.user_id` references `volunteer_details.user_id`, *not*
`users.user_id`. Every user with a `volunteer_locations` row therefore has a
`volunteer_details` row first. `user_locations.user_id`, by contrast, does
reference `users.user_id` directly.

`users` also references two tables outside the scope of this issue, so their
values are drawn from the existing lookups rather than invented:
`user_status_id` from `user_status` (which currently defines only id `1`) and
`language_1..3` from `supporting_languages` (ids 1–12).

## How consistency is maintained

**Geography.** Each user and organization is placed in a focus country, then a
state of that country, then a real city of that state. The ZIP/postal code is
derived from that state — US ZIP prefix ranges, Canadian province letters,
Australian postcode ranges, German PLZ leading digits, Indian PIN prefixes and
Irish Eircode routing keys. Time zones follow the state as well. Time zones are
mapped at state granularity, so a state spanning two zones (for example west
Texas) gets its predominant zone.

**Coordinates.** `users.last_location` (a PostgreSQL `point`, latitude first,
per the example in `ddl_users.sql`) and the `curr_loc`/`prev_loc` geography
points sit within roughly 0.05° of their own city's centroid. `prev_loc` is a
short hop from `curr_loc` rather than an unrelated point, because the table's
`fn_shift_prev_loc_*` trigger sets `prev_loc` from the previous `curr_loc` —
the two are successive positions of one person.

**Timestamps.** All timestamps fall inside the configured window, use
`YYYY-MM-DD HH:MM:SS`, and satisfy `created_at <= last_updated_at`. Dependent
rows never predate the user they belong to.

**Synthetic contact data.** E-mail addresses use the RFC 2606 reserved
`example.com` / `example.org` / `example.net` domains, and every phone number
falls in the `555-0100`–`555-0199` block reserved for fictional use, prefixed
with the country's real dialling code. Neither can reach a real person.

## Files

```
data-analytics/mock-data-generation/
├── config.py                  # all row counts, ratios, scope and the seed
├── utils.py                   # id, timestamp, point and CSV helpers
├── localization.py            # postal codes, time zones, phone formats
├── reference_data.py          # loads real lookup data and the city seed
├── generate_mock_data.py      # orchestrator: run this
├── validate_mock_data.py      # data-quality checks: run this after
├── load_mock_data.sql         # optional psql load test
├── requirements.txt
├── generators/
│   ├── reference_tables.py    # countries, states, cities, help_categories
│   ├── users.py               # users
│   ├── volunteers.py          # volunteer_details, user_skills, both locations
│   └── organizations.py       # organizations
├── reference/
│   └── cities_seed.csv        # curated real cities with coordinates
└── <ten generated CSVs>
```

## Known divergences worth reviewing

1. The wiki section for `cities` is headed *"Keep hold on inserting data in
   this table"*. That is read here as a hold on loading the live database, not
   on producing a CSV — issue #301 both lists `cities` in scope and says not to
   deploy to AWS. Nothing here is deployed.
2. A separate wiki page,
   [Importing CSV rows with geography parsing in cities table](https://github.com/saayam-for-all/database/wiki/Importing-CSV-rows-with-geography-parsing-in-cities-table-(EWKT---WKT---GeoJSON)),
   proposes a different shape for `cities`: a single `city_point
   geography(Point,4326)` column replacing `lattitude`/`longitude`, a
   `VARCHAR` `city_id`, and `last_update_time`. It conflicts with the main
   schema page. These CSVs follow the main page. If the geography variant is
   adopted, `generators/reference_tables.py` is the only file that changes.
3. Older CSVs under `data-analytics/sql/` and the schema dump in
   `database/mock-data-generation/db_info.json` predate several of the changes
   listed above and were deliberately not used as templates.
