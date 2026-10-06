"""AWS Lambda entry point for the Steward Dashboard's Review Volunteers API (issue #273).

Returns a paginated list of volunteer applications awaiting steward review -
user ID, last updated time, and the review action label - joining
volunteer_applications to users on user ID. See helpers.py for the query and
infrastructure/db/init/002_steward_volunteer_review.sql for the local dev
schema this was built and tested against.
"""
import json

import psycopg2

from helpers import build_pagination, get_applications_for_review, parse_pagination


def lambda_handler(event, context):
    """Handles the Review Volunteers API request.

    Expects a JSON body shaped like {"page": <int>, "page_size": <int>},
    either as an API Gateway proxy event (event["body"] as a JSON string) or
    as the raw payload itself for direct Lambda invocation.
    """
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else (raw_body or event)

        page, page_size = parse_pagination(body)

        data, total_records = get_applications_for_review(page, page_size)
        pagination = build_pagination(page, page_size, total_records)

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"data": data, "pagination": pagination}),
        }

    except json.JSONDecodeError as e:
        return {"statusCode": 400, "body": json.dumps({"error": f"Invalid JSON in request body: {str(e)}"})}
    except ValueError as e:
        return {"statusCode": 400, "body": json.dumps({"error": str(e)})}
    except psycopg2.Error as e:
        print(f"Database error in steward_volunteer_review_api: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "Internal server error"})}
    except Exception as e:
        print(f"Unexpected error in steward_volunteer_review_api: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": "Internal server error"})}
