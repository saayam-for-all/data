"""Run Data_ArchiveRequestData locally against mock data.

Contributors have no AWS Lambda, S3 or RDS access (CONTRIBUTING.md), so this
runner builds an in-memory SQLite copy of the requests table and the six lookup
tables from the CSVs already in the repository, calls the real
``lambda_handler`` with that connection and an S3 client that writes to disk,
and saves the sample export plus the validation summary.

Usage, from ``data-engineering/``:

    python -m src.data_archive_request_data.local_run
    python -m src.data_archive_request_data.local_run --watermark-start 2026-01-01

Outputs land in ``datasets/cleaned/request_archive/`` which is gitignored, so
no archived data is ever committed.
"""

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

if __package__:
    from .lambda_function import lambda_handler
    from .validation import format_validation_summary
else:  # Run as a plain script rather than with -m.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lambda_function import lambda_handler
    from validation import format_validation_summary

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_ENGINEERING_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = DATA_ENGINEERING_ROOT / "datasets" / "cleaned" / "request_archive"

# Mock sources already in the repository. The requests CSV is the schema
# reference issue #573 points at; the lookups are the seeded lookup tables.
LOOKUP_DIR = REPO_ROOT / "database" / "lookup_tables"
MOCK_SOURCES: Dict[str, Path] = {
    "requests": REPO_ROOT / "data-analytics" / "sql" / "requests.csv",
    "request_for": LOOKUP_DIR / "request_for.csv",
    "request_isleadvol": LOOKUP_DIR / "request_isleadvol.csv",
    "help_categories": LOOKUP_DIR / "help_categories.csv",
    "request_types": LOOKUP_DIR / "request_type.csv",
    "request_priorities": LOOKUP_DIR / "request_priority.csv",
    "request_statuses": LOOKUP_DIR / "request_status.csv",
}

MOCK_BUCKET = "saayam-request-archive-local"
NULL_TOKENS = {"", "NULL", "null"}


class LocalS3Client:
    """Stand-in for the boto3 S3 client that writes objects to a local folder.

    CONTRIBUTING.md asks for AWS calls to be mockable; the Lambda takes the
    client as an argument so this class can replace it without touching the
    production path.
    """

    def __init__(self, output_dir: Path):
        """Store the folder that uploaded objects are written to."""
        self.output_dir = output_dir
        self.uploads: List[Dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> Dict[str, Any]:
        """Write the object body to ``<output_dir>/<key basename>``."""
        key = kwargs["Key"]
        body = kwargs["Body"]
        data = body.read() if hasattr(body, "read") else body
        destination = self.output_dir / Path(key).name
        destination.write_bytes(data)
        self.uploads.append({"key": key, "path": destination, "bytes": len(data)})
        return {"ETag": "local-mock"}


def _clean(value: str) -> Any:
    """Map CSV placeholders for a missing value to None."""
    return None if value is None or value.strip() in NULL_TOKENS else value


def build_mock_database(
    sources: Optional[Dict[str, Path]] = None,
) -> sqlite3.Connection:
    """Load the mock CSVs into an in-memory SQLite database.

    Every column is created as TEXT, which keeps the join comparisons
    like-for-like and preserves ids such as ``CAT-OTHER`` and ``REQ-000001``.

    Args:
        sources: Table name to CSV path; defaults to MOCK_SOURCES.

    Returns:
        A connection holding requests and the six lookup tables.

    Raises:
        FileNotFoundError: If one of the mock CSVs is missing.
    """
    sources = sources or MOCK_SOURCES
    connection = sqlite3.connect(":memory:")

    for table, path in sources.items():
        if not path.exists():
            raise FileNotFoundError(f"Mock source for {table} not found: {path}")

        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            header = [column.strip().strip('"') for column in next(reader)]
            columns = ", ".join(f'"{column}" TEXT' for column in header)
            connection.execute(f'CREATE TABLE "{table}" ({columns})')

            placeholders = ", ".join("?" for _ in header)
            insert = f'INSERT INTO "{table}" VALUES ({placeholders})'
            for row in reader:
                if not row:
                    continue
                values = [_clean(value) for value in row[: len(header)]]
                values += [None] * (len(header) - len(values))
                connection.execute(insert, values)

    connection.commit()
    return connection


def main(argv: Optional[List[str]] = None) -> int:
    """Run the export locally and write the sample output and summary.

    Returns:
        0 when validation passed, 1 when it did not.
    """
    parser = argparse.ArgumentParser(
        description="Run Data_ArchiveRequestData against mock data."
    )
    parser.add_argument(
        "--watermark-start",
        default="1970-01-01 00:00:00",
        help="Exclusive lower bound on last_updated_at.",
    )
    parser.add_argument(
        "--watermark-end",
        default="2100-01-01 00:00:00",
        help="Inclusive upper bound on last_updated_at.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Folder for the sample export and the validation summary.",
    )
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    connection = build_mock_database()
    s3_client = LocalS3Client(args.output_dir)

    response = lambda_handler(
        {
            "bucket": MOCK_BUCKET,
            "schema": None,
            "watermark_start": args.watermark_start,
            "watermark_end": args.watermark_end,
        },
        connection=connection,
        s3_client=s3_client,
        paramstyle="qmark",
    )
    connection.close()

    body = json.loads(response["body"])
    summary = body.get("validation_summary")

    if summary:
        summary_path = args.output_dir / "validation_summary.md"
        summary_path.write_text(format_validation_summary(summary), encoding="utf-8")
        (args.output_dir / "validation_summary.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )
        print(f"Validation summary: {summary_path}")

    for upload in s3_client.uploads:
        print(f"Sample export: {upload['path']} ({upload['bytes']} bytes)")
        print(f"Would upload to: s3://{MOCK_BUCKET}/{upload['key']}")

    print(f"statusCode: {response['statusCode']}")
    if body.get("error"):
        print(f"error: {body['error']}")

    return 0 if response["statusCode"] == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
