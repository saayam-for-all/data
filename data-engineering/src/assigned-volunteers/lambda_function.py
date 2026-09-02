import json
from helpers import (
    validate_request_id,
    get_assigned_volunteer_id,
    get_volunteer_details,
    get_volunteer_status,
    get_volunteer_skills,
)


def lambda_function(event, context):
    try:
        raw_body = event.get("body")
        body = json.loads(raw_body) if isinstance(raw_body, str) else event

        request_id = body.get("request_id")

        if not request_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "request_id is a required field"}),
            }

        if not validate_request_id(request_id):
            return {
                "statusCode": 404,  # not found error code?
                "body": json.dumps({"error": "provided request_id does not exist"}),
            }

        volunteer_id = get_assigned_volunteer_id(request_id)

        if not volunteer_id:
            return {"statusCode": 200, "assignedVolunteers": []}

        volunteer_details = get_volunteer_details(volunteer_id)

        # TODO: if requested, get status and/or skills of the volunteer
        # Unknown: how status and/or skills will be requested

        return {"statusCode": 200, "assignedVolunteers": [volunteer_details]}
    except json.JSONDecodeError as e:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"Invalid JSON in request body: {e}"}),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Internal server error: {e}"}),
        }
