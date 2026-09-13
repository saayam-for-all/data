"""Generates the states table. states.country_id is NOT NULL, so every row
must reference a real generated countries.csv row."""

from typing import Dict, List

from reference_data import OTHER_STATES, US_STATES
from utils import format_ts, random_datetime_in_window


def generate_states(country_by_code: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    for state_code, state_name in US_STATES:
        country = country_by_code["US"]
        rows.append(_state_row(country_code="US", state_code=state_code,
                                state_name=state_name, country_id=country["country_id"]))

    for country_code, state_code, state_name in OTHER_STATES:
        country = country_by_code[country_code]
        rows.append(_state_row(country_code=country_code, state_code=state_code,
                                state_name=state_name, country_id=country["country_id"]))

    return rows


def _state_row(country_code: str, state_code: str, state_name: str, country_id: str) -> Dict[str, str]:
    return {
        "state_id": f"{country_code}-{state_code}",
        "country_id": country_id,
        "state_name": state_name,
        "state_code": state_code,
        "last_updated_at": format_ts(random_datetime_in_window()),
    }


def state_lookup(state_rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    """state_id -> row, for other generators to join against."""
    return {row["state_id"]: row for row in state_rows}
