"""Generates the cities table. cities.state_id is NOT NULL, so every row
must reference a real generated states.csv row (state_id, not the bare
state_code)."""

from typing import Dict, List

from reference_data import OTHER_CITIES, US_EXTRA_CITIES, US_STATE_CAPITALS
from utils import format_ts, random_datetime_in_window


def generate_cities(state_by_id: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    city_id = 1

    for state_code, (city_name, lat, lon) in US_STATE_CAPITALS.items():
        state_id = f"US-{state_code}"
        rows.append(_city_row(city_id, state_id, city_name, lat, lon))
        city_id += 1

        if state_code in US_EXTRA_CITIES:
            extra_name, extra_lat, extra_lon = US_EXTRA_CITIES[state_code]
            rows.append(_city_row(city_id, state_id, extra_name, extra_lat, extra_lon))
            city_id += 1

    for (country_code, state_code), city_list in OTHER_CITIES.items():
        state_id = f"{country_code}-{state_code}"
        for city_name, lat, lon in city_list:
            rows.append(_city_row(city_id, state_id, city_name, lat, lon))
            city_id += 1

    return rows


def _city_row(city_id: int, state_id: str, city_name: str, lat: float, lon: float) -> Dict[str, str]:
    return {
        "city_id": city_id,
        "state_id": state_id,
        "city_name": city_name,
        "lattitude": f"{lat:.6f}",
        "longitude": f"{lon:.6f}",
        "last_updated_at": format_ts(random_datetime_in_window()),
    }


def cities_by_state(city_rows: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    """state_id -> [city rows], for other generators to pick a consistent
    city for a given state."""
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for row in city_rows:
        grouped.setdefault(row["state_id"], []).append(row)
    return grouped
