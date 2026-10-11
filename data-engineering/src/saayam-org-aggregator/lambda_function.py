import json
import logging

from helpers import (
    get_req_info,
    get_ai_orgs,
    get_orgs_from_db,
    merge_organizations,
    get_beneficiary_location,
    get_beneficiary_coordinates,
    attach_distances,
    build_db_org_address,
    build_ai_org_address,
    new_geocoder,
    sort_by_distance,
    to_json_safe,
    _empty_ai_frame,
)
import geo

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        request_id = body.get("request_id")
        beneficiary_id = body.get("beneficiary_id")
        sort_by = body.get("sort_by")

        print("request_id:", request_id)
        print("beneficiary_id:", beneficiary_id)

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

        beneficiary_location, beneficiary_city = get_beneficiary_location(
            beneficiary_id
        )

        print(
            "beneficiary location, city:",
            beneficiary_location,
            beneficiary_city,
        )

        # "United States" is only a search hint for GenAI; it is never used
        # for distance calculation.
        search_location = beneficiary_location or "United States"

        if not beneficiary_city:
            beneficiary_city = ""

        req_info = get_req_info(request_id, beneficiary_id)

        print("request info:", req_info)

        subject = req_info.get("subject", "")
        description = req_info.get("description", "")
        category = req_info.get("category", "")

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

        # --- Beneficiary/request coordinates (never the viewer's) ---
        geocoder = new_geocoder()
        try:
            (
                beneficiary_coords,
                beneficiary_status,
                beneficiary_source,
            ) = get_beneficiary_coordinates(
                beneficiary_id, req_info.get("req_loc"), geocoder
            )
        except Exception as e:
            logger.exception("Beneficiary location lookup failed: %s", e)
            beneficiary_coords, beneficiary_status, beneficiary_source = (
                None,
                geo.STATUS_ERROR,
                None,
            )

        print(
            "beneficiary coords:",
            beneficiary_coords,
            "status:",
            beneficiary_status,
            "source:",
            beneficiary_source,
        )

        db_organizations = get_orgs_from_db(
            beneficiary_city,
            category,
        )

        try:
            genai_organizations = get_ai_orgs(
                subject,
                description,
                search_location,
                category,
            )
        except Exception as e:
            # GenAI failures must not hide the DB organizations.
            logger.exception("GenAI organizations unavailable: %s", e)
            genai_organizations = _empty_ai_frame()

        db_organizations = attach_distances(
            db_organizations,
            beneficiary_coords,
            beneficiary_status,
            geocoder,
            build_db_org_address,
        )
        genai_organizations = attach_distances(
            genai_organizations,
            beneficiary_coords,
            beneficiary_status,
            geocoder,
            build_ai_org_address,
        )

        combined_list = merge_organizations(
            db_organizations,
            genai_organizations,
        )

        organizations = to_json_safe(combined_list.to_dict(orient="records"))

        if sort_by == "distance":
            organizations = sort_by_distance(organizations)

        print(
            "organization count:",
            len(organizations),
            "geocoding calls:",
            geocoder.calls,
        )

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(organizations, default=str),
        }

    except json.JSONDecodeError as e:
        return {
            "statusCode": 400,
            "body": json.dumps(
                {
                    "error": (
                        f"Invalid JSON in request body: {str(e)}"
                    )
                }
            ),
        }

    except Exception as e:
        print("saayam-org-aggregator error:", str(e))

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "error": (
                        f"Internal server error: {str(e)}"
                    )
                }
            ),
        }
