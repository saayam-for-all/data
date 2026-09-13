"""Generates the volunteer_details table: a subset of users who opted in to
volunteer. volunteer_details.user_id is both the PK and a FK to users, so
every row here re-uses a real user_id already emitted by users.py."""

import json
import random
from typing import Any, Dict, List, Tuple

from utils import format_ts, random_datetime_after, weighted_bool

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIME_SLOTS = ["morning", "afternoon", "evening"]


def generate_volunteer_details(
    user_contexts: List[Dict[str, Any]], volunteer_ratio: float = 0.6
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (csv_rows, volunteer_contexts). volunteer_contexts is the
    subset of user_contexts that became volunteers, each annotated with its
    volunteer created_at/last_updated_at so volunteer_locations/user_skills
    can stay chronologically consistent."""

    sample_size = max(1, int(round(len(user_contexts) * volunteer_ratio)))
    volunteers = random.sample(user_contexts, min(sample_size, len(user_contexts)))

    rows: List[Dict[str, Any]] = []
    volunteer_contexts: List[Dict[str, Any]] = []

    for ctx in volunteers:
        created_at = random_datetime_after(ctx["base_date"], max_days=14)
        last_updated_at = random_datetime_after(created_at, max_days=60)

        terms_accepted = weighted_bool(0.97)
        terms_accepted_at = random_datetime_after(created_at, max_days=1) if terms_accepted else None

        has_path1 = weighted_bool(0.8)
        path1_updated_at = random_datetime_after(created_at, max_days=5) if has_path1 else None
        has_path2 = has_path1 and weighted_bool(0.5)
        path2_updated_at = random_datetime_after(path1_updated_at, max_days=5) if has_path2 else None

        chosen_days = sorted(random.sample(DAYS, random.randint(1, 4)), key=DAYS.index)
        availability_times = {day: random.choice(TIME_SLOTS) for day in chosen_days}

        row = {
            "user_id": ctx["user_id"],
            "terms_and_conditions": str(terms_accepted).upper(),
            "terms_accepted_at": format_ts(terms_accepted_at),
            "govt_id_path1": f"/uploads/govt_id/{ctx['user_id']}_1.pdf" if has_path1 else "",
            "govt_id_path2": f"/uploads/govt_id/{ctx['user_id']}_2.pdf" if has_path2 else "",
            "path1_updated_at": format_ts(path1_updated_at),
            "path2_updated_at": format_ts(path2_updated_at),
            "availability_days": json.dumps(chosen_days),
            "availability_times": json.dumps(availability_times),
            "created_at": format_ts(created_at),
            "last_updated_at": format_ts(last_updated_at),
        }
        rows.append(row)

        volunteer_contexts.append({
            **ctx,
            "vol_created_at": created_at,
            "vol_last_updated_at": last_updated_at,
        })

    return rows, volunteer_contexts
