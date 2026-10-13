
import json
from concurrent.futures import ThreadPoolExecutor

from helpers import (
    get_ai_orgs,
    get_orgs_from_db,
    merge_organizations,
    add_distances_to_organizations,
    resolve_beneficiary_coordinates,
)


def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        subject = body.get("subject")
        description = body.get("description")
        location = body.get("location")
        category = body.get("category")

        if not location or not category:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "error": "location and category are required fields"
                })
            }

        # Fetch database and GenAI organizations in parallel.
        with ThreadPoolExecutor() as executor:
            db_future = executor.submit(
                get_orgs_from_db, location, category
            )
            ai_future = executor.submit(
                get_ai_orgs, subject, description, location
            )

            db_organizations = db_future.result()
            genAI_organizations = ai_future.result()

        # Merge database and GenAI results.
        combined_list = merge_organizations(
            db_organizations,
            genAI_organizations
        )

        organizations = combined_list.to_dict(orient="records")

              # Resolve beneficiary coordinates when provided by a trusted backend.
        # Never substitute the search location for beneficiary coordinates.
        beneficiary_location = resolve_beneficiary_coordinates(body)

        # Add distance fields without removing organizations.
        organizations = add_distances_to_organizations(
            organizations,
            beneficiary_location
        )

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(organizations, allow_nan=False)
        }

    except json.JSONDecodeError as e:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": f"Invalid JSON in request body: {str(e)}"
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": f"Internal server error: {str(e)}"
            })
        }