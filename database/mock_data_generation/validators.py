"""Validation helpers for generated output."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from .schema_parser import ParsedSchema


# Calamity (iscalamity=True) requires priority >= HIGH (id=2).
_PRIORITY_HIGH = 2


@dataclass(slots=True)
class ValidationResult:
    table_name: str
    passed: bool
    errors: List[str]


def validate_csv_outputs(
    schema: ParsedSchema,
    output_dir: Path,
    selected_tables: List[str],
    parent_value_pools: Dict[str, List[str]],
    lookup_value_pools: Dict[str, List[str]],
) -> List[ValidationResult]:
    results: List[ValidationResult] = []

    for table_name in selected_tables:
        table = schema.require_table(table_name)
        path = output_dir / f"{table_name}.csv"
        errors: List[str] = []

        if not path.exists():
            results.append(ValidationResult(table_name, False, [f"Missing file: {path}"]))
            continue

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames or []
            if header != table.column_order:
                errors.append(
                    f"Header mismatch for {table_name}: expected {table.column_order}, got {header}"
                )

            # Index columns by name for quick metadata lookup.
            column_meta = {column.name: column for column in table.columns}

            # Track per-column duplicate counts for uniqueness checks.
            email_seen: Dict[str, int] = defaultdict(int)
            length_violations: Dict[str, int] = defaultdict(int)
            calamity_low_priority = 0

            for row_number, row in enumerate(reader, start=2):
                for column in table.columns:
                    value = row.get(column.name, "")

                    if column.is_primary_key and value == "":
                        errors.append(f"{table_name}:{row_number} primary key '{column.name}' is blank")

                    if column.foreign_key and value != "":
                        ref_table, _ = column.foreign_key.split(".", maxsplit=1)
                        valid_pool = parent_value_pools.get(ref_table) or lookup_value_pools.get(ref_table) or []
                        if str(value) not in {str(item) for item in valid_pool}:
                            errors.append(
                                f"{table_name}:{row_number} invalid FK '{column.name}'={value} -> {column.foreign_key}"
                            )

                    # Length check — applies to columns with a declared max_length.
                    if column.max_length and value and len(str(value)) > column.max_length:
                        length_violations[column.name] += 1

                # Email uniqueness on users.
                if table_name == "users":
                    email = str(row.get("primary_email_address", "")).strip()
                    if email:
                        email_seen[email] += 1

                # Calamity ⇒ priority ≥ HIGH on request.
                if table_name == "request":
                    is_calamity = str(row.get("iscalamity", "")).strip().lower() in {"true", "1"}
                    if is_calamity:
                        try:
                            priority = int(row.get("req_priority_id", 0) or 0)
                        except ValueError:
                            priority = 0
                        if priority < _PRIORITY_HIGH:
                            calamity_low_priority += 1

            # Collapse per-column violations into one summary line each
            # so a single noisy column doesn't blow past the 100-error cap.
            for column_name, count in sorted(length_violations.items()):
                limit = column_meta[column_name].max_length
                errors.append(
                    f"{table_name}: {count} row(s) exceed max_length {limit} on column '{column_name}'"
                )

            duplicate_emails = {e: c for e, c in email_seen.items() if c > 1}
            if duplicate_emails:
                total_dupe_rows = sum(duplicate_emails.values())
                errors.append(
                    f"{table_name}: {len(duplicate_emails)} duplicate email value(s) "
                    f"across {total_dupe_rows} rows in 'primary_email_address'"
                )

            if calamity_low_priority:
                errors.append(
                    f"{table_name}: {calamity_low_priority} row(s) have iscalamity=True with priority < HIGH"
                )

        results.append(ValidationResult(table_name, len(errors) == 0, errors[:100]))

    return results
