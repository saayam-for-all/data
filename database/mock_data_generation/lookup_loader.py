"""Lookup table loading for foreign key generation."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .location_reference_builder import ensure_location_reference


@dataclass(slots=True)
class LookupTable:
    name: str
    id_column: str
    rows: List[dict]

    @property
    def ids(self) -> List[str]:
        return [
            str(row[self.id_column]).strip()
            for row in self.rows
            if row.get(self.id_column) not in (None, "")
        ]


class LookupLoader:
    """Load all lookup CSVs from a directory."""

    def __init__(self, id_column_overrides: Optional[Dict[str, str]] = None):
        self.id_column_overrides = {
            self._normalize_name(k): v
            for k, v in (id_column_overrides or {}).items()
        }

    def load(self, lookup_dir: Path) -> Dict[str, LookupTable]:
        lookup_tables: Dict[str, LookupTable] = {}
        lookup_dir = Path(lookup_dir)

        if not lookup_dir.exists():
            raise FileNotFoundError(f"Lookup directory not found: {lookup_dir}")

        # Auto-build location_reference.csv if missing
        ensure_location_reference(lookup_dir)

        for csv_path in sorted(lookup_dir.glob("*.csv")):
            name = self._normalize_name(csv_path.stem)
            rows = self._read_csv(csv_path)
            if not rows:
                continue

            id_column = (
                self.id_column_overrides.get(name)
                or self._infer_id_column(name, rows[0])
            )

            lookup_tables[name] = LookupTable(
                name=name,
                id_column=id_column,
                rows=rows,
            )

        return lookup_tables

    @staticmethod
    def _normalize_name(value: str) -> str:
        return str(value).strip().lower()

    @staticmethod
    def _read_csv(path: Path) -> List[dict]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            cleaned_rows: List[dict] = []

            for row in reader:
                cleaned_row = {
                    str(key).strip(): ("" if value is None else str(value).strip())
                    for key, value in row.items()
                }
                cleaned_rows.append(cleaned_row)

            return cleaned_rows

    def _infer_id_column(self, table_name: str, header_row: dict) -> str:
        headers = [str(col).strip() for col in header_row.keys()]
        normalized_headers = [col.lower() for col in headers]

        # explicit override already handled before this method

        exact_candidates = [
            f"{table_name}_id",
            f"{table_name[:-1]}_id" if table_name.endswith("s") else "",
            "cat_id",
            "field_id",
            "item_id",
            "type_id",
            "channel_id",
            "user_id",
            "org_id",
            "state_id",
            "country_id",
            "req_for_id",
            "req_islead_id",
            "req_priority_id",
            "req_status_id",
            "req_type_id",
            "user_status_id",
            "user_category_id",
            "location_id",
        ]

        for candidate in exact_candidates:
            if not candidate:
                continue
            if candidate.lower() in normalized_headers:
                idx = normalized_headers.index(candidate.lower())
                return headers[idx]

        suffix_candidates = [
            headers[idx]
            for idx, col in enumerate(normalized_headers)
            if col.endswith("_id")
        ]
        if suffix_candidates:
            return suffix_candidates[0]

        return headers[0]


def build_state_country_pairs(state_lookup: LookupTable) -> List[dict]:
    """Create valid country/state pairs directly from the state lookup table."""
    pairs: List[dict] = []

    for row in state_lookup.rows:
        state_id = row.get("state_id") or row.get("id")
        country_id = row.get("country_id")
        state_name = row.get("state_name") or row.get("name") or ""
        state_code = row.get("state_code") or ""

        if state_id in (None, "") or country_id in (None, ""):
            continue

        pairs.append(
            {
                "state_id": str(state_id).strip(),
                "country_id": str(country_id).strip(),
                "state_name": str(state_name).strip(),
                "state_code": str(state_code).strip(),
            }
        )

    return pairs


def build_location_reference_rows(location_lookup: LookupTable) -> List[dict]:
    """Return normalized location reference rows."""
    rows: List[dict] = []

    for row in location_lookup.rows:
        country_id = row.get("country_id")
        state_id = row.get("state_id")
        city_name = row.get("city_name")
        time_zone = row.get("time_zone")
        last_location = row.get("last_location")

        if not all([country_id, state_id, city_name, time_zone, last_location]):
            continue

        rows.append(
            {
                "country_id": str(country_id).strip(),
                "state_id": str(state_id).strip(),
                "city_name": str(city_name).strip(),
                "time_zone": str(time_zone).strip(),
                "last_location": str(last_location).strip(),
            }
        )

    return rows