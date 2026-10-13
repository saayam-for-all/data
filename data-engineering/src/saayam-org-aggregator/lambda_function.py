import json
from helpers import get_ai_orgs, get_orgs_from_db, merge_organizations, _db_conn, _db_name
from distance import (
    add_distance_to_orgs,
    finalize_distance_columns,
    resolve_beneficiary_coordinates,
    sort_by_distance,
)
from concurrent.futures import ThreadPoolExecutor

# handle the lambda function call
def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        subject = body.get("subject")
        description = body.get("description")
        location = body.get("location")
        category = body.get("category")

        if not location or not category:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'location and category are required fields'})
            }

        # db_organizations = get_orgs_from_db(location, category)
        # genAI_organizations = get_ai_orgs(subject, description, location)

        #Implemented parallelization to speed up the reponse

        with ThreadPoolExecutor() as executor:
            db_future = executor.submit(get_orgs_from_db, location, category)
            ai_future = executor.submit(get_ai_orgs, subject, description, location)

            db_organizations = db_future.result()
            genAI_organizations = ai_future.result()

        # Distance is measured from the beneficiary/request location (never the
        # viewer) and cannot fail the request: unknown distance is null.
        beneficiary_coords, distance_status = resolve_beneficiary_coordinates(
            _db_conn, _db_name, body.get("request_id"), body.get("beneficiary_id")
        )
        db_organizations = add_distance_to_orgs(
            db_organizations, beneficiary_coords, distance_status, "db", _db_conn, _db_name
        )
        genAI_organizations = add_distance_to_orgs(
            genAI_organizations, beneficiary_coords, distance_status, "ai"
        )

        combined_list = merge_organizations(db_organizations, genAI_organizations)
        combined_list = finalize_distance_columns(combined_list)

        if str(body.get("sort_by") or "").lower() == "distance":
            combined_list = sort_by_distance(combined_list)

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
