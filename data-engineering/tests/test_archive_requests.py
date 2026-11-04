"""Acceptance tests against real PostgreSQL; AWS boundary is mocked."""

import csv
import hashlib
import io
import json
import os
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import boto3
import psycopg
import pytest
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from archive_fixture import create_fixture
from Data_ArchiveRequestData import lambda_function as archive

EVENT = {"archive_before": "2026-01-01T00:00:00Z", "status_ids": None}
DSN = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def database():
    """Use a fresh schema per test and clean only that schema afterward."""
    if not DSN:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL acceptance tests")
    config = replace(archive.load_config(), schema="archive_test_" + uuid.uuid4().hex)
    with psycopg.connect(DSN) as conn:
        create_fixture(conn, config)
    try:
        yield config
    finally:
        with psycopg.connect(DSN) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(config.schema))
            )


def run_export(config, event=None, output=None):
    """Return validation plus parsed CSV using a separate idle connection."""
    output = output if output is not None else io.StringIO()
    with psycopg.connect(DSN) as conn:
        summary = archive.export_requests(conn, event or EVENT, config, output)
    output.seek(0)
    return summary, list(csv.DictReader(output)), output.getvalue()


def test_single_enriched_export_retains_every_selected_identity(database):
    summary, rows, raw = run_export(database)
    assert summary["source_count"] == summary["exported_count"] == 6
    assert summary["duplicate_request_count"] == 0 and summary["validated"]
    assert [r["req_id"] for r in rows] == [f"REQ-{i:03}" for i in range(1, 7)]
    assert rows[0]["creator_name"] == rows[0]["beneficiary_name"] == "Alex Example"
    assert rows[0]["help_category"] == "Food assistance"
    assert rows[0]["request_status"] == "Completed"
    assert len(rows[0]) == 21
    for ref in database.references:
        assert ref.column not in rows[0]
        assert rows[1][ref.output] == r"\N"
        assert rows[2][ref.output].startswith("[UNMATCHED: ")
        counts = summary["references"][ref.column]
        assert counts["null"] == counts["unmatched"] == 1
        assert counts["matched"] == 4
    assert rows[3]["creator_name"] == "[MISSING LABEL: UBLANK]"
    assert summary["references"]["creator_id"]["missing_label"] == 1
    assert rows[4]["req_desc"] == ""
    assert rows[5]["req_desc"] == "Line 1\nLine 2 — café"
    assert rows[5]["req_doc_link"] == r"\\N"


def test_status_filter_and_exclusive_utc_cutoff(database):
    summary, rows, _ = run_export(database, {**EVENT, "status_ids": [3, 4]})
    assert summary["source_count"] == 4
    assert {r["req_id"] for r in rows} == {"REQ-001", "REQ-004", "REQ-005", "REQ-006"}
    _, offset_rows, _ = run_export(
        database, {**EVENT, "archive_before": "2025-12-31T19:00:00-05:00"}
    )
    assert len(offset_rows) == 6


def test_empty_selection_writes_one_header(database):
    summary, rows, raw = run_export(
        database, {**EVENT, "archive_before": "2020-01-01T00:00:00Z"}
    )
    assert summary["source_count"] == summary["exported_count"] == 0
    assert rows == [] and len(raw.splitlines()) == 1


@pytest.mark.parametrize("index", range(9))
def test_duplicate_lookup_keys_fail_before_export(database, index):
    ref = database.references[index]
    with psycopg.connect(DSN) as conn:
        conn.execute(
            sql.SQL("INSERT INTO {} SELECT * FROM {} LIMIT 1").format(
                sql.Identifier(database.schema, ref.table),
                sql.Identifier(database.schema, ref.table),
            )
        )
    with pytest.raises(ValueError, match="Nonunique lookup"):
        run_export(database)


@pytest.mark.parametrize("null_key", [False, True])
def test_duplicate_or_null_request_ids_are_rejected(database, null_key):
    with psycopg.connect(DSN) as conn:
        if null_key:
            conn.execute(
                sql.SQL("UPDATE {} SET req_id=NULL WHERE req_id='REQ-001'").format(
                    sql.Identifier(database.schema, database.table)
                )
            )
        else:
            conn.execute(
                sql.SQL(
                    "INSERT INTO {} SELECT * FROM {} WHERE req_id='REQ-001'"
                ).format(
                    sql.Identifier(database.schema, database.table),
                    sql.Identifier(database.schema, database.table),
                )
            )
    with pytest.raises(ValueError, match="duplicate or null"):
        run_export(database)


def test_snapshot_survives_concurrent_source_and_lookup_changes(database):
    class ConcurrentOutput(io.StringIO):
        """Mutate after source counting, before the export cursor starts."""

        triggered = False

        def write(self, value):
            if not self.triggered:
                self.triggered = True
                with psycopg.connect(DSN) as other:
                    other.execute(
                        sql.SQL(
                            "UPDATE {} SET full_name='Changed' WHERE user_id='U1'"
                        ).format(sql.Identifier(database.schema, "users"))
                    )
                    other.execute(
                        sql.SQL(
                            "INSERT INTO {} SELECT * FROM {} WHERE req_id='REQ-001'"
                        ).format(
                            sql.Identifier(database.schema, database.table),
                            sql.Identifier(database.schema, database.table),
                        )
                    )
            return super().write(value)

    summary, rows, _ = run_export(database, output=ConcurrentOutput())
    assert summary["source_count"] == summary["exported_count"] == 6
    assert rows[0]["creator_name"] == "Alex Example"


@pytest.mark.parametrize(
    "change,match",
    [
        ("ADD COLUMN extra_user_id text", "Unmapped reference"),
        ("DROP COLUMN beneficiary_id", "Mapping columns missing"),
        ("ADD COLUMN creator_name text", "Output names collide"),
    ],
)
def test_schema_drift_fails_loudly(database, change, match):
    with psycopg.connect(DSN) as conn:
        conn.execute(
            sql.SQL("ALTER TABLE {} " + change).format(
                sql.Identifier(database.schema, database.table)
            )
        )
    with pytest.raises(ValueError, match=match):
        run_export(database)


def test_declared_foreign_key_must_match_mapping(database):
    with psycopg.connect(DSN) as conn:
        conn.execute(
            sql.SQL("ALTER TABLE {} ADD PRIMARY KEY (user_id)").format(
                sql.Identifier(database.schema, "users")
            )
        )
        conn.execute(
            sql.SQL(
                "ALTER TABLE {} ADD FOREIGN KEY (req_cat_id) REFERENCES {} (user_id) NOT VALID"
            ).format(
                sql.Identifier(database.schema, database.table),
                sql.Identifier(database.schema, "users"),
            )
        )
    with pytest.raises(ValueError, match="Declared foreign key differs"):
        run_export(database)


def test_storage_limit_fails_before_publication(database):
    with pytest.raises(ValueError, match="storage limit"):
        run_export(replace(database, max_bytes=50))


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"archive_before": "2026-01-01", "status_ids": None},
        {**EVENT, "status_ids": []},
        {**EVENT, "status_ids": [True]},
        {**EVENT, "status_ids": ["3); DROP TABLE requests;--"]},
        {**EVENT, "archive_before": "invalid"},
    ],
)
def test_invalid_selection_is_rejected(event):
    with pytest.raises(ValueError):
        archive.archive_selection(event, archive.load_config())


def test_identifier_injection_and_duplicate_mapping_are_rejected():
    config = archive.load_config()
    with pytest.raises(ValueError, match="invalid identifiers"):
        replace(config, schema="public; DROP TABLE requests")
    with pytest.raises(ValueError, match="Duplicate mapping"):
        replace(config, references=config.references + (config.references[0],))


@pytest.fixture
def handler_environment(database, monkeypatch):
    """Exercise the actual handler with real DB and an in-memory S3 boundary."""
    monkeypatch.setenv("ARCHIVE_BUCKET", "synthetic-test-bucket")
    monkeypatch.setenv("DB_SCHEMA", database.schema)
    monkeypatch.setattr(archive, "connect_database", lambda: psycopg.connect(DSN))
    client = Mock()
    uploads = []

    def upload(stream, bucket, key, ExtraArgs):
        uploads.append((stream.read(), bucket, key, ExtraArgs))

    client.upload_fileobj.side_effect = upload
    monkeypatch.setattr(boto3, "client", lambda service: client)
    return client, uploads


def test_handler_uploads_exactly_one_validated_csv(database, handler_environment):
    client, uploads = handler_environment
    result = archive.lambda_handler(EVENT, None)
    assert len(uploads) == 1
    body, bucket, key, extra = uploads[0]
    assert result["function"] == "Data_ArchiveRequestData"
    assert result["source_count"] == result["exported_count"] == 6
    assert key.endswith(".csv") and key.startswith("requests/")
    assert extra["ServerSideEncryption"] == "AES256"
    assert (
        extra["Metadata"]["sha256"]
        == hashlib.sha256(body).hexdigest()
        == result["sha256"]
    )
    assert len(list(csv.DictReader(io.StringIO(body.decode("utf-8"))))) == 6
    with psycopg.connect(DSN) as conn:
        assert (
            conn.execute(
                sql.SQL("SELECT count(*) FROM {}").format(
                    sql.Identifier(database.schema, database.table)
                )
            ).fetchone()[0]
            == 9
        )


def test_handler_kms_encryption(database, handler_environment, monkeypatch):
    monkeypatch.setenv("ARCHIVE_KMS_KEY_ID", "alias/synthetic-archive")
    archive.lambda_handler(EVENT, None)
    extra = handler_environment[1][0][3]
    assert extra["ServerSideEncryption"] == "aws:kms"
    assert extra["SSEKMSKeyId"] == "alias/synthetic-archive"


def test_handler_does_not_upload_failed_validation(database, handler_environment):
    with psycopg.connect(DSN) as conn:
        conn.execute(
            sql.SQL("INSERT INTO {} SELECT * FROM {} LIMIT 1").format(
                sql.Identifier(database.schema, "users"),
                sql.Identifier(database.schema, "users"),
            )
        )
    with pytest.raises(ValueError):
        archive.lambda_handler(EVENT, None)
    handler_environment[0].upload_fileobj.assert_not_called()


def test_handler_propagates_s3_failure(database, handler_environment):
    handler_environment[0].upload_fileobj.side_effect = RuntimeError(
        "synthetic S3 failure"
    )
    with pytest.raises(RuntimeError, match="synthetic S3 failure"):
        archive.lambda_handler(EVENT, None)


def test_secrets_manager_connection_uses_verified_tls(monkeypatch):
    client = Mock()
    client.get_secret_value.return_value = {
        "SecretString": json.dumps(
            {
                "host": "example.invalid",
                "dbname": "example",
                "username": "example",
                "password": "synthetic",
            }
        )
    }
    monkeypatch.setenv("DB_SECRET_ID", "test-secret")
    monkeypatch.setattr(boto3, "client", lambda service: client)
    connect = Mock()
    monkeypatch.setattr(archive.psycopg, "connect", connect)
    archive.connect_database()
    assert connect.call_args.kwargs["sslmode"] == "verify-full"
    client.get_secret_value.assert_called_once_with(SecretId="test-secret")


def test_export_uses_read_only_transaction(database):
    """Verify a callback cannot write source rows inside the export transaction."""
    with psycopg.connect(DSN) as conn:

        class WritingOutput(io.StringIO):
            def write(self, value):
                conn.execute(
                    sql.SQL("DELETE FROM {}").format(
                        sql.Identifier(database.schema, database.table)
                    )
                )
                return super().write(value)

        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            archive.export_requests(conn, EVENT, database, WritingOutput())


def test_small_batches_keep_all_requests(database):
    """Exercise the server cursor across multiple fetches."""
    summary, rows, _ = run_export(replace(database, batch_size=1))
    assert summary["source_count"] == summary["exported_count"] == len(rows) == 6
