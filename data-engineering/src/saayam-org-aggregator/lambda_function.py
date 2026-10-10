import json
from helpers import attach_distances, get_ai_orgs, get_orgs_from_db, merge_organizations
from distance import sort_by_distance
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
        # Distance is measured from this request's beneficiary, not the viewer.
        request_id = body.get("request_id")
        sort_by = body.get("sort_by")

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

        combined_list = merge_organizations(db_organizations, genAI_organizations)

        orgs = attach_distances(combined_list, request_id)
        if sort_by == "distance":
            orgs = sort_by_distance(orgs)

        return {
            'statusCode': 200,
            'headers': {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": '*'
            },
            'body': json.dumps(orgs)
        }

    except json.JSONDecodeError as e:
        return {'statusCode': 400, 'body': json.dumps({'error': f'Invalid JSON in request body: {str(e)}'})}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'Internal server error: {str(e)}'})}
