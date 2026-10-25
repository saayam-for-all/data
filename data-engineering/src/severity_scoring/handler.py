import json

from src.severity_scoring.scorer import score_text


def _response(status_code, body):
    return {"statusCode": status_code, "body": body}


def lambda_handler(event, context):
    try:
        body = event.get("body", event)
        if isinstance(body, str):
            body = json.loads(body)
    except (ValueError, AttributeError):
        return _response(400, {"error": "Invalid request body"})

    if not isinstance(body, dict):
        return _response(400, {"error": "Request body must be a JSON object"})

    subject = body.get("subject") or ""
    description = body.get("description") or ""
    if not subject and not description:
        return _response(400, {"error": "subject or description is required"})
    result = score_text(subject + " " + description)

    return _response(200, result)