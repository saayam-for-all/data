import json
import os
import logging
from typing import Dict, Any

import psycopg2
import boto3


# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_db_connection():
    """Create and return a PostgreSQL database connection."""
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        port=os.environ.get("DB_PORT", 5432)
    )


def fetch_metrics(cursor) -> Dict[str, int]:
    """Run SQL queries to compute homepage metrics."""
    queries = {
        "totalRequests": "SELECT COUNT(*) FROM requests;",
        "requestsResolved": "SELECT COUNT(*) FROM requests WHERE status = 'resolved';",
        "totalVolunteers": "SELECT COUNT(*) FROM volunteers;",
        "totalBeneficiaries": "SELECT COUNT(*) FROM beneficiaries;"
    }

    results = {}
    for key, query in queries.items():
        cursor.execute(query)
        results[key] = cursor.fetchone()[0]

    return results


def upload_to_s3(data: Dict[str, Any]):
    """Upload the metrics JSON to S3."""
    s3 = boto3.client("s3")

    bucket = "saayam-public-metrics"
    key = "homepage/metrics.json"

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data),
        ContentType="application/json"
    )

    logger.info(f"Uploaded metrics.json to s3://{bucket}/{key}")


def lambda_handler(event, context):
    """AWS Lambda entry point."""
    try:
        logger.info("Starting homepage metrics aggregation...")

        conn = get_db_connection()
        cursor = conn.cursor()

        metrics = fetch_metrics(cursor)

        cursor.close()
        conn.close()

        upload_to_s3(metrics)

        logger.info("Successfully completed metrics aggregation.")
        return {"status": "success", "data": metrics}

    except Exception as e:
        logger.error(f"Error during metrics aggregation: {str(e)}")
        raise e