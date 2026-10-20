import json
import logging
from concurrent.futures import ThreadPoolExecutor

from helpers import (
    attach_distance,
    get_ai_orgs,
    get_beneficiary_location,
    get_beneficiary_location_by_request,
    get_orgs_from_db,
    merge_organizations,
)

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        subject = body.get("subject")
        description = body.get("description")
        location = body.get("location")
        category = body.get("category")

        # request_id takes precedence over beneficiary_id for location resolution
        request_id = body.get("request_id")
        beneficiary_id = body.get("beneficiary_id")

        if not location or not category:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "location and category are required fields"}),
            }

        if request_id:
            beneficiary_coords, location_status = get_beneficiary_location_by_request(request_id)
        elif beneficiary_id:
            beneficiary_coords, location_status = get_beneficiary_location(beneficiary_id)
        else:
            beneficiary_coords, location_status = None, "unknown_location"

        if beneficiary_coords is None:
            logger.warning(
                "Could not resolve beneficiary location (request_id=%r, beneficiary_id=%r, status=%r)",
                request_id,
                beneficiary_id,
                location_status,
            )

        with ThreadPoolExecutor() as executor:
            db_future = executor.submit(get_orgs_from_db, location, category)
            ai_future = executor.submit(get_ai_orgs, subject, description, location)
            db_organizations = db_future.result()
            genAI_organizations = ai_future.result()

        combined_df = merge_organizations(db_organizations, genAI_organizations)

        records = combined_df.to_dict(orient="records")
        records_with_distance = [attach_distance(org, beneficiary_coords) for org in records]

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(records_with_distance),
        }

    except json.JSONDecodeError as exc:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"Invalid JSON in request body: {exc}"}),
        }
    except Exception as exc:
        logger.exception("Unhandled error in lambda_handler")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Internal server error: {exc}"}),
        }
