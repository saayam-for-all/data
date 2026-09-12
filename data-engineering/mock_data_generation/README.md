# Saayam Mock Data Generation

Generates realistic, referentially-consistent mock CSV data for local
development, matching the schema described in the database wiki
("Changes to the Database, Waiting for Microservice").

## Setup

```bash
pip install faker
python generate_mock_data.py
python validate_data.py
```

Output: 10 CSVs written to `./output/`.

## Tables Generated (in dependency order)

| # | Table | Rows | Depends on |
|---|-------|------|------------|
| 1 | `countries` | 3 | — |
| 2 | `states` | 12 | countries |
| 3 | `cities` | 48 | states |
| 4 | `users` | 100 | countries, states |
| 5 | `volunteer_details` | 40 | users |
| 6 | `user_locations` | 100 | users |
| 7 | `volunteer_locations` | 40 | **volunteer_details** (not users) |
| 8 | `help_categories` | 7 | — |
| 9 | `user_skills` | ~76 | volunteer_details, help_categories |
| 10 | `organizations` | 15 | states |

## Key Schema Decisions

- **`volunteer_locations.user_id` references `volunteer_details`, not
  `users` directly.** Only 40 of our 100 users are volunteers — the other
  60 are regular beneficiaries who never signed up to help. If this table
  pointed to `users` instead, a non-volunteer could end up with a
  volunteer location record, which doesn't make sense since only actual
  volunteers get tracked for location-based matching.

- **Geography columns store raw `POINT(longitude latitude)` text**, not
  separate lat/long columns. Longitude comes first — a common mix-up,
  since most people think "latitude first." Getting the order backwards
  wouldn't necessarily error out, but it would silently place points in
  the wrong spot on the map (or an invalid one entirely, since latitude
  is capped at ±90 while longitude can go to ±180).

- **`user_skills` primary key is the pair `(user_id, cat_id)`**, not either
  column alone. A primary key must be unique per row — so the same person
  can appear multiple times (once per skill), and the same category can
  appear multiple times (once per person with that skill), but the *same
  person + same category* combination can only exist once. The
  `seen_pairs` set in the generation script enforces this by tracking
  every combination already created and skipping duplicates.

- **ID formats match production generators:**
  - `user_id`: `SID-00-XXX-XXX-XXX-XXX-XXX`
  - `org_id`: `ORG-XXX-XXX-XXX-XXXX`