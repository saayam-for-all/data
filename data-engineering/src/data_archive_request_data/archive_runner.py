"""Run the enriched requests export against a connection and validate it.

The runner only uses plain DB-API calls, so the Lambda (psycopg2 against RDS)
and the local development run (sqlite3 against the repo's mock CSVs) execute the
same queries and the same validation.

Rows are streamed from the database into a CSV spool rather than collected in a
list, and duplicates are detected as the rows go past: the export is ordered by
(watermark, req_id), so the rows a join fans out for one request are adjacent
and a comparison with the previous row is enough to catch them.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from . import db
    from .exporter import CsvSpool
    from .query_builder import (
        build_export_query,
        build_reference_audit_query,
        build_source_count_query,
        build_table_probe_query,
        export_column_names,
    )
    from .reference_mappings import (
        REFERENCE_COLUMNS,
        REQUEST_COLUMNS,
        REQUEST_PRIMARY_KEY,
    )
    from .validation import build_validation_summary
except ImportError:  # The deploy workflow copies these modules to the zip root.
    import db
    from exporter import CsvSpool
    from query_builder import (
        build_export_query,
        build_reference_audit_query,
        build_source_count_query,
        build_table_probe_query,
        export_column_names,
    )
    from reference_mappings import (
        REFERENCE_COLUMNS,
        REQUEST_COLUMNS,
        REQUEST_PRIMARY_KEY,
    )
    from validation import build_validation_summary

# A run above this many rows is refused rather than risking the Lambda's memory
# and /tmp. The caller narrows the watermark window instead.
DEFAULT_MAX_ROWS = 250_000

# Duplicated request ids are reported, not accumulated without limit.
MAX_REPORTED_DUPLICATES = 10


@dataclass
class ExportResult:
    """One export run: the spooled CSV and the validation summary."""

    columns: List[str] = field(default_factory=list)
    spool: Optional[CsvSpool] = None
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Whether every validation check held."""
        return self.summary.get("status") == "passed"

    def close(self) -> None:
        """Release the spooled CSV."""
        if self.spool is not None:
            self.spool.close()
            self.spool = None


def check_schema(
    connection: Any,
    schema: Optional[str] = None,
    fail_on_drift: bool = True,
) -> Dict[str, List[str]]:
    """Compare the live requests table against the columns the export knows.

    A column added to requests after this Lambda was written would otherwise be
    archived silently as nothing at all, so by default the run stops instead.

    Args:
        connection: DB-API connection.
        schema: Schema qualifying the table, or None for the search path.
        fail_on_drift: Raise instead of returning the drift.

    Returns:
        A dict with the "missing" and "unexported" column names.

    Raises:
        ValueError: If the table and the export disagree and fail_on_drift.
    """
    live_columns = db.table_columns(connection, build_table_probe_query(schema))
    missing, unexported = db.check_column_coverage(live_columns, REQUEST_COLUMNS)
    drift = {"missing": missing, "unexported": unexported}

    if (missing or unexported) and fail_on_drift:
        raise ValueError(
            "requests table does not match the export: "
            f"columns missing from the table {missing}, "
            f"columns the export would drop {unexported}. "
            "Update REQUEST_COLUMNS in reference_mappings.py, or set "
            "ARCHIVE_FAIL_ON_SCHEMA_DRIFT=false to archive anyway."
        )

    return drift


def run_export(
    connection: Any,
    watermark_start: Any,
    watermark_end: Any,
    schema: Optional[str] = None,
    paramstyle: str = "pyformat",
    include_reference_ids: bool = True,
    max_rows: int = DEFAULT_MAX_ROWS,
    fail_on_schema_drift: bool = True,
) -> ExportResult:
    """Export the enriched requests table for one archival window.

    Args:
        connection: DB-API connection to the Saayam database.
        watermark_start: Exclusive lower bound on the watermark column.
        watermark_end: Inclusive upper bound on the watermark column.
        schema: Schema qualifying the tables, or None for the search path.
        paramstyle: "pyformat" for psycopg2 or "qmark" for sqlite3.
        include_reference_ids: Keep the raw reference ids in the export.
        max_rows: Refuse a window holding more rows than this.
        fail_on_schema_drift: Stop when requests has columns the export does
            not cover.

    Returns:
        The spooled CSV and the validation summary for the run. The caller owns
        the spool and must close it.

    Raises:
        ValueError: If the window holds more than max_rows rows, or the table
            and the export disagree on columns.
    """
    params = (watermark_start, watermark_end)
    drift = check_schema(connection, schema, fail_on_drift=fail_on_schema_drift)

    source_row_count, source_request_count = db.fetch_one(
        connection,
        build_source_count_query(schema=schema, paramstyle=paramstyle),
        params,
    )
    source_row_count = int(source_row_count or 0)
    source_request_count = int(source_request_count or 0)

    if source_row_count > max_rows:
        raise ValueError(
            f"Window holds {source_row_count} rows, above the {max_rows} row "
            "ceiling for one run. Narrow watermark_start/watermark_end, or "
            "raise ARCHIVE_MAX_ROWS if the Lambda has the memory for it."
        )

    column_names = export_column_names(include_reference_ids)
    request_id_index = column_names.index(REQUEST_PRIMARY_KEY)

    spool = CsvSpool(column_names)
    exported_row_count = 0
    duplicate_row_count = 0
    duplicate_request_ids: List[str] = []
    previous_request_id = object()

    try:
        rows = db.stream_rows(
            connection,
            build_export_query(
                schema=schema,
                paramstyle=paramstyle,
                include_reference_ids=include_reference_ids,
            ),
            params,
        )

        for row in rows:
            request_id = row[request_id_index]
            if request_id == previous_request_id:
                duplicate_row_count += 1
                if len(duplicate_request_ids) < MAX_REPORTED_DUPLICATES:
                    duplicate_request_ids.append(str(request_id))
            previous_request_id = request_id

            spool.write_row(row)
            exported_row_count += 1

        spool.finish()
    except Exception:
        spool.close()
        raise

    reference_audit: Dict[str, Dict[str, int]] = {}
    for reference in REFERENCE_COLUMNS:
        null_count, unmatched_count = db.fetch_one(
            connection,
            build_reference_audit_query(
                reference, schema=schema, paramstyle=paramstyle
            ),
            params,
        )
        reference_audit[reference.source_column] = {
            "null_count": null_count,
            "unmatched_count": unmatched_count,
        }

    summary = build_validation_summary(
        source_row_count=source_row_count,
        source_request_count=source_request_count,
        exported_row_count=exported_row_count,
        exported_request_count=exported_row_count - duplicate_row_count,
        duplicate_request_ids=duplicate_request_ids,
        reference_audit=reference_audit,
    )
    summary["watermark_start"] = str(watermark_start)
    summary["watermark_end"] = str(watermark_end)
    summary["export_bytes"] = spool.byte_count
    summary["spilled_to_disk"] = spool.spilled_to_disk
    summary["schema_drift"] = drift

    return ExportResult(columns=column_names, spool=spool, summary=summary)
