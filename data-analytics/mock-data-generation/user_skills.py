"""Generates the user_skills table: 1-4 help-category skills per volunteer.
FK targets: user_skills.user_id -> users.user_id (via volunteer_details),
user_skills.cat_id -> help_categories.cat_id."""

import random
from typing import Any, Dict, List

from reference_data import USABLE_CAT_IDS
from utils import format_ts, random_datetime_after

SKILL_LEVELS = ["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]


def generate_user_skills(volunteer_contexts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for ctx in volunteer_contexts:
        skill_count = random.randint(1, 4)
        cat_ids = random.sample(USABLE_CAT_IDS, skill_count)

        for cat_id in cat_ids:
            created_at = random_datetime_after(ctx["vol_created_at"], max_days=10)
            last_updated_at = random_datetime_after(created_at, max_days=30)
            rows.append({
                "user_id": ctx["user_id"],
                "cat_id": cat_id,
                "skill_level": random.choice(SKILL_LEVELS),
                "created_at": format_ts(created_at),
                "last_updated_at": format_ts(last_updated_at),
            })

    return rows
