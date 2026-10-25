"""Generators for volunteer_details, user_skills and the two location tables.

The FK chain matters here and is easy to get wrong:
    volunteer_locations.user_id -> volunteer_details.user_id -> users.user_id
    user_locations.user_id      -> users.user_id
so volunteer_locations rows are only ever drawn from users that already have a
volunteer_details row.
"""

import random
from typing import Dict, List

import config
from utils import (
    format_bool,
    format_geography,
    format_timestamp,
    jitter_coordinate,
    json_text,
    later_than,
    NULL,
)

VOLUNTEER_DETAIL_FIELDS = [
    "user_id",
    "terms_and_conditions",
    "terms_accepted_at",
    "govt_id_path1",
    "govt_id_path2",
    "path1_updated_at",
    "path2_updated_at",
    "availability_days",
    "availability_times",
    "created_at",
    "last_updated_at",
]

USER_SKILL_FIELDS = ["user_id", "cat_id", "skill_level", "created_at", "last_updated_at"]

LOCATION_FIELDS = ["user_id", "prev_loc", "curr_loc", "last_updated_at"]

DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
TIME_SLOTS = ["EARLY_MORNING", "MORNING", "AFTERNOON", "EVENING", "NIGHT"]
SKILL_LEVELS = ["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]


def select_volunteers(profiles: List, ratio: float) -> List:
    count = int(round(len(profiles) * ratio))
    return random.sample(profiles, k=min(count, len(profiles)))


def generate_volunteer_details(volunteers: List, window) -> List[Dict[str, object]]:
    _, end = window
    rows = []
    for profile in volunteers:
        created_at = later_than(profile.registered_at, end)
        accepted = random.random() < 0.92
        terms_accepted_at = (
            format_timestamp(later_than(created_at, end)) if accepted else NULL
        )

        has_path1 = random.random() < 0.75
        has_path2 = has_path1 and random.random() < 0.4
        path1 = (
            f"s3://saayam-mock-govt-ids/{profile.user_id}/primary.pdf"
            if has_path1
            else NULL
        )
        path2 = (
            f"s3://saayam-mock-govt-ids/{profile.user_id}/secondary.pdf"
            if has_path2
            else NULL
        )

        rows.append(
            {
                "user_id": profile.user_id,
                "terms_and_conditions": format_bool(accepted),
                "terms_accepted_at": terms_accepted_at,
                "govt_id_path1": path1,
                "govt_id_path2": path2,
                "path1_updated_at": (
                    format_timestamp(later_than(created_at, end)) if has_path1 else NULL
                ),
                "path2_updated_at": (
                    format_timestamp(later_than(created_at, end)) if has_path2 else NULL
                ),
                "availability_days": json_text(
                    sorted(
                        random.sample(DAYS, k=random.randint(1, 5)),
                        key=DAYS.index,
                    )
                ),
                "availability_times": json_text(
                    sorted(
                        random.sample(TIME_SLOTS, k=random.randint(1, 3)),
                        key=TIME_SLOTS.index,
                    )
                ),
                "created_at": format_timestamp(created_at),
                "last_updated_at": format_timestamp(later_than(created_at, end)),
            }
        )
    return rows


def generate_user_skills(profiles: List, volunteer_ids, categories, window):
    _, end = window
    rows = []
    cat_ids = [category["cat_id"] for category in categories]

    for profile in profiles:
        is_volunteer = profile.user_id in volunteer_ids
        low, high = (
            config.SKILLS_PER_VOLUNTEER
            if is_volunteer
            else config.SKILLS_PER_NON_VOLUNTEER
        )
        skill_count = random.randint(low, high)
        if skill_count == 0:
            continue

        # PRIMARY KEY (user_id, cat_id): sample without replacement.
        for cat_id in random.sample(cat_ids, k=min(skill_count, len(cat_ids))):
            created_at = later_than(profile.registered_at, end)
            rows.append(
                {
                    "user_id": profile.user_id,
                    "cat_id": cat_id,
                    "skill_level": random.choice(SKILL_LEVELS),
                    "created_at": format_timestamp(created_at),
                    "last_updated_at": format_timestamp(later_than(created_at, end)),
                }
            )
    return rows


def generate_locations(profiles: List, window, ratio: float) -> List[Dict[str, object]]:
    """Rows for user_locations / volunteer_locations.

    curr_loc sits inside the user's own city; prev_loc is a short hop from it,
    because the table's trigger sets prev_loc from the previous curr_loc -- the
    two are successive positions of the same person, not unrelated points.
    """
    _, end = window
    selected = random.sample(profiles, k=int(round(len(profiles) * ratio)))
    rows = []
    for profile in selected:
        city = profile.city
        curr_lat, curr_lon = jitter_coordinate(city.latitude, city.longitude, 0.05)
        prev_lat, prev_lon = jitter_coordinate(curr_lat, curr_lon, 0.03)
        rows.append(
            {
                "user_id": profile.user_id,
                "prev_loc": format_geography(prev_lat, prev_lon),
                "curr_loc": format_geography(curr_lat, curr_lon),
                "last_updated_at": format_timestamp(
                    later_than(profile.registered_at, end)
                ),
            }
        )
    return rows
