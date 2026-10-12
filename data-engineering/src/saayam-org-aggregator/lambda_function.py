import json
import logging
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from distance import add_distances
from helpers import (
    get_ai_orgs,
    get_beneficiary_location,
    get_orgs_from_db,
    get_request_context,
    merge_organizations,
    ORG_COLUMNS,
)

logger = logging.getLogger(__name__)

# handle the lambda function call
def lambda_handler(event, context):
    try:
        raw_body = event.get("body") if isinstance(event, dict) else None
        body = json.loads(raw_body) if isinstance(raw_body, str) else event
        body = body if isinstance(body, dict) else {}

        request_id = body.get("request_id") or body.get("req_id")
        beneficiary_id = body.get("beneficiary_id")
        if request_id:
            if not beneficiary_id:
                return {
                    "statusCode": 400,
                    "body": json.dumps({
                        "error": "request_id and beneficiary_id are required fields"
                    }),
                }
            request = get_request_context(request_id, beneficiary_id)
            if not request:
                return {
                    "statusCode": 404,
                    "body": json.dumps({
                        "error": "Request was not found for beneficiary"
                    }),
                }
            category = request.get("category")
            subject = request.get("req_subj")
            description = request.get("req_desc")
            beneficiary_location = get_beneficiary_location(
                request.get("beneficiary_id"), request.get("req_loc")
            )
            # Use the beneficiary's profile city for search filtering. If it is
            # unavailable, leave the category search broad instead of treating
            # an unparsed request value or caller-supplied location as theirs.
            location = beneficiary_location.get("city")
            ai_location = beneficiary_location.get("address") or location
        else:
            subject = body.get("subject")
            description = body.get("description")
            location = body.get("location")
            category = body.get("category")
            ai_location = location
            beneficiary_location = {
                "coordinates": None,
                "status": "unknown_location",
                "address": "",
                "city": None,
            }

        if not category or (not request_id and not location):
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "error": (
                        "A request with a category, or location and category, "
                        "is required"
                    )
                }),
            }

        with ThreadPoolExecutor() as executor:
            db_future = executor.submit(get_orgs_from_db, location, category)
            ai_future = executor.submit(
                get_ai_orgs, subject, description, ai_location, category
            )

            try:
                db_organizations = db_future.result()
            except Exception:
                logger.exception("Database organization lookup failed")
                db_organizations = pd.DataFrame()
            try:
                genAI_organizations = ai_future.result()
            except Exception:
                logger.exception("GenAI organization lookup failed")
                genAI_organizations = pd.DataFrame()

        combined_list = merge_organizations(db_organizations, genAI_organizations)
        try:
            combined_list = add_distances(combined_list, beneficiary_location)
        except Exception:
            logger.exception("Could not calculate organization distances")
            combined_list["distance"] = None
            combined_list["distance_unit"] = "miles"
            combined_list["distance_method"] = "straight_line"
            combined_list["distance_status"] = "error"

        combined_list = combined_list.reindex(columns=ORG_COLUMNS + [
            "db_or_ai",
            "distance",
            "distance_unit",
            "distance_method",
            "distance_status",
        ])

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": combined_list.to_json(orient="records"),
        }

    except json.JSONDecodeError as e:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"Invalid JSON in request body: {str(e)}"}),
        }
    except Exception as e:
        logger.exception("Organization aggregator request failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Internal server error: {str(e)}"}),
        }
