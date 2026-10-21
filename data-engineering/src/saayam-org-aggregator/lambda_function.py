import json

from helpers import (
    get_req_info,
    get_ai_orgs,
    get_orgs_from_db,
    merge_organizations,
    get_beneficiary_location,
    add_distances,
)
from org_distance import sort_by_distance


def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        request_id = body.get("request_id")
        beneficiary_id = body.get("beneficiary_id")

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

        # Search hint for GenAI only. Distance never uses this default; it
        # reports distance_status="unknown_location" instead (#433).
        if not beneficiary_location:
            beneficiary_location = "United States"

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

        db_organizations = get_orgs_from_db(
            beneficiary_city,
            category,
        )

        # A GenAI failure should not hide the DB organizations (#433).
        try:
            genai_organizations = get_ai_orgs(
                subject,
                description,
                beneficiary_location,
                category,
            )
        except Exception as e:
            print("GenAI organizations unavailable; continuing with DB results:", str(e))
            genai_organizations = None

        combined_list = merge_organizations(
            db_organizations,
            genai_organizations,
        )

        organizations = combined_list.to_dict(orient="records")

        # Straight-line distance from the beneficiary/request location (#433).
        organizations = add_distances(
            organizations,
            request_location=req_info.get("req_loc"),
            beneficiary_id=beneficiary_id,
        )

        # Optional: nearest first, unknown distance (N/A) last.
        if str(body.get("sort_by") or "").strip().lower() == "distance":
            organizations = sort_by_distance(organizations)

        print("organization count:", len(organizations))

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
