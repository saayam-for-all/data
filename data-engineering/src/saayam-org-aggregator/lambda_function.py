import json

from helpers import (
    get_req_info,
    get_ai_orgs,
    get_orgs_from_db,
    merge_organizations,
    get_beneficiary_location,
)


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

        genai_organizations = get_ai_orgs(
            subject,
            description,
            beneficiary_location,
            category,
        )

        combined_list = merge_organizations(
            db_organizations,
            genai_organizations,
        )

        organizations = combined_list.to_dict(orient="records")

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
