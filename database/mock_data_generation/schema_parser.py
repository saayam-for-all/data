"""Schema parsing utilities for db_info.json."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass(slots=True)
class ColumnMeta:
    name: str
    data_type: str
    is_nullable: bool = True
    max_length: Optional[int] = None
    is_primary_key: bool = False
    foreign_key: Optional[str] = None
    default: Any = None


@dataclass(slots=True)
class TableMeta:
    name: str
    columns: List[ColumnMeta] = field(default_factory=list)

    @property
    def primary_key(self) -> Optional[str]:
        for column in self.columns:
            if column.is_primary_key:
                return column.name
        return None

    @property
    def foreign_keys(self) -> Dict[str, str]:
        return {
            column.name: column.foreign_key
            for column in self.columns
            if column.foreign_key
        }

    @property
    def column_order(self) -> List[str]:
        return [column.name for column in self.columns]


@dataclass(slots=True)
class ParsedSchema:
    tables: Dict[str, TableMeta]

    def require_table(self, table_name: str) -> TableMeta:
        if table_name not in self.tables:
            raise KeyError(f"Table '{table_name}' was not found in schema")
        return self.tables[table_name]


class SchemaParser:
    """Parse db_info.json into normalized metadata."""

    def __init__(self, explicit_fk_map: Optional[Dict[str, Dict[str, str]]] = None):
        self.explicit_fk_map = explicit_fk_map or {}

    def parse(self, schema_path: Path) -> ParsedSchema:
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        raw_tables = self._extract_tables(data)

        parsed_tables: Dict[str, TableMeta] = {}
        for raw_name, raw_table in raw_tables.items():
            columns: List[ColumnMeta] = []
            for raw_column in self._extract_columns(raw_table):
                column_name = self._column_name(raw_column)
                data_type = str(
                    raw_column.get("data_type")
                    or raw_column.get("type")
                    or raw_column.get("column_type")
                    or "varchar"
                )
                is_pk = self._to_bool(
                    raw_column.get("is_primary_key", raw_column.get("primary_key", False)),
                    default=False,
                )
                nullable_value = (
                    raw_column.get("is_nullable")
                    if "is_nullable" in raw_column
                    else raw_column.get("nullable")
                )
                if nullable_value is None:
                    is_nullable = not is_pk
                else:
                    is_nullable = self._to_bool(nullable_value, default=not is_pk)

                max_length = (
                    raw_column.get("max_length")
                    or raw_column.get("character_maximum_length")
                    or self._extract_max_length(data_type)
                )

                columns.append(
                    ColumnMeta(
                        name=column_name,
                        data_type=data_type,
                        is_nullable=is_nullable,
                        max_length=int(max_length) if max_length not in (None, "") else None,
                        is_primary_key=is_pk,
                        foreign_key=self._extract_foreign_key(raw_name, column_name, raw_column),
                        default=raw_column.get("default"),
                    )
                )
            parsed_tables[raw_name] = TableMeta(name=raw_name, columns=columns)

        return ParsedSchema(tables=parsed_tables)

    @staticmethod
    def _extract_tables(data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("Unsupported db_info.json structure: expected top-level object")
        if isinstance(data.get("tables"), dict):
            return data["tables"]
        if isinstance(data.get("tables"), list):
            return {
                SchemaParser._table_name(item): item
                for item in data["tables"]
            }
        if all(isinstance(value, dict) for value in data.values()):
            return data
        raise ValueError("Unsupported db_info.json structure: could not find tables")

    @staticmethod
    def _table_name(raw_table: Dict[str, Any]) -> str:
        return str(
            raw_table.get("table_name")
            or raw_table.get("name")
            or raw_table.get("table")
        )

    @staticmethod
    def _extract_columns(raw_table: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        columns = raw_table.get("columns")
        if isinstance(columns, list):
            return columns
        if isinstance(columns, dict):
            return [
                dict({"column_name": name}, **value) if isinstance(value, dict) else {"column_name": name, "type": str(value)}
                for name, value in columns.items()
            ]
        raise ValueError(f"Unsupported table column structure for table: {raw_table}")

    @staticmethod
    def _column_name(raw_column: Dict[str, Any]) -> str:
        return str(
            raw_column.get("column_name")
            or raw_column.get("name")
            or raw_column.get("field_name")
        )

    def _extract_foreign_key(self, table_name: str, column_name: str, raw_column: Dict[str, Any]) -> Optional[str]:
        explicit = self.explicit_fk_map.get(table_name, {}).get(column_name)
        if explicit:
            return explicit

        fk = raw_column.get("foreign_key") or raw_column.get("references")
        if isinstance(fk, str) and "." in fk:
            return fk
        if isinstance(fk, dict):
            table = fk.get("table")
            column = fk.get("column")
            if table and column:
                return f"{table}.{column}"
        return None

    @staticmethod
    def _extract_max_length(data_type: str) -> Optional[int]:
        text = str(data_type).lower()
        if "character varying" not in text and not text.startswith("varchar") and not text.startswith("character(") and not text.startswith("char("):
            return None
        match = re.search(r"\((\d+)\)", text)
        return int(match.group(1)) if match else None

    @staticmethod
    def _to_bool(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "t", "1", "yes", "y"}:
            return True
        if text in {"false", "f", "0", "no", "n"}:
            return False
        return default
