# Mock Data Generation (Issue #301)

Synthetic CSV data for the 10 Virginia analytics tables, for local dev, API
testing, dashboard testing, and demos. No real or sensitive data is used.

## Tables Included

`countries`, `states`, `cities`, `users`, `volunteer_details`, `user_skills`,
`volunteer_locations`, `user_locations`, `help_categories`, `organizations`.

## Requirements

Python 3.8+. No external packages required - `generate_mock_data.py` and
`validate_data.py` use only the standard library (`csv`, `random`,
`datetime`, `argparse`).

## How to Run

```bash
python generate_mock_data.py                  # 100 users, seed 42 (default)
python generate_mock_data.py --rows 400        # 400 users, seed 42
python generate_mock_data.py --rows 400 --seed 7 --outdir ./out
python validate_data.py                        # run after generating, in the same directory
```

`--rows` controls the number of `users` rows generated; every dependent
table (`volunteer_details`, `user_skills`, `volunteer_locations`,
`user_locations`, `organizations`) scales proportionally from that number.
`countries`, `states`, and `help_categories` are intentionally fixed-size
lookup domains rather than scaled with `--rows` - generating hundreds of
fake countries wouldn't be realistic or useful for testing.
`help_categories` is the full, real 80-row lookup copied verbatim from
`data-analytics/sql/help_category.csv` (not a hand-picked subset), so
`cat_id` values line up exactly with what the rest of the codebase uses.

## Table Relationships

```
countries
   └─ states (country_id)
        ├─ cities (state_id)
        ├─ users (state_id, country_id)
        │    ├─ volunteer_details (user_id)
        │    │    ├─ user_skills (user_id, cat_id → help_categories)
        │    │    └─ volunteer_locations (user_id → volunteer_details.user_id)
        │    └─ user_locations (user_id → users.user_id directly)
        └─ organizations (state_id)

help_categories
   └─ user_skills (cat_id)
```

Note the one relationship that's easy to get backwards (called out in the
issue): `volunteer_locations.user_id` references `volunteer_details.user_id`,
not `users.user_id` directly - so every volunteer_locations row's user must
already have a volunteer_details row. `user_locations.user_id` references
`users.user_id` directly instead.

## Geographic Consistency

Every user/organization is assigned a real US state and one of a few real
cities within that state (approximate real centroids, then jittered
slightly). Coordinates for `volunteer_locations`/`user_locations` are
derived from that same city's centroid, so a given user's location data is
consistent across `users.last_location`, `volunteer_locations`, and
`user_locations` - not independently randomized.

## Schema Sources (and discrepancies found)

Schema was built from, in order of trust:
1. Real, currently-used CSVs in `data-analytics/sql/` (`country.csv`,
   `state.csv`, `help_category.csv`, `users.csv`, `volunteer_details.csv`,
   `volunteer_locations.csv`, `user_skills.csv`, `organizations.csv`) -
   matched column-for-column wherever a real file exists, since that's what
   other tools in the repo are presumably already built against.
2. `saayam-for-all/database` wiki, "* Changes to the Database, Waiting for
   Microservice" - used only for tables with no real CSV to check against
   (`cities`, `user_locations`).
3. `saayam-for-all/database` wiki, "Importing CSV rows with geography
   parsing in cities table (EWKT / WKT / GeoJSON)" - used to confirm the
   exact coordinate string format.

**Found and flagging, not silently resolved:**

- **`countries`/`states` still use `last_update_date`, not the wiki's
  planned `last_updated_at` rename.** Confirmed directly against the real
  `country.csv`/`state.csv` in the repo - the rename described in the wiki
  hasn't shipped to these two tables yet, so this generator matches the
  real column name rather than the wiki's future-state one.
- **`organizations.org_id` uses no dashes (`ORG00001`), and `org_type`/
  `org_size` are capitalized strings (`"Non-Profit"`, `"Small"`) rather than
  lowercase/underscored.** Matched to the real `organizations.csv`, which
  differs from the plain lowercase enum values shown in the wiki's DDL.
- **`cities` coordinate format is inconsistent between the two wiki
  sources**, and no real `cities.csv` exists in the repo to settle it. The
  DDL page says `cities` has separate `lattitude`/`longitude` DECIMAL
  columns (typo `lattitude` kept verbatim to match the real schema); the
  geography-import wiki page says `cities` has a single EWKT point column
  instead. This generator follows the DDL page (separate decimal columns)
  as the more directly authoritative source, but it should be confirmed
  with the team since the two docs actively disagree and there's no real
  data to check against either way.
- `volunteer_locations`/`user_locations` are real, current tables -
  confirmed both via the "Changes to the Database" wiki page (items 37 and
  41, `geography(Point,4326)` columns, `last_updated_at`) and the real
  `volunteer_locations.csv` sample, which matches exactly. An earlier draft
  of this README flagged these as possibly-undocumented; that's resolved.
  `user_locations.csv` still isn't checked into the repo as real data
  though, so that table's row values are synthetic-only with no real sample
  to cross-check.
- `user_status_id` and `user_category_id` on `users` reference lookup
  tables that are out of scope for this issue (not in the 10 tables list),
  so they're populated with plausible small integers rather than validated
  against real lookup values.

## Validation Steps

`validate_data.py` checks, after generation:
- Primary key uniqueness on every table.
- No orphan foreign keys (every FK value exists in its referenced table).
- `volunteer_locations`/`user_locations` coordinates parse as valid
  `SRID=4326;POINT(lon lat)` EWKT.
- `created_at <= last_updated_at` where both columns exist.
- No real-looking contact info (synthetic email domain check).

Run it after generation and it prints row counts and a pass/fail summary.
Verified locally at both `--rows 100` (default) and `--rows 400` (the
issue's suggested volume) - both pass all checks.

## Output Location

CSVs are generated into the current directory by default (or `--outdir`).
Final files belong in `data-analytics/mock-data-generation/`, alongside
this README and the two scripts.