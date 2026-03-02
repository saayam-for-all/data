import json
from helpers import get_ai_orgs, get_orgs_from_db, merge_organizations

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

        db_organizations = get_orgs_from_db(location, category)
        genAI_organizations = get_ai_orgs(subject, description, location)
        combined_list = merge_organizations(db_organizations, genAI_organizations)

        return {
            'statusCode': 200,
            'body': combined_list.to_dict(orient='records')
        }

    except json.JSONDecodeError as e:
        return {'statusCode': 400, 'body': json.dumps({'error': f'Invalid JSON in request body: {str(e)}'})}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'Internal server error: {str(e)}'})}
