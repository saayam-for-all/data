"""Generates the countries table."""

from typing import Dict, List

from reference_data import COUNTRIES
from utils import format_ts, random_datetime_in_window


def generate_countries() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for country_id, (name, phone_code, country_code, is_eu) in enumerate(COUNTRIES, start=1):
        rows.append({
            "country_id": country_id,
            "country_name": name,
            "phone_code": phone_code,
            "country_code": country_code,
            "last_updated_at": format_ts(random_datetime_in_window()),
            "is_eu_member": str(is_eu).upper(),
        })
    return rows


def country_lookup(country_rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    """country_code -> row, for other generators to join against."""
    return {row["country_code"]: row for row in country_rows}
