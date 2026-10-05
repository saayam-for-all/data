import json
import logging
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from helpers import (
    add_organization_distances,
    get_ai_orgs,
    get_beneficiary_location,
    get_orgs_from_db,
    merge_organizations,
)

logger = logging.getLogger(__name__)

# handle the lambda function call
def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        subject = body.get("subject")
        description = body.get("description")
        location = body.get("location")
        category = body.get("category")
        request_id = body.get("request_id") or body.get("req_id")
        beneficiary_id = body.get("beneficiary_id")

        if not location or not category:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'location and category are required fields'})
            }

        # Fetch both sources concurrently, but degrade gracefully if one source
        # is unavailable so a GenAI failure cannot discard database results.
        with ThreadPoolExecutor() as executor:
            db_future = executor.submit(get_orgs_from_db, location, category)
            ai_future = executor.submit(get_ai_orgs, subject, description, location)
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
        beneficiary_location = get_beneficiary_location(request_id, beneficiary_id)
        try:
            combined_list = add_organization_distances(combined_list, beneficiary_location)
        except Exception:
            # Distance is enrichment; never fail the Organizations response for it.
            logger.exception("Unable to add organization distances")
            combined_list["distance"] = None
            combined_list["distance_unit"] = "miles"
            combined_list["distance_method"] = "straight_line"
            combined_list["distance_status"] = "error"

        # Convert pandas missing values and numpy scalars into JSON-safe values.
        combined_list = combined_list.astype(object).where(pd.notna(combined_list), None)

        return {
            'statusCode': 200,
            'headers': {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": '*'
            },
            'body': json.dumps(combined_list.to_dict(orient='records'))
        }

    except json.JSONDecodeError as e:
        return {'statusCode': 400, 'body': json.dumps({'error': f'Invalid JSON in request body: {str(e)}'})}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'Internal server error: {str(e)}'})}
