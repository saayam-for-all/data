import json

from helpers import archive_requests


def lambda_handler(event, context):
    """
    Archive incrementally updated request records from PostgreSQL to S3.

    The archive operation is implemented in helpers.py. The watermark is
    advanced only after the exported row count matches the source row count.
    """
    try:
        result = archive_requests()

        print(json.dumps(result, default=str))

        return {
            "statusCode": 200,
            "body": json.dumps(result, default=str),
        }

    except Exception as e:
        print(f"Request archival failed: {str(e)}")

        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": f"Request archival failed: {str(e)}"
            }),
        }