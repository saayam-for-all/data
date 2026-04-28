# Patch summary

Fixes applied to address bugs found in the original generated output and review.

## Bugs fixed

| # | File | Original problem | Status |
|---|---|---|---|
| 1 | `generators/base_generators.py` | `uuid.uuid4()` bypassed `random.seed()`, breaking reproducibility — same seed produced different `user_id`/`req_id` values | Replaced with seeded UUID via `self.rng.getrandbits(128)` |
| 2 | `generators/base_generators.py` | `fake.phone_number()` produced extension-bearing strings up to 30+ chars; 644/5000 rows exceeded `varchar(20)` | Replaced with fixed `+1-NNN-NNN-NNNN` format (15 chars) |
| 3 | `generators/base_generators.py` | `audio_req_desc` fell through to `fake.sentence()` for every row — produced word-salad like *"My oil blood society necessary age speak picture help part field career."* | Explicit handler: empty 90% of rows, short realistic transcript otherwise |
| 4 | `generators/base_generators.py` | `req_doc_link` fell through to `fake.url()` for every row | Explicit handler: empty 80% of rows, `/uploads/req/<id>.pdf` otherwise |
| 5 | `generators/table_rules.py` | No calamity/priority invariant — 4,395/20,000 calamity requests had LOW or MEDIUM priority | `enrich_request_row` now forces priority to HIGH/CRITICAL when `iscalamity=True` |
| 6 | `generate_tables.py` | No email uniqueness — 63 duplicate emails in 5,000 users | Per-table `seen_emails` set with up to 5 retries on collision |
| 7 | `generate_tables.py` | `language_2` / `language_3` could equal `language_1` — 314 users had `language_1 == language_3` | Excludes already-chosen languages when picking the next |
| 8 | `generate_tables.py` | `location_reference.csv` shadowed `city_name` and `last_location`, collapsing 5,000 users into 18 cities | Location reference now contributes only `time_zone`; city falls through to Faker (4,265 distinct cities at full scale) |
| 9 | `validators.py` | No varchar length check | Added: counts and reports per-column length violations |
| 10 | `validators.py` | No email uniqueness check | Added: reports duplicate count for `users.primary_email_address` |
| 11 | `validators.py` | No calamity/priority correlation check | Added: reports rows where `iscalamity=True` and `priority < HIGH` |
| 12 | `location_reference_builder.py` | `import geonamescache` and a no-op `gc.get_cities()` call — unused 50MB dependency | Removed |

## Verified results (--seed 42, 5,000 users, 20,000 requests)

| Metric | Before | After |
|---|---|---|
| Email duplicates | 63 | 0 |
| Phones > 20 chars | 644 | 0 |
| Phones with `x` extension | 2,998 | 0 |
| Distinct cities | 18 | 4,265 |
| `language_1 == language_3` | 314 | 0 |
| Calamity with priority < HIGH | 4,395 | 0 |
| `audio_req_desc` non-empty (was Faker word-salad) | 20,000 | 1,703 (and now realistic) |
| `req_doc_link` non-empty (was fake URLs) | ~20,000 | 3,434 (now `/uploads/req/<id>.pdf`) |
| FK violations | 0 | 0 |
| Validator passes | yes | yes |

Reproducibility verified: same seed produces byte-identical CSVs across runs.

## Compatibility

- API unchanged. Same CLI flags, same `MockDataGenerationService.generate(...)` signature, same FastAPI endpoints.
- `geonamescache` no longer required (was never actually used).
- Validator output now richer — includes the new categories of violations. Existing FK and PK checks unchanged.
