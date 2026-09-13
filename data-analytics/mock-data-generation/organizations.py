"""Generates the organizations table.
organizations.state_id is the FK column; states.state_id is the referenced
PK (organizations is the child table). city_name is picked from a real city
belonging to the chosen state for geographic consistency."""

import random
from typing import Any, Dict, List

from reference_data import ORG_ADJECTIVES, ORG_NOUNS, ORG_SUFFIXES
from utils import (
    format_ts, make_org_id, random_datetime_after, random_datetime_in_window,
    weighted_bool,
)

ORG_TYPES = ["non_profit", "for_profit"]
ORG_SIZES = ["small", "medium", "large"]


def generate_organizations(
    count: int,
    state_rows: List[Dict[str, Any]],
    cities_by_state: Dict[str, List[Dict[str, Any]]],
    country_by_id: Dict[Any, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for i in range(1, count + 1):
        org_id = make_org_id(i)
        state = random.choice(state_rows)
        state_id = state["state_id"]
        country = country_by_id[state["country_id"]]
        city_list = cities_by_state.get(state_id, [])
        city_name = random.choice(city_list)["city_name"] if city_list else state["state_name"]

        org_name = f"{random.choice(ORG_ADJECTIVES)} {random.choice(ORG_NOUNS)} {random.choice(ORG_SUFFIXES)}"
        slug = org_name.lower().replace(" ", "")

        created_at = random_datetime_in_window()
        last_updated_at = random_datetime_after(created_at, max_days=90)

        org_type = random.choices(ORG_TYPES, weights=[7, 3], k=1)[0]

        rows.append({
            "org_id": org_id,
            "org_name": org_name,
            "street": f"{random.randint(100, 9999)} {random.choice(['Market','Commerce','Community','Center'])} St",
            "city_name": city_name,
            "state_id": state_id,
            "zip_code": f"{random.randint(10000, 99999)}",
            "mission": f"{org_name} connects volunteers with neighbors in {city_name} who need help with everyday tasks.",
            "web_url": f"https://www.{slug}.org",
            "phone": f"+{country['phone_code']}-555-{random.randint(200,999)}-{random.randint(1000,9999)}",
            "email": f"contact@{slug}.org",
            "org_type": org_type,
            "org_size": random.choice(ORG_SIZES),
            "org_rating": random.randint(1, 5),
            "is_collaborator": str(weighted_bool(0.5)).upper(),
            "is_contributor": str(weighted_bool(0.3)).upper(),
            "created_at": format_ts(created_at),
            "last_updated_at": format_ts(last_updated_at),
        })

    return rows
