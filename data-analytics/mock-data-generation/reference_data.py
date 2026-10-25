"""Loads the real reference data that generated rows must stay consistent with.

Country, state and help-category values come from database/lookup_tables/,
which is the data already loaded into the Saayam database. Reusing it is what
guarantees that generated foreign keys resolve against production lookups
instead of against invented codes.

Cities are not present in lookup_tables/, so reference/cities_seed.csv holds a
curated set of real cities with approximate centroid coordinates, keyed by
(country_id, state_code) so it resolves to real state_id values at load time.
"""

from typing import Dict, List, NamedTuple

import config
from utils import read_csv


class City(NamedTuple):
    city_id: int
    state_id: str
    country_id: int
    city_name: str
    latitude: float
    longitude: float


class ReferenceData(NamedTuple):
    countries: List[Dict[str, str]]
    states: List[Dict[str, str]]
    help_categories: List[Dict[str, str]]
    cities: List[City]
    # Cities grouped by the state they belong to, for coherent placement.
    cities_by_state: Dict[str, List[City]]
    country_by_id: Dict[int, Dict[str, str]]
    state_by_id: Dict[str, Dict[str, str]]


def _strip(value: str) -> str:
    """lookup_tables CSVs quote values and use the literal NULL for empties."""
    if value is None:
        return ""
    value = value.strip().strip('"')
    return "" if value == "NULL" else value


def load() -> ReferenceData:
    countries = [
        {
            "country_id": int(_strip(row["country_id"])),
            "country_name": _strip(row["country_name"]),
            "phone_code": _strip(row["phone_code"]),
            "country_code": _strip(row["country_code"]),
            "is_eu_member": _strip(row["is_eu_member"]).lower() == "true",
        }
        for row in read_csv(config.COUNTRY_LOOKUP)
    ]

    all_states = [
        {
            "state_id": _strip(row["state_id"]),
            "country_id": int(_strip(row["country_id"])),
            "state_name": _strip(row["state_name"]),
            "state_code": _strip(row["state_code"]),
        }
        for row in read_csv(config.STATE_LOOKUP)
    ]

    if config.STATE_SCOPE_ALL:
        states = all_states
    else:
        focus = set(config.FOCUS_COUNTRY_IDS)
        states = [s for s in all_states if s["country_id"] in focus]

    help_categories = [
        {
            "cat_id": _strip(row["cat_id"]),
            "cat_name": _strip(row["cat_name"]),
            "cat_desc": _strip(row["cat_desc"]),
        }
        for row in read_csv(config.HELP_CATEGORY_LOOKUP)
    ]

    # (country_id, state_code) -> state_id, so the seed never hardcodes ids.
    state_id_by_code = {
        (s["country_id"], s["state_code"]): s["state_id"]
        for s in states
        if s["state_code"]
    }

    cities: List[City] = []
    unresolved: List[str] = []
    next_city_id = 1
    for row in read_csv(config.REFERENCE_DIR / "cities_seed.csv"):
        country_id = int(row["country_id"])
        key = (country_id, row["state_code"])
        state_id = state_id_by_code.get(key)
        if state_id is None:
            unresolved.append(f"{country_id}/{row['state_code']}/{row['city_name']}")
            continue
        cities.append(
            City(
                city_id=next_city_id,
                state_id=state_id,
                country_id=country_id,
                city_name=row["city_name"],
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
            )
        )
        next_city_id += 1

    if unresolved:
        raise ValueError(
            "cities_seed.csv rows do not resolve to a state in the lookup data: "
            + ", ".join(unresolved)
        )

    if config.CITY_ROWS is not None:
        cities = cities[: config.CITY_ROWS]

    cities_by_state: Dict[str, List[City]] = {}
    for city in cities:
        cities_by_state.setdefault(city.state_id, []).append(city)

    return ReferenceData(
        countries=countries,
        states=states,
        help_categories=help_categories,
        cities=cities,
        cities_by_state=cities_by_state,
        country_by_id={c["country_id"]: c for c in countries},
        state_by_id={s["state_id"]: s for s in states},
    )
