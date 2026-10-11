import json

import pandas as pd
from helpers import (
    add_distance_information,
    get_ai_orgs,
    get_beneficiary_coordinates,
    get_beneficiary_location,
    get_orgs_from_db,
    get_req_info,
    merge_organizations,
    sort_organizations_by_distance,
)


def lambda_handler(event, context):
    try:
        raw_body = event.get("body")

        if isinstance(raw_body, str):
            body = json.loads(raw_body)
        elif isinstance(raw_body, dict):
            body = raw_body
        else:
            body = event

        request_id = body.get("request_id")
        beneficiary_id = body.get("beneficiary_id")

        if not request_id or not beneficiary_id:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": ("Missing required fields: request_id, beneficiary_id")}
                ),
            }

        req_info = get_req_info(
            request_id,
            beneficiary_id,
        )

        subject = req_info.get(
            "subject",
            "",
        )

        description = req_info.get(
            "description",
            "",
        )

        category = req_info.get(
            "category",
            "",
        )

        request_location = req_info.get("req_loc")

        if not category:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": (f"Request {request_id} has no category assigned")}
                ),
            }

        (
            beneficiary_profile_location,
            beneficiary_city,
        ) = get_beneficiary_location(beneficiary_id)

        (
            beneficiary_coordinates,
            beneficiary_distance_status,
        ) = get_beneficiary_coordinates(
            request_location=request_location,
            beneficiary_id=beneficiary_id,
        )

        db_organizations = get_orgs_from_db(
            beneficiary_city,
            category,
        )

        genai_organizations = get_ai_orgs(
            subject,
            description,
            beneficiary_profile_location or "",
            category,
        )

        combined_list = merge_organizations(
            db_organizations,
            genai_organizations,
        )

        combined_list = add_distance_information(
            combined_list,
            beneficiary_coordinates,
            beneficiary_distance_status,
        )

        if body.get("sort_by") == "distance" or body.get("sort_by_distance") is True:
            combined_list = sort_organizations_by_distance(combined_list)

        combined_list = combined_list.astype(object).where(
            pd.notna(combined_list),
            None,
        )

        organizations = combined_list.to_dict(orient="records")

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": ("application/json"),
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(organizations),
        }

    except json.JSONDecodeError as exc:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": (f"Invalid JSON in request body: {exc}")}),
        }

    except Exception as exc:
        print(
            "saayam-org-aggregator error:",
            str(exc),
        )

        return {
            "statusCode": 500,
            "body": json.dumps({"error": (f"Internal server error: {exc}")}),
        }
