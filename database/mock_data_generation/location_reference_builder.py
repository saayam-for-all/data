"""Auto-build location_reference.csv from real geodata + repo lookup IDs."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List


REAL_LOCATION_SEEDS = [
    {"country_name": "UNITED_STATES_OF_AMERICA", "state_name": "ILLINOIS", "city_name": "Chicago", "time_zone": "America/Chicago", "last_location": "Chicago, IL"},
    {"country_name": "UNITED_STATES_OF_AMERICA", "state_name": "ILLINOIS", "city_name": "Aurora", "time_zone": "America/Chicago", "last_location": "Aurora, IL"},
    {"country_name": "UNITED_STATES_OF_AMERICA", "state_name": "ILLINOIS", "city_name": "Naperville", "time_zone": "America/Chicago", "last_location": "Naperville, IL"},
    {"country_name": "UNITED_STATES_OF_AMERICA", "state_name": "CALIFORNIA", "city_name": "Los Angeles", "time_zone": "America/Los_Angeles", "last_location": "Los Angeles, CA"},
    {"country_name": "UNITED_STATES_OF_AMERICA", "state_name": "CALIFORNIA", "city_name": "San Diego", "time_zone": "America/Los_Angeles", "last_location": "San Diego, CA"},
    {"country_name": "UNITED_STATES_OF_AMERICA", "state_name": "CALIFORNIA", "city_name": "San Francisco", "time_zone": "America/Los_Angeles", "last_location": "San Francisco, CA"},
    {"country_name": "UNITED_STATES_OF_AMERICA", "state_name": "NEW_YORK", "city_name": "New York", "time_zone": "America/New_York", "last_location": "New York, NY"},
    {"country_name": "UNITED_STATES_OF_AMERICA", "state_name": "WASHINGTON", "city_name": "Seattle", "time_zone": "America/Los_Angeles", "last_location": "Seattle, WA"},
    {"country_name": "UNITED_STATES_OF_AMERICA", "state_name": "TEXAS", "city_name": "Dallas", "time_zone": "America/Chicago", "last_location": "Dallas, TX"},
    {"country_name": "UNITED_STATES_OF_AMERICA", "state_name": "TEXAS", "city_name": "Houston", "time_zone": "America/Chicago", "last_location": "Houston, TX"},
    {"country_name": "UNITED_STATES_OF_AMERICA", "state_name": "FLORIDA", "city_name": "Miami", "time_zone": "America/New_York", "last_location": "Miami, FL"},
    {"country_name": "INDIA", "state_name": "MAHARASHTRA", "city_name": "Mumbai", "time_zone": "Asia/Kolkata", "last_location": "Mumbai, Maharashtra"},
    {"country_name": "INDIA", "state_name": "DELHI", "city_name": "New Delhi", "time_zone": "Asia/Kolkata", "last_location": "New Delhi, Delhi"},
    {"country_name": "INDIA", "state_name": "KARNATAKA", "city_name": "Bengaluru", "time_zone": "Asia/Kolkata", "last_location": "Bengaluru, Karnataka"},
    {"country_name": "INDIA", "state_name": "TAMIL_NADU", "city_name": "Chennai", "time_zone": "Asia/Kolkata", "last_location": "Chennai, Tamil Nadu"},
    {"country_name": "CANADA", "state_name": "ONTARIO", "city_name": "Toronto", "time_zone": "America/Toronto", "last_location": "Toronto, ON"},
    {"country_name": "CANADA", "state_name": "QUEBEC", "city_name": "Montreal", "time_zone": "America/Toronto", "last_location": "Montreal, QC"},
    {"country_name": "CANADA", "state_name": "BRITISH_COLUMBIA", "city_name": "Vancouver", "time_zone": "America/Vancouver", "last_location": "Vancouver, BC"},
]


def ensure_location_reference(lookup_dir: Path) -> Path:
    """Create location_reference.csv if it does not already exist."""
    lookup_dir = Path(lookup_dir)
    output_path = lookup_dir / "location_reference.csv"

    if output_path.exists():
        return output_path

    state_rows = _read_csv(lookup_dir / "state.csv")
    country_rows = _read_csv(lookup_dir / "country.csv")

    state_map = _build_state_map(state_rows)
    country_map = _build_country_map(country_rows)

    rows = _build_rows(state_map, country_map)
    _write_csv(output_path, rows)

    return output_path


def _read_csv(path: Path) -> List[dict]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {
                str(k).strip(): ("" if v is None else str(v).strip())
                for k, v in row.items()
            }
            for row in reader
        ]


def _normalize(value: str) -> str:
    return str(value).strip().upper()


def _build_state_map(state_rows: List[dict]) -> Dict[tuple, dict]:
    state_map: Dict[tuple, dict] = {}

    for row in state_rows:
        state_name = _normalize(row.get("state_name", ""))
        country_id = str(row.get("country_id", "")).strip()
        state_id = str(row.get("state_id", "")).strip()
        state_code = str(row.get("state_code", "")).strip()

        if not state_name or not country_id or not state_id:
            continue

        state_map[(country_id, state_name)] = {
            "state_id": state_id,
            "country_id": country_id,
            "state_name": state_name,
            "state_code": state_code,
        }

    return state_map


def _build_country_map(country_rows: List[dict]) -> Dict[str, dict]:
    country_map: Dict[str, dict] = {}

    for row in country_rows:
        country_name = _normalize(row.get("country_name", ""))
        country_id = str(row.get("country_id", "")).strip()

        if not country_name or not country_id:
            continue

        country_map[country_name] = {
            "country_id": country_id,
            "country_name": country_name,
        }

    return country_map


def _build_rows(state_map: Dict[tuple, dict], country_map: Dict[str, dict]) -> List[dict]:
    rows: List[dict] = []

    for seed in REAL_LOCATION_SEEDS:
        country_name = _normalize(seed["country_name"])
        state_name = _normalize(seed["state_name"])

        country = country_map.get(country_name)
        if not country:
            continue

        state = state_map.get((country["country_id"], state_name))
        if not state:
            continue

        rows.append(
            {
                "location_id": f'{state["state_id"]}::{seed["city_name"]}',
                "country_id": state["country_id"],
                "state_id": state["state_id"],
                "state_name": state["state_name"],
                "state_code": state["state_code"],
                "city_name": seed["city_name"],
                "time_zone": seed["time_zone"],
                "last_location": seed["last_location"],
            }
        )

    return rows


def _write_csv(path: Path, rows: List[dict]) -> None:
    fieldnames = [
        "location_id",
        "country_id",
        "state_id",
        "state_name",
        "state_code",
        "city_name",
        "time_zone",
        "last_location",
    ]

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)