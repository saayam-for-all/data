from __future__ import annotations

import random
from datetime import timedelta

import pandas as pd

from utils import (
    choose_skill_codes,
    fmt_ts,
    maybe_none,
    random_timestamp,
    read_help_categories,
    read_users,
    weighted_choice,
)


APPLICATION_STATUS_WEIGHTS = {
    "draft": 0.10,
    "submitted": 0.20,
    "under_review": 0.20,
    "approved": 0.25,
    "rejected": 0.10,
    "on_hold": 0.05,
    "completed": 0.10,
}

AVAILABILITY_OPTIONS = [
    "weekdays_morning",
    "weekdays_evening",
    "weekends_only",
    "flexible",
    "part_time",
    "full_time",
]


def build_application_row(user_id: int, cat_ids: list[int]) -> dict:
    created_at = random_timestamp()
    last_updated_at = created_at + timedelta(
        days=random.randint(0, 120),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    terms_accepted_at = created_at + timedelta(minutes=random.randint(1, 180))
    path_updated_at = created_at + timedelta(
        days=random.randint(0, 30),
        hours=random.randint(0, 23),
    )

    application_status = weighted_choice(APPLICATION_STATUS_WEIGHTS)
    is_completed = application_status in {"approved", "completed"}

    skill_codes = choose_skill_codes(cat_ids)

    current_page = 5 if is_completed else random.randint(1, 5)
    govt_id_path = maybe_none(f"/uploads/govt_ids/user_{user_id}.pdf", probability=0.10)

    return {
        "user_id": user_id,
        "terms_and_conditions": True,
        "terms_accepted_at": fmt_ts(terms_accepted_at),
        "govt_id_path": govt_id_path,
        "path_updated_at": fmt_ts(path_updated_at),
        "skill_codes": ",".join(map(str, skill_codes)),
        "availability": random.choice(AVAILABILITY_OPTIONS),
        "current_page": current_page,
        "application_status": application_status,
        "is_completed": is_completed,
        "created_at": fmt_ts(created_at),
        "last_updated_at": fmt_ts(last_updated_at),
    }


def generate_volunteer_applications(row_count: int = 100, seed: int = 42) -> pd.DataFrame:
    random.seed(seed)

    user_ids = read_users(max(row_count * 2, 5000))
    cat_ids = read_help_categories()

    chosen_users = random.sample(user_ids, row_count)
    rows = [build_application_row(user_id, cat_ids) for user_id in chosen_users]

    return pd.DataFrame(rows)