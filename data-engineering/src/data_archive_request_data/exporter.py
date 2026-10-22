"""CSV rendering and S3 upload for the enriched requests archive."""

import csv
import io
from datetime import datetime
from typing import Any, Iterable, Optional, Sequence

CSV_LINE_TERMINATOR = "\n"
DEFAULT_S3_PREFIX = "requests_enriched"
EXPORT_FILE_NAME = "requests_enriched.csv"


def rows_to_csv(column_names: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """Render query rows as CSV text with a header row.

    Args:
        column_names: Export column names, in order.
        rows: Query rows in the same column order.

    Returns:
        The CSV document as text. None values are written as empty fields.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=CSV_LINE_TERMINATOR)
    writer.writerow(column_names)

    for row in rows:
        writer.writerow(["" if value is None else value for value in row])

    return buffer.getvalue()


def build_s3_key(
    run_timestamp: datetime,
    prefix: str = DEFAULT_S3_PREFIX,
    file_name: str = EXPORT_FILE_NAME,
) -> str:
    """Build the partitioned S3 key for one export run.

    Args:
        run_timestamp: UTC timestamp of the run.
        prefix: Key prefix inside the bucket.
        file_name: File name written in the run partition.

    Returns:
        A key of the form <prefix>/archive_year=YYYY/archive_month=MM/
        archive_day=DD/run_ts=<ts>/<file_name>.
    """
    clean_prefix = prefix.strip("/") or DEFAULT_S3_PREFIX
    return "/".join(
        (
            clean_prefix,
            f"archive_year={run_timestamp:%Y}",
            f"archive_month={run_timestamp:%m}",
            f"archive_day={run_timestamp:%d}",
            f"run_ts={run_timestamp:%Y%m%dT%H%M%SZ}",
            file_name,
        )
    )


def upload_csv_to_s3(
    csv_text: str,
    bucket: str,
    key: str,
    s3_client: Optional[Any] = None,
    region: Optional[str] = None,
    kms_key_id: Optional[str] = None,
) -> dict:
    """Upload the rendered CSV to S3.

    Args:
        csv_text: The CSV document.
        bucket: Destination bucket.
        key: Destination key.
        s3_client: Pre-built client; a boto3 client is created when omitted,
            which lets local runs and tests pass a mock instead.
        region: AWS region used when a client has to be created.
        kms_key_id: KMS key for server-side encryption, when the bucket
            requires a customer-managed key.

    Returns:
        A dict with the bucket, key, byte size and S3 URI of the upload.
    """
    if s3_client is None:
        import boto3  # Imported lazily so local runs need no AWS SDK.

        s3_client = boto3.client("s3", region_name=region)

    body = csv_text.encode("utf-8")
    put_kwargs = {
        "Bucket": bucket,
        "Key": key,
        "Body": body,
        "ContentType": "text/csv",
    }
    if kms_key_id:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = kms_key_id

    s3_client.put_object(**put_kwargs)

    return {
        "bucket": bucket,
        "key": key,
        "bytes": len(body),
        "s3_uri": f"s3://{bucket}/{key}",
    }
