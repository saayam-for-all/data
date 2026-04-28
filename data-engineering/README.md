# Data Engineering — Working README

> **Use this as a quick operational guide for active Data Engineering tasks.**
>
> For workflow rules and standards, see [CONTRIBUTING.md](./CONTRIBUTING.md).  
> For architecture and technical handoff context, see [KNOWLEDGE_TRANSFER.md](./KNOWLEDGE_TRANSFER.md).  
> For active issues, see [TASK_TRACKER.md](./TASK_TRACKER.md).

---

## Local Setup

```bash
cd data-engineering
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Mock Data Generation (Issue #117)

### Scope Covered

- Table: `volunteer_details`
- FK reference: `volunteer_details.user_id -> users.user_id`

### Script and Files

- Script: `database/mock-data-generation/generate_volunteer_details.py`
- Schema source: `database/mock-data-generation/db_info.json`
- Users source CSV: `database/mock_db/users.csv`
- Output CSV: `database/mock_db/volunteer_details.csv`

### Rule Enforced Each Run

- Volunteer coverage is based on users count:
  - `target_volunteers = round(total_users * volunteer_ratio)`
  - default `volunteer_ratio = 0.15` (15%)
- If output already exists, existing volunteer rows are preserved and only missing rows are appended up to target.
- Duplicate `user_id` rows are not appended.
- Selection is deterministic with `--seed`.
- Only existing `users.user_id` values are used, preserving referential integrity.

### Run Command

From repo root:

```bash
python3 database/mock-data-generation/generate_volunteer_details.py
```

With optional flags:

```bash
python3 database/mock-data-generation/generate_volunteer_details.py \
  --volunteer-ratio 0.15 \
  --seed 117 \
  --max-volunteers 100
```

---

## Dependency Note

The `volunteer_details` generator currently uses Python standard library only, so no `requirements.txt` updates are required.
