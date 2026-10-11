import json
import logging

from helpers import (
    get_beneficiary_location,
    get_req_info,
    get_orgs_from_db,
    get_ai_orgs,
    calculate_distances,
    merge_organizations,
)

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    """Entry point for the saayam-org-aggregator Lambda.

    Expects JSON body with: request_id, beneficiary_id.
    Returns a list of organizations, each with distance fields.
    """
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        request_id = body.get("request_id")
        beneficiary_id = body.get("beneficiary_id")

        logger.info("request_id: %s, beneficiary_id: %s", request_id, beneficiary_id)

        if not request_id or not beneficiary_id:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": (
                            "Missing required fields: "
                            "request_id, beneficiary_id"
                        )
                    }
                ),
            }

        # --- Beneficiary location (fallback chain, NO default) -----------
        # Priority: request coords → user_locations → profile address → null
        beneficiary_location, beneficiary_city, beneficiary_coords, ben_status = (
            get_beneficiary_location(beneficiary_id, request_id)
        )

        logger.info(
            "Beneficiary — location: %s, city: %s, coords: %s, status: %s",
            beneficiary_location,
            beneficiary_city,
            beneficiary_coords,
            ben_status,
        )

        # --- Request info ------------------------------------------------
        req_info = get_req_info(request_id, beneficiary_id)

        logger.info("Request info: %s", req_info)

        category = req_info.get("category", "")
        subject = req_info.get("subject", "")
        description = req_info.get("description", "")

        if not category:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": (
                            f"Request {request_id} "
                            "has no category assigned"
                        )
                    }
                ),
            }

        # --- Fetch organizations -----------------------------------------
        db_organizations = get_orgs_from_db(
            beneficiary_city or "",
            category,
        )

        genai_organizations = get_ai_orgs(
            subject,
            description,
            beneficiary_location or "",
            category,
        )

        # --- Calculate distances -----------------------------------------
        db_organizations = calculate_distances(
            db_organizations,
            beneficiary_location,
            beneficiary_coords,
            ben_status,
        )
        genai_organizations = calculate_distances(
            genai_organizations,
            beneficiary_location,
            beneficiary_coords,
            ben_status,
        )

        # --- Merge -------------------------------------------------------
        combined = merge_organizations(db_organizations, genai_organizations)

        # Replace NaN with None so json.dumps produces valid JSON nulls.
        combined = combined.where(combined.notna(), None)
        organizations = combined.to_dict(orient="records")

        logger.info("Returning %d organizations", len(organizations))

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(organizations),
        }

    except json.JSONDecodeError as e:
        return {
            "statusCode": 400,
            "body": json.dumps(
                {"error": f"Invalid JSON in request body: {str(e)}"}
            ),
        }

    except Exception as e:
        logger.error("saayam-org-aggregator error: %s", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps(
                {"error": f"Internal server error: {str(e)}"}
            ),
        }
