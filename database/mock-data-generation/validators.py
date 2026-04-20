"""
validators.py
-------------
Post-generation referential integrity checks.

The pipeline calls ``validate_all`` after all CSVs have been written.
Each check verifies that every FK column in a generated table contains
only values that exist in the referenced parent table's output CSV.

Violations are collected and printed as warnings — they do not halt the
pipeline because some real-world edge cases (e.g. NULL-allowed FKs,
empty optional pools) are not fatal for mock data.
"""

from __future__ import annotations

import csv
from pathlib import Path

from relationship_resolver import FK_MAP, FKColumn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_pk_set(csv_path: Path, pk_col: str) -> set[str]:
    """Read all distinct values of ``pk_col`` from a CSV file.

    Args:
        csv_path: Path to the CSV file.
        pk_col:   Column name to extract as the PK pool.

    Returns:
        Set of non-empty string values found in that column.
        Returns an empty set if the file does not exist.
    """
    if not csv_path.exists():
        return set()
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or pk_col not in reader.fieldnames:
            return set()
        return {row[pk_col].strip() for row in reader if row[pk_col].strip()}


# SQL null tokens that CSV exports write as plain text.  These must be
# treated as absent values, not as FK values to validate.
_SQL_NULL_TOKENS: frozenset[str] = frozenset({"null", "none", "na", "n/a", "nil"})


def _is_null_token(value: str) -> bool:
    """Return True if *value* represents a SQL / CSV null.

    Covers the empty string and common literal tokens (NULL, None, NA …)
    that database export tools write in place of a real NULL cell.

    Args:
        value: Raw cell value already stripped of surrounding whitespace.

    Returns:
        ``True`` when the value should be treated as absent / NULL.
    """
    return not value or value.lower() in _SQL_NULL_TOKENS


def _load_fk_values(csv_path: Path, fk_col: str) -> list[str]:
    """Read all non-null values of ``fk_col`` from a CSV file (including duplicates).

    Empty strings and SQL null tokens (``NULL``, ``None``, etc.) are excluded
    because they represent nullable FK columns and carry no referential
    constraint.

    Args:
        csv_path: Path to the CSV file.
        fk_col:   Column name to extract FK values from.

    Returns:
        List of non-null string values in that column.
        Returns an empty list if the file does not exist.
    """
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or fk_col not in reader.fieldnames:
            return []
        return [
            row[fk_col].strip()
            for row in reader
            if not _is_null_token(row[fk_col].strip())
        ]


# ---------------------------------------------------------------------------
# Violation data class
# ---------------------------------------------------------------------------


class Violation:
    """Represents a single referential integrity violation."""

    def __init__(
        self,
        child_table: str,
        child_col: str,
        parent_table: str,
        parent_col: str,
        bad_values: set[str],
        total_fk_rows: int,
    ) -> None:
        self.child_table = child_table
        self.child_col = child_col
        self.parent_table = parent_table
        self.parent_col = parent_col
        self.bad_values = bad_values
        self.total_fk_rows = total_fk_rows

    @property
    def count(self) -> int:
        return len(self.bad_values)

    def __str__(self) -> str:
        pct = (self.count / self.total_fk_rows * 100) if self.total_fk_rows else 0
        sample = sorted(self.bad_values)[:5]
        return (
            f"  VIOLATION  {self.child_table}.{self.child_col}"
            f" → {self.parent_table}.{self.parent_col}"
            f"  ({self.count}/{self.total_fk_rows} rows, {pct:.1f}%)"
            f"  sample bad values: {sample}"
        )


# ---------------------------------------------------------------------------
# Core validation logic
# ---------------------------------------------------------------------------


def validate_fk(fk: FKColumn, output_dir: Path) -> Violation | None:
    """Check one FK relationship for dangling references.

    Loads the parent PK set and the child FK column values from their
    respective CSVs in ``output_dir`` and reports any child values that
    are not present in the parent set.

    Null-token FK values are pre-filtered by ``_load_fk_values`` and skipped.

    Args:
        fk:         The FK relationship descriptor.
        output_dir: Directory containing all generated and copied CSVs.

    Returns:
        A :class:`Violation` if any bad values are found, otherwise ``None``.
    """
    parent_csv = output_dir / f"{fk.parent_table}.csv"
    child_csv = output_dir / f"{fk.child_table}.csv"

    if not parent_csv.exists():
        return None   # parent table not generated yet; skip silently
    if not child_csv.exists():
        return None

    parent_pks = _load_pk_set(parent_csv, fk.parent_col)
    if not parent_pks:
        return None   # parent has no data; no constraint to check

    child_fk_values = _load_fk_values(child_csv, fk.child_col)
    if not child_fk_values:
        return None

    bad = {v for v in child_fk_values if v not in parent_pks}
    if not bad:
        return None

    return Violation(
        child_table=fk.child_table,
        child_col=fk.child_col,
        parent_table=fk.parent_table,
        parent_col=fk.parent_col,
        bad_values=bad,
        total_fk_rows=len(child_fk_values),
    )


def validate_pk_uniqueness(table: str, pk_col: str, output_dir: Path) -> list[str]:
    """Check that a single-column PK has no duplicate values.

    Args:
        table:      Table name.
        pk_col:     PK column to check.
        output_dir: Directory containing CSVs.

    Returns:
        List of duplicate PK values found (empty if all unique).
    """
    csv_path = output_dir / f"{table}.csv"
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or pk_col not in reader.fieldnames:
            return []
        seen: set[str] = set()
        dupes: list[str] = []
        for row in reader:
            val = row[pk_col].strip()
            if val in seen:
                dupes.append(val)
            seen.add(val)
    return dupes


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def validate_all(output_dir: Path, verbose: bool = True) -> int:
    """Run all FK and PK uniqueness checks against the CSVs in ``output_dir``.

    Checks every FK in :data:`relationship_resolver.FK_MAP` plus PK
    uniqueness for a selection of high-traffic tables.

    Args:
        output_dir: Directory containing all generated CSV files.
        verbose:    If ``True``, print per-check results to stdout.

    Returns:
        Total number of violations found (0 means clean).
    """
    violations: list[Violation] = []
    pk_errors: dict[str, list[str]] = {}

    # --- FK checks ---
    for fk in FK_MAP:
        v = validate_fk(fk, output_dir)
        if v:
            violations.append(v)

    # --- PK uniqueness for key tables ---
    pk_checks: list[tuple[str, str]] = [
        ("users",            "user_id"),
        ("request",          "req_id"),
        ("organizations",    "org_id"),
        ("meetings",         "meeting_id"),
        ("volunteer_applications", "user_id"),
        ("volunteer_details",      "user_id"),
        # user_skills has a composite PK (user_id, cat_id) — not checked here
        # because validate_pk_uniqueness only handles single-column PKs.
        ("volunteers_assigned", "volunteers_assigned_id"),
        ("request_comments", "comment_id"),
    ]
    for table, pk_col in pk_checks:
        dupes = validate_pk_uniqueness(table, pk_col, output_dir)
        if dupes:
            pk_errors[f"{table}.{pk_col}"] = dupes[:10]

    # --- Report ---
    total = len(violations) + sum(len(v) for v in pk_errors.values())

    if verbose:
        if not violations and not pk_errors:
            print("  validation  all FK and PK checks passed")
        else:
            for v in violations:
                print(str(v))
            for key, dupes in pk_errors.items():
                print(f"  DUPLICATE PK  {key}  sample: {dupes[:5]}")

    return total


# ---------------------------------------------------------------------------
# Row-count summary (not a validation, but useful alongside it)
# ---------------------------------------------------------------------------


def row_count_summary(output_dir: Path) -> dict[str, int]:
    """Return a mapping of table name → row count for all CSVs in output_dir.

    Args:
        output_dir: Directory containing generated CSV files.

    Returns:
        Dict mapping table name (without ``.csv``) to number of data rows.
    """
    summary: dict[str, int] = {}
    for csv_path in sorted(output_dir.glob("*.csv")):
        table = csv_path.stem
        with csv_path.open("r", encoding="utf-8", newline="") as fh:
            row_count = sum(1 for _ in fh) - 1   # minus header
        summary[table] = max(row_count, 0)
    return summary
