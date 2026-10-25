import json
from concurrent.futures import ThreadPoolExecutor
from utils.geocoding import load_geocoding_provider

from helpers import (
    get_ai_orgs,
    get_beneficiary_location,
    get_orgs_from_db,
    get_req_info,
    merge_organizations,
)
from org_distance import add_distance_fields, sort_by_distance


def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        request_id = body.get("request_id")
        beneficiary_id = body.get("beneficiary_id")

        subject = body.get("subject")
        description = body.get("description")
        location = body.get("location")
        category = body.get("category")
        req_info = None

        # A request-backed call must provide both IDs.
        if bool(request_id) != bool(beneficiary_id):
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "error": (
                        "request_id and beneficiary_id "
                        "must be provided together"
                    )
                }),
            }

        # Use request details for Request Details calls.
        # Body values remain available for existing callers.
        if request_id and beneficiary_id:
            req_info = get_req_info(request_id, beneficiary_id)
            subject = req_info.get("subject") or subject
            description = req_info.get("description") or description
            category = req_info.get("category") or category

        if not location or not category:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "error": "location and category are required fields"
                }),
            }

        with ThreadPoolExecutor() as executor:
            db_future = executor.submit(
                get_orgs_from_db, location, category
            )
            ai_future = executor.submit(
                get_ai_orgs, subject, description, location
            )

            db_organizations = db_future.result()
            genAI_organizations = ai_future.result()

        combined_list = merge_organizations(
            db_organizations,
            genAI_organizations,
        )

        organizations = combined_list.to_dict(orient="records")

        request_location = (
            get_beneficiary_location(
                beneficiary_id,
                req_info.get("req_loc"),
            )
            if req_info and beneficiary_id
            else None
        )

        geocoder = load_geocoding_provider()
        organizations = add_distance_fields(
            organizations,
            request_location,
            geocoder=geocoder,
        )
        organizations = sort_by_distance(organizations)

        response_columns = [
            "name",
            "location",
            "contact",
            "email",
            "web_url",
            "mission",
            "source",
            "db_or_ai",
            "distance",
            "distance_unit",
            "distance_status",
        ]

        organizations = [
            {
                column: organization.get(column)
                for column in response_columns
            }
            for organization in organizations
        ]

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(organizations),
        }

    except json.JSONDecodeError as exc:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": f"Invalid JSON in request body: {exc}"
            }),
        }
    except Exception as exc:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": f"Internal server error: {exc}"
            }),
        }