# Mock Data Generation

Metadata-driven pipeline that generates realistic CSV mock data for all
database tables defined in `db_info.json`.

Output goes to `database/mock_db/`.

---

## Quick Start

```bash
# From the repo root
cd database/mock-data-generation

# Install the one external dependency (first time only)
pip install -r requirements.txt

# Dev mode — 50 users, 200 requests, fast
python generate_mock_data.py --mode dev

# Full mode — 5 000 users, 20 000 requests
python generate_mock_data.py --mode full

# Deterministic output (same seed → same data)
python generate_mock_data.py --mode full --seed 42

# Check FK/PK integrity on existing CSVs without regenerating
python generate_mock_data.py --validate-only

# Override one table's row count
python generate_mock_data.py --mode full --override request=500
```

---

## File Overview

| File | Purpose |
|------|---------|
| `config.py` | All tunables: row counts per mode, random seed, enum values, column overrides, path constants. Edit this first when adjusting targets. |
| `schema_loader.py` | Parses `db_info.json` into typed `TableMeta` / `ColumnMeta` structures. Normalises raw type strings (e.g. `"character varying (255)"` → `"varchar"`). |
| `relationship_resolver.py` | Hardcoded FK map (db_info.json has no FK declarations), effective PKs for tables with schema gaps, and `topological_order()` to sort tables by dependency. |
| `generators.py` | One `generate_<table>()` function per non-lookup table. A generic type-driven resolver handles simple columns; custom logic handles FK sampling, JSON fields, and business rules (e.g. `serviced_date` only set when request is closed). |
| `validators.py` | Post-generation FK and PK uniqueness checks. Violations are reported as warnings — they do not stop the pipeline. |
| `generate_mock_data.py` | Orchestrator: loads schema → copies lookup CSVs → resolves generation order → runs generators → writes CSVs → validates → prints summary. |
| `db_info.json` | Schema source of truth (do not edit). |
| `requirements.txt` | Single external dependency: `faker`. |

**Legacy scripts** (preserved, not used by the new pipeline):

| File | Note |
|------|------|
| `utils.py` | Original shared helpers. Still importable. |
| `volunteer_applications.py` | Superseded by `generators.py`. |
| `user_skills.py` | Superseded by `generators.py`. |
| `generate_volunteer_details.py` | Superseded. Works standalone if needed. |
| `generate_volunteers_assigned.py` | Superseded. Works standalone if needed. |

---

## Schema Sources

| Source | Role |
|--------|------|
| `db_info.json` | Primary: table names, column names, types, PK flags. |
| `database/lookup_tables/*.csv` | Pre-populated reference data (country, state, help_categories, etc.). Copied verbatim to `mock_db/`; not regenerated. |

---

## Output

All files are written to `database/mock_db/`:

```
mock_db/
├── country.csv                 ← copied from lookup_tables/
├── state.csv                   ← copied
├── help_categories.csv         ← copied
├── ... (all other lookup CSVs)
├── users.csv                   ← generated
├── request.csv                 ← generated
├── volunteers_assigned.csv     ← generated
└── ... (all other generated tables)
```

---

## Configuration

All tunables live in `config.py`. Key sections:

### Row counts (`ROW_COUNTS`)

```python
ROW_COUNTS = {
    "dev":  { "counts": {"users": 50,   "request": 200,    ...} },
    "full": { "counts": {"users": 5000, "request": 20000,  ...} },
}
```

Ratio-based tables (child tables sized as a fraction of `users`) use the
`"ratios"` sub-key:

```python
"ratios": {
    "volunteer_details": 0.15,   # 15% of users become volunteers
    "user_availability": 0.70,   # 70% of users have availability rows
    ...
}
```

### Enum values (`ENUM_VALUES`)

Enums not declared in `db_info.json` are listed here:

```python
ENUM_VALUES = {
    "organizations.org_type": ["NON_PROFIT", "NGO", "GOVERNMENT", ...],
    "volunteer_rating.rating": [1, 2, 3, 4, 5],
    ...
}
```

### Column overrides (`COLUMN_OVERRIDES`)

Per-column generation instructions that the generic resolver cannot infer:

```python
COLUMN_OVERRIDES = {
    "request.iscalamity": {"kind": "weighted_bool", "true_weight": 0.05},
    "volunteer_details.govt_id_path1": {
        "kind": "template",
        "pattern": "/mock-storage/kyc/{user_id}/govt_id_front.pdf",
    },
}
```

---

## Dependency Graph (generation order)

```
Tier 0  Lookup tables (copied, not generated)
        country, state, help_categories, req_add_info_metadata,
        list_item_metadata, notification_channels, notification_types,
        request_for, request_isleadvol, request_priority,
        request_status, request_type, user_category, user_status,
        supporting_languages, help_categories_map

Tier 1  Independent (no FK to generated tables)
        action, identity_type, sla, news_snippets, user_signoff,
        volunteer_organizations, city, emergency_numbers

Tier 2  → lookup tables only
        organizations, users

Tier 3  → users
        user_additional_details, user_availability, user_locations,
        user_notification_preferences, user_notification_status,
        user_org_map, volunteer_applications, user_skills,
        volunteer_details, volunteer_locations,
        fraud_requests, meetings

Tier 4  → users + meetings
        meeting_participants

Tier 5  → users + lookup tables
        request

Tier 6  → request + users
        request_comments, request_guest_details, req_add_info,
        notifications, volunteer_rating, volunteers_assigned
```

---

## Scale Notes

- `--mode dev` is designed for local iteration and CI smoke tests (~5 seconds).
- `--mode full` targets 5 000 users / 20 000 requests (~30–60 seconds).
- To scale to 40 000+ requests, edit `ROW_COUNTS["full"]["counts"]` in
  `config.py`. No code changes needed.
- `volunteer_rating` and `volunteers_assigned` use collision-avoidance loops,
  so very large targets may slow down if the (request × user) space is small.
  Increase `users` proportionally.

---

## Known Schema Gaps

These issues exist in `db_info.json` and are worked around in
`relationship_resolver.py`:

| Issue | Workaround |
|-------|-----------|
| `state`, `notification_channels`, `notification_types`, `notifications`, `user_notification_preferences` have no `primary_key: true` column | `EFFECTIVE_PKS` dict overrides the PK for each |
| No FK declarations anywhere in `db_info.json` | Full FK map hardcoded in `FK_MAP` |
| `supporting_languages.created_at` type is `"timest"` (truncated) | Normalised to `"timestamp"` by `schema_loader.py` |

---

## Requirements

```
faker>=24.0.0
```

Install:
```bash
pip install -r database/mock-data-generation/requirements.txt
```

Only one external package is needed.
The rest of the pipeline uses Python standard library only
(`random`, `csv`, `json`, `datetime`, `hashlib`, `pathlib`, `argparse`).
