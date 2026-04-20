"""
schema_loader.py
----------------
Reads db_info.json and exposes structured metadata about every table.

All other pipeline modules import from here instead of parsing db_info.json
directly, so the JSON structure is normalised in one place.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------


class ColumnMeta(NamedTuple):
    """Metadata for a single column as extracted from db_info.json."""

    name: str
    raw_type: str        # original type string, e.g. "character varying (255)"
    base_type: str       # normalised single word: "varchar", "integer", etc.
    is_pk: bool


class TableMeta(NamedTuple):
    """Metadata for a single table."""

    name: str
    columns: list[ColumnMeta]
    pk_columns: list[str]    # ordered list of PK column names


# ---------------------------------------------------------------------------
# Type normalisation
# ---------------------------------------------------------------------------

# Maps fragments found in raw type strings → normalised base type token.
# Checked in order; first match wins.
_TYPE_MAP: list[tuple[str, str]] = [
    ("character varying", "varchar"),
    ("character",         "char"),
    ("timestamp",         "timestamp"),
    ("bigint",            "bigint"),
    ("smallint",          "smallint"),  # must come before "int"
    ("small int",         "smallint"),
    ("integer",           "integer"),
    ("int",               "integer"),
    ("numeric",           "numeric"),
    ("boolean",           "boolean"),
    ("bool",              "boolean"),
    ("text",              "text"),
    ("jsonb",             "jsonb"),
    ("json",              "json"),
    ("date",              "date"),
    ("geography",         "geography"),
    ("timest",            "timestamp"),  # truncated value in db_info.json
    ("enum",              "enum"),
    ("user-defined",      "user_defined"),
    ("user defined",      "user_defined"),
]


def _normalise_type(raw: str) -> str:
    """Return a normalised single-word type token from a raw db_info type string.

    Args:
        raw: Type string from db_info.json, e.g. ``"character varying (255)"``.

    Returns:
        A lowercase single-word token such as ``"varchar"``, ``"integer"``,
        or ``"text"``.  Falls back to ``"unknown"`` if no pattern matches.
    """
    lower = raw.strip().lower()
    for fragment, token in _TYPE_MAP:
        if fragment in lower:
            return token
    return "unknown"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_schema(db_info_path: Path) -> dict[str, TableMeta]:
    """Parse db_info.json and return a mapping of table name → TableMeta.

    The function normalises raw type strings and collects declared primary-key
    columns.  Tables with no ``primary_key: true`` column are still loaded;
    callers should consult ``relationship_resolver.py`` for the authoritative
    PK list.

    Args:
        db_info_path: Absolute path to ``db_info.json``.

    Returns:
        Dict mapping each table name to a :class:`TableMeta` instance.

    Raises:
        FileNotFoundError: If ``db_info_path`` does not exist.
        KeyError: If the JSON is missing the expected ``"tables"`` key.
        ValueError: If a table entry has no ``"columns"`` list.
    """
    with db_info_path.open("r", encoding="utf-8") as fh:
        raw: dict = json.load(fh)

    if "tables" not in raw:
        raise KeyError(f"'tables' key missing in {db_info_path}")

    schema: dict[str, TableMeta] = {}

    for table_name, table_def in raw["tables"].items():
        raw_columns: list[dict] = table_def.get("columns")
        if not raw_columns:
            raise ValueError(
                f"Table '{table_name}' has no columns in {db_info_path}"
            )

        cols: list[ColumnMeta] = []
        pk_cols: list[str] = []

        for col_def in raw_columns:
            col_name: str = col_def["name"]
            raw_type: str = col_def.get("type", "unknown")
            is_pk: bool = bool(col_def.get("primary_key", False))
            base_type: str = _normalise_type(raw_type)

            cols.append(ColumnMeta(
                name=col_name,
                raw_type=raw_type,
                base_type=base_type,
                is_pk=is_pk,
            ))
            if is_pk:
                pk_cols.append(col_name)

        schema[table_name] = TableMeta(
            name=table_name,
            columns=cols,
            pk_columns=pk_cols,
        )

    return schema

