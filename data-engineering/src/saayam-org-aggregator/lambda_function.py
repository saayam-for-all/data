import json
from helpers import (
    get_ai_orgs,
    get_orgs_from_db,
    merge_organizations,
    _db_conn,
    _db_name,
)
from concurrent.futures import ThreadPoolExecutor
from organization_distance_adapter import (
    aggregate_request_organizations_with_distances,
)

# handle the lambda function call
def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        subject = body.get("subject")
        description = body.get("description")
        location = body.get("location")
        category = body.get("category")
        request_id = body.get("request_id")
        beneficiary_id = body.get("beneficiary_id")
        sort_by_distance = body.get("sort_by_distance") is True

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

        combined_list = merge_organizations(
        db_organizations,
        genAI_organizations,
        )
        for column, default in {
            "distance": None,
            "distance_unit": "miles",
            "distance_method": "straight_line",
            "distance_status": "unknown_location",
        }.items():
            if column not in combined_list.columns:
                combined_list[column] = default

        if request_id:
            try:
                with _db_conn.cursor() as cursor:
                    combined_list = aggregate_request_organizations_with_distances(
                    cursor=cursor,
                    schema=_db_name,
                    request_id=request_id,
                    db_organizations=db_organizations,
                    genai_organizations=genAI_organizations,
                    beneficiary_id=beneficiary_id,
                    sort_by_distance=sort_by_distance,
                )
            except Exception as distance_error:
                print(f"Distance enrichment unavailable: {distance_error}")

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
