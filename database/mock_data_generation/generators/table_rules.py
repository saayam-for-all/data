"""Table-specific realism rules kept intentionally small and isolated."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Dict, List


REQUEST_STATUS_RESOLVED_IDS = {"3", "6", "7", 3, 6, 7}

# Priority IDs from request_priority.csv: 0=LOW, 1=MEDIUM, 2=HIGH, 3=CRITICAL
_HIGH_PRIORITY_IDS = (2, 3)

# Module-level RNG for invariant repairs. Seeded by the engine via
# `seed_rules_rng()` so output stays reproducible.
_rng = random.Random()


def seed_rules_rng(seed: int) -> None:
    """Engine calls this to keep table-rule randomness reproducible."""
    _rng.seed(seed)


def enrich_users_row(row: Dict[str, object]) -> Dict[str, object]:
    first = str(row.get("first_name", "")).strip()
    middle = str(row.get("middle_name", "")).strip()
    last = str(row.get("last_name", "")).strip()
    if "full_name" in row:
        row["full_name"] = " ".join(part for part in [first, middle, last] if part).strip()
    if "language_1" in row and not row.get("language_1"):
        row["language_1"] = "English"
    return row


def enrich_request_row(row: Dict[str, object]) -> Dict[str, object]:
    # Calamity ⇒ priority ≥ HIGH (2). Calamity requests with LOW/MEDIUM priority
    # are nonsensical and were appearing in ~22% of generated calamity rows.
    is_calamity = row.get("iscalamity")
    if is_calamity in (True, "True", "true", 1, "1"):
        try:
            current_priority = int(row.get("req_priority_id", 0))
        except (TypeError, ValueError):
            current_priority = 0
        if current_priority < 2:
            row["req_priority_id"] = _rng.choice(_HIGH_PRIORITY_IDS)

    submission_date = str(row.get("submission_date", "")).strip()
    if not submission_date:
        submission_date = "2025-01-01 09:00:00"
        row["submission_date"] = submission_date

    try:
        submission_dt = datetime.strptime(submission_date, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return row

    row["last_update_date"] = (submission_dt + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")

    status_id = row.get("req_status_id")
    if status_id in REQUEST_STATUS_RESOLVED_IDS:
        row["serviced_date"] = (submission_dt + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    elif "serviced_date" in row:
        row["serviced_date"] = ""

    return row


def apply_table_rules(table_name: str, row: Dict[str, object]) -> Dict[str, object]:
    if table_name == "users":
        return enrich_users_row(row)
    if table_name == "request":
        return enrich_request_row(row)
    return row


KNOWN_TABLES: List[str] = ["users", "request"]
