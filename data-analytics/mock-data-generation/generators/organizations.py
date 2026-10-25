"""Generator for the organizations table.

organizations is the child table: organizations.state_id references
states.state_id. Organization names, URLs and e-mails are synthetic; URLs and
e-mails use the RFC 2606 reserved example.org domain so nothing resolves to a
real site, while still satisfying the schema CHECK constraints
(web_url LIKE 'http%', email LIKE '%@%').
"""

import random
import re
from typing import Dict, List

import config
import localization
from reference_data import ReferenceData
from utils import (
    format_bool,
    format_timestamp,
    later_than,
    org_id as make_org_id,
    random_datetime,
    weighted_choices,
    NULL,
)

ORGANIZATION_FIELDS = [
    "org_id",
    "org_name",
    "street",
    "city_name",
    "state_id",
    "zip_code",
    "mission",
    "web_url",
    "phone",
    "email",
    "org_type",
    "org_size",
    "org_rating",
    "is_collaborator",
    "is_contributor",
    "created_at",
    "last_updated_at",
]

# org_type_enum and org_size_enum values are lowercase in the schema.
ORG_TYPES = ["non_profit", "for_profit"]
ORG_SIZES = ["small", "medium", "large"]

FOCUS_WORDS = [
    "Food", "Shelter", "Literacy", "Health", "Youth", "Elder Care",
    "Disability", "Housing", "Education", "Environment", "Employment",
    "Refugee", "Transport", "Legal Aid", "Mental Health", "Disaster Relief",
]
ORG_SUFFIXES = [
    "Alliance", "Collective", "Coalition", "Trust", "Network", "Foundation",
    "Initiative", "Society", "Partners", "Outreach", "Services", "Council",
]

MISSION_TEMPLATES = [
    "Provides {focus} support to under-served households across {city}.",
    "Connects volunteers with {focus} programmes throughout the {city} area.",
    "Works to remove barriers to {focus} for families living in {city}.",
    "Runs community {focus} projects and referral services in and around {city}.",
    "Coordinates {focus} assistance for residents of {city} and nearby towns.",
]


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:50]


def generate_organizations(reference: ReferenceData, window, count: int):
    start, end = window

    states_with_cities = {}
    for state_id in reference.cities_by_state:
        state = reference.state_by_id[state_id]
        states_with_cities.setdefault(state["country_id"], []).append(state_id)

    country_ids = weighted_choices(
        {k: v for k, v in config.COUNTRY_WEIGHTS.items() if k in states_with_cities},
        count,
    )

    rows: List[Dict[str, object]] = []
    for index, country_id in enumerate(country_ids, start=1):
        country = reference.country_by_id[country_id]
        state_id = random.choice(states_with_cities[country_id])
        state = reference.state_by_id[state_id]
        city = random.choice(reference.cities_by_state[state_id])

        focus = random.choice(FOCUS_WORDS)
        org_name = f"{city.city_name} {focus} {random.choice(ORG_SUFFIXES)}"
        org_name = org_name[:125]
        slug = _slug(org_name)

        created_at = random_datetime(start, end)
        has_rating = random.random() < 0.85

        rows.append(
            {
                "org_id": make_org_id(index),
                "org_name": org_name,
                "street": f"{random.randint(1, 9999)} {random.choice(['Main', 'Oak', 'Cedar', 'Market', 'Church', 'Station', 'Park', 'Mill'])} {random.choice(['Street', 'Road', 'Avenue', 'Lane', 'Way'])}",
                "city_name": city.city_name,
                "state_id": state_id,
                "zip_code": localization.postal_code(country_id, state["state_code"]),
                "mission": random.choice(MISSION_TEMPLATES).format(
                    focus=focus.lower(), city=city.city_name
                ),
                "web_url": f"https://www.{slug}.example.org",
                "phone": localization.phone_number(country["phone_code"]),
                "email": f"contact@{slug}.example.org",
                "org_type": random.choices(ORG_TYPES, weights=[0.85, 0.15])[0],
                "org_size": random.choice(ORG_SIZES),
                "org_rating": random.randint(1, 5) if has_rating else NULL,
                "is_collaborator": format_bool(random.random() < 0.45),
                "is_contributor": format_bool(random.random() < 0.35),
                "created_at": format_timestamp(created_at),
                "last_updated_at": format_timestamp(later_than(created_at, end)),
            }
        )
    return rows
