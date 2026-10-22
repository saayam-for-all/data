"""Run the enriched requests export against a connection and validate it.

The runner only uses plain DB-API calls, so the Lambda (psycopg2 against RDS)
and the local development run (sqlite3 against the repo's mock CSVs) execute the
same queries and the same validation.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

try:
    from . import db
    from .query_builder import (
        build_export_query,
        build_reference_audit_query,
        build_source_count_query,
    )
    from .reference_mappings import REFERENCE_COLUMNS, REQUEST_PRIMARY_KEY
    from .validation import build_validation_summary
except ImportError:  # The deploy workflow copies these modules to the zip root.
    import db
    from query_builder import (
        build_export_query,
        build_reference_audit_query,
        build_source_count_query,
    )
    from reference_mappings import REFERENCE_COLUMNS, REQUEST_PRIMARY_KEY
    from validation import build_validation_summary


@dataclass
class ExportResult:
    """One export run: the enriched rows and the validation summary."""

    columns: List[str] = field(default_factory=list)
    rows: List[Sequence[Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Whether every validation check held."""
        return self.summary.get("status") == "passed"


def run_export(
    connection: Any,
    watermark_start: Any,
    watermark_end: Any,
    schema: Optional[str] = None,
    paramstyle: str = "pyformat",
    include_reference_ids: bool = True,
) -> ExportResult:
    """Export the enriched requests table for one archival window.

    Args:
        connection: DB-API connection to the Saayam database.
        watermark_start: Exclusive lower bound on the watermark column.
        watermark_end: Inclusive upper bound on the watermark column.
        schema: Schema qualifying the tables, or None for the search path.
        paramstyle: "pyformat" for psycopg2 or "qmark" for sqlite3.
        include_reference_ids: Keep the raw reference ids in the export.

    Returns:
        The export rows and the validation summary for the run.
    """
    params = (watermark_start, watermark_end)

    source_row_count, source_request_count = db.fetch_one(
        connection,
        build_source_count_query(schema=schema, paramstyle=paramstyle),
        params,
    )

    columns, rows = db.fetch_all(
        connection,
        build_export_query(
            schema=schema,
            paramstyle=paramstyle,
            include_reference_ids=include_reference_ids,
        ),
        params,
    )

    request_id_index = columns.index(REQUEST_PRIMARY_KEY)
    request_ids = [row[request_id_index] for row in rows]

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
        source_row_count=int(source_row_count),
        source_request_count=int(source_request_count),
        request_ids=request_ids,
        reference_audit=reference_audit,
    )
    summary["watermark_start"] = str(watermark_start)
    summary["watermark_end"] = str(watermark_end)

    return ExportResult(columns=columns, rows=rows, summary=summary)
