from __future__ import annotations

import json
import random
from datetime import timedelta
from typing import Any

import reference_data as ref

from config import GeneratorConfig
from schema import (
    ORGANIZATION_SIZES,
    ORGANIZATION_TYPES,
    SKILL_LEVELS,
)
from utils import (
    GENERATION_END,
    GENERATION_START,
    format_timestamp,
    generate_org_id,
    generate_user_id,
    geography_point,
    jitter_coordinates,
    postgres_point,
    random_date_of_birth,
    random_datetime,
    random_datetime_between,
)


def generate_countries(
    rng: random.Random,
) -> list[dict[str, Any]]:
    rows = []

    for country in ref.COUNTRIES:
        updated_at = random_datetime(rng)

        rows.append(
            {
                "country_id": country["country_id"],
                "country_name": country["country_name"],
                "phone_code": country["phone_code"],
                "country_code": country["country_code"],
                "last_updated_at": format_timestamp(updated_at),
                "is_eu_member": country["is_eu_member"],
            }
        )

    return rows


def generate_states(
    rng: random.Random,
) -> list[dict[str, Any]]:
    rows = []

    for state in ref.US_STATES:
        updated_at = random_datetime(rng)

        rows.append(
            {
                "state_id": state["state_id"],
                "country_id": state["country_id"],
                "state_name": state["state_name"],
                "state_code": state["state_code"],
                "last_updated_at": format_timestamp(updated_at),
            }
        )

    return rows


def generate_cities(
    rng: random.Random,
    config: GeneratorConfig,
) -> list[dict[str, Any]]:
    rows = []

    city_id = 1

    for state_index, state in enumerate(ref.US_STATES):
        for city_index in range(config.cities_per_state):
            word_index = (
                state_index * config.cities_per_state + city_index
            ) % len(ref.CITY_NAME_WORDS)

            suffix_index = city_index % len(ref.CITY_NAME_SUFFIXES)

            city_name = (
                f"{ref.CITY_NAME_WORDS[word_index]} "
                f"{ref.CITY_NAME_SUFFIXES[suffix_index]}"
            )

            latitude, longitude = jitter_coordinates(
                rng,
                state["latitude"],
                state["longitude"],
                max_delta=0.40,
            )

            updated_at = random_datetime(rng)

            rows.append(
                {
                    "city_id": city_id,
                    "state_id": state["state_id"],
                    "city_name": city_name,
                    "lattitude": f"{latitude:.6f}",
                    "longitude": f"{longitude:.6f}",
                    "last_updated_at": format_timestamp(updated_at),
                }
            )

            city_id += 1

    return rows


def generate_help_categories(
    rng: random.Random,
) -> list[dict[str, Any]]:
    rows = []

    for category in ref.HELP_CATEGORIES:
        updated_at = random_datetime(rng)

        rows.append(
            {
                "cat_id": category["cat_id"],
                "cat_name": category["cat_name"],
                "cat_desc": category["cat_desc"],
                "last_updated_at": format_timestamp(updated_at),
            }
        )

    return rows


def _build_city_lookup(
    cities: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}

    for city in cities:
        result.setdefault(city["state_id"], []).append(city)

    return result


def _state_lookup() -> dict[str, dict[str, Any]]:
    return {
        state["state_id"]: state
        for state in ref.US_STATES
    }


def _synthetic_zip_code(
    state: dict[str, Any],
    sequence_number: int,
) -> str:
    suffix = sequence_number % 1000

    return f"{state['zip_prefix']}{suffix:03d}"


def generate_users(
    rng: random.Random,
    config: GeneratorConfig,
    cities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []

    state_by_id = _state_lookup()
    cities_by_state = _build_city_lookup(cities)

    eligible_states = [
        state
        for state in ref.US_STATES
        if cities_by_state.get(state["state_id"])
    ]

    for index in range(1, config.users + 1):
        state = rng.choice(eligible_states)

        city = rng.choice(
            cities_by_state[state["state_id"]]
        )

        user_id = generate_user_id(index)

        first_name = f"Synthetic{index:04d}"
        middle_name = ""
        last_name = "User"

        full_name = f"{first_name} {last_name}"

        latitude, longitude = jitter_coordinates(
            rng,
            float(city["lattitude"]),
            float(city["longitude"]),
            config.location_jitter_degrees,
        )

        last_updated_at = random_datetime(rng)

        promo_updated_at = random_datetime_between(
            rng,
            GENERATION_START,
            last_updated_at,
        )

        zip_code = _synthetic_zip_code(
            state_by_id[state["state_id"]],
            index,
        )

        rows.append(
            {
                "user_id": user_id,
                "state_id": state["state_id"],
                "country_id": state["country_id"],

                # user_status_id is an FK to an out-of-scope lookup table.
                # It is nullable in the Virginia schema, so NULL avoids
                # inventing an invalid external reference.
                "user_status_id": None,

                "full_name": full_name,
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,

                "primary_email_address": (
                    f"synthetic.user{index:04d}@example.invalid"
                ),

                "primary_phone_number": (
                    f"555{index % 10_000_000:07d}"
                ),

                "addr_ln1": f"{1000 + index} Mock Data Lane",
                "addr_ln2": (
                    f"Unit {index % 200 + 1}"
                    if index % 3 == 0
                    else ""
                ),
                "addr_ln3": "",

                "city_name": city["city_name"],
                "zip_code": zip_code,

                "last_location": postgres_point(
                    latitude,
                    longitude,
                ),

                "last_updated_at": format_timestamp(
                    last_updated_at
                ),

                "time_zone": state["time_zone"],

                "profile_picture_path": (
                    f"/mock/profile/{user_id}.png"
                ),

                "gender": rng.choice(
                    [
                        "female",
                        "male",
                        "non_binary",
                        "prefer_not_to_say",
                    ]
                ),

                # These are foreign keys to supporting_languages,
                # which is outside the ten-table scope of Issue #301.
                "language_1": None,
                "language_2": None,
                "language_3": None,

                "promotion_wizard_stage": rng.randint(0, 5),

                "promotion_wizard_last_updated_at": (
                    format_timestamp(promo_updated_at)
                ),

                "external_auth_provider": "mock",

                "dob": random_date_of_birth(rng),

                # All generated users belong to US states.
                "is_eu": False,
            }
        )

    return rows


def generate_volunteer_details(
    rng: random.Random,
    config: GeneratorConfig,
    users: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not users:
        return []

    volunteer_count = round(
        len(users) * config.volunteer_ratio
    )

    volunteer_count = min(
        volunteer_count,
        len(users),
    )

    volunteer_users = rng.sample(
        users,
        volunteer_count,
    )

    rows = []

    for user in volunteer_users:
        created_at = random_datetime(rng)

        terms_accepted_at = random_datetime_between(
            rng,
            created_at,
            GENERATION_END,
        )

        path1_updated_at = random_datetime_between(
            rng,
            created_at,
            GENERATION_END,
        )

        path2_updated_at = random_datetime_between(
            rng,
            created_at,
            GENERATION_END,
        )

        latest_related_timestamp = max(
            created_at,
            terms_accepted_at,
            path1_updated_at,
            path2_updated_at,
        )

        last_updated_at = random_datetime_between(
            rng,
            latest_related_timestamp,
            GENERATION_END,
        )

        number_of_days = rng.randint(2, 6)

        availability_days = sorted(
            rng.sample(
                ref.AVAILABILITY_DAYS,
                number_of_days,
            ),
            key=ref.AVAILABILITY_DAYS.index,
        )

        number_of_windows = rng.randint(1, 3)

        availability_times = rng.sample(
            ref.AVAILABILITY_WINDOWS,
            number_of_windows,
        )

        user_id = user["user_id"]

        rows.append(
            {
                "user_id": user_id,
                "terms_and_conditions": True,
                "terms_accepted_at": format_timestamp(
                    terms_accepted_at
                ),

                "govt_id_path1": (
                    f"/mock/government-id/{user_id}/front.png"
                ),

                "govt_id_path2": (
                    f"/mock/government-id/{user_id}/back.png"
                ),

                "path1_updated_at": format_timestamp(
                    path1_updated_at
                ),

                "path2_updated_at": format_timestamp(
                    path2_updated_at
                ),

                "availability_days": json.dumps(
                    availability_days,
                    separators=(",", ":"),
                ),

                "availability_times": json.dumps(
                    availability_times,
                    separators=(",", ":"),
                ),

                "created_at": format_timestamp(created_at),

                "last_updated_at": format_timestamp(
                    last_updated_at
                ),
            }
        )

    return rows


def generate_user_skills(
    rng: random.Random,
    config: GeneratorConfig,
    users: list[dict[str, Any]],
    help_categories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []

    if not help_categories:
        return rows

    category_ids = [
        category["cat_id"]
        for category in help_categories
    ]

    if config.skills_per_user_max > len(category_ids):
        raise ValueError(
            "skills_per_user_max exceeds number of help categories"
        )

    skill_levels = sorted(SKILL_LEVELS)

    for user in users:
        skill_count = rng.randint(
            config.skills_per_user_min,
            config.skills_per_user_max,
        )

        selected_categories = rng.sample(
            category_ids,
            skill_count,
        )

        for category_id in selected_categories:
            created_at = random_datetime(rng)

            last_updated_at = random_datetime_between(
                rng,
                created_at,
                GENERATION_END,
            )

            rows.append(
                {
                    "user_id": user["user_id"],
                    "cat_id": category_id,
                    "skill_level": rng.choice(skill_levels),
                    "created_at": format_timestamp(created_at),
                    "last_updated_at": format_timestamp(
                        last_updated_at
                    ),
                }
            )

    return rows


def generate_organizations(
    rng: random.Random,
    config: GeneratorConfig,
    cities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []

    if not cities:
        return rows

    state_by_id = _state_lookup()

    org_types = sorted(ORGANIZATION_TYPES)
    org_sizes = sorted(ORGANIZATION_SIZES)

    for index in range(1, config.organizations + 1):
        city = rng.choice(cities)

        state = state_by_id[city["state_id"]]

        created_at = random_datetime(rng)

        last_updated_at = random_datetime_between(
            rng,
            created_at,
            GENERATION_END,
        )

        org_id = generate_org_id(index)

        zip_code = _synthetic_zip_code(
            state,
            index + 500,
        )

        rows.append(
            {
                "org_id": org_id,

                "org_name": (
                    f"Synthetic Community Organization {index:04d}"
                ),

                "street": (
                    f"{2000 + index} Community Test Avenue"
                ),

                "city_name": city["city_name"],
                "state_id": state["state_id"],
                "zip_code": zip_code,

                "mission": (
                    "Synthetic organization created only for "
                    "Saayam dashboard and API testing."
                ),

                "web_url": (
                    f"https://organization{index:04d}.example.invalid"
                ),

                "phone": (
                    f"555{(index + 5_000_000) % 10_000_000:07d}"
                ),

                "email": (
                    f"organization{index:04d}@example.invalid"
                ),

                "org_type": rng.choice(org_types),
                "org_size": rng.choice(org_sizes),

                "org_rating": rng.randint(1, 5),

                "is_collaborator": rng.choice(
                    [True, False]
                ),

                "is_contributor": rng.choice(
                    [True, False]
                ),

                "created_at": format_timestamp(created_at),

                "last_updated_at": format_timestamp(
                    last_updated_at
                ),
            }
        )

    return rows


def _city_for_user(
    user: dict[str, Any],
    city_lookup: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    key = (
        user["state_id"],
        user["city_name"],
    )

    city = city_lookup.get(key)

    if city is None:
        raise ValueError(
            f"Cannot find city for user {user['user_id']}: {key}"
        )

    return city


def _build_city_name_lookup(
    cities: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (
            city["state_id"],
            city["city_name"],
        ): city
        for city in cities
    }


def _generate_location_pair(
    rng: random.Random,
    city: dict[str, Any],
    config: GeneratorConfig,
) -> tuple[str, str]:
    city_latitude = float(city["lattitude"])
    city_longitude = float(city["longitude"])

    previous_latitude, previous_longitude = jitter_coordinates(
        rng,
        city_latitude,
        city_longitude,
        config.location_jitter_degrees,
    )

    current_latitude, current_longitude = jitter_coordinates(
        rng,
        city_latitude,
        city_longitude,
        config.location_jitter_degrees,
    )

    previous_location = geography_point(
        previous_latitude,
        previous_longitude,
    )

    current_location = geography_point(
        current_latitude,
        current_longitude,
    )

    return previous_location, current_location


def generate_user_locations(
    rng: random.Random,
    config: GeneratorConfig,
    users: list[dict[str, Any]],
    cities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not users:
        return []

    location_count = round(
        len(users) * config.user_location_ratio
    )

    location_count = min(
        location_count,
        len(users),
    )

    selected_users = rng.sample(
        users,
        location_count,
    )

    city_lookup = _build_city_name_lookup(cities)

    rows = []

    for user in selected_users:
        city = _city_for_user(
            user,
            city_lookup,
        )

        previous_location, current_location = (
            _generate_location_pair(
                rng,
                city,
                config,
            )
        )

        last_updated_at = random_datetime(rng)

        rows.append(
            {
                "user_id": user["user_id"],
                "prev_loc": previous_location,
                "curr_loc": current_location,
                "last_updated_at": format_timestamp(
                    last_updated_at
                ),
            }
        )

    return rows


def generate_volunteer_locations(
    rng: random.Random,
    config: GeneratorConfig,
    volunteer_details: list[dict[str, Any]],
    users: list[dict[str, Any]],
    cities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not volunteer_details:
        return []

    location_count = round(
        len(volunteer_details)
        * config.volunteer_location_ratio
    )

    location_count = min(
        location_count,
        len(volunteer_details),
    )

    selected_volunteers = rng.sample(
        volunteer_details,
        location_count,
    )

    users_by_id = {
        user["user_id"]: user
        for user in users
    }

    city_lookup = _build_city_name_lookup(cities)

    rows = []

    for volunteer in selected_volunteers:
        user_id = volunteer["user_id"]

        user = users_by_id[user_id]

        city = _city_for_user(
            user,
            city_lookup,
        )

        previous_location, current_location = (
            _generate_location_pair(
                rng,
                city,
                config,
            )
        )

        last_updated_at = random_datetime(rng)

        rows.append(
            {
                "user_id": user_id,
                "prev_loc": previous_location,
                "curr_loc": current_location,
                "last_updated_at": format_timestamp(
                    last_updated_at
                ),
            }
        )

    return rows


def generate_all(
    config: GeneratorConfig,
) -> dict[str, list[dict[str, Any]]]:
    config.validate()

    rng = random.Random(config.seed)

    countries = generate_countries(rng)
    states = generate_states(rng)

    cities = generate_cities(
        rng,
        config,
    )

    help_categories = generate_help_categories(rng)

    users = generate_users(
        rng,
        config,
        cities,
    )

    volunteer_details = generate_volunteer_details(
        rng,
        config,
        users,
    )

    user_skills = generate_user_skills(
        rng,
        config,
        users,
        help_categories,
    )

    organizations = generate_organizations(
        rng,
        config,
        cities,
    )

    user_locations = generate_user_locations(
        rng,
        config,
        users,
        cities,
    )

    volunteer_locations = generate_volunteer_locations(
        rng,
        config,
        volunteer_details,
        users,
        cities,
    )

    return {
        "countries": countries,
        "states": states,
        "cities": cities,
        "users": users,
        "volunteer_details": volunteer_details,
        "user_skills": user_skills,
        "volunteer_locations": volunteer_locations,
        "user_locations": user_locations,
        "help_categories": help_categories,
        "organizations": organizations,
    }