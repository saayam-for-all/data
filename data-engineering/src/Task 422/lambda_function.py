"""Optional Lambda entry point; no cloud calls or schema creation on import."""

import base64
import binascii
from functools import lru_cache
import json
import logging

from profanity_routing.config import build_service
from profanity_routing.service import handle_submission


@lru_cache(maxsize=1)
def get_service():
    """Reuse an engine and API client between warm invocations."""
    return build_service()


def lambda_handler(event, context):
    """Accept direct submissions or API Gateway v1/v2 proxy events."""
    try:
        if not isinstance(event, dict):
            raise ValueError("Invalid event.")
        if "body" in event:
            method = event.get("httpMethod") or event.get("requestContext", {}).get(
                "http", {}
            ).get("method", "POST")
            if method != "POST":
                return _response({"error_code": "method_not_allowed"}, 405)
            body = event["body"]
            if event.get("isBase64Encoded"):
                body = base64.b64decode(body, validate=True).decode("utf-8")
            if not isinstance(body, str) or len(body.encode("utf-8")) > 16_384:
                raise ValueError("Invalid body.")
            payload = json.loads(body)
        else:
            payload = event
    except (ValueError, TypeError, AttributeError, binascii.Error):
        return _response({"error_code": "invalid_input", "message": "Invalid JSON event."}, 400)
    try:
        response, status = handle_submission(get_service(), payload)
    except Exception:
        # No exception text: database URLs and API headers may contain secrets.
        logging.getLogger(__name__).error("Task 422 service configuration or execution failed")
        response, status = {"error_code": "service_unavailable", "recorded": False}, 503
    return _response(response, status)


def _response(payload, status):
    """Encode the API Gateway proxy contract consistently."""
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
