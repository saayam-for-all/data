"""Generates the users table.

users.country_id / users.state_id are consistent by construction: a state is
picked first, and country_id is always that state's own parent country
(never an unrelated random country). city_name / last_location are derived
from a real city belonging to that state, per the "Geographic Data
Consistency" requirement (country -> state -> city).
"""

import random
from datetime import timedelta
from typing import Any, Dict, List, Tuple

from reference_data import (
    AUTH_PROVIDERS, FIRST_NAMES, GENDERS, LAST_NAMES, MIDDLE_INITIALS,
    TIME_ZONES,
)
from utils import (
    WINDOW_END, format_date, format_ts, jitter_coord, make_user_id, pg_point,
    random_datetime_after, random_datetime_in_window, random_dob,
    weighted_bool,
)

STREET_NAMES = ["Maple", "Oak", "Elm", "Main", "Sunset", "Cedar", "Lake", "Pine", "Willow", "Highland"]
STREET_SUFFIXES = ["St", "Ave", "Rd", "Blvd", "Ln", "Dr", "Ct"]


def generate_users(
    count: int,
    state_rows: List[Dict[str, Any]],
    cities_by_state: Dict[str, List[Dict[str, Any]]],
    country_by_id: Dict[Any, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (csv_rows, contexts). `contexts` carries extra per-user data
    (base_date, resolved lat/lon, etc.) that downstream generators
    (volunteer_details, user_skills, *_locations) need to stay consistent,
    but which is not itself a users.csv column."""

    rows: List[Dict[str, Any]] = []
    contexts: List[Dict[str, Any]] = []

    for i in range(1, count + 1):
        user_id = make_user_id(i)

        state = random.choice(state_rows)
        state_id = state["state_id"]
        country = country_by_id[state["country_id"]]
        is_eu = country["is_eu_member"] == "TRUE"

        city_list = cities_by_state.get(state_id, [])
        city = random.choice(city_list) if city_list else None
        if city:
            city_name = city["city_name"]
            lat, lon = float(city["lattitude"]), float(city["longitude"])
        else:
            city_name = state["state_name"]
            lat, lon = 0.0, 0.0

        # Leave headroom so downstream (volunteer_details/user_skills/
        # locations) timestamps, which must be >= base_date, stay inside
        # the overall window.
        base_date = random_datetime_in_window(end=WINDOW_END - timedelta(days=45))
        last_updated_at = random_datetime_after(base_date, max_days=30)

        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        middle_name = f"{random.choice(MIDDLE_INITIALS)}." if weighted_bool(0.5) else None
        full_name = " ".join(p for p in [first_name, middle_name, last_name] if p)

        promotion_wizard_stage = random.choice([None, 1, 2, 3, 4, 5])
        promotion_wizard_last_updated_at = (
            random_datetime_after(last_updated_at, max_days=5) if promotion_wizard_stage else None
        )

        jittered_lat, jittered_lon = jitter_coord(lat, lon, max_delta=0.05) if city else (lat, lon)

        row = {
            "user_id": user_id,
            "state_id": state_id,
            "country_id": state["country_id"],
            "user_status_id": "",  # user_status table out of scope for this dataset
            "full_name": full_name,
            "first_name": first_name,
            "middle_name": middle_name or "",
            "last_name": last_name,
            "primary_email_address": f"{first_name.lower()}.{last_name.lower()}{i}@example.com",
            "primary_phone_number": f"+{country['phone_code']}-555-{(100 + i) % 900:03d}-{(1000 + i * 7) % 9000:04d}",
            "addr_ln1": f"{random.randint(100, 9999)} {random.choice(STREET_NAMES)} {random.choice(STREET_SUFFIXES)}",
            "addr_ln2": f"Apt {random.randint(1, 400)}" if weighted_bool(0.3) else "",
            "addr_ln3": "",
            "city_name": city_name,
            "zip_code": f"{random.randint(10000, 99999)}",
            "last_location": pg_point(jittered_lat, jittered_lon) if city and weighted_bool(0.7) else "",
            "last_updated_at": format_ts(last_updated_at),
            "time_zone": random.choice(TIME_ZONES),
            "profile_picture_path": f"/uploads/profile/{user_id}.jpg" if weighted_bool(0.4) else "",
            "gender": random.choice(GENDERS) if weighted_bool(0.85) else "",
            "language_1": "",  # supporting_languages table out of scope
            "language_2": "",
            "language_3": "",
            "promotion_wizard_stage": promotion_wizard_stage if promotion_wizard_stage else "",
            "promotion_wizard_last_updated_at": format_ts(promotion_wizard_last_updated_at),
            "external_auth_provider": random.choice(AUTH_PROVIDERS) if weighted_bool(0.7) else "",
            "dob": format_date(random_dob(18, 80, as_of=base_date)),
            "is_eu": str(is_eu).upper(),
        }
        rows.append(row)

        contexts.append({
            "user_id": user_id,
            "base_date": base_date,
            "state_id": state_id,
            "city_name": city_name,
            "lat": lat,
            "lon": lon,
            "has_city": city is not None,
        })

    return rows, contexts
