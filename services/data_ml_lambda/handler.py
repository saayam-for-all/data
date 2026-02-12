import json
import uuid
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REQUIRED_FIELDS = ["user_id", "request_type", "payload"]

def _response(status_code: int, body: dict):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }

def _validate(payload: dict):
    for key in REQUIRED_FIELDS:
        if key not in payload:
            return False, f"Missing required field: {key}"

    if not isinstance(payload["user_id"], str) or not payload["user_id"].strip():
        return False, "user_id must be a non-empty string"

    if not isinstance(payload["request_type"], str) or not payload["request_type"].strip():
        return False, "request_type must be a non-empty string"

    if not isinstance(payload["payload"], dict):
        return False, "payload must be an object"

    return True, None

def lambda_handler(event, context):
    request_id = (
        event.get("requestContext", {}).get("requestId")
        or getattr(context, "aws_request_id", None)
        or str(uuid.uuid4())
    )

    body_raw = event.get("body")
    if body_raw is None:
        logger.info({"request_id": request_id, "summary": "Missing body"})
        return _response(400, {"request_id": request_id, "error": "Missing request body"})

    try:
        body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
    except json.JSONDecodeError:
        logger.info({"request_id": request_id, "summary": "Invalid JSON"})
        return _response(400, {"request_id": request_id, "error": "Invalid JSON body"})

    is_valid, err = _validate(body)
    if not is_valid:
        logger.info({"request_id": request_id, "summary": f"Validation failed: {err}"})
        return _response(400, {"request_id": request_id, "error": err})

    logger.info({
        "request_id": request_id,
        "summary": f"Valid request user_id={body['user_id']} type={body['request_type']}"
    })

    return _response(200, {
        "request_id": request_id,
        "status": "success",
        "message": "Mock response generated",
        "data": {"echo_request_type": body["request_type"]}
    })
