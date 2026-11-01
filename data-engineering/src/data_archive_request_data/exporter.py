"""CSV spooling and S3 upload for the enriched requests archive.

Rows are written to the CSV as they arrive from the database and spill to the
Lambda's /tmp once they outgrow a small memory buffer, so a run holds a bounded
amount of the export in memory no matter how wide the archival window is.
"""

import csv
import io
import tempfile
from datetime import datetime
from typing import Any, Iterable, Optional, Sequence

CSV_LINE_TERMINATOR = "\n"
DEFAULT_S3_PREFIX = "requests_enriched"
EXPORT_FILE_NAME = "requests_enriched.csv"

# Below this the CSV stays in memory; above it SpooledTemporaryFile moves it to
# disk. 8 MiB keeps a typical incremental window entirely in memory.
SPOOL_MAX_MEMORY_BYTES = 8 * 1024 * 1024


class CsvSpool:
    """A CSV document written incrementally, buffered in memory then on disk.

    The caller writes rows as they are streamed from the database, calls
    finish() once, and then hands fileobj straight to the S3 upload.
    """

    def __init__(
        self,
        column_names: Sequence[str],
        max_memory_bytes: int = SPOOL_MAX_MEMORY_BYTES,
    ):
        """Open the spool and write the header row.

        Args:
            column_names: Export column names, in order.
            max_memory_bytes: Bytes buffered before spilling to disk.
        """
        self._spool = tempfile.SpooledTemporaryFile(
            max_size=max_memory_bytes, mode="w+b"
        )
        # The wrapper is kept as an attribute so it is not garbage collected,
        # which would close the spool underneath us.
        self._text = io.TextIOWrapper(self._spool, encoding="utf-8", newline="")
        self._writer = csv.writer(self._text, lineterminator=CSV_LINE_TERMINATOR)
        self._writer.writerow(column_names)
        self._byte_count = 0

    def write_row(self, row: Sequence[Any]) -> None:
        """Append one row, writing None as an empty field."""
        self._writer.writerow(["" if value is None else value for value in row])

    def write_rows(self, rows: Iterable[Sequence[Any]]) -> int:
        """Append many rows and return how many were written."""
        written = 0
        for row in rows:
            self.write_row(row)
            written += 1

        return written

    def finish(self) -> int:
        """Flush the writer and rewind for reading.

        Returns:
            The size of the CSV document in bytes.
        """
        self._text.flush()
        self._byte_count = self._spool.tell()
        self._spool.seek(0)

        return self._byte_count

    @property
    def fileobj(self) -> Any:
        """The rewound binary file object holding the CSV."""
        return self._spool

    @property
    def byte_count(self) -> int:
        """Size of the CSV document in bytes, after finish()."""
        return self._byte_count

    @property
    def spilled_to_disk(self) -> bool:
        """Whether the document outgrew the memory buffer."""
        return getattr(self._spool, "_rolled", False)

    def read_text(self) -> str:
        """Return the whole CSV as text and rewind. For local runs and tests."""
        self._spool.seek(0)
        text = self._spool.read().decode("utf-8")
        self._spool.seek(0)

        return text

    def close(self) -> None:
        """Release the buffer and any temporary file behind it."""
        try:
            self._text.detach()
        except ValueError:
            pass
        self._spool.close()

    def __enter__(self) -> "CsvSpool":
        """Allow use as a context manager."""
        return self

    def __exit__(self, *exc_info: Any) -> None:
        """Close the spool on the way out."""
        self.close()


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
    spool: CsvSpool,
    bucket: str,
    key: str,
    s3_client: Optional[Any] = None,
    region: Optional[str] = None,
    kms_key_id: Optional[str] = None,
) -> dict:
    """Upload a finished CSV spool to S3.

    The file object is passed to put_object rather than a string, so the body
    is streamed from the buffer instead of being copied into memory again.

    Args:
        spool: A CsvSpool on which finish() has been called.
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

    put_kwargs = {
        "Bucket": bucket,
        "Key": key,
        "Body": spool.fileobj,
        "ContentType": "text/csv",
    }
    if kms_key_id:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = kms_key_id

    s3_client.put_object(**put_kwargs)

    return {
        "bucket": bucket,
        "key": key,
        "bytes": spool.byte_count,
        "spilled_to_disk": spool.spilled_to_disk,
        "s3_uri": f"s3://{bucket}/{key}",
    }
