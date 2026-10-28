
import os
import csv
import io
from datetime import datetime
from pathlib import Path

import boto3
import psycopg2


def load_sql(filename):
    """Load SQL from the Lambda directory."""
    return Path(__file__).with_name(filename).read_text(encoding="utf-8")


def get_db_connection():
    """Connect to PostgreSQL using environment variables."""
    required = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [name for name in required if not os.getenv(name)]

    if missing:
        raise ValueError(
            "Missing database configuration: " + ", ".join(missing)
        )

    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        port=int(os.getenv("DB_PORT", "5432")),
        connect_timeout=10,
    )


def fetch_archive_snapshot(connection, previous_watermark, current_watermark):
    """Get the source count and enriched records from one snapshot."""
    parameters = {
        "previous_watermark": previous_watermark,
        "current_watermark": current_watermark,
    }

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )

            cursor.execute(load_sql("source_count.sql"), parameters)
            result = cursor.fetchone()

            if result is None:
                raise ValueError("Source count query returned no result")

            source_count = int(result[0])

            cursor.execute(load_sql("enriched_requests.sql"), parameters)

            columns = [column[0] for column in cursor.description]
            records = [
                dict(zip(columns, row))
                for row in cursor.fetchall()
            ]

        connection.commit()
        return source_count, records

    except Exception:
        connection.rollback()
        raise


def validate_export(records, expected_count):
    """Check that all requests are present without duplicates."""
    exported_count = len(records)
    request_ids = [record["req_id"] for record in records]
    unique_count = len(set(request_ids))

    validation = {
        "expected_count": expected_count,
        "exported_count": exported_count,
        "unique_request_count": unique_count,
        "count_matches": exported_count == expected_count,
        "no_duplicates": unique_count == exported_count,
    }

    validation["valid"] = (
        validation["count_matches"] and validation["no_duplicates"]
    )

    if not validation["valid"]:
        raise ValueError(f"Archive validation failed: {validation}")

    return validation


def generate_csv(records):
    """Generate one enriched CSV with empty fields for NULL values."""
    if not records:
        return ""

    output = io.StringIO(newline="")

    writer = csv.DictWriter(
        output,
        fieldnames=list(records[0].keys()),
        extrasaction="raise",
        lineterminator="\n",
    )

    writer.writeheader()
    writer.writerows(records)

    return output.getvalue()


def lambda_handler(event, context):
    """Export validated, enriched requests to Amazon S3."""
    event = event or {}

    bucket_name = os.environ["ARCHIVE_BUCKET"]

    previous_watermark = datetime.fromisoformat(
        event["previous_watermark"]
    )
    current_watermark = datetime.fromisoformat(
        event["current_watermark"]
    )

    if current_watermark <= previous_watermark:
        raise ValueError(
            "Current watermark must be later than previous watermark."
        )

    object_key = (
        "request-archive/"
        f"from={previous_watermark.isoformat()}/"
        f"to={current_watermark.isoformat()}/"
        "enriched_requests.csv"
    )

    connection = get_db_connection()

    try:
        source_count, records = fetch_archive_snapshot(
            connection,
            previous_watermark,
            current_watermark,
        )
    finally:
        connection.close()

    validation = validate_export(records, source_count)
    csv_content = generate_csv(records)

    if not csv_content:
        raise ValueError("CSV content cannot be empty")

    response = boto3.client("s3").put_object(
        Bucket=bucket_name,
        Key=object_key,
        Body=csv_content.encode("utf-8"),
        ContentType="text/csv; charset=utf-8",
    )

    return {
        "status": "success",
        "validation": validation,
        "s3": {
            "bucket": bucket_name,
            "key": object_key,
            "etag": response.get("ETag"),
        },
    }
