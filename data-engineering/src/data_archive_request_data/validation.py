"""Validation summary for one enriched requests archive run.

The summary answers the checks issue #574 asks for: the exported request count
matches the source records selected for archival, requests with null or
unmatched references are still exported, and no request is duplicated by a join.
"""

from typing import Any, Dict, List, Sequence

try:
    from .reference_mappings import REFERENCE_COLUMNS
except ImportError:  # The deploy workflow copies these modules to the zip root.
    from reference_mappings import REFERENCE_COLUMNS


def build_validation_summary(
    source_row_count: int,
    source_request_count: int,
    exported_row_count: int,
    exported_request_count: int,
    duplicate_request_ids: Sequence[str],
    reference_audit: Dict[str, Dict[str, int]],
) -> Dict[str, Any]:
    """Build the validation summary for one run.

    Args:
        source_row_count: Rows in requests inside the archival window.
        source_request_count: Distinct req_id inside the archival window.
        exported_row_count: Rows written to the export.
        exported_request_count: Distinct req_id written to the export.
        duplicate_request_ids: Request ids a join emitted more than once, up to
            the reporting limit.
        reference_audit: Per reference column, its null_count and
            unmatched_count inside the window.

    Returns:
        The summary, with status set to "passed" only when every check holds
        and a failures list naming the checks that did not.
    """
    duplicates = [str(request_id) for request_id in duplicate_request_ids]
    failures: List[str] = []

    if exported_row_count != source_row_count:
        failures.append(
            "Exported row count ({exported}) does not match the source records "
            "selected for archival ({source}).".format(
                exported=exported_row_count, source=source_row_count
            )
        )

    if exported_request_count != source_request_count:
        failures.append(
            "Exported request count ({exported}) does not match the source "
            "request count ({source}).".format(
                exported=exported_request_count, source=source_request_count
            )
        )

    if duplicates:
        failures.append(
            "Joins duplicated requests: {ids}.".format(ids=", ".join(duplicates))
        )

    references = []
    for reference in REFERENCE_COLUMNS:
        audit = reference_audit.get(reference.source_column, {})
        references.append(
            {
                "column_in_requests": reference.source_column,
                "referenced_table": reference.referenced_table,
                "referenced_column": reference.referenced_column,
                "readable_column": reference.readable_column,
                "export_column": reference.output_column,
                "join_type": "LEFT JOIN",
                "null_count": int(audit.get("null_count") or 0),
                "unmatched_count": int(audit.get("unmatched_count") or 0),
            }
        )

    unresolved = sum(
        reference["null_count"] + reference["unmatched_count"]
        for reference in references
    )

    return {
        "source_row_count": source_row_count,
        "source_request_count": source_request_count,
        "exported_row_count": exported_row_count,
        "exported_request_count": exported_request_count,
        "duplicate_request_ids": duplicates,
        "counts_match": exported_row_count == source_row_count,
        "requests_duplicated": bool(duplicates),
        "unresolved_reference_values": unresolved,
        "references": references,
        "failures": failures,
        "status": "passed" if not failures else "failed",
    }


def format_validation_summary(summary: Dict[str, Any]) -> str:
    """Render the validation summary as Markdown for the issue thread."""
    duplicated = "yes" if summary["requests_duplicated"] else "no"
    lines = [
        "# Data_ArchiveRequestData validation summary",
        "",
        "- Status: **{status}**".format(status=summary["status"]),
        "- Source records selected for archival: {count}".format(
            count=summary["source_row_count"]
        ),
        "- Exported rows: {count}".format(count=summary["exported_row_count"]),
        "- Distinct requests exported: {count}".format(
            count=summary["exported_request_count"]
        ),
        "- Requests duplicated by joins: {duplicated}".format(duplicated=duplicated),
        "- Null or unmatched reference values kept in the export: {count}".format(
            count=summary["unresolved_reference_values"]
        ),
    ]

    if "export_bytes" in summary:
        lines.append(
            "- Export size: {count} bytes".format(count=summary["export_bytes"])
        )

    lines += [
        "",
        "## Reference columns",
        "",
        "| Column in requests | Referenced table | Referenced column |"
        " Export column | Join | Null values | Unmatched values |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for reference in summary["references"]:
        lines.append(
            "| {column_in_requests} | {referenced_table} | {referenced_column} |"
            " {export_column} | {join_type} | {null_count} |"
            " {unmatched_count} |".format(**reference)
        )

    if summary["failures"]:
        lines += ["", "## Failures", ""]
        lines += [
            "- {failure}".format(failure=failure)
            for failure in summary["failures"]
        ]

    lines.append("")
    return "\n".join(lines)
