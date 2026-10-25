"""Shared paths and the dated Virginia table-schema contract."""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_LOOKUP = BASE / "reference_data"
SCHEMA = json.loads((BASE / "schema.json").read_text(encoding="utf-8"))
EXPECTED_HEADERS = {filename: list(columns) for filename, columns in SCHEMA.items()}
