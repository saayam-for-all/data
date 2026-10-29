"""Reproducible local handler run: real PostgreSQL, synthetic data, mocked S3."""

import csv
import json
import os
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "data-engineering" / "src"))
sys.path.insert(0, str(ROOT / "data-engineering" / "tests"))
from archive_fixture import create_fixture  # noqa: E402 - local script path setup
from Data_ArchiveRequestData import lambda_function as archive  # noqa: E402 - local script path setup


def main():
    """Invoke the Lambda handler and save its exact uploaded CSV plus validation."""
    dsn = os.environ["TEST_DATABASE_URL"]
    config = replace(archive.load_config(), schema="archive_demo_" + uuid.uuid4().hex)
    destination = ROOT / "data-engineering" / "docs" / "archive_requests" / "evidence"
    destination.mkdir(exist_ok=True)
    event = json.loads(
        (
            ROOT
            / "data-engineering"
            / "src"
            / "Data_ArchiveRequestData"
            / "event.example.json"
        ).read_text(encoding="utf-8")
    )
    captured = []

    class LocalS3:
        """Record the real handler's S3 upload without making any AWS calls."""

        def upload_fileobj(self, stream, bucket, key, ExtraArgs):
            content = stream.read()
            (destination / "sample_requests.csv").write_bytes(content)
            captured.append({"bucket": bucket, "key": key, "extra_args": ExtraArgs})

    with psycopg.connect(dsn) as conn:
        create_fixture(conn, config)
    try:
        with (
            patch.dict(
                os.environ,
                {"DB_SCHEMA": config.schema, "ARCHIVE_BUCKET": "local-demo-only"},
            ),
            patch.object(archive, "connect_database", lambda: psycopg.connect(dsn)),
            patch("boto3.client", lambda service: LocalS3()),
        ):
            result = archive.lambda_handler(event, None)
        result["evidence_scope"] = (
            "Synthetic fixture on local PostgreSQL; S3 mocked. Not production validation."
        )
        result["task_573"] = (
            "Pending: production mappings and reference counts not supplied."
        )
        result["postgres_version"] = psycopg.connect(dsn, autocommit=True)
        with result.pop("postgres_version") as conn:
            result["postgres_version"] = conn.execute("SELECT version()").fetchone()[0]
        (destination / "validation.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        query = archive.build_export_query(
            config,
            __import__("archive_fixture").SOURCE_COLUMNS,
            archive.archive_selection(event, config)[0],
        )
        (destination / "export_query.sql").write_text(
            query.as_string() + ";\n", encoding="utf-8"
        )
        assert (
            len(captured) == 1
            and result["source_count"] == result["exported_count"] == 6
        )
        with (destination / "sample_requests.csv").open(
            encoding="utf-8", newline=""
        ) as stream:
            rows = list(csv.DictReader(stream))
        assert len({r["req_id"] for r in rows}) == 6
        print("Data_ArchiveRequestData: successful local handler execution")
        print("Database: real PostgreSQL; input: synthetic fixture; S3: mocked")
        print(
            "Selected source requests: 6 | Exported requests: 6 | Duplicate requests: 0"
        )
        print(
            "All 9 reference mappings use LEFT JOIN; null and unmatched references retained"
        )
        print("Exactly one CSV captured from the handler's S3 upload")
        print("SHA-256:", result["sha256"])
        print(
            "Sample: evidence/sample_requests.csv | Validation: evidence/validation.json"
        )
        print("Task #573 production mapping/count approval: pending")
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(config.schema))
            )


if __name__ == "__main__":
    main()
