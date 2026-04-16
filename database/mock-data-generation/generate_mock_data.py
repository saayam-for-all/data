"""
generate_mock_data.py
---------------------
Main orchestrator for the metadata-driven mock-data generation pipeline.

Usage::

    python generate_mock_data.py --mode dev
    python generate_mock_data.py --mode full
    python generate_mock_data.py --mode full --seed 42
    python generate_mock_data.py --validate-only
    python generate_mock_data.py --mode full --override request=500

The script:
  1. Loads the schema from db_info.json via schema_loader.
  2. Copies lookup-table CSVs from database/lookup_tables/ into database/mock_db/.
  3. Builds a runtime context with the ID pools from those lookup tables.
  4. Resolves the topological generation order via relationship_resolver.
  5. Runs each table's generator function in dependency order.
  6. After each table is generated, updates the context with its PK pool.
  7. Writes all generated rows to database/mock_db/<table>.csv.
  8. Runs validators.validate_all and prints a row-count summary.
"""

from __future__ import annotations

import argparse
import csv
import random
import shutil
import sys
from datetime import datetime
from pathlib import Path

from faker import Faker

import config as cfg
from generators import GENERATORS
from relationship_resolver import (
    LOOKUP_TABLES,
    topological_order,
)
from schema_loader import load_schema
from validators import row_count_summary, validate_all


# ---------------------------------------------------------------------------
# CSV I/O helpers
# ---------------------------------------------------------------------------


def _write_csv(output_path: Path, rows: list[dict[str, str]]) -> None:
    """Write a list of row dicts to a CSV file, creating parent dirs as needed.

    Args:
        output_path: Destination file path.
        rows:        List of dicts; all values should already be strings.
    """
    if not rows:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_csv_headers_only(output_path: Path, columns: list[str]) -> None:
    """Write a header-only CSV so every table always has a file in mock_db/.

    Called when a generator returns 0 rows — ensures downstream tools and
    validators can still open the file and read its schema.

    Args:
        output_path: Destination file path.
        columns:     Ordered list of column names to write as the header row.
    """
    if not columns:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()


def _read_csv_column(csv_path: Path, col_name: str) -> list[str]:
    """Read all non-empty values of one column from a CSV file.

    Args:
        csv_path: Path to the CSV.
        col_name: Column to extract.

    Returns:
        List of string values (empty strings excluded).
    """
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or col_name not in reader.fieldnames:
            return []
        return [row[col_name].strip() for row in reader if row[col_name].strip()]


def _read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    """Read all rows from a CSV into a list of dicts.

    Args:
        csv_path: Path to the CSV.

    Returns:
        List of row dicts.  Empty list if file missing.
    """
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Lookup table handling
# ---------------------------------------------------------------------------


def _copy_lookup_tables(output_dir: Path) -> None:
    """Copy every CSV from lookup_tables/ into mock_db/ verbatim.

    Args:
        output_dir: Destination directory (database/mock_db/).
    """
    for src in cfg.LOOKUP_DIR.glob("*.csv"):
        if src.name == ".gitkeep":
            continue
        dst = output_dir / src.name
        shutil.copy2(src, dst)


def _build_lookup_context(output_dir: Path) -> dict:
    """Build the initial runtime context from the copied lookup CSVs.

    Reads the PK column from each lookup table and stores the values under
    the conventional context key (e.g. ``country_ids``, ``cat_ids``).

    Returns the context dict with all lookup ID pools pre-populated.

    Args:
        output_dir: Directory where lookup CSVs were just copied.

    Returns:
        Context dict.
    """
    # Maps table_name → (pk_col, context_key)
    lookup_pk_map: dict[str, tuple[str, str]] = {
        "country":              ("country_id",       "country_ids"),
        "state":                ("state_id",         "state_ids"),
        "help_categories":      ("cat_id",           "cat_ids"),
        "help_categories_map":  ("child_id",         "cat_map_child_ids"),
        "req_add_info_metadata":("field_id",         "field_ids"),
        "list_item_metadata":   ("item_id",          "item_ids"),
        "notification_channels":("channel_id",       "channel_ids"),
        "notification_types":   ("type_id",          "notification_type_ids"),
        "request_for":          ("req_for_id",       "req_for_ids"),
        "request_isleadvol":    ("req_islead_id",    "req_islead_ids"),
        "request_priority":     ("req_priority_id",  "req_priority_ids"),
        "request_status":       ("req_status_id",    "req_status_ids"),
        "request_type":         ("req_type_id",      "req_type_ids"),
        "user_category":        ("user_category_id", "user_category_ids"),
        "user_status":          ("user_status_id",   "user_status_ids"),
        "supporting_languages": ("language_id",      "language_ids"),
    }

    ctx: dict = {}
    for table, (pk_col, ctx_key) in lookup_pk_map.items():
        csv_path = output_dir / f"{table}.csv"
        values = _read_csv_column(csv_path, pk_col)
        ctx[ctx_key] = values

    # Extra: build structured lookup indexes for req_add_info generation
    ctx["req_add_info_metadata_by_cat"] = _index_metadata_by_cat(output_dir)
    ctx["list_items_by_field"] = _index_list_items(output_dir)

    return ctx


def _index_metadata_by_cat(output_dir: Path) -> dict[str, list[dict]]:
    """Return req_add_info_metadata rows grouped by cat_id.

    Args:
        output_dir: Directory containing the copied lookup CSVs.

    Returns:
        Dict mapping cat_id → list of field dicts.
    """
    rows = _read_csv_rows(output_dir / "req_add_info_metadata.csv")
    index: dict[str, list[dict]] = {}
    for row in rows:
        cat = row.get("cat_id", "").strip()
        if cat:
            index.setdefault(cat, []).append(row)
    return index


def _index_list_items(output_dir: Path) -> dict[str, list[str]]:
    """Return list_item_metadata item_values grouped by field_id.

    Args:
        output_dir: Directory containing the copied lookup CSVs.

    Returns:
        Dict mapping field_id → list of item_value strings.
    """
    rows = _read_csv_rows(output_dir / "list_item_metadata.csv")
    index: dict[str, list[str]] = {}
    for row in rows:
        fid = row.get("field_id", "").strip()
        val = row.get("item_value", "").strip()
        if fid and val:
            index.setdefault(fid, []).append(val)
    return index


# ---------------------------------------------------------------------------
# Count resolution
# ---------------------------------------------------------------------------


def _resolve_count(
    table: str,
    mode_cfg: dict,
    ctx: dict,
    overrides: dict[str, int],
) -> int:
    """Resolve the target row count for a table given mode config and context.

    Priority: CLI override → explicit count → ratio-based calculation.

    Args:
        table:     Table name.
        mode_cfg:  The relevant sub-dict from ``config.ROW_COUNTS[mode]``.
        ctx:       Runtime context (used for ratio-based calculations).
        overrides: Per-table row count overrides from ``--override`` flags.

    Returns:
        Target row count as an integer.
    """
    if table in overrides:
        return overrides[table]

    counts = mode_cfg.get("counts", {})
    ratios = mode_cfg.get("ratios", {})

    if table in counts:
        return counts[table]

    # Ratio-based: fraction of user pool
    user_count = len(ctx.get("user_ids", []))
    if table in ratios and user_count:
        ratio = ratios[table]
        return max(1, round(user_count * ratio))

    # Fully derived tables (count is computed inside the generator)
    if table in ("user_skills", "meeting_participants"):
        return 0  # generator ignores count and self-determines

    return 0


# ---------------------------------------------------------------------------
# Context update after generation
# ---------------------------------------------------------------------------

# Maps table name → (pk_column, context_key) for tables whose PKs need
# to be available to downstream generators.
_PK_REGISTRATION: dict[str, tuple[str, str]] = {
    "users":                ("user_id",         "user_ids"),
    "request":              ("req_id",          "request_ids"),
    "organizations":        ("org_id",          "org_ids"),
    "meetings":             ("meeting_id",       "meeting_ids"),
    "volunteer_details":    ("user_id",          "volunteer_detail_ids"),
    "volunteer_applications":("user_id",         "vol_app_user_ids"),
}


def _update_context_after(table: str, rows: list[dict[str, str]], ctx: dict) -> None:
    """Store generated PK values in the context so downstream tables can use them.

    Also stores the full row list for tables that downstream generators
    need to inspect (e.g. ``request_data`` for ``req_add_info``).

    Args:
        table: The table that was just generated.
        rows:  The generated rows.
        ctx:   The shared runtime context dict to mutate.
    """
    if table in _PK_REGISTRATION:
        pk_col, ctx_key = _PK_REGISTRATION[table]
        ctx[ctx_key] = [row[pk_col] for row in rows if pk_col in row]

    if table == "request":
        ctx["request_data"] = rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed :class:`argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(
        description="Generate mock CSV data for all database tables."
    )
    parser.add_argument(
        "--mode",
        choices=["dev", "full"],
        default="dev",
        help="Generation mode: 'dev' (small, fast) or 'full' (5 000 users / 20 000 requests). "
             "Default: dev.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=cfg.DEFAULT_SEED,
        help=f"Random seed for deterministic output. Default: {cfg.DEFAULT_SEED}.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Skip generation; only run FK/PK validation on existing mock_db/ CSVs.",
    )
    parser.add_argument(
        "--override",
        metavar="TABLE=N",
        action="append",
        default=[],
        help="Override row count for a specific table, e.g. --override request=500. "
             "Can be repeated.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=cfg.OUTPUT_DIR,
        help=f"Output directory for generated CSVs. Default: {cfg.OUTPUT_DIR}.",
    )
    return parser.parse_args()


def _parse_overrides(raw: list[str]) -> dict[str, int]:
    """Parse ``--override TABLE=N`` flags into a dict.

    Args:
        raw: List of raw override strings from argparse.

    Returns:
        Dict mapping table name to override row count.

    Raises:
        SystemExit: If any override string is malformed.
    """
    result: dict[str, int] = {}
    for item in raw:
        if "=" not in item:
            print(f"ERROR: --override must be TABLE=N, got '{item}'", file=sys.stderr)
            sys.exit(1)
        table, _, n_str = item.partition("=")
        try:
            result[table.strip()] = int(n_str.strip())
        except ValueError:
            print(f"ERROR: --override N must be an integer, got '{n_str}'", file=sys.stderr)
            sys.exit(1)
    return result


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    mode: str,
    seed: int,
    output_dir: Path,
    overrides: dict[str, int],
) -> None:
    """Execute the full generation pipeline.

    Steps:
      1. Load schema from db_info.json.
      2. Copy lookup CSVs to output_dir and build initial context.
      3. Resolve topological generation order.
      4. Generate each non-lookup table in order.
      5. Write CSVs and update context.
      6. Validate and print summary.

    Args:
        mode:       ``"dev"`` or ``"full"``.
        seed:       Integer random seed.
        output_dir: Destination directory for all output CSVs.
        overrides:  Per-table row count overrides.
    """
    start_time = datetime.now()
    print(f"\n{'='*60}")
    print(f"  Saayam mock-data generator  |  mode={mode}  seed={seed}")
    print(f"  output  →  {output_dir}")
    print(f"{'='*60}")

    # 1. Load schema
    schema = load_schema(cfg.DB_INFO_PATH)
    print(f"\n  schema    {len(schema)} tables loaded from db_info.json")

    # 2. Copy lookup tables + build context
    output_dir.mkdir(parents=True, exist_ok=True)
    _copy_lookup_tables(output_dir)
    ctx = _build_lookup_context(output_dir)
    print(f"  lookups   {len(cfg.LOOKUP_ONLY_TABLES)} lookup CSVs copied to {output_dir.name}/")

    # 3. Topological order — only for tables that have generators
    all_tables = list(schema.keys())
    ordered = topological_order(all_tables)
    # Keep only tables that have a generator; lookup tables were already handled
    generate_sequence = [t for t in ordered if t in GENERATORS]
    print(f"  order     {len(generate_sequence)} tables queued for generation\n")

    # 4. Initialise RNG and Faker
    rng = random.Random(seed)
    Faker.seed(seed)
    fake = Faker()

    # 5. Mode config
    mode_cfg = cfg.ROW_COUNTS[mode]

    # 6. Generate each table
    for table in generate_sequence:
        count = _resolve_count(table, mode_cfg, ctx, overrides)
        generator_fn = GENERATORS[table]

        try:
            rows = generator_fn(ctx=ctx, rng=rng, fake=fake, count=count)
        except Exception as exc:   # pragma: no cover
            print(f"  ERROR     {table}  {exc}")
            continue

        out_path = output_dir / f"{table}.csv"
        if rows:
            _write_csv(out_path, rows)
            _update_context_after(table, rows, ctx)
            print(f"  generated {table:<40} {len(rows):>7} rows")
        else:
            columns = [c.name for c in schema[table].columns]
            _write_csv_headers_only(out_path, columns)
            print(f"  skipped   {table:<40}       0 rows  (header-only CSV written)")

    # 7. Validate
    print(f"\n{'─'*60}")
    print("  running FK and PK validation …")
    violation_count = validate_all(output_dir, verbose=True)
    status = "PASS" if violation_count == 0 else f"WARN  ({violation_count} issues)"
    print(f"  validation result: {status}")

    # 8. Row-count summary
    print(f"\n{'─'*60}")
    print("  row counts")
    summary = row_count_summary(output_dir)
    for table, n in sorted(summary.items()):
        print(f"    {table:<45} {n:>7}")

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n  done  ({elapsed:.1f}s)\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse CLI arguments and run the appropriate pipeline action."""
    args = _parse_args()
    overrides = _parse_overrides(args.override)
    output_dir: Path = args.output_dir

    if args.validate_only:
        print(f"  validating existing CSVs in {output_dir} …")
        violation_count = validate_all(output_dir, verbose=True)
        summary = row_count_summary(output_dir)
        for table, n in sorted(summary.items()):
            print(f"    {table:<45} {n:>7}")
        sys.exit(0 if violation_count == 0 else 1)

    run_pipeline(
        mode=args.mode,
        seed=args.seed,
        output_dir=output_dir,
        overrides=overrides,
    )


if __name__ == "__main__":
    main()
