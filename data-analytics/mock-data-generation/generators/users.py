"""Generator for the users table.

Every value that identifies a person is synthetic: names come from Faker's
generated name pools, e-mail domains are the RFC 2606 reserved example.*
domains, and phone numbers use the 555 reserved-fiction block. Only the
geography (country, state, city, coordinates) is real, which is what issue #301
requires for country -> state -> city -> ZIP coherence.
"""

import random
from datetime import timedelta
from typing import Dict, List, NamedTuple

from faker import Faker

import config
import localization
from reference_data import City, ReferenceData
from utils import (
    format_bool,
    format_date,
    format_point,
    format_timestamp,
    later_than,
    random_datetime,
    user_id as make_user_id,
    weighted_choices,
    NULL,
)

USER_FIELDS = [
    "user_id",
    "state_id",
    "country_id",
    "user_status_id",
    "full_name",
    "first_name",
    "middle_name",
    "last_name",
    "primary_email_address",
    "primary_phone_number",
    "addr_ln1",
    "addr_ln2",
    "addr_ln3",
    "city_name",
    "zip_code",
    "last_location",
    "last_updated_at",
    "time_zone",
    "profile_picture_path",
    "gender",
    "language_1",
    "language_2",
    "language_3",
    "promotion_wizard_stage",
    "promotion_wizard_last_updated_at",
    "external_auth_provider",
    "dob",
    "is_eu",
]

GENDERS = ["MALE", "FEMALE", "NON_BINARY", "PREFER_NOT_TO_SAY"]
AUTH_PROVIDERS = ["COGNITO", "GOOGLE", "FACEBOOK", "APPLE"]
EXAMPLE_DOMAINS = ["example.com", "example.org", "example.net"]


class UserProfile(NamedTuple):
    """Internal record threaded through the dependent generators.

    `registered_at` is not a users column -- the table only has
    last_updated_at -- but downstream rows must not predate the account, so it
    is carried in memory to keep timestamps ordered.
    """

    user_id: str
    country_id: int
    state_id: str
    state_code: str
    city: City
    registered_at: object
    last_updated_at: object


def _fakers() -> Dict[int, Faker]:
    fakers = {}
    for country_id, locale in localization.FAKER_LOCALE.items():
        faker = Faker(locale)
        faker.seed_instance(config.RANDOM_SEED + country_id)
        fakers[country_id] = faker
    return fakers


def _email(first: str, last: str, index: int) -> str:
    handle = f"{first}.{last}".lower()
    handle = "".join(ch for ch in handle if ch.isalnum() or ch == ".")
    return f"{handle}{index}@{random.choice(EXAMPLE_DOMAINS)}"


def generate_users(reference: ReferenceData, window, count: int):
    """Return (csv_rows, profiles)."""
    start, end = window
    fakers = _fakers()

    # Only place users in states that have curated cities, so every user has a
    # real city and plausible coordinates.
    states_with_cities = {}
    for state_id, cities in reference.cities_by_state.items():
        state = reference.state_by_id[state_id]
        states_with_cities.setdefault(state["country_id"], []).append(state_id)

    country_ids = weighted_choices(
        {k: v for k, v in config.COUNTRY_WEIGHTS.items() if k in states_with_cities},
        count,
    )

    rows: List[Dict[str, object]] = []
    profiles: List[UserProfile] = []

    for index, country_id in enumerate(country_ids, start=1):
        faker = fakers[country_id]
        country = reference.country_by_id[country_id]
        state_id = random.choice(states_with_cities[country_id])
        state = reference.state_by_id[state_id]
        city = random.choice(reference.cities_by_state[state_id])

        # Pick gender first so the generated given names agree with it.
        gender = random.choice(GENDERS)
        if gender == "MALE":
            given = faker.first_name_male
        elif gender == "FEMALE":
            given = faker.first_name_female
        else:
            given = faker.first_name

        first_name = given()
        last_name = faker.last_name()
        has_middle = random.random() < 0.35
        middle_name = given() if has_middle else NULL
        full_name = " ".join(
            part for part in [first_name, middle_name or "", last_name] if part
        )

        registered_at = random_datetime(start, end)
        last_updated_at = later_than(registered_at, end)

        # A user's recorded position sits inside their own city.
        latitude, longitude = city.latitude, city.longitude
        from utils import jitter_coordinate

        latitude, longitude = jitter_coordinate(latitude, longitude, 0.05)

        has_wizard = random.random() < 0.7
        promo_stage = random.randint(0, 5) if has_wizard else NULL
        promo_updated = (
            format_timestamp(later_than(registered_at, last_updated_at))
            if has_wizard
            else NULL
        )

        languages = random.sample(config.LANGUAGE_IDS, k=random.randint(1, 3))
        languages += [NULL] * (3 - len(languages))

        # secondary_address() is not implemented for every Faker locale, so
        # the unit/apartment line is built here instead.
        address_line_2 = (
            f"{random.choice(['Apt', 'Suite', 'Unit', 'Flat'])} "
            f"{random.randint(1, 450)}"
            if random.random() < 0.3
            else NULL
        )

        user = make_user_id(index)
        rows.append(
            {
                "user_id": user,
                "state_id": state_id,
                "country_id": country_id,
                "user_status_id": random.choice(config.USER_STATUS_IDS),
                "full_name": full_name,
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,
                "primary_email_address": _email(first_name, last_name, index),
                "primary_phone_number": localization.phone_number(
                    country["phone_code"]
                ),
                # street_address() bundles a unit number in some locales,
                # which would duplicate addr_ln2; build the line explicitly.
                "addr_ln1": f"{faker.building_number()} {faker.street_name()}",
                "addr_ln2": address_line_2,
                "addr_ln3": NULL,
                "city_name": city.city_name,
                "zip_code": localization.postal_code(country_id, state["state_code"]),
                "last_location": format_point(latitude, longitude),
                "last_updated_at": format_timestamp(last_updated_at),
                "time_zone": localization.time_zone(country_id, state["state_code"]),
                "profile_picture_path": (
                    f"s3://saayam-mock-profile-pictures/{user}.jpg"
                    if random.random() < 0.4
                    else NULL
                ),
                "gender": gender,
                "language_1": languages[0],
                "language_2": languages[1],
                "language_3": languages[2],
                "promotion_wizard_stage": promo_stage,
                "promotion_wizard_last_updated_at": promo_updated,
                "external_auth_provider": (
                    random.choice(AUTH_PROVIDERS) if random.random() < 0.8 else NULL
                ),
                "dob": format_date(
                    faker.date_of_birth(minimum_age=18, maximum_age=80)
                ),
                "is_eu": format_bool(country["is_eu_member"]),
            }
        )

        profiles.append(
            UserProfile(
                user_id=user,
                country_id=country_id,
                state_id=state_id,
                state_code=state["state_code"],
                city=city,
                registered_at=registered_at,
                last_updated_at=last_updated_at,
            )
        )

    return rows, profiles
