"""Generators for the four reference tables: countries, states, cities,
help_categories.

These carry real reference values (country/state/category names are not
personal data, and the issue's own example of a correct row is
United States -> California -> San Jose). Only the timestamps are generated.
"""

import random
from typing import Dict, List

from reference_data import ReferenceData
from utils import format_bool, format_timestamp, random_datetime

COUNTRY_FIELDS = [
    "country_id",
    "country_name",
    "phone_code",
    "country_code",
    "last_updated_at",
    "is_eu_member",
]

STATE_FIELDS = [
    "state_id",
    "country_id",
    "state_name",
    "state_code",
    "last_updated_at",
]

# NOTE: `lattitude` is spelled that way in the schema (ddl_city.sql and the
# wiki's "Table after changes" block). Do not correct it here -- the CSV header
# has to match the column name for a COPY to succeed.
CITY_FIELDS = [
    "city_id",
    "state_id",
    "city_name",
    "lattitude",
    "longitude",
    "last_updated_at",
]

HELP_CATEGORY_FIELDS = ["cat_id", "cat_name", "cat_desc", "last_updated_at"]


def generate_countries(reference: ReferenceData, window) -> List[Dict[str, str]]:
    start, end = window
    rows = []
    for country in reference.countries:
        rows.append(
            {
                "country_id": country["country_id"],
                "country_name": country["country_name"],
                "phone_code": country["phone_code"],
                "country_code": country["country_code"],
                "last_updated_at": format_timestamp(random_datetime(start, end)),
                "is_eu_member": format_bool(country["is_eu_member"]),
            }
        )
    return rows


def generate_states(reference: ReferenceData, window) -> List[Dict[str, str]]:
    start, end = window
    rows = []
    for state in reference.states:
        rows.append(
            {
                "state_id": state["state_id"],
                "country_id": state["country_id"],
                "state_name": state["state_name"],
                "state_code": state["state_code"],
                "last_updated_at": format_timestamp(random_datetime(start, end)),
            }
        )
    return rows


def generate_cities(reference: ReferenceData, window) -> List[Dict[str, str]]:
    start, end = window
    rows = []
    for city in reference.cities:
        rows.append(
            {
                "city_id": city.city_id,
                "state_id": city.state_id,
                "city_name": city.city_name,
                "lattitude": f"{city.latitude:.6f}",
                "longitude": f"{city.longitude:.6f}",
                "last_updated_at": format_timestamp(random_datetime(start, end)),
            }
        )
    return rows


def generate_help_categories(reference: ReferenceData, window) -> List[Dict[str, str]]:
    start, end = window
    rows = []
    for category in reference.help_categories:
        rows.append(
            {
                "cat_id": category["cat_id"],
                "cat_name": category["cat_name"],
                "cat_desc": category["cat_desc"],
                "last_updated_at": format_timestamp(random_datetime(start, end)),
            }
        )
    return rows
