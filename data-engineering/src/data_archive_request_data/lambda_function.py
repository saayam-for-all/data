"""Data_ArchiveRequestData: archive one enriched requests table to S3.

Issue #574. The previous pipeline exported the requests table and the lookup
tables it refers to as separate files, so reading an archived request meant
joining six files back together. This Lambda exports a single table instead:
every reference id is resolved to its readable value with a LEFT JOIN on the
referenced table's primary key, so requests whose references are null or
unmatched stay in the export and no join can duplicate a request.

Rows are streamed from the database into a CSV that spills to /tmp once it
outgrows a small memory buffer, and a window above ARCHIVE_MAX_ROWS is refused
rather than risking the Lambda's memory. The run is validated before anything
is written to S3: the exported request count has to match the source records
selected for archival and no req_id may appear twice. A failed validation
returns 500 and uploads nothing.

Configuration comes from the event first, then the environment:

    ARCHIVE_S3_BUCKET        destination bucket (required)
    ARCHIVE_S3_PREFIX        key prefix, default "requests_enriched"
    ARCHIVE_S3_KMS_KEY_ID    optional KMS key for server-side encryption
    AWS_REGION               bucket region
    REQUEST_ARCHIVE_SCHEMA   schema holding requests, default "public"
    ARCHIVE_WATERMARK_START  exclusive lower bound, default "1970-01-01 00:00:00"
    ARCHIVE_INCLUDE_REFERENCE_IDS  keep raw ids beside readable values, default true
    ARCHIVE_MAX_ROWS         row ceiling for one run, default 250000
    ARCHIVE_FAIL_ON_SCHEMA_DRIFT  stop on unexported columns, default true
    DATABASE_URL             libpq connection string
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from . import db
    from .archive_runner import DEFAULT_MAX_ROWS, run_export
    from .exporter import DEFAULT_S3_PREFIX, build_s3_key, upload_csv_to_s3
    from .validation import format_validation_summary
except ImportError:  # The deploy workflow copies these modules to the zip root.
    import db
    from archive_runner import DEFAULT_MAX_ROWS, run_export
    from exporter import DEFAULT_S3_PREFIX, build_s3_key, upload_csv_to_s3
    from validation import format_validation_summary

LAMBDA_NAME = "Data_ArchiveRequestData"
DEFAULT_SCHEMA = "public"
DEFAULT_WATERMARK_START = "1970-01-01 00:00:00"


def _as_bool(value: Any, default: bool = True) -> bool:
    """Read a boolean from an event value or environment string."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _setting(event: Dict[str, Any], key: str, env_var: str, default: Any = None) -> Any:
    """Return a setting from the event, then the environment, then the default.

    A key present in the event wins even when its value is None, which is how a
    run asks for unqualified table names instead of the configured schema.
    """
    if key in event:
        return event[key]
    return os.environ.get(env_var, default)


def lambda_handler(
    event: Optional[Dict[str, Any]],
    context: Any = None,
    connection: Any = None,
    s3_client: Any = None,
    paramstyle: str = "pyformat",
) -> Dict[str, Any]:
    """Export the enriched requests table for one window and upload it to S3.

    Args:
        event: Optional per-run overrides of the configuration above, plus
            "dry_run" to validate without uploading.
        context: Lambda context; unused.
        connection: Pre-built DB-API connection. Injected by local runs and
            tests; a psycopg2 connection is opened when omitted.
        s3_client: Pre-built S3 client. Injected by local runs and tests.
        paramstyle: Placeholder style of the connection: "pyformat" for
            psycopg2, "qmark" for the sqlite3 connection used locally.

    Returns:
        An API-Gateway-shaped response whose body carries the validation
        summary and, on success, the uploaded object.
    """
    event = event or {}
    owns_connection = connection is None
    result = None

    try:
        bucket = _setting(event, "bucket", "ARCHIVE_S3_BUCKET")
        dry_run = _as_bool(event.get("dry_run"), default=False)
        if not bucket and not dry_run:
            raise ValueError("ARCHIVE_S3_BUCKET is not set")

        prefix = _setting(event, "prefix", "ARCHIVE_S3_PREFIX", DEFAULT_S3_PREFIX)
        region = _setting(event, "region", "AWS_REGION")
        kms_key_id = _setting(event, "kms_key_id", "ARCHIVE_S3_KMS_KEY_ID")
        schema = _setting(event, "schema", "REQUEST_ARCHIVE_SCHEMA", DEFAULT_SCHEMA)
        watermark_start = _setting(
            event,
            "watermark_start",
            "ARCHIVE_WATERMARK_START",
            DEFAULT_WATERMARK_START,
        )
        watermark_end = event.get("watermark_end") or datetime.now(
            timezone.utc
        ).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
        include_reference_ids = _as_bool(
            _setting(
                event,
                "include_reference_ids",
                "ARCHIVE_INCLUDE_REFERENCE_IDS",
                True,
            )
        )
        max_rows = int(
            _setting(event, "max_rows", "ARCHIVE_MAX_ROWS", DEFAULT_MAX_ROWS)
        )
        fail_on_schema_drift = _as_bool(
            _setting(
                event,
                "fail_on_schema_drift",
                "ARCHIVE_FAIL_ON_SCHEMA_DRIFT",
                True,
            )
        )

        if connection is None:
            connection = db.connect()

        result = run_export(
            connection,
            watermark_start=watermark_start,
            watermark_end=watermark_end,
            schema=schema,
            paramstyle=paramstyle,
            include_reference_ids=include_reference_ids,
            max_rows=max_rows,
            fail_on_schema_drift=fail_on_schema_drift,
        )

        summary = result.summary
        print(format_validation_summary(summary))

        if not result.passed:
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {
                        "lambda": LAMBDA_NAME,
                        "uploaded": False,
                        "error": "Validation failed; nothing was uploaded.",
                        "validation_summary": summary,
                    },
                    default=str,
                ),
            }

        if dry_run:
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "lambda": LAMBDA_NAME,
                        "uploaded": False,
                        "dry_run": True,
                        "csv_bytes": summary["export_bytes"],
                        "validation_summary": summary,
                    },
                    default=str,
                ),
            }

        key = build_s3_key(datetime.now(timezone.utc), prefix=prefix)
        upload = upload_csv_to_s3(
            result.spool,
            bucket=bucket,
            key=key,
            s3_client=s3_client,
            region=region,
            kms_key_id=kms_key_id,
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "lambda": LAMBDA_NAME,
                    "uploaded": True,
                    "export": upload,
                    "validation_summary": summary,
                },
                default=str,
            ),
        }

    except Exception as error:  # Surfaced to CloudWatch by the caller.
        return {
            "statusCode": 500,
            "body": json.dumps(
                {"lambda": LAMBDA_NAME, "uploaded": False, "error": str(error)}
            ),
        }

    finally:
        if result is not None:
            result.close()
        if owns_connection and connection is not None:
            connection.close()
