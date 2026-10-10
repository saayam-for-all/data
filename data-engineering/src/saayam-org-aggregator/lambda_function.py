import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from distance import enrich_organizations
from helpers import (
    get_ai_orgs,
    get_geocode_cache,
    get_geocoder,
    get_orgs_from_db,
    get_request_context,
    merge_organizations,
)


def _parse_event(event):
    """Return the request payload from a direct or API Gateway event."""
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    raw_body = event.get("body")
    body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body or event
    if not isinstance(body, dict):
        raise ValueError("request body must be an object")
    return body


def _error_response(status_code, message):
    """Build a JSON API Gateway error response."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps({"error": message}),
    }


# handle the lambda function call
def lambda_handler(event, context):
    """Return matching organizations enriched with beneficiary-based distance."""
    try:
        body = _parse_event(event)
        request_id = body.get("request_id") or body.get("req_id")
        beneficiary_id = body.get("beneficiary_id")
        request_context = {}
        if request_id is not None or beneficiary_id is not None:
            try:
                request_context = get_request_context(request_id, beneficiary_id)
            except Exception as error:
                print(f"Beneficiary location lookup failed: {error}")

        search_context = request_context.get("search", {})
        subject = body.get("subject") or search_context.get("subject")
        description = body.get("description") or search_context.get("description")
        location = body.get("location") or search_context.get("location")
        category = body.get("category") or search_context.get("category")

        if not location or not category:
            return _error_response(400, "location and category are required fields")

        with ThreadPoolExecutor() as executor:
            db_future = executor.submit(get_orgs_from_db, location, category)
            ai_future = executor.submit(get_ai_orgs, subject, description, location)

            try:
                db_organizations = db_future.result()
                db_error = None
            except Exception as error:
                db_organizations = pd.DataFrame()
                db_error = error
            try:
                genAI_organizations = ai_future.result()
                ai_error = None
            except Exception as error:
                genAI_organizations = pd.DataFrame()
                ai_error = error

        if db_error and ai_error:
            raise RuntimeError(f"Organization sources failed: database={db_error}; genai={ai_error}")

        combined_list = merge_organizations(db_organizations, genAI_organizations)
        organization_records = combined_list.to_dict(orient="records")
        organization_records = enrich_organizations(
            organization_records,
            request_context.get("beneficiary_location"),
            geocoder=get_geocoder(),
            cache=get_geocode_cache(),
        )
        if str(body.get("sort_by", "")).casefold() in ("distance", "nearest_distance"):
            organization_records.sort(
                key=lambda organization: (
                    organization.get("distance") is None,
                    organization.get("distance") if organization.get("distance") is not None else 0,
                )
            )

        return {
            'statusCode': 200,
            'headers': {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": '*'
            },
            'body': json.dumps(organization_records, default=str)
        }

    except json.JSONDecodeError as e:
        return _error_response(400, f'Invalid JSON in request body: {str(e)}')
    except ValueError as e:
        return _error_response(400, str(e))
    except Exception as e:
        return _error_response(500, f'Internal server error: {str(e)}')
