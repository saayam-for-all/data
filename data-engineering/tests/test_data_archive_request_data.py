"""Tests for the Data_ArchiveRequestData Lambda (issue #574).

Contributors have no RDS, Lambda or S3 access, so these tests run the real
queries against an in-memory SQLite database built from CSV fixtures and pass a
mock S3 client into the handler, the way CONTRIBUTING.md asks for AWS calls to
be mocked. The fixtures deliberately include requests whose references are null
and requests whose references match nothing, plus a lookup table with a
duplicated key, so the LEFT JOIN behaviour and the duplicate check are both
exercised.
"""

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.data_archive_request_data.archive_runner import run_export
from src.data_archive_request_data.exporter import build_s3_key, rows_to_csv
from src.data_archive_request_data.lambda_function import lambda_handler
from src.data_archive_request_data.local_run import build_mock_database
from src.data_archive_request_data.query_builder import (
    build_export_query,
    build_reference_audit_query,
    export_column_names,
)
from src.data_archive_request_data.reference_mappings import (
    REFERENCE_COLUMNS,
    REQUEST_COLUMNS,
)
from src.data_archive_request_data.validation import build_validation_summary

WATERMARK_START = "1970-01-01 00:00:00"
WATERMARK_END = "2100-01-01 00:00:00"

LOOKUP_FIXTURES: Dict[str, Dict[str, Any]] = {
    "request_for": {
        "header": ["req_for_id", "req_for", "req_for_desc", "last_updated_date"],
        "rows": [
            ["0", "SELF", "For the individual", "NULL"],
            ["1", "OTHER", "For someone else", "NULL"],
        ],
    },
    "request_isleadvol": {
        "header": [
            "req_islead_id",
            "req_islead",
            "req_islead_desc",
            "last_updated_date",
        ],
        "rows": [
            ["0", "NO", "Supporting volunteer", "NULL"],
            ["1", "YES", "Lead volunteer", "NULL"],
        ],
    },
    "help_categories": {
        "header": ["cat_id", "cat_name", "cat_desc"],
        "rows": [
            ["1", "FOOD_AND_ESSENTIALS", "FOOD_DESC"],
            ["2", "HOUSING", "HOUSING_DESC"],
        ],
    },
    "request_type": {
        "header": ["req_type_id", "req_type", "req_type_desc", "last_updated_date"],
        "rows": [
            ["0", "IN_PERSON", "On site", "NULL"],
            ["1", "REMOTE", "Remote", "NULL"],
        ],
    },
    "request_priority": {
        "header": [
            "req_priority_id",
            "req_priority",
            "req_priority_desc",
            "last_updated_date",
        ],
        "rows": [
            ["0", "LOW", "Can wait", "NULL"],
            ["1", "MEDIUM", "Soon", "NULL"],
        ],
    },
    "request_status": {
        "header": [
            "req_status_id",
            "req_status",
            "req_status_desc",
            "last_updated_date",
        ],
        "rows": [
            ["0", "CREATED", "Awaiting review", "NULL"],
            ["1", "RESOLVED", "Completed", "NULL"],
        ],
    },
}

# REQ-000001 resolves every reference, REQ-000002 carries ids that match
# nothing, REQ-000003 leaves every reference null.
REQUEST_FIXTURES: List[Dict[str, str]] = [
    {
        "req_id": "REQ-000001",
        "creator_id": "SID-00-000-000-001",
        "req_for_id": "0",
        "req_islead_id": "1",
        "req_cat_id": "1",
        "req_type_id": "1",
        "req_priority_id": "0",
        "req_status_id": "1",
        "req_subj": "Help with rent",
        "last_updated_at": "2026-02-01 10:00:00",
    },
    {
        "req_id": "REQ-000002",
        "creator_id": "SID-00-000-000-002",
        "req_for_id": "9",
        "req_islead_id": "9",
        "req_cat_id": "CAT-OTHER",
        "req_type_id": "9",
        "req_priority_id": "9",
        "req_status_id": "9",
        "req_subj": "Unmatched references",
        "last_updated_at": "2026-02-02 10:00:00",
    },
    {
        "req_id": "REQ-000003",
        "creator_id": "SID-00-000-000-003",
        "req_subj": "Null references",
        "last_updated_at": "2026-02-03 10:00:00",
    },
]


def _write_csv(path: Path, header: List[str], rows: List[List[str]]) -> None:
    """Write one fixture CSV."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _build_sources(
    tmp_path: Path,
    duplicate_status_rows: bool = False,
) -> Dict[str, Path]:
    """Write the fixture CSVs and return the table-to-path mapping.

    Args:
        tmp_path: Folder for the fixture files.
        duplicate_status_rows: Seed request_status with the same id twice, which
            a primary key would prevent in the real database but which must be
            caught by the duplicate check if it ever happens.
    """
    sources: Dict[str, Path] = {}

    requests_path = tmp_path / "requests.csv"
    rows = []
    for fixture in REQUEST_FIXTURES:
        rows.append([fixture.get(column, "") for column in REQUEST_COLUMNS])
    _write_csv(requests_path, list(REQUEST_COLUMNS), rows)
    sources["requests"] = requests_path

    for table, fixture in LOOKUP_FIXTURES.items():
        path = tmp_path / f"{table}.csv"
        lookup_rows = [list(row) for row in fixture["rows"]]
        if table == "request_status" and duplicate_status_rows:
            lookup_rows.append(["1", "RESOLVED_DUPLICATE", "Duplicate key", "NULL"])
        _write_csv(path, fixture["header"], lookup_rows)
        sources[table] = path

    return sources


@pytest.fixture()
def mock_connection(tmp_path):
    """A SQLite connection holding the fixture requests and lookup tables."""
    connection = build_mock_database(_build_sources(tmp_path))
    yield connection
    connection.close()


class FakeS3Client:
    """Records put_object calls instead of talking to S3."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        return {"ETag": "fake"}


def _run(connection, **kwargs):
    """Run the export over the mock connection."""
    return run_export(
        connection,
        watermark_start=kwargs.pop("watermark_start", WATERMARK_START),
        watermark_end=kwargs.pop("watermark_end", WATERMARK_END),
        schema=None,
        paramstyle="qmark",
        **kwargs,
    )


def test_every_referenced_table_is_left_joined_on_its_primary_key():
    query = build_export_query(schema="public")

    for reference in REFERENCE_COLUMNS:
        expected = (
            f"LEFT JOIN public.{reference.referenced_table} {reference.alias} "
            f"ON {reference.alias}.{reference.referenced_column} "
            f"= r.{reference.source_column}"
        )
        assert expected in query

    assert len(re.findall(r"\bLEFT JOIN\b", query)) == len(REFERENCE_COLUMNS)
    assert not re.search(r"\b(INNER|RIGHT|FULL|CROSS)\s+JOIN\b", query)
    assert not re.search(r"(?<!LEFT )\bJOIN\b", query)


def test_export_query_is_incremental_on_the_watermark_column():
    query = build_export_query()

    assert "WHERE r.last_updated_at > %s" in query
    assert "AND r.last_updated_at <= %s" in query
    assert "ORDER BY r.last_updated_at, r.req_id" in query


def test_export_replaces_reference_ids_with_readable_values():
    columns = export_column_names(include_reference_ids=False)

    for reference in REFERENCE_COLUMNS:
        assert reference.output_column in columns
        assert reference.source_column not in columns

    assert "req_id" in columns
    assert len(columns) == len(REQUEST_COLUMNS)


def test_reference_ids_are_kept_next_to_the_readable_values_by_default():
    columns = export_column_names()

    for reference in REFERENCE_COLUMNS:
        assert reference.output_column in columns
        assert reference.source_column in columns
        assert columns.index(reference.output_column) + 1 == columns.index(
            reference.source_column
        )


def test_reference_audit_query_counts_nulls_and_unmatched_separately():
    reference = REFERENCE_COLUMNS[0]
    query = build_reference_audit_query(reference, schema="public")

    assert "null_count" in query
    assert "unmatched_count" in query
    assert f"LEFT JOIN public.{reference.referenced_table} ref" in query


def test_export_keeps_requests_with_null_and_unmatched_references(mock_connection):
    result = _run(mock_connection)
    exported = {row[result.columns.index("req_id")] for row in result.rows}

    assert exported == {"REQ-000001", "REQ-000002", "REQ-000003"}
    assert result.summary["source_row_count"] == 3
    assert result.summary["exported_row_count"] == 3
    assert result.summary["counts_match"] is True
    assert result.summary["requests_duplicated"] is False
    assert result.summary["status"] == "passed"


def test_readable_values_replace_ids_and_unmatched_references_stay_empty(
    mock_connection,
):
    result = _run(mock_connection)
    by_request = {
        row[result.columns.index("req_id")]: dict(zip(result.columns, row))
        for row in result.rows
    }

    resolved = by_request["REQ-000001"]
    assert resolved["req_status"] == "RESOLVED"
    assert resolved["req_category"] == "FOOD_AND_ESSENTIALS"
    assert resolved["req_islead"] == "YES"
    assert resolved["req_status_id"] == "1"

    unmatched = by_request["REQ-000002"]
    assert unmatched["req_status_id"] == "9"
    assert unmatched["req_status"] is None
    assert unmatched["req_category"] is None

    missing = by_request["REQ-000003"]
    assert missing["req_status_id"] is None
    assert missing["req_status"] is None


def test_validation_summary_reports_null_and_unmatched_counts(mock_connection):
    result = _run(mock_connection)
    by_column = {
        reference["column_in_requests"]: reference
        for reference in result.summary["references"]
    }

    assert by_column["req_status_id"]["null_count"] == 1
    assert by_column["req_status_id"]["unmatched_count"] == 1
    assert by_column["req_status_id"]["join_type"] == "LEFT JOIN"
    assert result.summary["unresolved_reference_values"] == 2 * len(REFERENCE_COLUMNS)


def test_watermark_window_limits_the_export(mock_connection):
    result = _run(
        mock_connection,
        watermark_start="2026-02-01 10:00:00",
        watermark_end="2026-02-02 10:00:00",
    )

    assert result.summary["source_row_count"] == 1
    assert [row[result.columns.index("req_id")] for row in result.rows] == [
        "REQ-000002"
    ]
    assert result.summary["status"] == "passed"


def test_duplicated_lookup_rows_are_caught_as_duplicated_requests(tmp_path):
    connection = build_mock_database(
        _build_sources(tmp_path, duplicate_status_rows=True)
    )
    try:
        result = _run(connection)
    finally:
        connection.close()

    assert result.summary["status"] == "failed"
    assert result.summary["requests_duplicated"] is True
    assert "REQ-000001" in result.summary["duplicate_request_ids"]
    assert result.summary["exported_row_count"] == 4
    assert result.summary["source_row_count"] == 3


def test_validation_summary_flags_a_count_mismatch():
    summary = build_validation_summary(
        source_row_count=3,
        source_request_count=3,
        request_ids=["REQ-000001", "REQ-000002"],
        reference_audit={},
    )

    assert summary["status"] == "failed"
    assert summary["counts_match"] is False
    assert any("does not match" in failure for failure in summary["failures"])


def test_rows_to_csv_writes_a_header_and_blanks_for_nulls():
    csv_text = rows_to_csv(["req_id", "req_status"], [["REQ-000001", None]])

    assert csv_text.splitlines() == ["req_id,req_status", "REQ-000001,"]


def test_s3_key_is_partitioned_by_run_date():
    key = build_s3_key(datetime(2026, 2, 3, 4, 5, 6), prefix="requests_enriched")

    assert key == (
        "requests_enriched/archive_year=2026/archive_month=02/archive_day=03/"
        "run_ts=20260203T040506Z/requests_enriched.csv"
    )


def test_handler_uploads_one_enriched_file_when_validation_passes(mock_connection):
    s3_client = FakeS3Client()

    response = lambda_handler(
        {
            "bucket": "saayam-request-archive-test",
            "schema": None,
            "watermark_start": WATERMARK_START,
            "watermark_end": WATERMARK_END,
        },
        connection=mock_connection,
        s3_client=s3_client,
        paramstyle="qmark",
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["uploaded"] is True
    assert len(s3_client.calls) == 1

    call = s3_client.calls[0]
    assert call["Bucket"] == "saayam-request-archive-test"
    assert call["ContentType"] == "text/csv"

    lines = call["Body"].decode("utf-8").splitlines()
    assert lines[0] == ",".join(export_column_names())
    assert len(lines) == 4
    assert body["validation_summary"]["status"] == "passed"


def test_handler_uploads_nothing_when_validation_fails(tmp_path):
    connection = build_mock_database(
        _build_sources(tmp_path, duplicate_status_rows=True)
    )
    s3_client = FakeS3Client()

    try:
        response = lambda_handler(
            {
                "bucket": "saayam-request-archive-test",
                "schema": None,
                "watermark_start": WATERMARK_START,
                "watermark_end": WATERMARK_END,
            },
            connection=connection,
            s3_client=s3_client,
            paramstyle="qmark",
        )
    finally:
        connection.close()
    body = json.loads(response["body"])

    assert response["statusCode"] == 500
    assert body["uploaded"] is False
    assert s3_client.calls == []
    assert body["validation_summary"]["requests_duplicated"] is True


def test_handler_dry_run_validates_without_uploading(mock_connection):
    s3_client = FakeS3Client()

    response = lambda_handler(
        {
            "schema": None,
            "dry_run": True,
            "watermark_start": WATERMARK_START,
            "watermark_end": WATERMARK_END,
        },
        connection=mock_connection,
        s3_client=s3_client,
        paramstyle="qmark",
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["uploaded"] is False
    assert body["dry_run"] is True
    assert s3_client.calls == []


def test_repository_mock_data_exports_without_duplicates_or_losses():
    """The repo's own requests CSV and lookup tables export one row per request."""
    connection = build_mock_database()
    try:
        result = _run(connection)
    finally:
        connection.close()

    assert result.summary["source_row_count"] > 0
    assert result.summary["counts_match"] is True
    assert result.summary["requests_duplicated"] is False
    assert result.summary["status"] == "passed"
